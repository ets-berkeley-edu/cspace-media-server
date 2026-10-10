import gzip
import hashlib
import json
import logging
import secrets as random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import TENANTS
from fastapi.testclient import TestClient

from serena import etl_api, tables
from serena.app import create_app
from serena.config import Settings
from serena.runs import Runs, State
from serena.store import Store

# Tokens are made at run time: none is written in the repository.
TOKENS = {tenant: random.token_urlsafe(32) for tenant in TENANTS}
OLD_PAHMA = random.token_urlsafe(32)
HEADER = "blob_csid\tmedia_csid\tkind\taccess\n"
ROWS = "".join(f"b{n}\tm{n}\timage\tpublic\n" for n in range(3))  # synthetic CSIDs; the format is preflight's job
FILE = (HEADER + ROWS).encode()


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime(2026, 10, 10, 10, 30, tzinfo=UTC))  # 03:30 Pacific, October 10


@pytest.fixture
def client(store: Store, s3: Any, secretsmanager: Any, clock: Clock) -> TestClient:
    ids = {}
    for tenant, token in TOKENS.items():
        value = {"current": token, "previous": OLD_PAHMA if tenant == "pahma" else ""}
        ids[tenant] = secretsmanager.create_secret(Name=f"etl/{tenant}", SecretString=json.dumps(value))["ARN"]
    settings = Settings(tenants=TENANTS, table_prefix="t", buckets={t: f"b-{t}" for t in TENANTS},
                        etl_token_secret_ids=ids, upload_max_mb=1, _env_file=None)
    return TestClient(create_app(settings, store, s3=s3, secretsmanager=secretsmanager, clock=clock))


def auth(tenant: str = "pahma") -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKENS[tenant]}"}


def upload_headers(body: bytes, tenant: str = "pahma", **extra: str) -> dict[str, str]:
    rows = max(body.count(b"\n") + (0 if body.endswith(b"\n") else 1) - 1, 0)
    return {**auth(tenant), "Content-Type": "text/tab-separated-values", "X-Row-Count": str(rows),
            "X-Content-SHA256": hashlib.sha256(body).hexdigest(), **extra}


def start(client: TestClient, tenant: str = "pahma") -> dict[str, Any]:
    response = client.post(f"/etl/v1/museums/{tenant}/runs", headers=auth(tenant))
    assert response.status_code in (200, 201), response.text
    body: dict[str, Any] = response.json()
    return body


def put(client: TestClient, run: dict[str, Any], body: bytes, **headers: str) -> Any:
    return client.put(run["links"]["blob_media"], content=body, headers=upload_headers(body, **headers))


def is_problem(response: Any, status: int) -> None:
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["status"] == status


# --- tokens

def test_ping_names_the_tokens_museum(client: TestClient) -> None:
    response = client.get("/etl/v1/ping", headers=auth("cinefiles"))
    assert response.status_code == 200
    assert response.json() == {"museum": "cinefiles"}


def test_the_previous_token_works_during_a_rotation(client: TestClient) -> None:
    response = client.get("/etl/v1/ping", headers={"Authorization": f"Bearer {OLD_PAHMA}"})
    assert response.json() == {"museum": "pahma"}


@pytest.mark.parametrize("header", [None, "Bearer", "Basic abc", "Bearer " + "x" * 43])
def test_no_or_unknown_token(client: TestClient, header: str | None) -> None:
    response = client.get("/etl/v1/ping", headers={"Authorization": header} if header else {})
    is_problem(response, 401)
    assert response.headers["www-authenticate"] == "Bearer"


def test_a_token_for_another_museum(client: TestClient) -> None:
    is_problem(client.post("/etl/v1/museums/cinefiles/runs", headers=auth("pahma")), 403)


def test_a_museum_serena_doesnt_serve(client: TestClient) -> None:
    is_problem(client.post("/etl/v1/museums/nowhere/runs", headers=auth()), 404)


def test_tokens_that_cant_be_read(store: Store, s3: Any, secretsmanager: Any) -> None:
    settings = Settings(tenants=TENANTS, table_prefix="t", etl_token_secret_ids={"pahma": "missing"}, _env_file=None)
    client = TestClient(create_app(settings, store, s3=s3, secretsmanager=secretsmanager))
    is_problem(client.get("/etl/v1/ping", headers=auth()), 503)


def test_a_rotation_reaches_the_task(store: Store, s3: Any, secretsmanager: Any) -> None:
    arn = secretsmanager.create_secret(Name="etl/r", SecretString=json.dumps({"current": TOKENS["pahma"]}))["ARN"]
    settings = Settings(tenants=TENANTS, table_prefix="t", etl_token_secret_ids={"pahma": arn},
                        secret_cache_seconds=0, _env_file=None)
    client = TestClient(create_app(settings, store, s3=s3, secretsmanager=secretsmanager))
    new = random.token_urlsafe(32)
    secretsmanager.put_secret_value(SecretId=arn, SecretString=json.dumps({"current": new}))
    assert client.get("/etl/v1/ping", headers={"Authorization": f"Bearer {new}"}).status_code == 200
    assert client.get("/etl/v1/ping", headers=auth()).status_code == 401


def test_the_token_is_never_logged(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    run = start(client)
    put(client, run, FILE)
    client.get("/etl/v1/ping", headers={"Authorization": "Bearer " + "y" * 43})
    for record in caplog.records:
        assert TOKENS["pahma"] not in record.getMessage()
        assert TOKENS["pahma"] not in json.dumps({k: str(v) for k, v in vars(record).items()})


# --- runs

def test_start_a_run(client: TestClient) -> None:
    response = client.post("/etl/v1/museums/pahma/runs", headers=auth())
    assert response.status_code == 201
    run = response.json()
    assert (run["run_id"], run["night"], run["state"]) == ("pahma-2026-10-10-1", "2026-10-10", "started")
    assert run["file_name"] == "blob-media.pahma.2026-10-10.tsv"
    assert (run["poll_interval_seconds"], run["step_timeout_seconds"]) == (15, 1800)
    assert run["links"]["blob_media"] == "/etl/v1/museums/pahma/runs/pahma-2026-10-10-1/blob-media"
    assert response.headers["cache-control"] == "no-store"


def test_starting_again_returns_the_open_run(client: TestClient) -> None:
    first = start(client)
    response = client.post("/etl/v1/museums/pahma/runs", headers=auth())
    assert response.status_code == 200
    assert response.json()["run_id"] == first["run_id"]


def test_the_night_is_the_pacific_date(client: TestClient, clock: Clock) -> None:
    clock.now = datetime(2026, 10, 10, 6, 59, tzinfo=UTC)  # 23:59 Pacific, October 9
    assert start(client)["night"] == "2026-10-09"


def test_an_admins_values_reach_the_etl(client: TestClient, store: Store) -> None:
    store.client.put_item(TableName=store.table(tables.SETTINGS), Item={
        "pk": {"S": "pahma"}, "values": {"S": json.dumps({"etl_poll_interval_seconds": 30})}})
    assert start(client)["poll_interval_seconds"] == 30


def test_a_later_night_abandons_an_earlier_open_run(client: TestClient, clock: Clock) -> None:
    first = start(client)
    clock.now = datetime(2026, 10, 11, 10, 30, tzinfo=UTC)
    second = start(client)
    assert second["run_id"] == "pahma-2026-10-11-1"
    old = client.get(first["links"]["self"], headers=auth()).json()
    assert old["state"] == "abandoned"
    assert old["reasons"] == ["a later night's run started"]


def test_a_later_night_waits_for_a_busy_run(client: TestClient, store: Store, clock: Clock) -> None:
    first = start(client)
    runs = Runs(store, clock)
    run = runs.get("pahma", first["run_id"])
    assert run is not None
    runs.transition(run, State.PREFLIGHTING)
    clock.now = datetime(2026, 10, 11, 10, 30, tzinfo=UTC)
    response = client.post("/etl/v1/museums/pahma/runs", headers=auth())
    is_problem(response, 409)
    assert "still being preflighted" in response.json()["detail"]


def test_a_new_run_the_same_night_once_closed(client: TestClient, store: Store, clock: Clock) -> None:
    first = start(client)
    runs = Runs(store, clock)
    run = runs.get("pahma", first["run_id"])
    assert run is not None
    runs.transition(run, State.ABANDONED)
    assert start(client)["run_id"] == "pahma-2026-10-10-2"


def test_museums_have_their_own_runs(client: TestClient) -> None:
    assert start(client, "pahma")["run_id"] != start(client, "ucjeps")["run_id"]
    is_problem(client.get("/etl/v1/museums/ucjeps/runs/pahma-2026-10-10-1", headers=auth("ucjeps")), 404)


@pytest.mark.parametrize("run_id", ["pahma-2026-10-10-9", "pahma-2026-13-01-1", "pahma-x", "pahma-2026-10-10-01"])
def test_no_such_run(client: TestClient, run_id: str) -> None:
    start(client)
    is_problem(client.get(f"/etl/v1/museums/pahma/runs/{run_id}", headers=auth()), 404)


# --- upload

def test_upload(client: TestClient, s3: Any) -> None:
    run = start(client)
    response = put(client, run, FILE)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "received"
    assert body["upload"]["rows"] == 3
    assert body["upload"]["sha256"] == hashlib.sha256(FILE).hexdigest()
    stored = s3.get_object(Bucket="b-pahma", Key="blob-media/pahma-2026-10-10-1/blob-media.pahma.2026-10-10.tsv.gz")
    assert gzip.decompress(stored["Body"].read()) == FILE


def test_upload_gzipped(client: TestClient) -> None:
    run = start(client)
    response = client.put(run["links"]["blob_media"], content=gzip.compress(FILE),
                          headers=upload_headers(FILE, **{"Content-Encoding": "gzip"}))
    assert response.status_code == 200, response.text
    assert response.json()["upload"]["rows"] == 3


def test_the_same_file_again_changes_nothing(client: TestClient) -> None:
    run = start(client)
    first = put(client, run, FILE).json()
    again = put(client, run, FILE).json()
    assert again["upload"] == first["upload"]


def test_a_corrected_file_replaces_the_previous_one(client: TestClient, store: Store, clock: Clock) -> None:
    run = start(client)
    put(client, run, FILE)
    runs = Runs(store, clock)
    current = runs.get("pahma", run["run_id"])
    assert current is not None
    runs.transition(current, State.PREFLIGHTING)
    is_problem(put(client, run, FILE + b"b9\tm9\timage\tpublic\n"), 409)  # not while it's being preflighted
    current = runs.get("pahma", run["run_id"])
    assert current is not None
    runs.transition(current, State.READY)
    corrected = put(client, run, FILE + b"b9\tm9\timage\tpublic\n").json()
    assert (corrected["state"], corrected["upload"]["rows"]) == ("received", 4)  # to be preflighted again


def test_no_upload_after_the_load_is_reported(client: TestClient, store: Store, clock: Clock) -> None:
    run = start(client)
    runs = Runs(store, clock)
    current = runs.get("pahma", run["run_id"])
    assert current is not None
    runs.transition(current, State.SOLR_LOADED)
    is_problem(put(client, run, FILE), 409)


@pytest.mark.parametrize(("headers", "status"), [
    ({"X-Content-SHA256": "0" * 64}, 422),
    ({"X-Row-Count": "4"}, 422),
    ({"X-Content-SHA256": "not-hex"}, 400),
    ({"X-Row-Count": "-1"}, 400),
    ({"Content-Type": "text/csv"}, 415),
    ({"Content-Encoding": "br"}, 415),
])
def test_upload_refused(client: TestClient, headers: dict[str, str], status: int) -> None:
    run = start(client)
    is_problem(client.put(run["links"]["blob_media"], content=FILE, headers={**upload_headers(FILE), **headers}),
               status)


def test_missing_headers(client: TestClient) -> None:
    run = start(client)
    response = client.put(run["links"]["blob_media"], content=FILE,
                          headers={**auth(), "Content-Type": "text/tab-separated-values"})
    is_problem(response, 400)
    assert "x-row-count" in response.json()["detail"]


def test_too_large(client: TestClient) -> None:
    run = start(client)
    body = HEADER.encode() + b"x" * (1024 * 1024)  # the limit is 1 MB in these tests
    is_problem(put(client, run, body), 413)


def test_too_large_when_decompressed(client: TestClient) -> None:
    run = start(client)
    bomb = gzip.compress(b"\n" * (5 * 1024 * 1024))  # a few KB that expand to 5 MB
    response = client.put(run["links"]["blob_media"], content=bomb,
                          headers={**upload_headers(b""), "Content-Encoding": "gzip"})
    is_problem(response, 413)


def test_bad_gzip(client: TestClient) -> None:
    run = start(client)
    response = client.put(run["links"]["blob_media"], content=b"not gzip",
                          headers={**upload_headers(FILE), "Content-Encoding": "gzip"})
    is_problem(response, 400)


# --- AWS failing

def test_storage_failing_is_503(client: TestClient, s3: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from botocore.exceptions import EndpointConnectionError

    run = start(client)

    def unreachable(*args: object, **kwargs: object) -> None:
        raise EndpointConnectionError(endpoint_url="https://s3.test")

    monkeypatch.setattr(s3, "upload_file", unreachable)
    response = put(client, run, FILE)
    is_problem(response, 503)
    assert "s3.test" not in response.text  # no internals


def test_records_failing_is_503(client: TestClient, store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    from botocore.exceptions import ClientError

    def throttled(**kwargs: object) -> None:
        raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "x"}}, "Query")

    monkeypatch.setattr(store.client, "query", throttled)
    is_problem(client.post("/etl/v1/museums/pahma/runs", headers=auth()), 503)


# --- documentation

def test_the_api_documentation_in_the_repository_is_current() -> None:
    saved = Path(__file__).parents[2] / "docs" / "api" / "etl-v1.json"
    assert saved.read_text() == etl_api.openapi_document(), (
        "docs/api/etl-v1.json is out of date: run  python -m serena.etl_api --openapi > ../docs/api/etl-v1.json")
