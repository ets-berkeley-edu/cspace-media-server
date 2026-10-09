from datetime import UTC, datetime
from typing import Any

import pytest
from conftest import TENANTS
from fastapi.testclient import TestClient

from serena import tables
from serena.app import create_app
from serena.config import Settings
from serena.store import Store
from serena.unserved import DynamoRecorder, Reason, Unserved

AT = datetime(2026, 10, 9, 18, 7, 30, tzinfo=UTC)  # in the 18:05 bucket


def _items(store: Store) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = store.client.scan(TableName=store.table(tables.UNSERVED))["Items"]
    return sorted(items, key=lambda item: (item["pk"]["S"], item["sk"]["S"]))


def test_counts_are_written_per_museum_bucket_and_reason(store: Store) -> None:
    recorder = DynamoRecorder(store.client, store.table(tables.UNSERVED))
    for n in range(7):
        recorder.record(Unserved("pahma", Reason.NOT_LISTED, f"/pahma/imageserver/blobs/b{n}/content", AT))
    recorder.record(Unserved(None, Reason.UNKNOWN_MUSEUM, "/nowhere/imageserver/x", AT))
    assert recorder.flush() == 2
    default, pahma = _items(store)
    assert (default["pk"]["S"], default["sk"]["S"], default["count"]["N"]) == (
        "default#2026-10-09T18:05Z", "unknown_museum", "1")
    assert (pahma["pk"]["S"], pahma["sk"]["S"], pahma["count"]["N"]) == ("pahma#2026-10-09T18:05Z", "not_listed", "7")
    assert [s["S"] for s in pahma["samples"]["L"]] == [f"/pahma/imageserver/blobs/b{n}/content" for n in range(2, 7)]
    assert int(pahma["expires_at"]["N"]) == int(datetime(2026, 11, 8, 18, 5, tzinfo=UTC).timestamp())
    assert recorder.flush() == 0  # nothing pending


def test_later_writes_add_to_the_count(store: Store) -> None:
    recorder = DynamoRecorder(store.client, store.table(tables.UNSERVED))
    for _ in range(2):
        recorder.record(Unserved("pahma", Reason.TAKEN_DOWN, "/p", AT))
        recorder.flush()
    (item,) = _items(store)
    assert item["count"]["N"] == "2"


def test_counts_that_cant_be_written_are_kept(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = DynamoRecorder(store.client, store.table(tables.UNSERVED))
    recorder.record(Unserved("pahma", Reason.NOT_LISTED, "/p", AT))
    real = store.client.update_item

    def unreachable(**kwargs: Any) -> None:
        raise ConnectionError("DynamoDB unreachable")

    monkeypatch.setattr(store.client, "update_item", unreachable)
    assert recorder.flush() == 0
    monkeypatch.setattr(store.client, "update_item", real)
    assert recorder.flush() == 1
    (item,) = _items(store)
    assert item["count"]["N"] == "1"


def test_the_app_writes_its_counts_when_it_stops(store: Store) -> None:
    settings = Settings(tenants=TENANTS, table_prefix="t", unserved_flush_seconds=3600, _env_file=None)
    with TestClient(create_app(settings, store), follow_redirects=False) as client:
        client.get("/pahma/imageserver/blobs/abc/content")
        assert _items(store) == []  # not yet: every hour, in this test
    (item,) = _items(store)
    assert item["sk"]["S"] == "not_listed"
