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


def refresh_date(client: TestClient, worker: Worker, blobs: dict[str, str], outcome: str = "loaded") -> dict[str, Any]:
    """A whole refresh, as the ETL job drives it (design: The daily sequence)."""
    refresh = start(client)
    upload(client, refresh, file_of(blobs))
    assert client.post(refresh["links"]["check"], headers=auth()).status_code == 202
    assert worker.tick() == 1
    refresh = poll(client, refresh)
    if refresh["state"] != "ready":
        return refresh
    response = client.post(refresh["links"]["solr_load"], json={"outcome": outcome, "rows": 1234}, headers=auth())
    assert response.status_code == 200, response.text
    if outcome != "loaded":
        return poll(client, refresh)
    assert client.post(refresh["links"]["update"], headers=auth()).status_code == 202
    assert worker.tick() == 1
    return poll(client, refresh)


def served(store: Store) -> dict[str, str]:
    return {blob: row.media_csid for blob, row in current_rows(store, "pahma").items()}


def test_a_first_day(client: TestClient, worker: Worker, store: Store) -> None:
    blobs = {f"b{i}": f"m{i}" for i in range(50)}
    refresh = refresh_date(client, worker, blobs)
    assert refresh["state"] == "updated"
    assert refresh["check"]["result"] == "passed"
    assert "first servability update: the delta threshold doesn't apply" in refresh["check"]["warnings"]
    assert refresh["solr_load"] == {"outcome": "loaded", "rows": 1234}
    assert refresh["update"] == {"deleted": 0, "written": 50, "unchanged": 0}
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
    assert refresh["update"] == {"deleted": 2, "written": 2, "unchanged": 97}
    assert served(store) == second


def test_too_many_changes_fail_the_check(client: TestClient, worker: Worker, store: Store, clock: Any) -> None:
    first = {f"b{i}": f"m{i}" for i in range(100)}
    refresh_date(client, worker, first)
    clock.now = datetime(2026, 10, 11, 10, 30, tzinfo=UTC)
    refresh = refresh_date(client, worker, {f"b{i}": f"m{i}" for i in range(90)})  # 10% removed
    assert refresh["state"] == "check_failed"
    assert refresh["check"]["delta_percent"] == 10.0
    assert served(store) == first  # nothing updated
    is_problem(client.post(refresh["links"]["solr_load"], json={"outcome": "loaded", "rows": 1}, headers=auth()), 409)
    # Asking again re-checks the stored file (for a rerun after an admin's override, D64); without one it fails again.
    assert client.post(refresh["links"]["check"], headers=auth()).status_code == 202
    assert worker.tick() == 1
    assert poll(client, refresh)["state"] == "check_failed" and served(store) == first


def test_a_fallen_back_load_updates_nothing(client: TestClient, worker: Worker, store: Store) -> None:
    refresh = refresh_date(client, worker, {"b1": "m1"}, outcome="fell_back")
    assert refresh["state"] == "abandoned"
    assert refresh["reasons"] == ["the public core's load fell back"]
    assert served(store) == {}
    is_problem(client.post(refresh["links"]["update"], headers=auth()), 409)
    again = client.post(refresh["links"]["solr_load"], json={"outcome": "fell_back", "rows": 0}, headers=auth())
    assert again.status_code == 200  # repeating it is safe


def test_calls_out_of_order(client: TestClient) -> None:
    refresh = start(client)
    is_problem(client.post(refresh["links"]["check"], headers=auth()), 409)  # no file yet
    is_problem(client.post(refresh["links"]["update"], headers=auth()), 409)
    is_problem(client.post(refresh["links"]["solr_load"], json={"outcome": "loaded", "rows": 1}, headers=auth()), 409)
    is_problem(client.post(refresh["links"]["solr_load"], json={"outcome": "maybe", "rows": 1}, headers=auth()), 400)


def test_repeating_calls_is_safe(client: TestClient, worker: Worker) -> None:
    refresh = start(client)
    upload(client, refresh, file_of({"b1": "m1"}))
    assert client.post(refresh["links"]["check"], headers=auth()).status_code == 202
    assert client.post(refresh["links"]["check"], headers=auth()).status_code == 202  # still queued
    worker.tick()
    assert client.post(refresh["links"]["check"], headers=auth()).status_code == 200  # done: returned as it is
    client.post(refresh["links"]["solr_load"], json={"outcome": "loaded", "rows": 1}, headers=auth())
    assert client.post(refresh["links"]["solr_load"], json={"outcome": "loaded", "rows": 1},
                       headers=auth()).status_code == 200
    assert client.post(refresh["links"]["update"], headers=auth()).status_code == 202
    assert client.post(refresh["links"]["update"], headers=auth()).status_code == 202
    worker.tick()
    assert client.post(refresh["links"]["update"], headers=auth()).status_code == 200


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
    assert poll(client, refresh)["state"] == "ready"


def test_an_update_that_keeps_failing(client: TestClient, worker: Worker, store: Store,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    from botocore.exceptions import ClientError

    refresh = start(client)
    upload(client, refresh, file_of({"b1": "m1"}))
    client.post(refresh["links"]["check"], headers=auth())
    worker.tick()
    client.post(refresh["links"]["solr_load"], json={"outcome": "loaded", "rows": 1}, headers=auth())
    client.post(refresh["links"]["update"], headers=auth())

    def throttled(**kwargs: object) -> None:
        raise ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "BatchWriteItem")

    monkeypatch.setattr(store.client, "batch_write_item", throttled)
    assert worker.tick() == 1
    failed = poll(client, refresh)
    assert failed["state"] == "update_failed"
    assert "after 3 attempts" in failed["reasons"][-1]


def test_another_museums_rows_are_left_alone(client: TestClient, worker: Worker, store: Store) -> None:
    store.client.put_item(TableName=store.table(tables.SERVABILITY), Item={
        "pk": {"S": "ucjeps#u1"}, "tenant": {"S": "ucjeps"}, "blob_csid": {"S": "u1"}, "kind": {"S": "image"},
        "access": {"S": "public"}, "media_csid": {"S": "um1"}})
    refresh_date(client, worker, {"b1": "m1"})
    assert set(current_rows(store, "ucjeps")) == {"u1"}


def test_the_worker_stops_when_asked(worker: Worker) -> None:
    worker.stopping.set()  # what SIGTERM does
    worker.run_forever()  # returns at once instead of looping
