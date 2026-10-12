import gzip
import json
from datetime import timedelta
from typing import Any

import pytest
from botocore.exceptions import ClientError
from conftest import TENANTS
from etl_helpers import OLD_PAHMA, TOKENS, auth, start
from fastapi.testclient import TestClient
from test_worker import file_of, upload

from fakecspace.app import ADMINS
from fakecspace.app import app as fake_app
from serena import museum, tables
from serena import servability_update as updating
from serena.alerts import Alert, Alerts, Kind
from serena.app import create_app
from serena.config import Settings
from serena.museum_settings import MuseumSettings
from serena.overrides import LIFETIME_SECONDS, Overrides
from serena.refreshes import Refreshes
from serena.store import Store
from serena.worker import Worker, WorkerServices

CHANGES = {"X-Serena-Admin": "1"}
BLOBS = {f"0a1b2c3d-0000-4000-8000-{n:012d}": f"1a2b3c4d-0000-4000-8000-{n:012d}" for n in range(40)}  # synthetic


class SecondsClock:
    def __init__(self) -> None:
        self.now = 1_791_590_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def app(store: Store, s3: Any, secretsmanager: Any, clock: Any) -> Any:
    ids = {}
    for tenant, token in TOKENS.items():
        value = {"current": token, "previous": OLD_PAHMA if tenant == "pahma" else ""}
        ids[tenant] = secretsmanager.create_secret(Name=f"etl/{tenant}", SecretString=json.dumps(value))["ARN"]
    settings = Settings(tenants=TENANTS, table_prefix="t", buckets={t: f"b-{t}" for t in TENANTS},
                        etl_token_secret_ids=ids, upload_max_mb=1, admin_cookie_secure=False, _env_file=None)
    built = create_app(settings, store, s3=s3, secretsmanager=secretsmanager, clock=clock,
                       cspace_http=lambda tenant: TestClient(fake_app, base_url=TENANTS[tenant]))
    built.state.admin_refreshes.overrides.clock = SecondsClock()
    return built


@pytest.fixture
def etl(app: Any) -> TestClient:
    return TestClient(app)


@pytest.fixture
def admin(app: Any) -> TestClient:
    browser = TestClient(app)
    response = browser.post("/admin/v1/sessions", headers=CHANGES,
                            json={"museum": "pahma", "username": "admin", "password": ADMINS["admin"]})
    assert response.status_code == 200, response.text
    return browser


@pytest.fixture
def worker(app: Any, store: Store, s3: Any, clock: Any) -> Worker:
    settings = app.state.settings
    services = WorkerServices(settings, museum.load_all(TENANTS), MuseumSettings(store, 0), Refreshes(store, clock),
                              store, s3, overrides=app.state.admin_refreshes.overrides)
    return Worker(services, sleep=lambda seconds: None)


def until_ready(etl: TestClient, worker: Worker, blobs: dict[str, str]) -> dict[str, Any]:
    """A refresh up to its servable list check's result, as the ETL job drives it."""
    refresh = start(etl)
    upload(etl, refresh, file_of(blobs))
    assert etl.post(refresh["links"]["check"], headers=auth()).status_code == 202
    assert worker.tick() == 1
    body: dict[str, Any] = etl.get(refresh["links"]["self"], headers=auth()).json()
    return body


def updated_refresh(etl: TestClient, worker: Worker, blobs: dict[str, str]) -> dict[str, Any]:
    refresh = until_ready(etl, worker, blobs)
    loaded = etl.post(refresh["links"]["solr_load"], json={"outcome": "loaded", "rows": 1}, headers=auth())
    assert loaded.status_code == 200
    assert etl.post(refresh["links"]["update"], headers=auth()).status_code == 202
    assert worker.tick() == 1
    body: dict[str, Any] = etl.get(refresh["links"]["self"], headers=auth()).json()
    assert body["state"] == "updated"
    return body


def refresh_of(admin: TestClient, refresh_id: str) -> dict[str, Any]:
    body: dict[str, Any] = admin.get(f"/admin/v1/museums/pahma/refreshes/{refresh_id}").json()
    return body


def audit(admin: TestClient) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = admin.get("/admin/v1/museums/pahma/audit").json()["entries"]
    return entries


# --- refreshes

def test_refreshes_and_a_refresh(admin: TestClient, etl: TestClient, worker: Worker) -> None:
    refresh = updated_refresh(etl, worker, BLOBS)
    refreshes = admin.get("/admin/v1/museums/pahma/refreshes").json()["refreshes"]
    assert [r["refresh_id"] for r in refreshes] == [refresh["refresh_id"]] and refreshes[0]["state"] == "updated"
    one = refresh_of(admin, refresh["refresh_id"])
    assert one["newest"] and one["actions"] == [] and one["upload"]["rows"] == len(BLOBS)
    assert one["update"]["written"] == len(BLOBS)
    assert admin.get("/admin/v1/museums/pahma/refreshes/pahma-2026-10-10-9").status_code == 404
    assert admin.get("/admin/v1/museums/cinefiles/refreshes").status_code == 401  # signed in to PAHMA only


# --- retrying a servability update (D63)

def failed_update(etl: TestClient, worker: Worker, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    refresh = until_ready(etl, worker, BLOBS)
    etl.post(refresh["links"]["solr_load"], json={"outcome": "loaded", "rows": 1}, headers=auth())
    etl.post(refresh["links"]["update"], headers=auth())

    def down(*args: Any, **kwargs: Any) -> None:
        raise ClientError({"Error": {"Code": "InternalServerError", "Message": "synthetic"}}, "BatchWriteItem")

    with monkeypatch.context() as patch:
        patch.setattr(updating, "update", down)
        worker.tick()
    body: dict[str, Any] = etl.get(refresh["links"]["self"], headers=auth()).json()
    assert body["state"] == "update_failed"
    return body


def test_retry_a_failed_update(admin: TestClient, etl: TestClient, worker: Worker,
                              monkeypatch: pytest.MonkeyPatch) -> None:
    refresh = failed_update(etl, worker, monkeypatch)
    assert refresh_of(admin, refresh["refresh_id"])["actions"] == ["retry_update"]
    url = f"/admin/v1/museums/pahma/refreshes/{refresh['refresh_id']}/retry-update"
    assert admin.post(url, json={"reason": "DynamoDB is back"}).status_code == 403  # without the app's header
    assert admin.post(url, headers=CHANGES, json={"reason": ""}).status_code == 422  # a reason is required
    response = admin.post(url, headers=CHANGES, json={"reason": "DynamoDB is back"})
    assert response.status_code == 200 and response.json()["state"] == "updating"
    assert worker.tick() == 1
    after = refresh_of(admin, refresh["refresh_id"])
    assert after["state"] == "updated"
    assert "servability update retried by an admin: DynamoDB is back" in after["reasons"]
    entry = audit(admin)[0]
    assert entry["action"] == "update_retry" and entry["target"] == refresh["refresh_id"]
    assert entry["details"] == {"reason": "DynamoDB is back"}


def test_no_retry_once_a_later_day_started(admin: TestClient, etl: TestClient, worker: Worker, clock: Any,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    refresh = failed_update(etl, worker, monkeypatch)
    clock.now += timedelta(days=1)
    start(etl)
    assert refresh_of(admin, refresh["refresh_id"])["actions"] == []
    response = admin.post(f"/admin/v1/museums/pahma/refreshes/{refresh['refresh_id']}/retry-update", headers=CHANGES,
                          json={"reason": "too late"})
    assert response.status_code == 409


# --- recording the load after a failed refresh (D65)

def test_record_the_load_and_update(admin: TestClient, etl: TestClient, worker: Worker) -> None:
    refresh = until_ready(etl, worker, BLOBS)  # the ETL never reported the load: a failed refresh
    assert refresh_of(admin, refresh["refresh_id"])["actions"] == ["record_load"]
    url = f"/admin/v1/museums/pahma/refreshes/{refresh['refresh_id']}/record-load"
    assert admin.post(url, headers=CHANGES, json={"confirmed": False, "reason": "ETL log checked"}).status_code == 422
    assert admin.post(url, headers=CHANGES, json={"confirmed": True, "reason": ""}).status_code == 422
    response = admin.post(url, headers=CHANGES, json={"confirmed": True, "rows": 1234, "reason": "ETL log checked"})
    assert response.status_code == 200 and response.json()["state"] == "updating"
    assert worker.tick() == 1
    after = refresh_of(admin, refresh["refresh_id"])
    assert after["state"] == "updated"
    assert after["solr_load"] == {"outcome": "loaded", "rows": 1234, "recorded_by_admin": True}
    assert audit(admin)[0]["action"] == "record_load"


# --- overriding the threshold, for the next refresh (D62, D64)

def changed(blobs: dict[str, str], share: float) -> dict[str, str]:
    """The same Blobs, with the first `share` of their Media CSIDs changed."""
    cut = int(len(blobs) * share)
    return {b: (m.replace("1a2b", "9a2b") if i < cut else m) for i, (b, m) in enumerate(blobs.items())}


def test_override_the_threshold_for_the_next_refresh(admin: TestClient, etl: TestClient, worker: Worker,
                                                 store: Store, s3: Any, clock: Any,
                                                 caplog: pytest.LogCaptureFixture) -> None:
    updated_refresh(etl, worker, BLOBS)
    clock.now += timedelta(days=1)
    big = changed(BLOBS, 0.5)
    failed = until_ready(etl, worker, big)
    assert failed["state"] == "check_failed"
    assert refresh_of(admin, failed["refresh_id"])["actions"] == ["override_threshold"]
    url = f"/admin/v1/museums/pahma/refreshes/{failed['refresh_id']}/override-threshold"
    response = admin.post(url, headers=CHANGES, json={"reason": "PAHMA republished half its images"})
    assert response.status_code == 200 and response.json()["override"]["after_refresh"] == failed["refresh_id"]
    status = admin.get("/admin/v1/museums/pahma/status").json()
    assert status["override"]["reason"] == "PAHMA republished half its images"
    assert status["unacknowledged"] == 1  # the override's alert, which the worker emails (D62)
    alert = admin.get("/admin/v1/museums/pahma/alerts").json()["alerts"][0]
    assert alert["kind"] == "threshold_overridden" and failed["refresh_id"] in alert["message"]
    assert refresh_of(admin, failed["refresh_id"])["actions"] == []  # armed: not offered again
    assert admin.post(url, headers=CHANGES, json={"reason": "twice"}).status_code == 409

    # The ETL team reruns the ETL job: the same refresh takes the servable list again, and its check uses the override.
    caplog.set_level("INFO", logger="serena.worker")
    rerun = until_ready(etl, worker, big)
    done = [r for r in caplog.records if r.getMessage() == "servable list check done"]
    assert done[-1].threshold_overridden is True  # type: ignore[attr-defined]
    assert rerun["refresh_id"] == failed["refresh_id"] and rerun["state"] == "ready"
    assert any("overridden by an admin" in w for w in rerun["check"]["warnings"])
    assert admin.get("/admin/v1/museums/pahma/status").json()["override"] is None  # used up

    # The emailed alert: the worker's resend sends it, the app has no SNS permission of its own.
    sns = __import__("boto3").client("sns", region_name="us-west-2")
    topic = sns.create_topic(Name="serena-alerts")["TopicArn"]
    assert Alerts(store, sns, topic).resend_unsent("pahma") == 1
    entry = audit(admin)[0]
    assert entry["action"] == "threshold_override" and entry["target"] == failed["refresh_id"]


def test_no_override_when_the_check_failed_otherwise(admin: TestClient, etl: TestClient,
                                                         worker: Worker, clock: Any) -> None:
    updated_refresh(etl, worker, BLOBS)
    clock.now += timedelta(days=1)
    bad = {**changed(BLOBS, 0.5), "not a CSID!": "1a2b3c4d-0000-4000-8000-000000000001"}
    failed = until_ready(etl, worker, bad)
    assert failed["state"] == "check_failed" and refresh_of(admin, failed["refresh_id"])["actions"] == []
    response = admin.post(f"/admin/v1/museums/pahma/refreshes/{failed['refresh_id']}/override-threshold",
                          headers=CHANGES, json={"reason": "no"})
    assert response.status_code == 409


def test_an_override_expires_and_can_be_cancelled(app: Any, admin: TestClient, etl: TestClient, worker: Worker,
                                                  clock: Any) -> None:
    updated_refresh(etl, worker, BLOBS)
    clock.now += timedelta(days=1)
    failed = until_ready(etl, worker, changed(BLOBS, 0.5))
    url = f"/admin/v1/museums/pahma/refreshes/{failed['refresh_id']}/override-threshold"
    admin.post(url, headers=CHANGES, json={"reason": "expected"})
    overrides: Overrides = app.state.admin_refreshes.overrides
    overrides.clock.now += LIFETIME_SECONDS  # type: ignore[attr-defined]
    assert admin.get("/admin/v1/museums/pahma/status").json()["override"] is None
    overrides.clock.now -= LIFETIME_SECONDS - 60  # type: ignore[attr-defined]
    admin.post(url, headers=CHANGES, json={"reason": "expected"})
    kinds = [a["kind"] for a in admin.get("/admin/v1/museums/pahma/alerts").json()["alerts"]]
    assert kinds.count("threshold_overridden") == 2  # armed again after the same refresh: recorded and emailed again
    assert admin.delete("/admin/v1/museums/pahma/threshold-override", headers=CHANGES).status_code == 200
    assert admin.get("/admin/v1/museums/pahma/status").json()["override"] is None
    assert audit(admin)[0]["action"] == "threshold_override_cancel"
    assert admin.delete("/admin/v1/museums/pahma/threshold-override", headers=CHANGES).status_code == 404


# --- an admin upload (D66)

def admin_upload(admin: TestClient, body: bytes, confirmed: bool = True,
                 reason: str = "ETL%20log%20checked%3A%20caf%C3%A9") -> Any:
    return admin.put("/admin/v1/museums/pahma/uploads", content=body, headers={
        **CHANGES, "X-Loaded-Confirmed": "yes" if confirmed else "",
        "X-File-Name": "servable-list.pahma.2026-10-09.tsv", "X-Refresh-Date": "2026-10-09", "X-Reason": reason})


@pytest.mark.parametrize("compress", [False, True])
def test_upload_a_days_file(admin: TestClient, etl: TestClient, worker: Worker, store: Store,
                              compress: bool) -> None:
    body = file_of(BLOBS)
    response = admin_upload(admin, gzip.compress(body) if compress else body)
    assert response.status_code == 200, response.text
    refresh = response.json()
    assert refresh["state"] == "checking" and refresh["upload"]["rows"] == len(BLOBS)
    assert refresh["uploaded_refresh_date"] == "2026-10-09"  # the refresh's own refresh date is today
    assert any("servable list uploaded by an admin: servable-list.pahma.2026-10-09.tsv, for the refresh date "
               "2026-10-09: ETL log checked: café" in r for r in refresh["reasons"])
    assert worker.tick() == 1  # the servable list check; it passes, and the servability update is queued at once
    assert refresh_of(admin, refresh["refresh_id"])["state"] == "updating"
    assert worker.tick() == 1
    assert refresh_of(admin, refresh["refresh_id"])["state"] == "updated"
    rows = store.client.scan(TableName=store.table(tables.SERVABILITY))["Items"]
    assert len(rows) == len(BLOBS)
    entry = audit(admin)[0]
    assert entry["action"] == "file_upload" and entry["details"]["rows"] == len(BLOBS)


def test_an_uploaded_file_that_fails_check_changes_nothing(admin: TestClient, worker: Worker,
                                                               store: Store) -> None:
    refresh = admin_upload(admin, b"not\ta\tservable\tlist\n").json()
    worker.tick()
    assert refresh_of(admin, refresh["refresh_id"])["state"] == "check_failed"
    assert store.client.scan(TableName=store.table(tables.SERVABILITY))["Items"] == []


def test_upload_refused(admin: TestClient, etl: TestClient) -> None:
    assert admin_upload(admin, file_of(BLOBS), confirmed=False).status_code == 422
    assert admin_upload(admin, file_of(BLOBS), reason="").status_code == 422
    start(etl)  # today's refresh is open
    assert admin_upload(admin, file_of(BLOBS)).status_code == 409


def test_upload_after_an_earlier_day_was_left_open(admin: TestClient, etl: TestClient, worker: Worker,
                                                     clock: Any) -> None:
    """Yesterday's servable list check failed (not on the threshold) and today no refresh started: the upload still
    works."""
    updated_refresh(etl, worker, BLOBS)
    clock.now += timedelta(days=1)
    failed = until_ready(etl, worker, {**BLOBS, "not a CSID!": "1a2b3c4d-0000-4000-8000-000000000001"})
    assert failed["state"] == "check_failed" and refresh_of(admin, failed["refresh_id"])["actions"] == []
    clock.now += timedelta(days=1)
    response = admin_upload(admin, file_of(BLOBS))
    assert response.status_code == 200, response.text
    assert refresh_of(admin, failed["refresh_id"])["state"] == "abandoned"


# --- alerts (D67)

def test_alerts_and_acknowledging(app: Any, admin: TestClient, store: Store) -> None:
    alerts = Alerts(store, None, "")
    alerts.raise_(Alert("pahma", "2026-10-10", Kind.MISSED_DEADLINE, "2026-10-10", "Today's refresh isn't finished"))
    alerts.raise_(Alert("cinefiles", "2026-10-10", Kind.MISSED_DEADLINE, "2026-10-10", "another museum's"))
    listed = admin.get("/admin/v1/museums/pahma/alerts").json()["alerts"]
    assert len(listed) == 1 and listed[0]["acknowledged_at"] is None
    assert admin.get("/admin/v1/museums/pahma/status").json()["unacknowledged"] == 1
    key = listed[0]["key"]
    assert admin.post("/admin/v1/museums/pahma/alerts/acknowledge", json={"key": key}).status_code == 403
    response = admin.post("/admin/v1/museums/pahma/alerts/acknowledge", headers=CHANGES, json={"key": key})
    assert response.status_code == 200
    after = admin.get("/admin/v1/museums/pahma/alerts").json()["alerts"][0]
    assert after["acknowledged_by"] == "admin" and after["acknowledged_at"]
    assert admin.get("/admin/v1/museums/pahma/status").json()["unacknowledged"] == 0
    assert admin.post("/admin/v1/museums/pahma/alerts/acknowledge", headers=CHANGES,
                      json={"key": key}).status_code == 409
    assert audit(admin)[0]["action"] == "alert_acknowledge"
