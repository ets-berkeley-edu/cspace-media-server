import gzip
import hashlib
from datetime import UTC, datetime
from typing import Any

import pytest
from conftest import TENANTS
from etl_helpers import auth, is_problem, start
from fastapi.testclient import TestClient

from serena import museum, tables
from serena.config import Settings
from serena.museum_settings import MuseumSettings
from serena.refreshes import Refreshes
from serena.servability_update import current_rows
from serena.store import Store
from serena.worker import Worker, WorkerServices

HEADER = "blob_csid\tmedia_csid\tkind\taccess\n"


def file_of(blobs: dict[str, str]) -> bytes:
    return (HEADER + "".join(f"{b}\t{m}\timage\tpublic\n" for b, m in blobs.items())).encode()


@pytest.fixture
def worker(store: Store, s3: Any, clock: Any) -> Worker:
    settings = Settings(tenants=TENANTS, table_prefix="t", buckets={t: f"b-{t}" for t in TENANTS}, _env_file=None)
    services = WorkerServices(settings, museum.load_all(TENANTS), MuseumSettings(store, 0), Refreshes(store, clock),
                              store, s3)
    return Worker(services, sleep=lambda seconds: None)


def upload(client: TestClient, refresh: dict[str, Any], body: bytes) -> None:
    response = client.put(refresh["links"]["servable_list"], content=gzip.compress(body), headers={
        **auth(), "Content-Type": "text/tab-separated-values", "Content-Encoding": "gzip",
        "X-Row-Count": str(body.count(b"\n") - 1), "X-Content-SHA256": hashlib.sha256(body).hexdigest()})
    assert response.status_code == 200, response.text


def poll(client: TestClient, refresh: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = client.get(refresh["links"]["self"], headers=auth()).json()
    return body


def refresh_date(client: TestClient, worker: Worker, blobs: dict[str, str]) -> dict[str, Any]:
    """A whole refresh, as the ETL job drives it after its Solr refresh (design: The daily sequence; D80): start,
    upload, check, poll. A passed check goes straight on to the servability update, in the same worker pass."""
    refresh = start(client)
    upload(client, refresh, file_of(blobs))
    assert client.post(refresh["links"]["check"], headers=auth()).status_code == 202
    assert worker.tick() == 1
    return poll(client, refresh)


def served(store: Store) -> dict[str, str]:
    return {blob: row.media_csid for blob, row in current_rows(store, "pahma").items()}


def test_a_first_day(client: TestClient, worker: Worker, store: Store) -> None:
    blobs = {f"b{i}": f"m{i}" for i in range(50)}
    refresh = refresh_date(client, worker, blobs)
    assert refresh["state"] == "updated"
    assert refresh["check"]["result"] == "passed"
    assert "first ETL list update: the delta threshold doesn't apply" in refresh["check"]["warnings"]
    assert set(refresh["links"]) == {"self", "servable_list", "check"}  # no Solr refresh report or update call (D72)
    assert refresh["update"] == {"deleted": 0, "written": 50, "unchanged": 0, "recalls_ended": 0,
                                 "recalls_kept": 0}
    assert served(store) == blobs
    latest = client.get("/etl/v1/museums/pahma", headers=auth()).json()
    assert latest["refresh_id"] == refresh["refresh_id"]


def test_the_next_day_deletes_writes_and_leaves_alone(client: TestClient, worker: Worker, store: Store,
                                                        clock: Any) -> None:
    first = {f"b{i}": f"m{i}" for i in range(100)}
    refresh_date(client, worker, first)
    clock.now = datetime(2026, 10, 11, 10, 30, tzinfo=UTC)
    second = dict(first)
    del second["b0"], second["b1"]  # removed
    second["b2"] = "other"  # changed
    second["b100"] = "m100"  # added
    refresh = refresh_date(client, worker, second)
    assert refresh["state"] == "updated"
    assert (refresh["check"]["removed"], refresh["check"]["changed"], refresh["check"]["added"]) == (2, 1, 1)
    assert refresh["update"] == {"deleted": 2, "written": 2, "unchanged": 97, "recalls_ended": 0,
                                 "recalls_kept": 0}
    assert served(store) == second


def test_too_many_changes_fail_the_check(client: TestClient, worker: Worker, store: Store, clock: Any) -> None:
    first = {f"b{i}": f"m{i}" for i in range(100)}
    refresh_date(client, worker, first)
    clock.now = datetime(2026, 10, 11, 10, 30, tzinfo=UTC)
    refresh = refresh_date(client, worker, {f"b{i}": f"m{i}" for i in range(90)})  # 10% removed
    assert refresh["state"] == "check_failed"
    assert refresh["check"]["delta_percent"] == 10.0
    assert served(store) == first  # nothing updated
    # Asking again without a corrected list returns the refresh as it is (an admin may override, D83).
    assert client.post(refresh["links"]["check"], headers=auth()).status_code == 200
    assert worker.tick() == 0
    # The ETL job rerun with a corrected list: the same refresh, checked again, then updated.
    again = refresh_date(client, worker, first)
    assert again["refresh_id"] == refresh["refresh_id"] and again["state"] == "updated" and served(store) == first


def test_calls_out_of_order(client: TestClient) -> None:
    refresh = start(client)
    is_problem(client.post(refresh["links"]["check"], headers=auth()), 409)  # no servable list yet
    # The Solr refresh report and the update call are gone (D72, D80).
    base = refresh["links"]["self"]
    assert client.post(f"{base}/solr-load", json={"outcome": "loaded", "rows": 1}, headers=auth()).status_code == 404
    assert client.post(f"{base}/update", headers=auth()).status_code == 404


def test_repeating_calls_is_safe(client: TestClient, worker: Worker) -> None:
    refresh = start(client)
    upload(client, refresh, file_of({"b1": "m1"}))
    assert client.post(refresh["links"]["check"], headers=auth()).status_code == 202
    assert client.post(refresh["links"]["check"], headers=auth()).status_code == 202  # still queued
    worker.tick()
    assert poll(client, refresh)["state"] == "updated"
    assert client.post(refresh["links"]["check"], headers=auth()).status_code == 200  # done: returned as it is
    body = file_of({"b1": "m1"})
    closed = client.put(refresh["links"]["servable_list"], content=body, headers={
        **auth(), "Content-Type": "text/tab-separated-values", "X-Row-Count": "1",
        "X-Content-SHA256": hashlib.sha256(body).hexdigest()})
    is_problem(closed, 409)  # closed: a new list needs a new refresh


def test_no_updated_refresh_yet(client: TestClient) -> None:
    is_problem(client.get("/etl/v1/museums/pahma", headers=auth()), 404)


def test_an_interrupted_step_is_claimed_again(client: TestClient, worker: Worker, store: Store, clock: Any) -> None:
    refresh = start(client)
    upload(client, refresh, file_of({"b1": "m1"}))
    client.post(refresh["links"]["check"], headers=auth())
    refreshes = Refreshes(store, clock)
    stuck = refreshes.get("pahma", refresh["refresh_id"])
    assert stuck is not None and refreshes.claim(stuck, "a-worker-that-stopped", 300)
    assert worker.tick() == 0  # its claim is fresh
    clock.now = datetime(2026, 10, 10, 10, 40, tzinfo=UTC)  # 10 minutes later: stale
    assert worker.tick() == 1
    assert poll(client, refresh)["state"] == "updated"


def test_an_update_that_keeps_failing(client: TestClient, worker: Worker, store: Store,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    from botocore.exceptions import ClientError

    refresh = start(client)
    upload(client, refresh, file_of({"b1": "m1"}))
    client.post(refresh["links"]["check"], headers=auth())

    def throttled(**kwargs: object) -> None:
        raise ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "BatchWriteItem")

    monkeypatch.setattr(store.client, "batch_write_item", throttled)
    assert worker.tick() == 1
    failed = poll(client, refresh)
    assert failed["state"] == "update_failed"
    assert failed["check"]["result"] == "passed" and "after 3 attempts" in failed["reasons"][-1]
    # The ETL job rerun: a list may be uploaded again to an update_failed refresh, and checked again.
    monkeypatch.undo()
    upload(client, refresh, file_of({"b1": "m1", "b2": "m2"}))
    assert poll(client, refresh)["state"] == "received"
    assert client.post(refresh["links"]["check"], headers=auth()).status_code == 202
    assert worker.tick() == 1 and poll(client, refresh)["state"] == "updated"


def test_another_museums_rows_are_left_alone(client: TestClient, worker: Worker, store: Store) -> None:
    store.client.put_item(TableName=store.table(tables.SERVABILITY), Item={
        "pk": {"S": "ucjeps#u1"}, "tenant": {"S": "ucjeps"}, "blob_csid": {"S": "u1"}, "kind": {"S": "image"},
        "access": {"S": "public"}, "media_csid": {"S": "um1"}})
    refresh_date(client, worker, {"b1": "m1"})
    assert set(current_rows(store, "ucjeps")) == {"u1"}


def test_a_failed_step_raises_its_alert_at_once(store: Store, s3: Any, clock: Any, client: TestClient,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """The team hears of a failed check or servability update at once, not on the watchdog's next pass."""
    from botocore.exceptions import ClientError

    from serena.alerts import Alerts
    from serena.watchdog import Watchdog

    settings = Settings(tenants=TENANTS, table_prefix="t", buckets={t: f"b-{t}" for t in TENANTS}, _env_file=None)
    museums = museum.load_all(TENANTS)
    watchdog = Watchdog(museums, MuseumSettings(store, 0), Refreshes(store, clock), Alerts(store, None, "", clock),
                        clock)
    worker = Worker(WorkerServices(settings, museums, MuseumSettings(store, 0), Refreshes(store, clock), store, s3,
                                   watchdog), sleep=lambda seconds: None)

    def kinds() -> list[str]:
        items = store.client.scan(TableName=store.table(tables.ALERTS))["Items"]
        return sorted(item["kind"]["S"] for item in items)

    first = {f"b{i}": f"m{i}" for i in range(100)}
    refresh_date(client, worker, first)
    clock.now = datetime(2026, 10, 11, 10, 30, tzinfo=UTC)
    failed = refresh_date(client, worker, {f"b{i}": f"m{i}" for i in range(90)})  # 10% removed
    assert failed["state"] == "check_failed" and kinds() == ["check_failed"]
    assert watchdog.check_museum("pahma")[0].kind.value == "check_failed"  # its later passes record nothing more
    assert kinds() == ["check_failed"]

    def throttled(**kwargs: object) -> None:
        raise ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "BatchWriteItem")

    clock.now = datetime(2026, 10, 12, 10, 30, tzinfo=UTC)
    monkeypatch.setattr(store.client, "batch_write_item", throttled)
    assert refresh_date(client, worker, {**first, "b0": "other"})["state"] == "update_failed"
    assert kinds() == ["check_failed", "update_failed"]


def test_the_worker_stops_when_asked(worker: Worker) -> None:
    worker.stopping.set()  # what SIGTERM does
    worker.run_forever()  # returns at once instead of looping
