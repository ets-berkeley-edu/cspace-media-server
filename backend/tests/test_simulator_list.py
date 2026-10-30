"""Manual refresh's "Make one from the simulator" (serena-fakecspace-questions F12): an ETL list made from the
CollectionSpace simulator's records, only where every museum's server is the simulator."""
import uuid
from typing import Any, cast

import pytest
from conftest import TENANTS
from etl_helpers import OLD_PAHMA, TOKENS
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_admin_refreshes import CHANGES, refresh_of

from fakecspace.app import ADMINS
from fakecspace.app import app as fake_app
from serena import museum
from serena.app import create_app
from serena.config import Settings, simulator_url
from serena.museum_settings import MuseumSettings
from serena.refreshes import Refreshes
from serena.store import Store
from serena.worker import Worker, WorkerServices

PLACEHOLDER = museum.load("pahma").placeholder_blob_csid


def csid() -> str:
    return str(uuid.uuid4())  # synthetic


def make(store: Store, s3: Any, secretsmanager: Any, clock: Any, simulated: bool) -> TestClient:
    import json
    ids = {}
    for tenant, token in TOKENS.items():
        value = {"current": token, "previous": OLD_PAHMA if tenant == "pahma" else ""}
        ids[tenant] = secretsmanager.create_secret(Name=f"etl/{tenant}/{simulated}",
                                                   SecretString=json.dumps(value))["ARN"]
    settings = Settings(tenants=TENANTS, table_prefix="t", buckets={t: f"b-{t}" for t in TENANTS},
                        etl_token_secret_ids=ids, upload_max_mb=1, admin_cookie_secure=False,
                        simulated_cspace=simulated, _env_file=None)
    app = create_app(settings, store, s3=s3, secretsmanager=secretsmanager, clock=clock,
                     cspace_http=lambda tenant: TestClient(fake_app, base_url=TENANTS[tenant]))
    browser = TestClient(app)
    response = browser.post("/admin/v1/sessions", headers=CHANGES,
                            json={"museum": "pahma", "username": "admin", "password": ADMINS["admin"]})
    assert response.status_code == 200, response.text
    return browser


@pytest.fixture
def admin(store: Store, s3: Any, secretsmanager: Any, clock: Any) -> TestClient:
    return make(store, s3, secretsmanager, clock, simulated=True)


def add(museum_key: str, **record: Any) -> dict[str, Any]:
    body = {"csid": csid(), "blob": csid(), "kind": "image", **record}
    response = TestClient(fake_app, base_url=TENANTS[museum_key]).post("/_fake/media", json=body)
    assert response.status_code == 200, response.text
    return body


def test_simulator_urls() -> None:
    assert simulator_url("http://pahma.fakecspace:8180")
    assert simulator_url("http://fakecspace.serena-dev.internal:8180/pahma")
    assert simulator_url("https://pahma.cspace.test")
    assert not simulator_url("https://pahma.cspace.berkeley.edu")
    assert not simulator_url("https://fakecspace-pahma.example.org")


def test_simulated_cspace_is_refused_with_a_real_collectionspace() -> None:
    with pytest.raises(ValidationError, match="not pahma"):
        Settings(tenants={**TENANTS, "pahma": "https://pahma.cspace.berkeley.edu"}, simulated_cspace=True,
                 _env_file=None)
    with pytest.raises(ValidationError, match="no museum is set"):
        Settings(tenants={}, simulated_cspace=True, _env_file=None)
    assert Settings(tenants=TENANTS, simulated_cspace=True, _env_file=None).simulated_cspace


def test_the_simulator_keeps_each_records_museum_and_access() -> None:
    pdf = add("cinefiles", kind="pdf", access="restricted")
    named = add("pahma", museum="ucjeps")  # the body's museum wins over the host name
    listed = TestClient(fake_app, base_url=TENANTS["cinefiles"]).get("/_fake/records").json()
    mine = next(r for r in listed if r["csid"] == pdf["csid"])
    assert (mine["kind"], mine["access"], mine["has_file"]) == ("pdf", "restricted", True)
    assert named["csid"] in {r["csid"] for r in TestClient(fake_app, base_url=TENANTS["ucjeps"]).get(
        "/_fake/records").json()}
    assert named["csid"] not in {r["csid"] for r in TestClient(fake_app, base_url=TENANTS["pahma"]).get(
        "/_fake/records").json()}
    bad = TestClient(fake_app).post("/_fake/media", json={"csid": csid(), "access": "secret"})
    assert bad.status_code == 400


def test_a_list_from_the_simulator(admin: TestClient) -> None:
    shown = add("pahma")
    card = add("pahma", kind="card")
    deleted = add("pahma")
    hidden = add("pahma")
    no_file = add("pahma")
    placeholder = add("pahma", blob=PLACEHOLDER, identification="Placeholder")
    fake = TestClient(fake_app, base_url=TENANTS["pahma"])
    assert fake.post(f"/_fake/delete/{deleted['csid']}").status_code == 200
    assert fake.post(f"/_fake/approve/{hidden['csid']}", json={"approved": False}).status_code == 200
    assert fake.post(f"/_fake/remove-file/{no_file['csid']}").status_code == 200

    response = admin.get("/admin/v1/museums/pahma/simulator/servable-list")
    assert response.status_code == 200, response.text
    body = response.json()
    lines = body["tsv"].splitlines()
    assert lines[0] == "blob_csid\tmedia_csid\tkind\taccess"
    assert body["rows"] == len(lines) - 1 and body["file_name"].startswith("simulator-pahma-")
    assert f"{shown['blob']}\t{shown['csid']}\timage\tpublic" in lines
    assert f"{card['blob']}\t{card['csid']}\tcard\tpublic" in lines
    if placeholder["blob"] == PLACEHOLDER:  # the placeholder image is listed without its Media CSID
        assert f"{PLACEHOLDER}\t\timage\tpublic" in lines
    for gone in (deleted, hidden, no_file):
        assert not any(gone["csid"] in line for line in lines)
    assert {"soft-deleted", "not approved for web", "no file"} <= set(body["left_out"])


def test_apply_a_list_from_the_simulator(admin: TestClient, store: Store, s3: Any, clock: Any) -> None:
    add("pahma")
    made = admin.get("/admin/v1/museums/pahma/simulator/servable-list").json()
    dry = admin.post("/admin/v1/museums/pahma/servable-lists/dry-run", content=made["tsv"].encode(), headers=CHANGES)
    assert dry.status_code == 200, dry.text
    headers = {**CHANGES, "X-Live-Core-Confirmed": "simulator", "X-File-Name": made["file_name"],
               "X-Refresh-Date": "", "X-Reason": "Testing%20a%20BMU%20upload"}
    started = admin.post("/admin/v1/museums/pahma/refreshes", content=made["tsv"].encode(), headers=headers)
    assert started.status_code == 201, started.text
    refresh = started.json()
    assert refresh["upload"]["rows"] == made["rows"]
    assert any(f"{made['file_name']} made from the simulator" in r for r in refresh["reasons"])
    services = WorkerServices(cast(Any, admin.app).state.settings, museum.load_all(TENANTS), MuseumSettings(store, 0),
                              Refreshes(store, clock), store, s3)
    assert Worker(services, sleep=lambda seconds: None).tick() == 1
    assert refresh_of(admin, refresh["refresh_id"])["state"] == "updated"


def test_only_where_every_museum_is_the_simulator(store: Store, s3: Any, secretsmanager: Any, clock: Any) -> None:
    admin = make(store, s3, secretsmanager, clock, simulated=False)
    assert admin.get("/admin/v1/me").json()["simulated_cspace"] is False
    assert admin.get("/admin/v1/museums/pahma/simulator/servable-list").status_code == 404
    refused = admin.post("/admin/v1/museums/pahma/refreshes", content=b"blob_csid\tmedia_csid\tkind\taccess\n",
                         headers={**CHANGES, "X-Live-Core-Confirmed": "simulator", "X-Reason": "Testing"})
    assert refused.status_code == 422


def test_the_simulator_not_answering(admin: TestClient) -> None:
    response = admin.get("/admin/v1/museums/pahma/simulator/servable-list")
    assert response.status_code == 200
    cast(Any, admin.app).state.admin.http = lambda tenant: _Failing()
    assert admin.get("/admin/v1/museums/pahma/simulator/servable-list").status_code == 503


class _Failing:
    def get(self, *args: Any, **kwargs: Any) -> Any:
        import httpx
        raise httpx.ConnectError("refused")
