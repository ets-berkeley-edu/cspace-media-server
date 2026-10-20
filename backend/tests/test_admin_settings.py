"""The Settings page's API, the audit log's 30 days, its CSV export and its retention (decided October 12, 2026, D86
to D99)."""
import csv
import io
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from conftest import TENANTS
from fastapi.testclient import TestClient
from test_admin import CHANGES, Clock, make_app, sign_in

from serena import museum, tables
from serena.audit import Action, Audit
from serena.config import Settings
from serena.museum_settings import MuseumSettings
from serena.refreshes import Refreshes
from serena.store import Store
from serena.worker import Worker, WorkerServices

URL = "/admin/v1/museums/pahma/settings"


@pytest.fixture
def app(store: Store, s3: Any, secretsmanager: Any) -> Any:
    built = make_app(store, s3, secretsmanager)
    built.state.admin.sessions.clock = Clock()
    return built


@pytest.fixture
def client(app: Any) -> TestClient:
    return TestClient(app, base_url="http://testserver")


def settings_of(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["name"]: s for s in body["settings"]}


def put(client: TestClient, name: str, value: Any, reason: str = "PAHMA asked for it") -> Any:
    return client.put(f"{URL}/{name}", headers=CHANGES, json={"value": value, "reason": reason})


def kinds_of_alerts(store: Store) -> list[str]:
    return sorted(i["kind"]["S"] for i in store.client.scan(TableName=store.table(tables.ALERTS))["Items"])


def test_the_settings_and_their_default_values(client: TestClient) -> None:
    assert client.get(URL).status_code == 401
    sign_in(client)
    body = client.get(URL).json()
    settings = settings_of(body)
    assert list(settings) == ["watchdog_deadline", "etl_poll_interval_seconds", "etl_step_timeout_seconds",
                              "delta_threshold_percent", "size_limit_mb.image", "size_limit_mb.card",
                              "size_limit_mb.3D", "size_limit_mb.pdf", "audit_retention_days",
                              "placeholder_media_csid"]
    assert settings["watchdog_deadline"] == {"name": "watchdog_deadline", "group": "watchdog",
                                             "label": "Deadline for today's refresh (HH:MM, Pacific)",
                                             "value": "08:00", "default": "08:00", "changed": False,
                                             "kind": "time", "min": None, "max": None}
    # What each value must be, from StartingSettings' bounds, for the admin app to check on Save (D219).
    assert [(settings[n]["kind"], settings[n]["min"], settings[n]["max"]) for n in
            ("etl_poll_interval_seconds", "etl_step_timeout_seconds", "delta_threshold_percent", "size_limit_mb.pdf",
             "audit_retention_days", "placeholder_media_csid")] == [
        ("whole", 5, 300), ("whole", 60, 7200), ("number", 0.1, 100), ("whole", 1, 2048), ("choice", None, None),
        ("csid", None, None)]
    assert [c["days"] for c in body["audit_retention_choices"]] == [90, 183, 365, 548, 730, 1095]
    # The size limits name each kind as people read it: "catalog card", not the raw "card" (D151).
    assert [settings[f"size_limit_mb.{kind}"]["label"] for kind in ("image", "card", "3D", "pdf")] == [
        "Largest image file fetched (MB)", "Largest catalog card file fetched (MB)",
        "Largest 3D model file fetched (MB)", "Largest PDF file fetched (MB)"]


def test_change_a_setting(app: Any, client: TestClient, store: Store) -> None:
    sign_in(client)
    response = put(client, "etl_step_timeout_seconds", 900)
    assert response.status_code == 200, response.text
    assert settings_of(response.json())["etl_step_timeout_seconds"] | {"label": ""} == {
        "name": "etl_step_timeout_seconds", "group": "etl", "label": "", "value": 900, "default": 1800,
        "changed": True, "kind": "whole", "min": 60, "max": 7200}
    # The app reads it at once (the other tasks within a minute), and so does the ETL API.
    assert app.state.museum_settings.get(museum.load("pahma")).etl_step_timeout_seconds == 900
    entry = client.get("/admin/v1/museums/pahma/audit").json()["entries"][0]
    assert (entry["action"], entry["target"]) == ("settings_change", "etl_step_timeout_seconds")
    assert entry["details"] == {"before": 1800, "after": 900, "reason": "PAHMA asked for it"}
    assert kinds_of_alerts(store) == []  # not a protection: no alert


def test_weakening_a_protection_is_emailed(client: TestClient, store: Store) -> None:
    sign_in(client)
    assert put(client, "delta_threshold_percent", 12.5).status_code == 200
    assert put(client, "audit_retention_days", 365).status_code == 200
    assert kinds_of_alerts(store) == ["setting_changed", "setting_changed"]
    alerts = client.get("/admin/v1/museums/pahma/alerts").json()["alerts"]
    assert {a["title"] for a in alerts} == {"An admin changed a setting"}
    messages = sorted(a["message"] for a in alerts)
    assert messages[0] == ("An admin changed a setting for PAHMA: Delta threshold (%), from 5.0 to 12.5. Reason: PAHMA "
                           "asked for it")
    assert "How long the audit log is kept (days), from 90 to 365" in messages[1]


@pytest.mark.parametrize(("name", "value", "problem"), [
    ("etl_step_timeout_seconds", 10, "ETL step timeout (seconds): give a whole number from 60 to 7,200."),
    ("etl_poll_interval_seconds", 301, "ETL poll interval (seconds): give a whole number from 5 to 300."),
    ("etl_poll_interval_seconds", "12.5", "ETL poll interval (seconds): give a whole number from 5 to 300."),
    ("delta_threshold_percent", 0.05, "Delta threshold (%): give a number from 0.1 to 100."),
    ("delta_threshold_percent", "5d", "Delta threshold (%): give a number from 0.1 to 100."),
    ("watchdog_deadline", "8am", "Deadline for today's refresh (HH:MM, Pacific): give a time as HH:MM, from 00:00 to "
                                 "23:59."),
    ("size_limit_mb.pdf", 4096, "Largest PDF file fetched (MB): give a whole number from 1 to 2,048."),
    ("audit_retention_days", 30, "How long the audit log is kept (days): give one of 90, 183, 365, 548, 730, 1,095."),
])
def test_values_out_of_bounds_are_refused(client: TestClient, name: str, value: Any, problem: str) -> None:
    """In words, never pydantic's (D221), and nothing is saved."""
    sign_in(client)
    response = put(client, name, value)
    assert response.status_code == 422 and response.json()["detail"] == problem


def test_refused_without_the_header_a_reason_or_a_known_setting(client: TestClient) -> None:
    sign_in(client)
    assert client.put(f"{URL}/watchdog_deadline", json={"value": "07:30", "reason": "x"}).status_code == 403
    assert put(client, "watchdog_deadline", "07:30", reason="").status_code == 422
    assert put(client, "no_such_setting", 1).status_code == 404


def test_a_size_limit_and_use_default(client: TestClient, store: Store) -> None:
    sign_in(client)
    settings = settings_of(put(client, "size_limit_mb.pdf", 300).json())
    assert settings["size_limit_mb.pdf"]["value"] == 300 and not settings["size_limit_mb.image"]["changed"]
    response = client.post(f"{URL}/size_limit_mb.pdf/reset", headers=CHANGES, json={"reason": "back to normal"})
    assert response.status_code == 200 and not settings_of(response.json())["size_limit_mb.pdf"]["changed"]
    assert store.settings_overrides("pahma") == {}  # the admin's value is gone: a new default takes effect
    entry = client.get("/admin/v1/museums/pahma/audit").json()["entries"][0]
    assert entry["details"] == {"before": 300, "after": 200, "reason": "back to normal", "default_value": True}


def test_two_admins_cant_undo_each_others_change(store: Store) -> None:
    _, version = store.settings_with_version("pahma")
    assert store.put_settings_overrides("pahma", {"watchdog_deadline": "07:00"}, version)
    assert not store.put_settings_overrides("pahma", {"watchdog_deadline": "09:00"}, version)  # stale
    assert store.settings_overrides("pahma") == {"watchdog_deadline": "07:00"}


# --- the audit log: 30 days, the export and the retention

def old_entry(store: Store, days: int, action: str = "sign_in", target: str = "") -> None:
    at = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    store.client.put_item(TableName=store.table(tables.AUDIT), Item={
        "pk": {"S": "pahma"}, "sk": {"S": f"{at}#admin#000000"}, "at": {"S": at}, "admin": {"S": "admin"},
        "action": {"S": action}, "target": {"S": target}, "details": {"S": "{}"}})


def test_the_audit_page_shows_30_days(client: TestClient, store: Store) -> None:
    old_entry(store, 45)
    sign_in(client)
    body = client.get("/admin/v1/museums/pahma/audit").json()
    assert body["days"] == 30 and [e["action"] for e in body["entries"]] == ["sign_in"]  # today's only


def test_the_csv_export(client: TestClient, store: Store) -> None:
    old_entry(store, 45, target="=HYPERLINK(\"http://example.invalid\")")
    sign_in(client)
    response = client.get("/admin/v1/museums/pahma/audit/export.csv")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].startswith('attachment; filename="serena-audit-pahma-')
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0] == ["time (UTC)", "by", "action", "target", "details"]
    assert [r[2] for r in rows[1:]] == ["sign_in", "sign_in"]  # oldest first, the 45-day-old one included
    assert rows[1][3].startswith("'=")  # never run as a formula
    assert client.get("/admin/v1/museums/pahma/audit").json()["entries"][0]["action"] == "audit_export"


def test_a_refreshs_own_entries_are_by_serena(client: TestClient, store: Store) -> None:
    """The Audit log's "By" column and the CSV's (the UI review, October 13, 2026): a refresh's entries are by Serena,
    with the refresh as the target or in the details. The stored entry is unchanged."""
    audit = Audit(store)
    media = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"  # synthetic
    audit.record("pahma", "refresh pahma-2026-10-12-1", Action.RECALL_ENDED, media, {"why": "no longer listed"})
    audit.record("pahma", "refresh pahma-2026-10-12-1", Action.REFRESH_OUTCOME, "pahma-2026-10-12-1",
                 {"state": "updated"})
    sign_in(client)
    shown = {e["action"]: e for e in client.get("/admin/v1/museums/pahma/audit").json()["entries"]}
    assert shown["recall_ended"]["by"] == "Serena"
    assert shown["recall_ended"]["admin"] == "refresh pahma-2026-10-12-1"
    assert shown["recall_ended"]["details"] == {"why": "no longer listed", "refresh": "pahma-2026-10-12-1"}
    assert shown["refresh_outcome"]["details"] == {"state": "updated"}  # the refresh is already the target
    assert shown["sign_in"]["by"] == "admin"
    rows = list(csv.reader(io.StringIO(client.get("/admin/v1/museums/pahma/audit/export.csv").text)))
    assert {r[1] for r in rows[1:]} == {"Serena", "admin"}


def test_how_many_entries_a_shorter_retention_removes(client: TestClient, store: Store) -> None:
    old_entry(store, 100)
    old_entry(store, 200)
    sign_in(client)
    choices = {c["days"]: c["entries_removed"] for c in client.get(URL).json()["audit_retention_choices"]}
    assert choices == {90: 2, 183: 1, 365: 0, 548: 0, 730: 0, 1095: 0}


def test_the_worker_removes_old_entries_once_a_day(store: Store, s3: Any) -> None:
    for days in (10, 100, 400):
        old_entry(store, days)
    Audit(store).record("pahma", "admin", Action.SIGN_IN)
    settings = Settings(tenants=TENANTS, table_prefix="t", _env_file=None)
    museum_settings = MuseumSettings(store, 0)
    worker = Worker(WorkerServices(settings, museum.load_all(TENANTS), museum_settings, Refreshes(store), store, s3))
    now = datetime.now(UTC)
    assert worker.purge_audit(now) == 2  # 90 days by default: the 100- and 400-day-old entries
    assert worker.purge_audit(now) == 0  # once a day
    assert len(list(Audit(store).everything("pahma"))) == 2


def test_the_refreshes_page_shows_30_days(client: TestClient, store: Store) -> None:
    now = datetime.now(UTC)
    for days in (45, 2):
        moment = now - timedelta(days=days)
        Refreshes(store, lambda moment=moment: moment).start("pahma")  # type: ignore[misc]
    sign_in(client)
    body = client.get("/admin/v1/museums/pahma/refreshes").json()
    assert body["days"] == 30 and len(body["refreshes"]) == 1
