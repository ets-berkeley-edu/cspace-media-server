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
from etl_helpers import FILE, HEADER, OLD_PAHMA, TOKENS, Clock, auth, is_problem, put, start, upload_headers
from fastapi.testclient import TestClient

from serena import etl_api, tables
from serena.app import create_app
from serena.config import Settings
from serena.refreshes import Refreshes, State
from serena.store import Store

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
    is_problem(client.post("/etl/v1/museums/cinefiles/refreshes", headers=auth("pahma")), 403)


def test_a_museum_serena_doesnt_serve(client: TestClient) -> None:
    is_problem(client.post("/etl/v1/museums/nowhere/refreshes", headers=auth()), 404)


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
    refresh = start(client)
    put(client, refresh, FILE)
    client.get("/etl/v1/ping", headers={"Authorization": "Bearer " + "y" * 43})
    for record in caplog.records:
        assert TOKENS["pahma"] not in record.getMessage()
        assert TOKENS["pahma"] not in json.dumps({k: str(v) for k, v in vars(record).items()})


# --- refreshes

def test_start_a_refresh(client: TestClient) -> None:
    response = client.post("/etl/v1/museums/pahma/refreshes", headers=auth())
    assert response.status_code == 201
    refresh = response.json()
    assert (refresh["refresh_id"], refresh["refresh_date"], refresh["state"]) == ("pahma-2026-10-10-1", "2026-10-10",
                                                                                 "started")
    assert refresh["file_name"] == "servable-list.pahma.2026-10-10.tsv"
    assert (refresh["poll_interval_seconds"], refresh["step_timeout_seconds"]) == (15, 1800)
    assert refresh["links"]["servable_list"] == "/etl/v1/museums/pahma/refreshes/pahma-2026-10-10-1/servable-list"
    assert response.headers["cache-control"] == "no-store"


def test_starting_again_returns_the_open_refresh(client: TestClient) -> None:
    first = start(client)
    response = client.post("/etl/v1/museums/pahma/refreshes", headers=auth())
    assert response.status_code == 200
    assert response.json()["refresh_id"] == first["refresh_id"]


def test_the_day_is_the_pacific_date(client: TestClient, clock: Clock) -> None:
    clock.now = datetime(2026, 10, 10, 6, 59, tzinfo=UTC)  # 23:59 Pacific, October 9
    assert start(client)["refresh_date"] == "2026-10-09"


def test_an_admins_values_reach_the_etl(client: TestClient, store: Store) -> None:
    store.client.put_item(TableName=store.table(tables.SETTINGS), Item={
        "pk": {"S": "pahma"}, "values": {"S": json.dumps({"etl_poll_interval_seconds": 30})}})
    assert start(client)["poll_interval_seconds"] == 30


def test_a_later_day_abandons_an_earlier_open_refresh(client: TestClient, clock: Clock) -> None:
    first = start(client)
    clock.now = datetime(2026, 10, 11, 10, 30, tzinfo=UTC)
    second = start(client)
    assert second["refresh_id"] == "pahma-2026-10-11-1"
    old = client.get(first["links"]["self"], headers=auth()).json()
    assert old["state"] == "abandoned"
    assert old["reasons"] == ["a later refresh date's refresh started"]


def test_a_later_day_waits_for_a_busy_refresh(client: TestClient, store: Store, clock: Clock) -> None:
    first = start(client)
    refreshes = Refreshes(store, clock)
    refresh = refreshes.get("pahma", first["refresh_id"])
    assert refresh is not None
    refreshes.transition(refresh, State.CHECKING)
    clock.now = datetime(2026, 10, 11, 10, 30, tzinfo=UTC)
    response = client.post("/etl/v1/museums/pahma/refreshes", headers=auth())
    is_problem(response, 409)
    assert "still being checked" in response.json()["detail"]


def test_a_new_refresh_the_same_day_once_closed(client: TestClient, store: Store, clock: Clock) -> None:
    first = start(client)
    refreshes = Refreshes(store, clock)
    refresh = refreshes.get("pahma", first["refresh_id"])
    assert refresh is not None
    refreshes.transition(refresh, State.ABANDONED)
    assert start(client)["refresh_id"] == "pahma-2026-10-10-2"


def test_museums_have_their_own_refreshes(client: TestClient) -> None:
    assert start(client, "pahma")["refresh_id"] != start(client, "ucjeps")["refresh_id"]
    is_problem(client.get("/etl/v1/museums/ucjeps/refreshes/pahma-2026-10-10-1", headers=auth("ucjeps")), 404)


@pytest.mark.parametrize("refresh_id", ["pahma-2026-10-10-9", "pahma-2026-13-01-1", "pahma-x", "pahma-2026-10-10-01"])
def test_no_such_refresh(client: TestClient, refresh_id: str) -> None:
    start(client)
    is_problem(client.get(f"/etl/v1/museums/pahma/refreshes/{refresh_id}", headers=auth()), 404)


# --- upload

def test_upload(client: TestClient, s3: Any) -> None:
    refresh = start(client)
    response = put(client, refresh, FILE)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "received"
    assert body["upload"]["rows"] == 3
    assert body["upload"]["sha256"] == hashlib.sha256(FILE).hexdigest()
    key = "servable-list/pahma-2026-10-10-1/servable-list.pahma.2026-10-10.tsv.gz"
    stored = s3.get_object(Bucket="b-pahma", Key=key)
    assert gzip.decompress(stored["Body"].read()) == FILE


def test_upload_gzipped(client: TestClient) -> None:
    refresh = start(client)
    response = client.put(refresh["links"]["servable_list"], content=gzip.compress(FILE),
                          headers=upload_headers(FILE, **{"Content-Encoding": "gzip"}))
    assert response.status_code == 200, response.text
    assert response.json()["upload"]["rows"] == 3


def test_the_same_file_again_changes_nothing(client: TestClient) -> None:
    refresh = start(client)
    first = put(client, refresh, FILE).json()
    again = put(client, refresh, FILE).json()
    assert again["upload"] == first["upload"]


def test_a_corrected_file_replaces_the_previous_one(client: TestClient, store: Store, clock: Clock) -> None:
    refresh = start(client)
    put(client, refresh, FILE)
    refreshes = Refreshes(store, clock)
    current = refreshes.get("pahma", refresh["refresh_id"])
    assert current is not None
    refreshes.transition(current, State.CHECKING)
    is_problem(put(client, refresh, FILE + b"b9\tm9\timage\tpublic\n"), 409)  # not while it's being checked
    current = refreshes.get("pahma", refresh["refresh_id"])
    assert current is not None
    refreshes.transition(current, State.READY)
    corrected = put(client, refresh, FILE + b"b9\tm9\timage\tpublic\n").json()
    assert (corrected["state"], corrected["upload"]["rows"]) == ("received", 4)  # to be checked again


def test_no_upload_after_the_load_is_reported(client: TestClient, store: Store, clock: Clock) -> None:
    refresh = start(client)
    refreshes = Refreshes(store, clock)
    current = refreshes.get("pahma", refresh["refresh_id"])
    assert current is not None
    refreshes.transition(current, State.SOLR_LOADED)
    is_problem(put(client, refresh, FILE), 409)


@pytest.mark.parametrize(("headers", "status"), [
    ({"X-Content-SHA256": "0" * 64}, 422),
    ({"X-Row-Count": "4"}, 422),
    ({"X-Content-SHA256": "not-hex"}, 400),
    ({"X-Row-Count": "-1"}, 400),
    ({"Content-Type": "text/csv"}, 415),
    ({"Content-Encoding": "br"}, 415),
])
def test_upload_refused(client: TestClient, headers: dict[str, str], status: int) -> None:
    refresh = start(client)
    is_problem(client.put(refresh["links"]["servable_list"], content=FILE, headers={**upload_headers(FILE), **headers}),
               status)


def test_missing_headers(client: TestClient) -> None:
    refresh = start(client)
    response = client.put(refresh["links"]["servable_list"], content=FILE,
                          headers={**auth(), "Content-Type": "text/tab-separated-values"})
    is_problem(response, 400)
    assert "x-row-count" in response.json()["detail"]


def test_too_large(client: TestClient) -> None:
    refresh = start(client)
    body = HEADER.encode() + b"x" * (1024 * 1024)  # the limit is 1 MB in these tests
    is_problem(put(client, refresh, body), 413)


def test_too_large_when_decompressed(client: TestClient) -> None:
    refresh = start(client)
    bomb = gzip.compress(b"\n" * (5 * 1024 * 1024))  # a few KB that expand to 5 MB
    response = client.put(refresh["links"]["servable_list"], content=bomb,
                          headers={**upload_headers(b""), "Content-Encoding": "gzip"})
    is_problem(response, 413)


def test_bad_gzip(client: TestClient) -> None:
    refresh = start(client)
    response = client.put(refresh["links"]["servable_list"], content=b"not gzip",
                          headers={**upload_headers(FILE), "Content-Encoding": "gzip"})
    is_problem(response, 400)


# --- AWS failing

def test_storage_failing_is_503(client: TestClient, s3: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from botocore.exceptions import EndpointConnectionError

    refresh = start(client)

    def unreachable(*args: object, **kwargs: object) -> None:
        raise EndpointConnectionError(endpoint_url="https://s3.test")

    monkeypatch.setattr(s3, "upload_file", unreachable)
    response = put(client, refresh, FILE)
    is_problem(response, 503)
    assert "s3.test" not in response.text  # no internals


def test_records_failing_is_503(client: TestClient, store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    from botocore.exceptions import ClientError

    def throttled(**kwargs: object) -> None:
        raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "x"}}, "Query")

    monkeypatch.setattr(store.client, "query", throttled)
    is_problem(client.post("/etl/v1/museums/pahma/refreshes", headers=auth()), 503)


# --- documentation

def test_the_api_documentation_in_the_repository_is_current() -> None:
    saved = Path(__file__).parents[2] / "docs" / "api" / "etl-v1.json"
    assert saved.read_text() == etl_api.openapi_document(), (
        "docs/api/etl-v1.json is out of date: run  python -m serena.etl_api --openapi > ../docs/api/etl-v1.json")
