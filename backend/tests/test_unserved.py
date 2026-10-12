"""Unserved requests are logged, for the Requests page (D102: no Unserved requests table)."""
import logging

import pytest
from conftest import TENANTS
from fastapi.testclient import TestClient

from serena import tables
from serena.app import create_app
from serena.config import Settings
from serena.store import Store
from serena.unserved import MemoryRecorder, Reason, report


def test_each_one_is_logged_with_its_museum_reason_and_path(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="serena.unserved")
    recorder = MemoryRecorder()
    report(recorder, "pahma", Reason.NOT_LISTED, "/pahma/imageserver/blobs/b1/content")
    report(None, None, Reason.UNKNOWN_MUSEUM, "/nowhere/imageserver/x")  # no recorder: logged all the same
    lines = [r for r in caplog.records if r.getMessage() == "unserved"]
    assert [(r.museum, r.reason, r.path) for r in lines] == [  # type: ignore[attr-defined]
        ("pahma", "not_listed", "/pahma/imageserver/blobs/b1/content"),
        (None, "unknown_museum", "/nowhere/imageserver/x")]
    assert [(e.museum, e.reason) for e in recorder.recent] == [("pahma", Reason.NOT_LISTED)]


def test_there_is_no_unserved_requests_table(store: Store) -> None:
    assert "unserved" not in {table.name for table in tables.ALL}
    settings = Settings(tenants=TENANTS, table_prefix="t", _env_file=None)
    with TestClient(create_app(settings, store), follow_redirects=False) as client:
        assert client.get("/pahma/imageserver/blobs/abc/content").status_code == 302
