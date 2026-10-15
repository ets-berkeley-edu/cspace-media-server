"""Requests by Media CSID, …/media/<Media CSID>/blob/… (decided October 14, 2026, D174 to D180): answered as a
request for the Media record's listed Blob. Every CSID here is synthetic."""
from typing import Any

import pytest
from conftest import TENANTS, add_blob, recall
from fastapi.testclient import TestClient
from test_signed_redirect import BLOB, BYTES, MEDIA, SHA, cache

from serena import paths, servability, tables
from serena.app import create_app
from serena.config import Settings
from serena.lookup import explain
from serena.museum import load
from serena.refreshes import Refreshes
from serena.store import Store
from serena.unserved import MemoryRecorder, Reason

PAHMA = load("pahma")
CINEFILES = load("cinefiles")
OLD = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5a"  # a replaced image's old Blob, still listed


def listed(store: Store, blob: str, media: str, listed_at: str, **fields: str) -> None:
    add_blob(store, "pahma", blob, media, **fields)
    store.client.update_item(TableName=store.table(tables.SERVABILITY), Key={"pk": {"S": f"pahma#{blob}"}},
                             UpdateExpression="SET listed_at = :t", ExpressionAttributeValues={":t": {"S": listed_at}})


@pytest.fixture
def recorder() -> MemoryRecorder:
    return MemoryRecorder()


@pytest.fixture
def local(store: Store, s3: Any, recorder: MemoryRecorder) -> TestClient:
    settings = Settings(tenants=TENANTS, table_prefix="t", buckets={t: f"b-{t}" for t in TENANTS}, local_cdn=True,
                        dynamodb_endpoint="http://localhost:8000", _env_file=None)
    s3.put_object(Bucket="b-pahma", Key=f"objects/{SHA}", Body=BYTES, ContentType="image/jpeg")
    return TestClient(create_app(settings, store, recorder, s3=s3), follow_redirects=False)


def media(size: str | None = "Medium", csid: str = MEDIA, tenant: str = "pahma") -> str:
    return f"/{tenant}/imageserver/media/{csid}/blob/" + (f"derivatives/{size}/content" if size else "content")


def test_the_shapes() -> None:
    assert paths.parse(PAHMA, f"media/{MEDIA}/blob/derivatives/Medium/content") == paths.MediaRequest(
        "pahma", MEDIA, "Medium")
    assert paths.parse(PAHMA, f"media/{MEDIA}/blob/content") == paths.MediaRequest("pahma", MEDIA, None)
    assert paths.parse(PAHMA, f"media/{MEDIA}/blob/derivatives/Thumbnial/content") == paths.Refused(
        Reason.DERIVATIVE_NOT_SERVED)
    assert paths.parse(PAHMA, "media/not.a.csid/blob/content") == paths.Refused(Reason.BAD_CSID)
    assert paths.parse(PAHMA, f"media/{MEDIA}/content") == paths.Refused(Reason.UNKNOWN_PATH)
    # The PDF link suffix stays with the Blob URLs Glimmer signs (D177).
    assert paths.parse(CINEFILES, f"media/{MEDIA}/blob/content/linked_pdf:x") == paths.Refused(Reason.UNKNOWN_PATH)


def test_served_from_the_blobs_own_cached_copy(local: TestClient, store: Store, recorder: MemoryRecorder) -> None:
    add_blob(store, "pahma", BLOB, MEDIA)
    cache(store, "pahma", "Medium")  # the Blob's own entry (D176)
    answer = local.get(media())
    assert answer.status_code == 302 and answer.headers["location"].startswith(f"/local-cdn/pahma/objects/{SHA}?")
    # Every check a Blob request gets (D174).
    assert local.get(media("Medium", "9f9f9f9f-0000-4000-8000-000000000000")).headers["location"] == (
        "/unavailable/pahma.svg")
    not_listed = recorder.recent[-1]
    recall(store, "pahma", MEDIA, BLOB)
    local.get(media())
    recalled = recorder.recent[-1]
    assert (not_listed.reason, recalled.reason) == (Reason.NOT_LISTED, Reason.RECALLED)
    assert recalled.path == media()  # logged as requested (D178)


def test_restricted_files_only_by_blob_url(store: Store) -> None:
    """D177: no signed link by Media URL."""
    add_blob(store, "cinefiles", BLOB, MEDIA, kind="pdf", access="restricted")
    _, decision = servability.resolve(CINEFILES, paths.MediaRequest("cinefiles", MEDIA, None), store)
    assert decision.reason is Reason.RESTRICTED


def test_a_media_record_listed_with_two_blobs(store: Store) -> None:
    """D175: the newest that passes; if none passes, the newest one's reason."""
    listed(store, OLD, MEDIA, "2026-10-10T10:00:00+00:00")
    listed(store, BLOB, MEDIA, "2026-10-14T10:00:00+00:00")
    request = paths.MediaRequest("pahma", MEDIA, "Medium")
    chosen, decision = servability.resolve(PAHMA, request, store)
    assert chosen is not None and chosen.blob_csid == BLOB and decision.servable
    listed(store, BLOB, MEDIA, "2026-10-14T10:00:00+00:00", kind="audio")  # the newest no longer passes
    chosen, decision = servability.resolve(PAHMA, request, store)
    assert chosen is not None and chosen.blob_csid == OLD and decision.servable
    listed(store, OLD, MEDIA, "2026-10-10T10:00:00+00:00", kind="video")
    chosen, decision = servability.resolve(PAHMA, request, store)
    assert chosen is not None and chosen.blob_csid == BLOB and decision.reason is Reason.KIND_NOT_SERVED


def test_the_servability_update_records_when_a_row_was_listed(store: Store) -> None:
    from serena.servability_update import update
    from serena.servable_list import Row

    update(store, "pahma", {BLOB: Row(MEDIA, "image", "public")}, lambda _: None, "2026-10-14T10:00:00+00:00")
    item = store.client.get_item(TableName=store.table(tables.SERVABILITY), Key={"pk": {"S": f"pahma#{BLOB}"}})
    assert item["Item"]["listed_at"]["S"] == "2026-10-14T10:00:00+00:00"
    update(store, "pahma", {BLOB: Row(MEDIA, "image", "public")}, lambda _: None, "2026-10-15T10:00:00+00:00")
    item = store.client.get_item(TableName=store.table(tables.SERVABILITY), Key={"pk": {"S": f"pahma#{BLOB}"}})
    assert item["Item"]["listed_at"]["S"] == "2026-10-14T10:00:00+00:00"  # unchanged rows aren't touched


def test_media_look_up(store: Store) -> None:
    """D180: looked up as the request is answered, through its listed Blob; no "not served yet" note."""
    add_blob(store, "pahma", BLOB, MEDIA)
    body = explain(PAHMA, media(), store, Refreshes(store))
    assert body["refused"] is None and body["input"] == media()
    (item,) = body["items"]
    assert item["blob_csid"] == BLOB and [s["size"] for s in item["sizes"]] == ["Medium"]
    unknown = explain(PAHMA, media("Medium", "9f9f9f9f-0000-4000-8000-000000000000"), store, Refreshes(store))
    assert unknown["items"][0]["sizes"][0]["reason"] == "not_listed"
    refused = explain(PAHMA, f"/pahma/imageserver/media/{MEDIA}/content", store, Refreshes(store))
    assert refused["refused"] == "unknown_path" and refused["items"][0]["blob_csid"] == BLOB


def test_one_size_of_a_media_record_for_the_file_dialog(store: Store, s3: Any, secretsmanager: Any) -> None:
    from test_admin import Clock, make_app, sign_in

    app = make_app(store, s3, secretsmanager)
    app.state.admin.sessions.clock = Clock()
    client = TestClient(app, base_url="http://testserver")
    sign_in(client)
    add_blob(store, "pahma", BLOB, MEDIA)
    s3.put_object(Bucket="b-pahma", Key=f"objects/{SHA}", Body=b"medium", ContentType="image/jpeg")
    cache(store, "pahma", "Medium")
    answer = client.get(f"/admin/v1/museums/pahma/media/{MEDIA}/preview?size=Medium")
    assert answer.status_code == 200 and answer.content == b"medium"
    assert client.get(f"/admin/v1/museums/pahma/media/{MEDIA}/preview?size=Thumbnial").status_code == 422
