from datetime import UTC, datetime
from typing import Any

import boto3
import pytest
from conftest import TENANTS

from serena import museum, tables
from serena.alerts import Alerts, Kind
from serena.museum_settings import MuseumSettings
from serena.refreshes import Refreshes, State
from serena.store import Store
from serena.watchdog import FAILED_WORDS, Watchdog


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime(2026, 10, 10, 10, 0, tzinfo=UTC))  # 03:00 Pacific (daylight time), October 10


@pytest.fixture
def topic(dynamodb: Any) -> tuple[Any, str, Any]:
    """An SNS topic with an SQS queue subscribed, to read what was emailed."""
    sns = boto3.client("sns", region_name="us-west-2")
    sqs = boto3.client("sqs", region_name="us-west-2")
    arn = sns.create_topic(Name="serena-alerts")["TopicArn"]
    queue = sqs.create_queue(QueueName="alerts")["QueueUrl"]
    queue_arn = sqs.get_queue_attributes(QueueUrl=queue, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    sns.subscribe(TopicArn=arn, Protocol="sqs", Endpoint=queue_arn)
    return sns, arn, (sqs, queue)


def emailed(topic: tuple[Any, str, Any]) -> list[str]:
    sqs, queue = topic[2]
    messages = sqs.receive_message(QueueUrl=queue, MaxNumberOfMessages=10).get("Messages", [])
    return [m["Body"] for m in messages]


@pytest.fixture
def watchdog(store: Store, topic: tuple[Any, str, Any], clock: Clock) -> Watchdog:
    sns, arn, _ = topic
    museums = {"pahma": museum.load("pahma")}
    return Watchdog(museums, MuseumSettings(store, 0), Refreshes(store, clock), Alerts(store, sns, arn, clock), clock)


def alerts_of(store: Store, tenant: str = "pahma") -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = store.client.query(
        TableName=store.table(tables.ALERTS), KeyConditionExpression="pk = :t",
        ExpressionAttributeValues={":t": {"S": tenant}})["Items"]
    return items


def at(clock: Clock, hour: int, minute: int = 0, day: int = 10) -> None:
    clock.now = datetime(2026, 10, day, hour + 7, minute, tzinfo=UTC)  # Pacific daylight time is UTC-7


def test_nothing_before_the_deadline(watchdog: Watchdog, clock: Clock) -> None:
    at(clock, 7, 59)
    assert watchdog.check() == []


def test_no_refresh_by_the_deadline(watchdog: Watchdog, clock: Clock, store: Store, topic: Any) -> None:
    at(clock, 8, 0)
    (alert,) = watchdog.check()
    assert (alert.kind, alert.refresh_date, alert.subject) == (Kind.MISSED_DEADLINE, "2026-10-10", "2026-10-10")
    assert "no refresh started" in alert.message
    (item,) = alerts_of(store)
    assert item["sk"]["S"] == "2026-10-10#missed_deadline#2026-10-10"
    assert "emailed_at" in item
    (body,) = emailed(topic)
    assert "pahma" in body and "Today's refresh isn't finished by the deadline" in body


def test_an_alert_is_recorded_and_emailed_once(watchdog: Watchdog, clock: Clock, store: Store, topic: Any) -> None:
    at(clock, 8, 0)
    watchdog.check()
    at(clock, 8, 5)
    assert len(watchdog.check()) == 1  # it still holds
    assert len(alerts_of(store)) == 1
    assert len(emailed(topic)) == 1


def test_an_unfinished_refresh_by_the_deadline(watchdog: Watchdog, clock: Clock, store: Store) -> None:
    refreshes = Refreshes(store, clock)
    at(clock, 3, 1)
    refresh, _ = refreshes.start("pahma")
    refreshes.transition(refresh, State.RECEIVED)
    at(clock, 8, 0)
    (alert,) = watchdog.check()
    assert alert.kind == Kind.MISSED_DEADLINE and "(received)" in alert.message


def test_an_updated_day_raises_nothing(watchdog: Watchdog, clock: Clock, store: Store) -> None:
    refreshes = Refreshes(store, clock)
    at(clock, 3, 1)
    refresh, _ = refreshes.start("pahma")
    refreshes.transition(refresh, State.UPDATED)
    at(clock, 9, 0)
    assert watchdog.check() == []


def test_an_admins_deadline(watchdog: Watchdog, clock: Clock, store: Store) -> None:
    store.client.put_item(TableName=store.table(tables.SETTINGS),
                          Item={"pk": {"S": "pahma"}, "values": {"S": '{"watchdog_deadline": "06:30"}'}})
    at(clock, 6, 30)
    assert [a.kind for a in watchdog.check()] == [Kind.MISSED_DEADLINE]


def test_the_deadline_in_winter(watchdog: Watchdog, clock: Clock) -> None:
    clock.now = datetime(2026, 12, 10, 15, 59, tzinfo=UTC)  # 07:59 Pacific standard time (UTC-8)
    assert watchdog.check() == []
    clock.now = datetime(2026, 12, 10, 16, 0, tzinfo=UTC)
    assert [a.kind for a in watchdog.check()] == [Kind.MISSED_DEADLINE]


@pytest.mark.parametrize(("state", "kind"), [(State.CHECK_FAILED, Kind.CHECK_FAILED),
                                             (State.UPDATE_FAILED, Kind.UPDATE_FAILED),
                                             (State.ABANDONED, Kind.ABANDONED)])
def test_failed_refreshes(watchdog: Watchdog, clock: Clock, store: Store, state: State, kind: Kind) -> None:
    refreshes = Refreshes(store, clock)
    at(clock, 3, 1)
    refresh, _ = refreshes.start("pahma")
    refreshes.transition(refresh, state, reason="the reason")
    at(clock, 3, 10)
    (alert,) = watchdog.check()
    assert (alert.kind, alert.subject) == (kind, refresh.refresh_id)
    # In words, not the state's name (October 14, 2026)
    assert alert.message == f"Refresh {refresh.refresh_id} {FAILED_WORDS[state]}: the reason. Its page says more."
    assert "_" not in alert.message.replace(refresh.refresh_id, "")  # no state name such as check_failed


def test_not_updated_in_24_hours(watchdog: Watchdog, clock: Clock, store: Store) -> None:
    refreshes = Refreshes(store, clock)
    at(clock, 3, 30)
    refresh, _ = refreshes.start("pahma")
    refreshes.transition(refresh, State.UPDATED)
    at(clock, 3, 29, day=11)
    assert [a.kind for a in watchdog.check()] == []
    at(clock, 3, 31, day=11)
    assert [a.kind for a in watchdog.check()] == [Kind.NOT_UPDATED]


def test_a_museum_that_never_updated_a_day_isnt_late(watchdog: Watchdog, clock: Clock) -> None:
    at(clock, 3, 0, day=20)
    assert watchdog.check() == []  # before the deadline, and no servability update to be 24 hours old


def test_an_email_that_failed_is_sent_again(watchdog: Watchdog, clock: Clock, store: Store, topic: Any,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    sns = topic[0]
    real = sns.publish

    def unreachable(**kwargs: object) -> None:
        raise ConnectionError("SNS unreachable")

    monkeypatch.setattr(sns, "publish", unreachable)
    at(clock, 8, 0)
    watchdog.check()
    (item,) = alerts_of(store)
    assert "emailed_at" not in item
    monkeypatch.setattr(sns, "publish", real)
    at(clock, 8, 5)
    watchdog.check()
    (item,) = alerts_of(store)
    assert "emailed_at" in item
    assert len(emailed(topic)) == 1


def test_without_a_topic_alerts_are_recorded(store: Store, clock: Clock) -> None:
    museums = {"pahma": museum.load("pahma")}
    dog = Watchdog(museums, MuseumSettings(store, 0), Refreshes(store, clock), Alerts(store, None, "", clock), clock)
    at(clock, 8, 0)
    dog.check()
    (item,) = alerts_of(store)
    assert "emailed_at" not in item


def test_the_worker_refreshes_the_watchdog_at_its_interval(store: Store, s3: Any, watchdog: Watchdog) -> None:
    from serena.config import Settings
    from serena.worker import Worker, WorkerServices

    settings = Settings(tenants=TENANTS, table_prefix="t", watchdog_seconds=300, _env_file=None)
    now = [1000.0]
    worker = Worker(WorkerServices(settings, watchdog.museums, watchdog.museum_settings, watchdog.refreshes, store, s3,
                                   watchdog), monotonic=lambda: now[0])
    assert worker.watch()
    now[0] += 299
    assert not worker.watch()
    now[0] += 2
    assert worker.watch()


def test_a_placeholder_image_no_record_is_named_for(store: Store, clock: Clock) -> None:
    """D173: once per refresh date, while the servable list lists the placeholder and no Media record is named."""
    from conftest import add_blob

    pahma = museum.load("pahma")
    dog = Watchdog({"pahma": pahma}, MuseumSettings(store, 0), Refreshes(store, clock), Alerts(store, None, "", clock),
                   clock, store=store)
    refreshes = Refreshes(store, clock)
    at(clock, 3, 30)
    refresh, _ = refreshes.start("pahma")
    refreshes.transition(refresh, State.UPDATED)
    at(clock, 3, 40)
    assert dog.check() == []  # not listed: nothing to say
    add_blob(store, "pahma", pahma.placeholder_blob_csid, None)
    (alert,) = dog.check()
    assert (alert.kind, alert.refresh_date, alert.subject) == (Kind.PLACEHOLDER_NOT_SET, "2026-10-10",
                                                               refresh.refresh_id)
    assert "generic picture" in alert.message and "Settings page" in alert.message
    store.put_settings_overrides("pahma", {"placeholder_media_csid": "3c4d5e6f-7081-4a92-8b3c-4d5e6f708192"},
                                 store.settings_with_version("pahma")[1])
    assert dog.check() == []
