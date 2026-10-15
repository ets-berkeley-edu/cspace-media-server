"""The placeholder image from a Media record named on the Settings page, and Serena's generic picture until one is
(decided October 14, 2026, D166 to D173). Every CSID here is synthetic; PAHMA's placeholder Blob CSID is from its
configuration."""
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from conftest import TENANTS, add_blob
from fastapi.testclient import TestClient
from test_admin import CHANGES, Clock, make_app, sign_in

from fakecspace.app import USERS
from fakecspace.app import store as fake
from serena import cache_index
from serena.audit import Action, Audit
from serena.lookup import explain
from serena.museum import load
from serena.refreshes import Refreshes
from serena.store import Store

PAHMA = load("pahma")
PLACEHOLDER = PAHMA.placeholder_blob_csid
assert PLACEHOLDER is not None
RECORD = "3c4d5e6f-7081-4a92-8b3c-4d5e6f708192"
OTHER_BLOB = "4d5e6f70-8192-4aa3-9c4d-5e6f70819203"
URL = "/admin/v1/museums/pahma/settings/placeholder_media_csid"
SIZES: list[str | None] = [None, *PAHMA.derivatives]


@pytest.fixture(autouse=True)
def reset_fake() -> Iterator[None]:
    fake.reset()
    yield
    fake.reset()


@pytest.fixture
def client(store: Store, s3: Any, secretsmanager: Any) -> TestClient:
    """The app with the CollectionSpace simulator as every museum's CollectionSpace."""
    ids = {tenant: f"serena/test/{tenant}/cspace" for tenant in TENANTS}
    login = next(iter(USERS.items()))
    for secret_id in ids.values():
        secretsmanager.create_secret(Name=secret_id, SecretString=json.dumps(
            {"username": login[0], "password": login[1]}))
    app = make_app(store, s3, secretsmanager, cspace_secret_ids=ids, cspace_retries=1)
    app.state.admin.sessions.clock = Clock()
    for tenant in TENANTS:  # no waiting between retries in the tests
        app.state.fetcher.clients.get(tenant).sleep = lambda seconds: None
    return TestClient(app, base_url="http://testserver", follow_redirects=False)


def put(client: TestClient, value: str, reason: str = "PAHMA's own picture") -> Any:
    return client.put(URL, headers=CHANGES, json={"value": value, "reason": reason})


def test_until_a_record_is_named_the_generic_picture(client: TestClient, store: Store) -> None:
    add_blob(store, "pahma", PLACEHOLDER, None)  # listed by the ETL, with no Media CSID
    answer = client.get(f"/pahma/imageserver/blobs/{PLACEHOLDER}/derivatives/Medium/content")
    assert (answer.status_code, answer.headers["location"]) == (302, "/placeholder.svg")
    assert answer.headers["cache-control"] == "no-store"  # a museum's own picture shows as soon as it's named
    picture = client.get("/placeholder.svg")
    assert picture.headers["content-type"] == "image/svg+xml" and b"Image restricted" in picture.content


def test_naming_the_record(client: TestClient, store: Store) -> None:
    add_blob(store, "pahma", PLACEHOLDER, None)
    sign_in(client)
    assert client.get("/admin/v1/museums/pahma/settings").json()["placeholder"] == {
        "blob_csid": PLACEHOLDER, "identification_number": None}
    # Checked with CollectionSpace before it's saved (D170): nothing changes for a record that won't do.
    assert "no Media record" in put(client, RECORD).json()["detail"]
    fake.add(RECORD, state="deleted", blob=PLACEHOLDER)
    assert "soft-deleted" in put(client, RECORD).json()["detail"]
    fake.reset()
    fake.add(RECORD, kind="pdf", blob=PLACEHOLDER)
    refused = put(client, RECORD)
    assert refused.status_code == 422 and "original file can't be served" in refused.json()["detail"]
    assert all(cache_index.lookup(store, "pahma", PLACEHOLDER, size) is None for size in SIZES)  # all or none
    assert put(client, "not a csid").status_code == 422
    fake.reset()
    fake.add(RECORD, blob=PLACEHOLDER, identification_number="P-1")
    answer = put(client, RECORD)
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert "warning" not in body
    assert body["placeholder"]["identification_number"] == "P-1"
    setting = next(s for s in body["settings"] if s["name"] == "placeholder_media_csid")
    assert (setting["value"], setting["default"], setting["changed"]) == (RECORD, None, True)
    # Every size fetched and indexed under the placeholder's Blob (D172).
    assert all(cache_index.lookup(store, "pahma", PLACEHOLDER, size) is not None for size in SIZES)
    (entry,) = [e for e in Audit(store).since("pahma", datetime(2026, 1, 1, tzinfo=UTC))
                if e.action == Action.SETTINGS_CHANGE]
    assert (entry.target, entry.details["before"], entry.details["after"]) == ("placeholder_media_csid", None, RECORD)
    assert entry.details["identification_number"] == "P-1"
    assert entry.details["fetched"] == ["original", *PAHMA.derivatives]
    # Served now: Media look up says so, every size.
    looked = explain(PAHMA, PLACEHOLDER, store, Refreshes(store), placeholder_media=RECORD)
    (item,) = looked["items"]
    assert item["steps"][-1]["ok"] is True and RECORD in item["steps"][-1]["outcome"]
    assert {s["served"] for s in item["sizes"]} == {True}
    # "Use default" goes back to the generic picture.
    reset = client.post(f"{URL}/reset", headers=CHANGES, json={"reason": "back to the generic picture"})
    assert reset.status_code == 200
    setting = next(s for s in reset.json()["settings"] if s["name"] == "placeholder_media_csid")
    assert setting["value"] is None
    client.app.state.museum_settings.forget("pahma")  # type: ignore[attr-defined]
    answer = client.get(f"/pahma/imageserver/blobs/{PLACEHOLDER}/derivatives/Medium/content", follow_redirects=False)
    assert answer.headers["location"] == "/placeholder.svg"


def test_a_record_with_another_blob_is_saved_with_a_warning(client: TestClient, store: Store) -> None:
    add_blob(store, "pahma", PLACEHOLDER, None)
    sign_in(client)
    fake.add(RECORD, blob=OTHER_BLOB)
    answer = put(client, RECORD)
    assert answer.status_code == 200
    assert f"Blob ({OTHER_BLOB}) isn't the one the ETL lists" in answer.json()["warning"]


def test_when_collectionspace_cant_be_reached(client: TestClient) -> None:
    sign_in(client)
    fake.add(RECORD, blob=PLACEHOLDER)
    fake.fail("/cspace-services/media/", 503, times=10)
    answer = put(client, RECORD)
    assert answer.status_code == 503 and "can't be reached" in answer.json()["detail"]


@pytest.mark.parametrize("museum", ["bampfa"])
def test_a_museum_whose_etl_lists_no_placeholder(client: TestClient, store: Store, museum: str) -> None:
    """Ready for any ETL later (D167): the record is checked and named, with nothing to fetch yet."""
    sign_in(client, museum)
    fake.add(RECORD, blob=OTHER_BLOB)
    answer = client.put(f"/admin/v1/museums/{museum}/settings/placeholder_media_csid", headers=CHANGES,
                        json={"value": RECORD, "reason": "ready for later"})
    assert answer.status_code == 200
    assert answer.json()["placeholder"]["blob_csid"] is None
