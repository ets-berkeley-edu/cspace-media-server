import gzip
import hashlib
from datetime import UTC, datetime
from typing import Any

import pytest
from conftest import TENANTS
from etl_helpers import auth, is_problem, start
from fastapi.testclient import TestClient

from serena import museum, tables
from serena.apply import current_rows
from serena.config import Settings
from serena.museum_settings import MuseumSettings
from serena.runs import Runs
from serena.store import Store
from serena.worker import Worker, WorkerServices

HEADER = "blob_csid\tmedia_csid\tkind\taccess\n"


def file_of(blobs: dict[str, str]) -> bytes:
    return (HEADER + "".join(f"{b}\t{m}\timage\tpublic\n" for b, m in blobs.items())).encode()


@pytest.fixture
def worker(store: Store, s3: Any, clock: Any) -> Worker:
    settings = Settings(tenants=TENANTS, table_prefix="t", buckets={t: f"b-{t}" for t in TENANTS}, _env_file=None)
    services = WorkerServices(settings, museum.load_all(TENANTS), MuseumSettings(store, 0), Runs(store, clock),
                              store, s3)
    return Worker(services, sleep=lambda seconds: None)


def upload(client: TestClient, run: dict[str, Any], body: bytes) -> None:
    response = client.put(run["links"]["blob_media"], content=gzip.compress(body), headers={
        **auth(), "Content-Type": "text/tab-separated-values", "Content-Encoding": "gzip",
        "X-Row-Count": str(body.count(b"\n") - 1), "X-Content-SHA256": hashlib.sha256(body).hexdigest()})
    assert response.status_code == 200, response.text


def poll(client: TestClient, run: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = client.get(run["links"]["self"], headers=auth()).json()
    return body


def night(client: TestClient, worker: Worker, blobs: dict[str, str], outcome: str = "loaded") -> dict[str, Any]:
    """A whole night, as the ETL drives it (design: The nightly sequence)."""
    run = start(client)
    upload(client, run, file_of(blobs))
    assert client.post(run["links"]["preflight"], headers=auth()).status_code == 202
    assert worker.tick() == 1
    run = poll(client, run)
    if run["state"] != "ready":
        return run
    response = client.post(run["links"]["solr_load"], json={"outcome": outcome, "rows": 1234}, headers=auth())
    assert response.status_code == 200, response.text
    if outcome != "loaded":
        return poll(client, run)
    assert client.post(run["links"]["apply"], headers=auth()).status_code == 202
    assert worker.tick() == 1
    return poll(client, run)


def served(store: Store) -> dict[str, str]:
    return {blob: row.media_csid for blob, row in current_rows(store, "pahma").items()}


def test_a_first_night(client: TestClient, worker: Worker, store: Store) -> None:
    blobs = {f"b{i}": f"m{i}" for i in range(50)}
    run = night(client, worker, blobs)
    assert run["state"] == "applied"
    assert run["preflight"]["result"] == "passed"
    assert "first load: the change threshold doesn't apply" in run["preflight"]["warnings"]
    assert run["solr_load"] == {"outcome": "loaded", "rows": 1234}
    assert run["apply"] == {"deleted": 0, "written": 50, "unchanged": 0}
    assert served(store) == blobs
    latest = client.get("/etl/v1/museums/pahma", headers=auth()).json()
    assert latest["run_id"] == run["run_id"]


def test_the_next_night_deletes_writes_and_leaves_alone(client: TestClient, worker: Worker, store: Store,
                                                        clock: Any) -> None:
    first = {f"b{i}": f"m{i}" for i in range(100)}
    night(client, worker, first)
    clock.now = datetime(2026, 10, 11, 10, 30, tzinfo=UTC)
    second = dict(first)
    del second["b0"], second["b1"]  # removed
    second["b2"] = "other"  # changed
    second["b100"] = "m100"  # added
    run = night(client, worker, second)
    assert run["state"] == "applied"
    assert (run["preflight"]["removed"], run["preflight"]["changed"], run["preflight"]["added"]) == (2, 1, 1)
    assert run["apply"] == {"deleted": 2, "written": 2, "unchanged": 97}
    assert served(store) == second


def test_too_many_changes_fail_the_preflight(client: TestClient, worker: Worker, store: Store, clock: Any) -> None:
    first = {f"b{i}": f"m{i}" for i in range(100)}
    night(client, worker, first)
    clock.now = datetime(2026, 10, 11, 10, 30, tzinfo=UTC)
    run = night(client, worker, {f"b{i}": f"m{i}" for i in range(90)})  # 10% removed
    assert run["state"] == "preflight_failed"
    assert run["preflight"]["change_percent"] == 10.0
    assert served(store) == first  # nothing applied
    is_problem(client.post(run["links"]["solr_load"], json={"outcome": "loaded", "rows": 1}, headers=auth()), 409)
    is_problem(client.post(run["links"]["preflight"], headers=auth()), 409)  # a corrected file is needed


def test_a_fallen_back_load_applies_nothing(client: TestClient, worker: Worker, store: Store) -> None:
    run = night(client, worker, {"b1": "m1"}, outcome="fell_back")
    assert run["state"] == "abandoned"
    assert run["reasons"] == ["the public core's load fell back"]
    assert served(store) == {}
    is_problem(client.post(run["links"]["apply"], headers=auth()), 409)
    again = client.post(run["links"]["solr_load"], json={"outcome": "fell_back", "rows": 0}, headers=auth())
    assert again.status_code == 200  # repeating it is safe


def test_calls_out_of_order(client: TestClient) -> None:
    run = start(client)
    is_problem(client.post(run["links"]["preflight"], headers=auth()), 409)  # no file yet
    is_problem(client.post(run["links"]["apply"], headers=auth()), 409)
    is_problem(client.post(run["links"]["solr_load"], json={"outcome": "loaded", "rows": 1}, headers=auth()), 409)
    is_problem(client.post(run["links"]["solr_load"], json={"outcome": "maybe", "rows": 1}, headers=auth()), 400)


def test_repeating_calls_is_safe(client: TestClient, worker: Worker) -> None:
    run = start(client)
    upload(client, run, file_of({"b1": "m1"}))
    assert client.post(run["links"]["preflight"], headers=auth()).status_code == 202
    assert client.post(run["links"]["preflight"], headers=auth()).status_code == 202  # still queued
    worker.tick()
    assert client.post(run["links"]["preflight"], headers=auth()).status_code == 200  # done: returned as it is
    client.post(run["links"]["solr_load"], json={"outcome": "loaded", "rows": 1}, headers=auth())
    assert client.post(run["links"]["solr_load"], json={"outcome": "loaded", "rows": 1},
                       headers=auth()).status_code == 200
    assert client.post(run["links"]["apply"], headers=auth()).status_code == 202
    assert client.post(run["links"]["apply"], headers=auth()).status_code == 202
    worker.tick()
    assert client.post(run["links"]["apply"], headers=auth()).status_code == 200


def test_no_applied_run_yet(client: TestClient) -> None:
    is_problem(client.get("/etl/v1/museums/pahma", headers=auth()), 404)


def test_an_interrupted_step_is_claimed_again(client: TestClient, worker: Worker, store: Store, clock: Any) -> None:
    run = start(client)
    upload(client, run, file_of({"b1": "m1"}))
    client.post(run["links"]["preflight"], headers=auth())
    runs = Runs(store, clock)
    stuck = runs.get("pahma", run["run_id"])
    assert stuck is not None and runs.claim(stuck, "a-worker-that-stopped", 300)
    assert worker.tick() == 0  # its claim is fresh
    clock.now = datetime(2026, 10, 10, 10, 40, tzinfo=UTC)  # 10 minutes later: stale
    assert worker.tick() == 1
    assert poll(client, run)["state"] == "ready"


def test_an_apply_that_keeps_failing(client: TestClient, worker: Worker, store: Store,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    from botocore.exceptions import ClientError

    run = start(client)
    upload(client, run, file_of({"b1": "m1"}))
    client.post(run["links"]["preflight"], headers=auth())
    worker.tick()
    client.post(run["links"]["solr_load"], json={"outcome": "loaded", "rows": 1}, headers=auth())
    client.post(run["links"]["apply"], headers=auth())

    def throttled(**kwargs: object) -> None:
        raise ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "BatchWriteItem")

    monkeypatch.setattr(store.client, "batch_write_item", throttled)
    assert worker.tick() == 1
    failed = poll(client, run)
    assert failed["state"] == "apply_failed"
    assert "after 3 attempts" in failed["reasons"][-1]


def test_another_museums_rows_are_left_alone(client: TestClient, worker: Worker, store: Store) -> None:
    store.client.put_item(TableName=store.table(tables.SERVABILITY), Item={
        "pk": {"S": "ucjeps#u1"}, "tenant": {"S": "ucjeps"}, "blob_csid": {"S": "u1"}, "kind": {"S": "image"},
        "access": {"S": "public"}, "media_csid": {"S": "um1"}})
    night(client, worker, {"b1": "m1"})
    assert set(current_rows(store, "ucjeps")) == {"u1"}


def test_the_worker_stops_when_asked(worker: Worker) -> None:
    worker.stopping.set()  # what SIGTERM does
    worker.run_forever()  # returns at once instead of looping
