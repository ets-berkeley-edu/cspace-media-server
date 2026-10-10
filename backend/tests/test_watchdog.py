from datetime import UTC, datetime
from typing import Any

import boto3
import pytest
from conftest import TENANTS

from serena import museum, tables
from serena.alerts import Alerts, Kind
from serena.museum_settings import MuseumSettings
from serena.runs import Runs, State
from serena.store import Store
from serena.watchdog import Watchdog


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
    return Watchdog(museums, MuseumSettings(store, 0), Runs(store, clock), Alerts(store, sns, arn, clock), clock)


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


def test_no_run_by_the_deadline(watchdog: Watchdog, clock: Clock, store: Store, topic: Any) -> None:
    at(clock, 8, 0)
    (alert,) = watchdog.check()
    assert (alert.kind, alert.night, alert.subject) == (Kind.MISSED_DEADLINE, "2026-10-10", "2026-10-10")
    assert "no run started" in alert.message
    (item,) = alerts_of(store)
    assert item["sk"]["S"] == "2026-10-10#missed_deadline#2026-10-10"
    assert "emailed_at" in item
    (body,) = emailed(topic)
    assert "pahma" in body and "Tonight's run isn't finished by the deadline" in body


def test_an_alert_is_recorded_and_emailed_once(watchdog: Watchdog, clock: Clock, store: Store, topic: Any) -> None:
    at(clock, 8, 0)
    watchdog.check()
    at(clock, 8, 5)
    assert len(watchdog.check()) == 1  # it still holds
    assert len(alerts_of(store)) == 1
    assert len(emailed(topic)) == 1


def test_an_unfinished_run_by_the_deadline(watchdog: Watchdog, clock: Clock, store: Store) -> None:
    runs = Runs(store, clock)
    at(clock, 3, 1)
    run, _ = runs.start("pahma")
    runs.transition(run, State.RECEIVED)
    at(clock, 8, 0)
    (alert,) = watchdog.check()
    assert alert.kind == Kind.MISSED_DEADLINE and "(received)" in alert.message


def test_an_applied_night_raises_nothing(watchdog: Watchdog, clock: Clock, store: Store) -> None:
    runs = Runs(store, clock)
    at(clock, 3, 1)
    run, _ = runs.start("pahma")
    runs.transition(run, State.APPLIED)
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


@pytest.mark.parametrize(("state", "kind"), [(State.PREFLIGHT_FAILED, Kind.PREFLIGHT_FAILED),
                                             (State.APPLY_FAILED, Kind.APPLY_FAILED),
                                             (State.ABANDONED, Kind.ABANDONED)])
def test_failed_runs(watchdog: Watchdog, clock: Clock, store: Store, state: State, kind: Kind) -> None:
    runs = Runs(store, clock)
    at(clock, 3, 1)
    run, _ = runs.start("pahma")
    runs.transition(run, state, reason="the reason")
    at(clock, 3, 10)
    (alert,) = watchdog.check()
    assert (alert.kind, alert.subject) == (kind, run.run_id)
    assert "the reason" in alert.message


def test_not_updated_in_24_hours(watchdog: Watchdog, clock: Clock, store: Store) -> None:
    runs = Runs(store, clock)
    at(clock, 3, 30)
    run, _ = runs.start("pahma")
    runs.transition(run, State.APPLIED)
    at(clock, 3, 29, day=11)
    assert [a.kind for a in watchdog.check()] == []
    at(clock, 3, 31, day=11)
    assert [a.kind for a in watchdog.check()] == [Kind.NOT_UPDATED]


def test_a_museum_that_never_applied_a_night_isnt_late(watchdog: Watchdog, clock: Clock) -> None:
    at(clock, 3, 0, day=20)
    assert watchdog.check() == []  # before the deadline, and no applied night to be 24 hours old


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
    dog = Watchdog(museums, MuseumSettings(store, 0), Runs(store, clock), Alerts(store, None, "", clock), clock)
    at(clock, 8, 0)
    dog.check()
    (item,) = alerts_of(store)
    assert "emailed_at" not in item


def test_the_worker_runs_the_watchdog_at_its_interval(store: Store, s3: Any, watchdog: Watchdog) -> None:
    from serena.config import Settings
    from serena.worker import Worker, WorkerServices

    settings = Settings(tenants=TENANTS, table_prefix="t", watchdog_seconds=300, _env_file=None)
    now = [1000.0]
    worker = Worker(WorkerServices(settings, watchdog.museums, watchdog.museum_settings, watchdog.runs, store, s3,
                                   watchdog), monotonic=lambda: now[0])
    assert worker.watch()
    now[0] += 299
    assert not worker.watch()
    now[0] += 2
    assert worker.watch()
