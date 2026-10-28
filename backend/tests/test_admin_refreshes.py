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
from serena.refreshes import Refresh, Refreshes, State, Upload, reason_kinds
from serena.store import Store
from serena.worker import Worker, WorkerServices

CHANGES = {"X-Serena-Admin": "1"}
BLOBS = {f"0a1b2c3d-0000-4000-8000-{n:012d}": f"1a2b3c4d-0000-4000-8000-{n:012d}" for n in range(40)}  # synthetic


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
                              store, s3)
    return Worker(services, sleep=lambda seconds: None)


def checked(etl: TestClient, worker: Worker, blobs: dict[str, str]) -> dict[str, Any]:
    """A refresh as the ETL job drives it, through one worker pass: the servable list check and, when it passes, the
    servability update (D80)."""
    refresh = start(etl)
    upload(etl, refresh, file_of(blobs))
    assert etl.post(refresh["links"]["check"], headers=auth()).status_code == 202
    assert worker.tick() == 1
    body: dict[str, Any] = etl.get(refresh["links"]["self"], headers=auth()).json()
    return body


def updated_refresh(etl: TestClient, worker: Worker, blobs: dict[str, str]) -> dict[str, Any]:
    body = checked(etl, worker, blobs)
    assert body["state"] == "updated"
    return body


def refresh_of(admin: TestClient, refresh_id: str) -> dict[str, Any]:
    body: dict[str, Any] = admin.get(f"/admin/v1/museums/pahma/refreshes/{refresh_id}").json()
    return body


def audit(admin: TestClient, actor: str = "admin") -> list[dict[str, Any]]:
    """The audit log's entries, newest first, by one actor: an admin, or "refresh" for refreshes' outcomes (D150)."""
    every: list[dict[str, Any]] = admin.get("/admin/v1/museums/pahma/audit").json()["entries"]
    entries = [e for e in every if (e["admin"].startswith("refresh ") if actor == "refresh" else e["admin"] == actor)]
    return entries


# --- refreshes

def test_refreshes_and_a_refresh(admin: TestClient, etl: TestClient, worker: Worker) -> None:
    refresh = updated_refresh(etl, worker, BLOBS)
    refreshes = admin.get("/admin/v1/museums/pahma/refreshes").json()["refreshes"]
    assert [r["refresh_id"] for r in refreshes] == [refresh["refresh_id"]] and refreshes[0]["state"] == "updated"
    one = refresh_of(admin, refresh["refresh_id"])
    assert one["newest"] and one["actions"] == [] and one["upload"]["rows"] == len(BLOBS) and not one["manual"]
    assert one["update"]["written"] == len(BLOBS)
    assert admin.get("/admin/v1/museums/pahma/refreshes/pahma-2026-10-10-9").status_code == 404
    assert admin.get("/admin/v1/museums/cinefiles/refreshes").status_code == 401  # signed in to PAHMA only


def test_the_current_and_pending_refreshes(admin: TestClient, etl: TestClient, worker: Worker,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """Mockup version 55: the current refresh is the newest updated one, the pending one the newest while it's open,
    with when the watchdog's deadline for its day passes (08:00 Pacific to start: 15:00 UTC in October)."""
    status = admin.get("/admin/v1/museums/pahma/status").json()
    assert (status["current"], status["pending"]) == (None, None)
    done = updated_refresh(etl, worker, BLOBS)
    status = admin.get("/admin/v1/museums/pahma/status").json()
    assert status["current"]["refresh_id"] == done["refresh_id"] and status["pending"] is None
    failed = failed_update(etl, worker, monkeypatch)
    status = admin.get("/admin/v1/museums/pahma/status").json()
    assert status["current"]["refresh_id"] == done["refresh_id"] and not status["current"]["newest"]
    pending = status["pending"]
    assert pending["refresh_id"] == failed["refresh_id"] and pending["state"] == "update_failed"
    assert pending["actions"] == ["retry_update"]
    assert pending["deadline_at"] == f"{failed['refresh_date']}T15:00:00Z"
    assert refresh_of(admin, failed["refresh_id"])["deadline_at"] == pending["deadline_at"]


# --- retrying a servability update (D63)

def failed_update(etl: TestClient, worker: Worker, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    refresh = start(etl)
    upload(etl, refresh, file_of(BLOBS))
    etl.post(refresh["links"]["check"], headers=auth())

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
    assert "ETL list update retried by admin: DynamoDB is back" in after["reasons"]
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
    assert response.json()["detail"].startswith("Not retried: the refresh pahma-2026-10-11-1 replaced it.")


# --- a failed update: the worker retries it by itself, and a retry that comes second (decided October 28, 2026)

def test_the_worker_retries_a_failed_update_every_10_minutes_for_6_hours(
        admin: TestClient, etl: TestClient, worker: Worker, clock: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    refresh = failed_update(etl, worker, monkeypatch)
    one = refresh_of(admin, refresh["refresh_id"])
    assert one["retry_until"] == "2026-10-10T16:30:00+00:00"  # 6 hours after it failed
    assert worker.tick() == 0  # not 10 minutes yet

    def down(*args: Any, **kwargs: Any) -> None:
        raise ClientError({"Error": {"Code": "InternalServerError", "Message": "synthetic"}}, "BatchWriteItem")

    with monkeypatch.context() as patch:
        patch.setattr(updating, "update", down)
        clock.now += timedelta(minutes=10)
        assert worker.tick() == 1
    again = refresh_of(admin, refresh["refresh_id"])
    # It failed the same way: the same time to stop, and no second copy of the reason.
    assert again["state"] == "update_failed" and again["retry_until"] == one["retry_until"]
    assert again["reasons"] == one["reasons"]
    clock.now += timedelta(minutes=10)
    assert worker.tick() == 1  # DynamoDB answers again
    assert refresh_of(admin, refresh["refresh_id"])["state"] == "updated"


def test_the_worker_stops_retrying_after_6_hours(admin: TestClient, etl: TestClient, worker: Worker, clock: Any,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    refresh = failed_update(etl, worker, monkeypatch)
    clock.now += timedelta(hours=6)
    assert worker.tick() == 0
    one = refresh_of(admin, refresh["refresh_id"])
    assert one["state"] == "update_failed" and one["actions"] == ["retry_update"]


def test_a_retry_that_comes_second(admin: TestClient, etl: TestClient, worker: Worker,
                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """Another admin's retry came first: Serena changes nothing, and says who (mockup version 56)."""
    refresh = failed_update(etl, worker, monkeypatch)
    url = f"/admin/v1/museums/pahma/refreshes/{refresh['refresh_id']}/retry-update"
    assert admin.post(url, headers=CHANGES, json={"reason": "DynamoDB is back"}).status_code == 200
    response = admin.post(url, headers=CHANGES, json={"reason": "trying too"})
    assert response.status_code == 409
    assert response.json()["detail"] == ("Not retried: admin retried it first, and Serena is applying the ETL list "
                                          "now. This page shows the refresh as it is.")
    one = refresh_of(admin, refresh["refresh_id"])
    assert not any("trying too" in reason for reason in one["reasons"])
    assert [e["details"]["reason"] for e in audit(admin) if e["action"] == "update_retry"] == ["DynamoDB is back"]


def test_the_worker_skips_a_retry_an_admin_made_first(admin: TestClient, etl: TestClient, worker: Worker, clock: Any,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    refresh = failed_update(etl, worker, monkeypatch)
    url = f"/admin/v1/museums/pahma/refreshes/{refresh['refresh_id']}/retry-update"
    stale = worker.s.refreshes.get("pahma", refresh["refresh_id"])
    assert stale is not None
    assert admin.post(url, headers=CHANGES, json={"reason": "DynamoDB is back"}).status_code == 200
    clock.now += timedelta(minutes=10)
    assert worker._retry(stale) is None  # read before the admin's retry: its conditional write fails
    assert worker.tick() == 1 and refresh_of(admin, refresh["refresh_id"])["state"] == "updated"


def test_the_local_stacks_failed_update(admin: TestClient, etl: TestClient, worker: Worker, store: Store,
                                        clock: Any) -> None:
    """devtools.failed_update, for testing checklist section 45: a failed update of the last updated ETL list, which
    the worker retries."""
    from devtools.failed_update import record

    refreshes = Refreshes(store, clock)
    assert record(refreshes, "pahma") is None  # nothing updated yet
    done = updated_refresh(etl, worker, BLOBS)
    failed = record(refreshes, "pahma")
    assert failed is not None and failed.state == State.UPDATE_FAILED and failed.retry_until
    assert refresh_of(admin, failed.refresh_id)["actions"] == ["retry_update"]
    assert refresh_of(admin, failed.refresh_id)["upload"]["sha256"] == done["upload"]["sha256"]
    clock.now += timedelta(minutes=10)
    assert worker.tick() == 1 and refresh_of(admin, failed.refresh_id)["state"] == "updated"


# --- overriding the delta threshold, for the failed refresh's own servable list (D62, D74, D83)

def changed(blobs: dict[str, str], share: float) -> dict[str, str]:
    """The same Blobs, with the first `share` of their Media CSIDs changed."""
    cut = int(len(blobs) * share)
    return {b: (m.replace("1a2b", "9a2b") if i < cut else m) for i, (b, m) in enumerate(blobs.items())}


def test_override_the_delta_threshold(admin: TestClient, etl: TestClient, worker: Worker, store: Store,
                                      clock: Any, caplog: pytest.LogCaptureFixture) -> None:
    updated_refresh(etl, worker, BLOBS)
    clock.now += timedelta(days=1)
    big = changed(BLOBS, 0.5)
    failed = checked(etl, worker, big)
    assert failed["state"] == "check_failed"
    assert refresh_of(admin, failed["refresh_id"])["actions"] == ["override_threshold"]
    url = f"/admin/v1/museums/pahma/refreshes/{failed['refresh_id']}/override-threshold"
    given = {"kind": "bulk_change", "reason": "PAHMA republished half its images"}
    assert admin.post(url, json=given).status_code == 403  # without the app's header
    assert admin.post(url, headers=CHANGES, json={"kind": "bulk_change", "reason": ""}).status_code == 422
    # Issue #120: why the change is expected, one of the kinds, and at least 20 characters of the admin's own words
    # (spaces run together count once).
    choose, more = "Choose why the change is expected.", "Say a little more: at least 20 characters."
    for body, said in [({"reason": given["reason"]}, choose), ({"kind": "because", "reason": given["reason"]}, choose),
                       ({"kind": "testing", "reason": "  too    short   "}, more)]:
        response = admin.post(url, headers=CHANGES, json=body)
        assert (response.status_code, response.json()["detail"]) == (422, said), body
    assert refresh_of(admin, failed["refresh_id"])["state"] == "check_failed"
    response = admin.post(url, headers=CHANGES, json={**given, "reason": " PAHMA republished  half its images "})
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "checking" and response.json()["actions"] == []
    # Who overrode it and why, with when, so the app can say so on every page (issue #108).
    override = response.json()["override"]
    assert (override["by"], override["kind"], override["reason"]) == ("admin", "bulk_change",
                                                                     "PAHMA republished half its images")
    assert override["at"]
    listed = admin.get("/admin/v1/museums/pahma/refreshes").json()["refreshes"]
    assert next(x for x in listed if x["refresh_id"] == failed["refresh_id"])["override"] == override
    assert admin.post(url, headers=CHANGES, json=given).status_code == 409
    status = admin.get("/admin/v1/museums/pahma/status").json()
    assert "override" not in status and status["unacknowledged"] == 1  # the override's alert (D62)
    alert = admin.get("/admin/v1/museums/pahma/alerts").json()["alerts"][0]
    assert alert["kind"] == "threshold_overridden" and failed["refresh_id"] in alert["message"]
    assert alert["title"] == "An admin overrode the delta threshold"
    assert alert["message"].endswith("Reason: Known bulk change in CollectionSpace: PAHMA republished half its images")

    # The worker checks the same servable list again without the delta threshold, then updates (no ETL rerun).
    caplog.set_level("INFO", logger="serena.worker")
    assert worker.tick() == 1
    after = refresh_of(admin, failed["refresh_id"])
    assert after["state"] == "updated" and after["update"]["written"] == len(BLOBS) // 2
    assert any("overridden by an admin" in w for w in after["check"]["warnings"])
    assert ("delta threshold overridden by an admin: Known bulk change in CollectionSpace: PAHMA republished half its "
            "images") in after["reasons"]
    # Issue #120: which list each reason goes in, recorded by Serena: the check's problem, then the override.
    assert after["reason_kinds"] == ["problem", "override"] and len(after["reasons"]) == 2
    assert after["override"] == override  # kept once the refresh is updated
    done = [r for r in caplog.records if r.getMessage() == "servable list check done"]
    assert done[-1].threshold_overridden is True  # type: ignore[attr-defined]
    assert worker.tick() == 0  # nothing left armed

    # The emailed alert: the worker's resend sends it, the app has no SNS permission of its own.
    sns = __import__("boto3").client("sns", region_name="us-west-2")
    topic = sns.create_topic(Name="serena-alerts")["TopicArn"]
    assert Alerts(store, sns, topic).resend_unsent("pahma") == 1
    entry = audit(admin)[0]
    assert entry["action"] == "threshold_override" and entry["target"] == failed["refresh_id"]
    assert entry["details"] == {"kind": "bulk_change", "reason": "PAHMA republished half its images",
                                "delta_percent": 50.0}


def test_no_override_when_the_check_failed_otherwise(admin: TestClient, etl: TestClient,
                                                         worker: Worker, clock: Any) -> None:
    updated_refresh(etl, worker, BLOBS)
    clock.now += timedelta(days=1)
    bad = {**changed(BLOBS, 0.5), "not a CSID!": "1a2b3c4d-0000-4000-8000-000000000001"}
    failed = checked(etl, worker, bad)
    assert failed["state"] == "check_failed" and refresh_of(admin, failed["refresh_id"])["actions"] == []
    response = admin.post(f"/admin/v1/museums/pahma/refreshes/{failed['refresh_id']}/override-threshold",
                          headers=CHANGES, json={"reason": "no"})
    assert response.status_code == 409


def test_a_new_list_drops_an_override(store: Store, clock: Any) -> None:
    """An override is for the list an admin looked at: a corrected list uploaded later is checked in full."""
    refreshes = Refreshes(store, clock)
    refresh, _ = refreshes.start("pahma")
    refresh = refreshes.transition(refresh, State.CHECK_FAILED, results={"override": {"at": "x"}})
    assert refresh.override is not None
    refresh = refreshes.transition(refresh, State.RECEIVED, upload=Upload("0" * 64, 1, 10, "k", "t"))
    stored = refreshes.get("pahma", refresh.refresh_id)
    assert refresh.override is None and stored is not None and stored.override is None


# --- a manual refresh (D66, D75, D82; issue #118): an uploaded list or one of the ETL's, checked, then waiting for an
# admin to run the servability update

def admin_refresh(admin: TestClient, body: bytes, confirmed: bool = True,
                 reason: str = "ETL%20log%20checked%3A%20caf%C3%A9", open_refresh: str = "") -> Any:
    return admin.post("/admin/v1/museums/pahma/refreshes", content=body, headers={
        **CHANGES, "X-Live-Core-Confirmed": "yes" if confirmed else "", "X-Open-Refresh": open_refresh,
        "X-File-Name": "servable-list.pahma.2026-10-09.tsv", "X-Refresh-Date": "2026-10-09", "X-Reason": reason})


def run_update(admin: TestClient, refresh_id: str, headers: dict[str, str] = CHANGES) -> Any:
    return admin.post(f"/admin/v1/museums/pahma/refreshes/{refresh_id}/run-update", headers=headers)


@pytest.mark.parametrize("compress", [False, True])
def test_a_manual_refresh(admin: TestClient, etl: TestClient, worker: Worker, store: Store, compress: bool) -> None:
    body = file_of(BLOBS)
    response = admin_refresh(admin, gzip.compress(body) if compress else body)
    assert response.status_code == 201, response.text
    refresh = response.json()
    assert refresh["state"] == "checking" and refresh["upload"]["rows"] == len(BLOBS)
    assert refresh["admin_refresh_date"] == "2026-10-09"  # the refresh's own refresh date is today
    assert refresh["manual"] and refresh["admin_refresh_from"] is None  # uploaded, not one of the ETL's lists
    assert any("manual refresh with the ETL list servable-list.pahma.2026-10-09.tsv, for the refresh date "
               "2026-10-09: ETL log checked: café" in r for r in refresh["reasons"])
    # The check passes; the refresh waits for an admin (MR9), and nothing changes until then.
    assert worker.tick() == 1
    waiting = refresh_of(admin, refresh["refresh_id"])
    assert waiting["state"] == "waiting" and waiting["actions"] == ["run_update"]
    assert waiting["check"]["result"] == "passed" and waiting["update"] is None
    assert store.client.scan(TableName=store.table(tables.SERVABILITY))["Items"] == []
    assert worker.tick() == 0  # the worker leaves it alone
    assert run_update(admin, refresh["refresh_id"], headers={}).status_code == 403  # without the app's header
    response = run_update(admin, refresh["refresh_id"])
    assert response.status_code == 200 and response.json()["state"] == "updating"
    assert run_update(admin, refresh["refresh_id"]).status_code == 409  # once
    assert worker.tick() == 1
    assert refresh_of(admin, refresh["refresh_id"])["state"] == "updated"
    rows = store.client.scan(TableName=store.table(tables.SERVABILITY))["Items"]
    assert len(rows) == len(BLOBS)
    ran, started = audit(admin)[:2]
    assert (ran["action"], ran["target"], ran["details"]) == ("update_run", refresh["refresh_id"], {})
    assert started["action"] == "admin_refresh" and started["details"]["rows"] == len(BLOBS)
    outcome = audit(admin, "refresh")[0]  # the refresh's outcome, by the refresh (D150)
    assert (outcome["action"], outcome["target"], outcome["details"]["state"]) == (
        "refresh_outcome", refresh["refresh_id"], "updated")


def test_a_manual_refresh_whose_check_fails_changes_nothing(admin: TestClient, worker: Worker,
                                                               store: Store) -> None:
    refresh = admin_refresh(admin, b"not\ta\tservable\tlist\n").json()
    worker.tick()
    assert refresh_of(admin, refresh["refresh_id"])["state"] == "check_failed"
    assert store.client.scan(TableName=store.table(tables.SERVABILITY))["Items"] == []
    assert run_update(admin, refresh["refresh_id"]).status_code == 409
    outcome = audit(admin, "refresh")[0]  # by the refresh, next to the ETL's calls (D150)
    assert (outcome["target"], outcome["details"]["state"]) == (refresh["refresh_id"], "check_failed")


def test_a_manual_refresh_refused(admin: TestClient, etl: TestClient) -> None:
    assert admin_refresh(admin, file_of(BLOBS), confirmed=False).status_code == 422
    assert admin_refresh(admin, file_of(BLOBS), reason="").status_code == 422
    refresh = start(etl)
    upload(etl, refresh, file_of(BLOBS))
    etl.post(refresh["links"]["check"], headers=auth())  # the worker is on it now
    response = admin_refresh(admin, file_of(BLOBS), open_refresh=refresh["refresh_id"])
    assert response.status_code == 409 and "wait for it to finish" in response.json()["detail"]


def test_a_manual_refresh_closes_only_the_open_refresh_it_was_shown(admin: TestClient, etl: TestClient,
                                                                    worker: Worker) -> None:
    """D82, MR13: the ETL job reached Serena, then failed; a manual refresh repairs it, once the admin confirms
    closing the open refresh the page named."""
    stuck = start(etl)
    upload(etl, stuck, file_of(BLOBS))  # received, never checked
    unnamed = admin_refresh(admin, file_of(BLOBS))
    assert unnamed.status_code == 409 and stuck["refresh_id"] in unnamed.json()["detail"]
    assert admin_refresh(admin, file_of(BLOBS), open_refresh="pahma-2026-10-10-9").status_code == 409
    assert refresh_of(admin, stuck["refresh_id"])["state"] == "received"  # still open: nothing was closed
    response = admin_refresh(admin, file_of(BLOBS), open_refresh=stuck["refresh_id"])
    assert response.status_code == 201, response.text
    new = response.json()
    assert new["refresh_id"] == stuck["refresh_id"][:-1] + "2"  # the same refresh date, the second refresh
    old = refresh_of(admin, stuck["refresh_id"])
    assert old["state"] == "abandoned" and f"closed by the manual refresh {new['refresh_id']}" in old["reasons"]
    assert old["reason_kinds"][-1] == "admin"  # issue #120: what admins did, on the refresh it closed
    assert refresh_of(admin, new["refresh_id"])["reason_kinds"] == ["admin"]  # the manual refresh itself
    assert worker.tick() == 1 and refresh_of(admin, new["refresh_id"])["state"] == "waiting"
    assert run_update(admin, new["refresh_id"]).status_code == 200
    assert worker.tick() == 1 and refresh_of(admin, new["refresh_id"])["state"] == "updated"
    outcomes = [(e["target"], e["details"]) for e in audit(admin, "refresh")]
    closing = {"state": "abandoned", "reasons": [f"closed by the manual refresh {new['refresh_id']}"]}
    assert (stuck["refresh_id"], closing) in outcomes  # D150
    assert (new["refresh_id"], "updated") in [(t, d["state"]) for t, d in outcomes]


def test_a_manual_refresh_after_an_earlier_day_was_left_open(admin: TestClient, etl: TestClient, worker: Worker,
                                                     clock: Any) -> None:
    """Yesterday's servable list check failed (not on the threshold) and today no refresh started: a manual refresh
    still works."""
    updated_refresh(etl, worker, BLOBS)
    clock.now += timedelta(days=1)
    failed = checked(etl, worker, {**BLOBS, "not a CSID!": "1a2b3c4d-0000-4000-8000-000000000001"})
    assert failed["state"] == "check_failed" and refresh_of(admin, failed["refresh_id"])["actions"] == []
    clock.now += timedelta(days=1)
    response = admin_refresh(admin, file_of(BLOBS), open_refresh=failed["refresh_id"])
    assert response.status_code == 201, response.text
    assert refresh_of(admin, failed["refresh_id"])["state"] == "abandoned"


def test_the_etls_recent_lists_and_a_manual_refresh_with_one(admin: TestClient, etl: TestClient, worker: Worker,
                                                            clock: Any) -> None:
    """MR3 to MR7: the ETL's lists, whatever their refresh's outcome, never an admin's upload; a manual refresh with
    one checks it again and is for that list's refresh date."""
    good = updated_refresh(etl, worker, BLOBS)
    clock.now += timedelta(days=1)
    failed = checked(etl, worker, changed(BLOBS, 0.5))  # fails on the delta threshold, and stays open
    lists = admin.get("/admin/v1/museums/pahma/servable-lists").json()["lists"]
    assert [x["refresh_id"] for x in lists] == [failed["refresh_id"], good["refresh_id"]]  # newest first
    assert (lists[0]["state"], lists[1]["state"]) == ("check_failed", "updated")
    assert lists[1]["rows"] == len(BLOBS) and len(lists[1]["sha256"]) == 64 and lists[1]["uploaded_at"]

    url = "/admin/v1/museums/pahma/refreshes/from-list"
    ask = {"refresh_id": good["refresh_id"], "reason": "yesterday's list", "open_refresh": failed["refresh_id"]}
    assert admin.post(url, json=ask).status_code == 403  # without the app's header
    assert admin.post(url, headers=CHANGES, json={**ask, "reason": ""}).status_code == 422
    assert admin.post(url, headers=CHANGES, json={**ask, "open_refresh": ""}).status_code == 409  # not confirmed
    assert admin.post(url, headers=CHANGES, json={**ask, "refresh_id": "pahma-2026-10-01-1"}).status_code == 404
    response = admin.post(url, headers=CHANGES, json=ask)
    assert response.status_code == 201, response.text
    new = response.json()
    assert new["state"] == "checking" and new["refresh_date"] == failed["refresh_date"]  # today's
    assert (new["admin_refresh_date"], new["admin_refresh_from"]) == (good["refresh_date"], good["refresh_id"])
    assert new["upload"]["sha256"] == lists[1]["sha256"] and new["upload"]["rows"] == len(BLOBS)
    assert any(f"manual refresh with the ETL list for {good['refresh_date']}, from {good['refresh_id']}: "
               "yesterday's list" in r for r in new["reasons"])
    assert refresh_of(admin, failed["refresh_id"])["state"] == "abandoned"
    started = audit(admin)[0]
    assert started["action"] == "admin_refresh" and started["details"]["from"] == good["refresh_id"]
    # A manual refresh's list isn't one of the ETL's, and the ETL's list can't be picked by a manual refresh's ID.
    assert [x["refresh_id"] for x in admin.get("/admin/v1/museums/pahma/servable-lists").json()["lists"]] == [
        failed["refresh_id"], good["refresh_id"]]
    again = {"refresh_id": new["refresh_id"], "reason": "no", "open_refresh": new["refresh_id"]}
    assert admin.post(url, headers=CHANGES, json=again).status_code == 404
    assert worker.tick() == 1 and refresh_of(admin, new["refresh_id"])["state"] == "waiting"  # no change: it passes


def test_a_waiting_refresh_is_closed_by_the_next_refresh(admin: TestClient, etl: TestClient, worker: Worker) -> None:
    """MR9: a passed manual refresh nobody updated is closed as abandoned when the ETL starts a refresh, even the same
    day; it never times out."""
    waiting = admin_refresh(admin, file_of(BLOBS)).json()
    assert worker.tick() == 1 and refresh_of(admin, waiting["refresh_id"])["state"] == "waiting"
    nightly = start(etl)
    assert nightly["refresh_id"] != waiting["refresh_id"]  # a new refresh, not the waiting one
    closed = refresh_of(admin, waiting["refresh_id"])
    assert closed["state"] == "abandoned" and closed["actions"] == []
    assert "a later refresh started before the ETL list update ran" in closed["reasons"]
    assert closed["reason_kinds"] == ["admin", "problem"]  # issue #120: the ETL's refresh closed it, not an admin
    outcome = audit(admin, "refresh")[0]
    assert (outcome["target"], outcome["details"]["reasons"]) == (
        waiting["refresh_id"], ["a later refresh started before the ETL list update ran"])


def test_an_override_on_a_manual_refresh_waits_too(admin: TestClient, etl: TestClient, worker: Worker,
                                                   clock: Any) -> None:
    """MR11: overriding a manual refresh's delta threshold checks its list again; on a pass it waits for the same
    button as a passed check."""
    updated_refresh(etl, worker, BLOBS)
    clock.now += timedelta(days=1)
    failed = admin_refresh(admin, file_of(changed(BLOBS, 0.5))).json()
    assert worker.tick() == 1 and refresh_of(admin, failed["refresh_id"])["actions"] == ["override_threshold"]
    response = admin.post(f"/admin/v1/museums/pahma/refreshes/{failed['refresh_id']}/override-threshold",
                          headers=CHANGES, json={"kind": "bulk_change", "reason": "PAHMA republished half its images"})
    assert response.status_code == 200, response.text
    alert = admin.get("/admin/v1/museums/pahma/alerts").json()["alerts"][0]
    assert "on a pass, waits for an admin to run the ETL list update" in alert["message"]
    assert worker.tick() == 1
    after = refresh_of(admin, failed["refresh_id"])
    assert after["state"] == "waiting" and after["actions"] == ["run_update"] and after["override"]
    assert run_update(admin, failed["refresh_id"]).status_code == 200
    assert worker.tick() == 1 and refresh_of(admin, failed["refresh_id"])["state"] == "updated"


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


def test_acknowledging_all(app: Any, admin: TestClient, store: Store) -> None:
    """Acknowledge all (D207 to D210): the keys the page shows, one audit entry each, others skipped."""
    alerts = Alerts(store, None, "")
    for day in ("2026-10-08", "2026-10-09", "2026-10-10"):
        alerts.raise_(Alert("pahma", day, Kind.MISSED_DEADLINE, day, f"Not finished on {day}"))
    # Another museum's alert, on a day PAHMA has none: its key (unique only within a museum) names nothing of PAHMA's.
    alerts.raise_(Alert("cinefiles", "2026-10-07", Kind.MISSED_DEADLINE, "2026-10-07", "another museum's"))
    keys = [a["key"] for a in admin.get("/admin/v1/museums/pahma/alerts").json()["alerts"]]
    cinefiles_key = "2026-10-07#missed_deadline#2026-10-07"
    # One was acknowledged meanwhile (another admin): it's skipped, not an error.
    one = admin.post("/admin/v1/museums/pahma/alerts/acknowledge", headers=CHANGES, json={"key": keys[0]})
    assert one.status_code == 200
    url = "/admin/v1/museums/pahma/alerts/acknowledge-all"
    assert admin.post(url, json={"keys": keys}).status_code == 403  # a change needs the header
    response = admin.post(url, headers=CHANGES, json={"keys": [*keys, keys[1], cinefiles_key, "no such alert"]})
    assert response.status_code == 200, response.text
    assert response.json() == {"acknowledged": keys[1:], "skipped": 3}
    listed = admin.get("/admin/v1/museums/pahma/alerts").json()["alerts"]
    assert all(a["acknowledged_by"] == "admin" and a["acknowledged_at"] for a in listed)
    assert admin.get("/admin/v1/museums/pahma/status").json()["unacknowledged"] == 0
    # The other museum's alert, named by its key while signed in to PAHMA, is untouched.
    assert alerts.recent("cinefiles", "2026-10-01")[0]["acknowledged_at"] is None
    acknowledged = [e for e in audit(admin) if e["action"] == "alert_acknowledge"]
    assert sorted(e["target"] for e in acknowledged) == sorted(keys)  # one entry per alert, the earlier one included
    # Nothing to do, too many, or a bad key: refused.
    assert admin.post(url, headers=CHANGES, json={"keys": []}).status_code == 422
    assert admin.post(url, headers=CHANGES, json={"keys": [f"k{i}" for i in range(501)]}).status_code == 422
    assert admin.post(url, headers=CHANGES, json={"keys": ["x" * 201]}).status_code == 422


def test_reasons_from_before_their_kinds_are_what_went_wrong(store: Store, clock: Any) -> None:
    """Issue #120: a reason recorded before Serena recorded kinds has none and counts as what went wrong; the kinds
    recorded since belong to the newest reasons."""
    refreshes = Refreshes(store)
    refresh, _ = refreshes.start("pahma")
    refresh = refreshes.transition(refresh, State.CHECK_FAILED, reason="no ETL list uploaded")
    refresh.reasons.insert(0, "an older reason")  # as if recorded before
    assert reason_kinds(refresh) == ["problem", "problem"]
    refresh.reason_kinds = ["admin"]
    assert reason_kinds(refresh) == ["problem", "admin"]
    assert reason_kinds(Refresh("pahma", "2026-10-10", 1, State.STARTED, "x", "x")) == []
