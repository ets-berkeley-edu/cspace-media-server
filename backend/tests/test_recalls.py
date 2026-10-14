"""Recalls and Media look up (decided October 12, 2026, D116 to D131). Every CSID, file and account is synthetic."""
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
from serena import cache_index, recalls, tables
from serena.audit import Audit
from serena.museum import load
from serena.store import Recall, Store

BLOB = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a50"
MEDIA = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c50"
BLOB_2 = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a51"
MEDIA_2 = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c51"
UNPUBLISHED_BLOB = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a52"  # in CollectionSpace, not (yet) in the servable list
UNPUBLISHED_MEDIA = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c52"
UNKNOWN = "9f9f9f9f-0000-4000-8000-000000000000"
PAHMA = load("pahma")
URL = "/admin/v1/museums/pahma/recalls"


@pytest.fixture(autouse=True)
def reset_fake() -> Iterator[None]:
    fake.reset()
    yield
    fake.reset()


@pytest.fixture
def app(store: Store, s3: Any, secretsmanager: Any) -> Any:
    ids = {tenant: f"serena/test/{tenant}/cspace" for tenant in TENANTS}
    login = next(iter(USERS.items()))
    for secret_id in ids.values():
        secretsmanager.create_secret(Name=secret_id, SecretString=json.dumps(
            {"username": login[0], "password": login[1]}))
    built = make_app(store, s3, secretsmanager, cspace_secret_ids=ids, cspace_retries=1)
    built.state.admin.sessions.clock = Clock()
    for tenant in TENANTS:  # no waiting between retries in the tests
        built.state.fetcher.clients.get(tenant).sleep = lambda seconds: None
    return built


@pytest.fixture
def client(app: Any) -> TestClient:
    return TestClient(app, base_url="http://testserver", follow_redirects=False)


@pytest.fixture
def listed(store: Store) -> None:
    add_blob(store, "pahma", BLOB, MEDIA)
    add_blob(store, "pahma", BLOB_2, MEDIA_2, kind="pdf")
    fake.add(UNPUBLISHED_MEDIA, blob=UNPUBLISHED_BLOB)


def summary(client: TestClient, text: str) -> dict[str, Any]:
    answer = client.post(f"{URL}/summary", headers=CHANGES, json={"text": text})
    assert answer.status_code == 200, answer.text
    body: dict[str, Any] = answer.json()
    return body


def alerts_of(store: Store, kind: str) -> list[dict[str, Any]]:
    items = store.client.scan(TableName=store.table(tables.ALERTS))["Items"]
    return [i for i in items if i["kind"]["S"] == kind]


# --- the input

def test_the_box_and_the_file_are_parsed_alike() -> None:
    assert recalls.parse(f" {BLOB},{MEDIA}\n\n{BLOB} {MEDIA_2}\r\n") == [BLOB, MEDIA, MEDIA_2]
    assert len(recalls.parse("\n".join(f"a-{n}" for n in range(1000)))) == 1000
    with pytest.raises(ValueError, match="at most 1,000"):
        recalls.parse("\n".join(f"a-{n}" for n in range(1001)))


# --- finding each CSID (D116, D117)

@pytest.mark.usefixtures("listed")
def test_serenas_table_first_then_collectionspace(client: TestClient, store: Store) -> None:
    sign_in(client)
    body = summary(client, f"{BLOB}\n{MEDIA}\n{MEDIA_2}\n{UNPUBLISHED_BLOB}\n{UNKNOWN}\nnot/a/csid\n"
                           f"{PAHMA.placeholder_blob_csid}")
    records = {r["media_csid"]: r for r in body["records"]}
    assert list(records) == [MEDIA, MEDIA_2, UNPUBLISHED_MEDIA]  # a Media CSID and its own Blob count once
    assert records[MEDIA] == {"media_csid": MEDIA, "blob_csids": [BLOB], "kind": "image", "served_today": True,
                              "recalled": False, "source": "serena", "entered": [BLOB, MEDIA]}
    assert records[MEDIA_2]["kind"] == "pdf"
    assert records[UNPUBLISHED_MEDIA] == {"media_csid": UNPUBLISHED_MEDIA, "blob_csids": [UNPUBLISHED_BLOB],
                                          "kind": None, "served_today": False, "recalled": False,
                                          "source": "collectionspace", "entered": [UNPUBLISHED_BLOB]}
    assert {n["csid"]: n["why"] for n in body["not_found"]} == {
        "not/a/csid": "not_a_csid", PAHMA.placeholder_blob_csid: "placeholder", UNKNOWN: "not_found"}
    asked = fake.calls
    assert f"/cspace-services/media/{BLOB}" not in asked  # the table knew it: CollectionSpace isn't asked
    assert f"/cspace-services/blobs/{UNPUBLISHED_BLOB}" in asked


@pytest.mark.usefixtures("listed")
def test_a_media_csid_collectionspace_knows(client: TestClient) -> None:
    sign_in(client)
    (record,) = summary(client, UNPUBLISHED_MEDIA)["records"]
    assert (record["media_csid"], record["blob_csids"], record["source"]) == (
        UNPUBLISHED_MEDIA, [UNPUBLISHED_BLOB], "collectionspace")


@pytest.mark.usefixtures("listed")
def test_when_collectionspace_cant_be_reached(client: TestClient) -> None:
    sign_in(client)
    fake.fail("/cspace-services/media/", 503, times=10)
    body = summary(client, f"{BLOB}\n{UNPUBLISHED_BLOB}")
    assert [r["media_csid"] for r in body["records"]] == [MEDIA]  # what Serena's table knows still goes ahead
    assert body["not_found"][0]["why"] == "collectionspace_unreachable"
    assert "can't be reached" in body["not_found"][0]["message"]


def test_the_form_needs_a_signed_in_admin_and_the_header(client: TestClient) -> None:
    assert client.post(f"{URL}/summary", headers=CHANGES, json={"text": BLOB}).status_code == 401
    sign_in(client)
    assert client.post(f"{URL}/summary", json={"text": BLOB}).status_code == 403
    assert client.post(f"{URL}/summary", headers=CHANGES, json={"text": " \n"}).status_code == 422
    many = "\n".join(f"a-{n}" for n in range(1001))
    assert "At most 1,000" in client.post(f"{URL}/summary", headers=CHANGES, json={"text": many}).json()["detail"]


# --- recalling (D118)

@pytest.mark.usefixtures("listed")
def test_taking_down(client: TestClient, store: Store) -> None:
    sign_in(client)
    image = f"/pahma/imageserver/blobs/{BLOB}/derivatives/Medium/content"
    answer = client.post(URL, headers=CHANGES, json={"text": f"{BLOB} {MEDIA_2} {UNPUBLISHED_BLOB}",
                                                    "reason": "  A  complaint  "})
    assert answer.status_code == 200
    assert answer.json()["recalled"] == [MEDIA, MEDIA_2, UNPUBLISHED_MEDIA]
    recall = store.recall("pahma", MEDIA)
    assert recall is not None and recall.blob_csids == (BLOB,) and recall.reason == "A complaint"
    assert client.get(image).headers["location"] == "/unavailable/pahma.svg"  # on the next request
    entries = [e for e in Audit(store).since("pahma", datetime(2026, 1, 1, tzinfo=UTC)) if e.action == "recall"]
    assert sorted(e.target for e in entries) == sorted([MEDIA, MEDIA_2, UNPUBLISHED_MEDIA])  # one per Media record
    (alert,) = alerts_of(store, "recall")
    assert "recalled 3 Media records for PAHMA. Reason: A complaint" in alert["message"]["S"]
    again = client.post(URL, headers=CHANGES, json={"text": MEDIA, "reason": "again"}).json()
    assert again["recalled"] == [] and again["records"][0]["recalled"] is True
    assert len(alerts_of(store, "recall")) == 1  # nothing new recalled: no alert
    assert client.post(URL, headers=CHANGES, json={"text": MEDIA, "reason": ""}).status_code == 422


# --- how a recall ends (D119)

def made(store: Store, media: str, blob: str, at: str = "2026-10-14T17:00:00+00:00") -> None:
    store.put_recall(Recall("pahma", media, (blob,), "admin", at, "a complaint"))


def test_a_refresh_ends_recalls_collectionspace_has_caught_up_with(store: Store, app: Any) -> None:
    alerts, audit = app.state.admin_recalls.alerts, Audit(store)
    gone, restricted, still, early = (f"1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c6{n}" for n in range(4))
    made(store, gone, f"{gone}-b")  # no longer listed at all
    add_blob(store, "pahma", f"{restricted}-b", restricted, access="restricted")  # now restricted
    made(store, restricted, f"{restricted}-b")
    add_blob(store, "pahma", f"{still}-b", still)  # the same Blob, still public
    made(store, still, f"{still}-b")
    add_blob(store, "pahma", f"{early}-b", early)
    made(store, early, f"{early}-b", at="2026-10-15T10:15:00+00:00")  # 03:15 Pacific on the refresh's own day
    ended = recalls.after_update(PAHMA, "pahma-2026-10-15-1", "2026-10-15", store, audit, alerts)
    assert (ended.ended, ended.kept) == (2, 1)
    assert store.recall("pahma", gone) is None and store.recall("pahma", restricted) is None
    kept = store.recall("pahma", still)
    assert kept is not None and (kept.kept_by, kept.kept_on) == ("pahma-2026-10-15-1", "2026-10-15")
    too_early = store.recall("pahma", early)
    assert too_early is not None and too_early.kept_by is None  # too early: looked at by the next refresh
    (still_public,) = alerts_of(store, "recall_still_public")
    assert still_public["subject"]["S"] == still and "release it" in still_public["message"]["S"]
    (removed,) = alerts_of(store, "recalls_ended")
    assert "ended 2 recalls" in removed["message"]["S"]
    entries = [e for e in audit.since("pahma", datetime(2026, 1, 1, tzinfo=UTC)) if e.action == "recall_ended"]
    assert {e.target for e in entries} == {gone, restricted}
    assert {e.admin for e in entries} == {"refresh pahma-2026-10-15-1"}
    # A replaced image, made public again: the Media record listed with a new Blob, the old one gone.
    add_blob(store, "pahma", f"{still}-new", still)
    store.client.delete_item(TableName=store.table(tables.SERVABILITY), Key={"pk": {"S": f"pahma#{still}-b"}})
    recalls.after_update(PAHMA, "pahma-2026-10-16-1", "2026-10-16", store, audit, alerts)
    assert store.recall("pahma", still) is None
    assert store.recall("pahma", early) is not None  # its Blob is still public: kept


@pytest.mark.usefixtures("listed")
def test_release_only_a_recall_a_refresh_kept(client: TestClient, store: Store) -> None:
    sign_in(client)
    made(store, MEDIA, BLOB)
    release = f"{URL}/{MEDIA}/release"
    assert client.post(release, headers=CHANGES, json={"reason": "a mistake"}).status_code == 409
    recalls.after_update(PAHMA, "pahma-2026-10-15-1", "2026-10-15", store, Audit(store), None)  # kept: still public
    assert client.post(release, json={"reason": "a mistake"}).status_code == 403
    assert client.post(release, headers=CHANGES, json={"reason": ""}).status_code == 422
    assert client.post(release, headers=CHANGES, json={"reason": "a mistake"}).status_code == 200
    assert store.recall("pahma", MEDIA) is None
    (alert,) = alerts_of(store, "recall_released")
    assert "kept. Reason: a mistake" in alert["message"]["S"]
    page = client.get(URL).json()
    assert page["active"] == [] and [(e["media_csid"], e["action"]) for e in page["ended"]] == [
        (MEDIA, "recall_release")]
    assert (page["max_in_box"], page["max_in_file"]) == (12, 1000)


@pytest.mark.usefixtures("listed")
def test_cancel_only_a_recall_no_refresh_has_kept(client: TestClient, store: Store) -> None:
    """An admin can undo a recall still waiting for a later refresh; once a refresh keeps it, Release (D148)."""
    sign_in(client)
    made(store, MEDIA, BLOB)
    cancel = f"{URL}/{MEDIA}/cancel"
    assert client.post(cancel, json={"reason": "wrong CSID"}).status_code == 403
    assert client.post(cancel, headers=CHANGES, json={"reason": ""}).status_code == 422
    assert client.post(cancel, headers=CHANGES, json={"reason": "wrong CSID"}).status_code == 200
    assert store.recall("pahma", MEDIA) is None
    (alert,) = alerts_of(store, "recall_cancelled")
    assert "before a refresh decided it. Reason: wrong CSID" in alert["message"]["S"]
    page = client.get(URL).json()
    assert page["active"] == [] and [(e["media_csid"], e["action"]) for e in page["ended"]] == [
        (MEDIA, "recall_cancel")]
    assert page["ended"][0]["details"]["reason"] == "wrong CSID"
    assert client.post(cancel, headers=CHANGES, json={"reason": "again"}).status_code == 409  # none to cancel
    made(store, MEDIA, BLOB)
    recalls.after_update(PAHMA, "pahma-2026-10-15-1", "2026-10-15", store, Audit(store), None)  # kept: still public
    assert client.post(cancel, headers=CHANGES, json={"reason": "too late"}).status_code == 409
    assert store.recall("pahma", MEDIA) is not None


# --- the thumbnails (D129)

@pytest.mark.usefixtures("listed")
def test_previews_from_the_stored_copy_or_collectionspace(client: TestClient, store: Store, s3: Any) -> None:
    preview = f"/admin/v1/museums/pahma/media/{MEDIA}/preview"
    assert client.get(preview).status_code == 401
    sign_in(client)
    fake.add(MEDIA, blob=BLOB)
    answer = client.get(preview)  # not stored: from CollectionSpace, not stored
    assert answer.status_code == 200 and answer.headers["content-type"] == "image/png"
    assert answer.headers["cache-control"] == "no-store"
    assert cache_index.lookup(store, "pahma", BLOB, "Thumbnail") is None
    s3.put_object(Bucket="b-pahma", Key="objects/" + "c" * 64, Body=b"stored", ContentType="image/jpeg")
    cache_index.record(store, "pahma", BLOB, "Thumbnail", cache_index.Entry("c" * 64, "image/jpeg", 6, "2026-10-12"))
    stored = client.get(preview)
    assert stored.content == b"stored" and stored.headers["cache-control"] == "no-store"
    assert client.get(f"{preview}?size=full").status_code == 200  # OriginalJpeg, from CollectionSpace
    assert client.get(f"{preview}?size=huge").status_code == 422
    add_blob(store, "pahma", "3d-blob", "3d-media", kind="3D")
    assert client.get("/admin/v1/museums/pahma/media/3d-media/preview").status_code == 404


# --- Media look up (D121 to D123)

@pytest.mark.usefixtures("listed")
def test_look_up_a_file(client: TestClient, store: Store) -> None:
    lookup = "/admin/v1/museums/pahma/lookup"
    fake.add(MEDIA, blob=BLOB)
    sign_in(client)
    body = client.get(lookup, params={"q": f"https://example.edu/pahma/imageserver/blobs/{BLOB}/derivatives/"
                                           "Medium/content?uid=1&sig=x"}).json()
    assert body["input"] == f"/pahma/imageserver/blobs/{BLOB}/derivatives/Medium/content"
    (item,) = body["items"]
    assert [s["ok"] for s in item["steps"]] == [True, True, True, True]
    assert item["sizes"] == [{"size": "Medium", "served": True, "reason": None, "stored": None,
                              "verdict": "served: would be fetched on the next request"}]
    made(store, MEDIA, BLOB)
    (item,) = client.get(lookup, params={"q": MEDIA}).json()["items"]  # a Media CSID: every size
    assert item["steps"][-1]["ok"] is False and "a complaint" in item["steps"][-1]["outcome"]
    assert [s["size"] for s in item["sizes"]] == ["original", *PAHMA.derivatives]
    assert {s["reason"] for s in item["sizes"]} == {"recalled"}
    (pdf,) = client.get(lookup, params={"q": BLOB_2}).json()["items"]
    assert [s["size"] for s in pdf["sizes"]] == ["original"]  # a PDF is served only as its original file
    suffix = "/pahma/imageserver/blobs/" + BLOB + "/content/linked_pdf:someone"
    assert "someone" not in client.get(lookup, params={"q": suffix}).text
    assert client.get(lookup, params={"q": UNKNOWN}).json()["items"][0]["sizes"][0]["reason"] == "not_listed"
    assert client.get(lookup, params={"q": "/bampfa/imageserver/blobs/x/content"}).status_code == 422
    assert client.get(lookup, params={"q": "not a csid"}).status_code == 422


# --- Media look up beside CollectionSpace (D139 to D143)

def stored(store: Store, blob: str, size: str | None, last_served: str | None = None) -> None:
    cache_index.record(store, "pahma", blob, size, cache_index.Entry("b" * 64, "image/png", 9, "2026-10-01T10:00:00Z",
                                                                     last_served))


@pytest.mark.usefixtures("listed")
def test_media_look_up_shows_collectionspace_beside_serena(client: TestClient, store: Store) -> None:
    lookup = "/admin/v1/museums/pahma/lookup"
    fake.add(MEDIA, blob=BLOB, identification_number="9-12345")
    stored(store, BLOB, "Thumbnail", "2026-10-12T18:00:00Z")
    sign_in(client)
    (item,) = client.get(lookup, params={"q": MEDIA}).json()["items"]
    cs = item["cspace"]
    assert (cs["state"], cs["media_csid"], cs["blob_csid"]) == ("exists", MEDIA, BLOB)
    assert cs["identification_number"] == "9-12345"  # the page's heading (D153)
    assert cs["fields"] == [{"label": "Approved for web", "value": "Yes"}]  # PAHMA's lookup field (D140)
    assert cs["next"] == "Nothing has changed in CollectionSpace since the last refresh."
    thumbnail = next(s for s in item["sizes"] if s["size"] == "Thumbnail")
    assert thumbnail["stored"]["fetched_at"] == "2026-10-01T10:00:00Z"
    assert thumbnail["stored"]["last_served"] == "2026-10-12T18:00:00Z"

    fake.media[MEDIA].state = "deleted"  # soft-deleted since: only stored sizes are served
    (item,) = client.get(lookup, params={"q": MEDIA}).json()["items"]
    assert item["cspace"]["state"] == "deleted" and "soft-deleted" in item["cspace"]["next"]
    sizes = {s["size"]: (s["served"], s["reason"]) for s in item["sizes"]}
    assert sizes["Thumbnail"] == (True, None) and sizes["Medium"] == (False, "media_deleted")

    fake.media[MEDIA].state, fake.media[MEDIA].blob = "project", "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5f"  # replaced
    (item,) = client.get(lookup, params={"q": BLOB}).json()["items"]
    assert item["cspace"]["blob_csid"] != BLOB and "another Blob" in item["cspace"]["next"]

    (item,) = client.get(lookup, params={"q": UNPUBLISHED_BLOB}).json()["items"]  # not listed: found by its Blob
    assert item["cspace"]["media_csid"] == UNPUBLISHED_MEDIA and "left it out" in item["cspace"]["next"]
    (item,) = client.get(lookup, params={"q": UNKNOWN}).json()["items"]
    assert item["cspace"] == {"state": "gone", "next": "CollectionSpace has no Blob or Media record with this CSID "
                                                       "either."}
    placeholder = PAHMA.placeholder_blob_csid
    assert placeholder is not None
    add_blob(store, "pahma", placeholder, None)
    (item,) = client.get(lookup, params={"q": placeholder}).json()["items"]
    assert item["cspace"] == {"state": "no_media"}


@pytest.mark.usefixtures("listed")
def test_media_look_up_without_collectionspace(client: TestClient) -> None:
    fake.add(MEDIA, blob=BLOB)
    fake.fail("/media/", 503, times=10)
    sign_in(client)
    (item,) = client.get("/admin/v1/museums/pahma/lookup", params={"q": MEDIA}).json()["items"]
    assert item["cspace"] == {"state": "unavailable"}
    assert {s["reason"] for s in item["sizes"]} == {None}  # Serena's verdict doesn't depend on CollectionSpace


@pytest.mark.usefixtures("listed")
def test_media_look_up_during_a_collectionspace_outage(client: TestClient) -> None:
    """The simulator's outage switch: every call answers 503, its records kept (checklist section 19)."""
    fake.add(MEDIA, blob=BLOB)
    fake.unreachable = True
    sign_in(client)
    (item,) = client.get("/admin/v1/museums/pahma/lookup", params={"q": MEDIA}).json()["items"]
    assert item["cspace"] == {"state": "unavailable"}
    fake.unreachable = False
    (item,) = client.get("/admin/v1/museums/pahma/lookup", params={"q": MEDIA}).json()["items"]
    assert item["cspace"]["state"] == "exists"


def test_what_the_next_refresh_will_do() -> None:
    from serena.cspace.client import MediaRecord, MediaState
    from serena.lookup import _after, _next
    record = MediaRecord(MediaState.EXISTS, BLOB, "2026-10-13T16:45:00.000Z")
    assert _after(record.updated_at, "2026-10-12T10:01:00+00:00") is True
    assert _after(record.updated_at, "2026-10-14T10:01:00+00:00") is False
    assert _after(None, "2026-10-14T10:01:00+00:00") is False
    assert "ends the recall if it isn't" in _next(True, BLOB, "image", record, True, None, True)
    assert "a cached size is the old image" in _next(True, BLOB_2, "image", record, True, None, False)
    assert "keeps the recall, with another alert" in _next(True, BLOB, "image", record, False, "pahma-2026-10-12-1",
                                                          True)
    assert "shows whether it's public now" in _next(False, BLOB, "file", record, True, None, False)


def test_last_served_is_recorded_at_most_once_a_day(store: Store) -> None:
    stored(store, BLOB, "Medium", "2026-10-12T18:00:00Z")
    entry = cache_index.lookup(store, "pahma", BLOB, "Medium")
    assert entry is not None
    cache_index.served(store, "pahma", BLOB, "Medium", entry, datetime(2026, 10, 13, 9, 0, tzinfo=UTC))
    assert cache_index.lookup(store, "pahma", BLOB, "Medium").last_served == "2026-10-12T18:00:00Z"  # type: ignore[union-attr]
    cache_index.served(store, "pahma", BLOB, "Medium", entry, datetime(2026, 10, 13, 18, 30, tzinfo=UTC))
    assert cache_index.lookup(store, "pahma", BLOB, "Medium").last_served == "2026-10-13T18:30:00Z"  # type: ignore[union-attr]
    stale = cache_index.Entry(entry.sha256, entry.content_type, entry.size, entry.fetched_at, None)
    cache_index.served(store, "pahma", BLOB, "Medium", stale, datetime(2026, 10, 13, 19, 0, tzinfo=UTC))
    assert cache_index.lookup(store, "pahma", BLOB, "Medium").last_served == "2026-10-13T18:30:00Z"  # type: ignore[union-attr]
    cache_index.served(store, "pahma", "no-such-blob", "Medium", stale, datetime(2026, 10, 13, 19, 0, tzinfo=UTC))
    assert cache_index.lookup(store, "pahma", "no-such-blob", "Medium") is None  # never creates an entry


@pytest.mark.usefixtures("listed")
def test_a_blobs_file_at_one_size(client: TestClient, store: Store, s3: Any) -> None:
    preview = f"/admin/v1/museums/pahma/blobs/{BLOB}/preview"
    assert client.get(preview).status_code == 401
    sign_in(client)
    fake.add(MEDIA, blob=BLOB)
    answer = client.get(f"{preview}?size=Medium")  # not stored: from CollectionSpace by its Media record
    assert answer.status_code == 200 and answer.headers["cache-control"] == "no-store"
    assert cache_index.lookup(store, "pahma", BLOB, "Medium") is None  # never stored
    s3.put_object(Bucket="b-pahma", Key="objects/" + "d" * 64, Body=b"stored", ContentType="image/jpeg")
    cache_index.record(store, "pahma", BLOB, "Medium", cache_index.Entry("d" * 64, "image/jpeg", 6, "2026-10-12"))
    assert client.get(f"{preview}?size=Medium").content == b"stored"
    assert client.get(f"{preview}?size=full").status_code == 200  # the largest size: OriginalJpeg
    assert client.get(f"{preview}?size=Huge").status_code == 422
    assert client.get(f"/admin/v1/museums/pahma/media/{MEDIA}/preview?size=thumbnail&source=cspace").status_code == 200
    unlisted = client.get(f"/admin/v1/museums/pahma/blobs/{UNPUBLISHED_BLOB}/preview?size=Thumbnail")
    assert unlisted.status_code == 200  # not listed: its Media record found in CollectionSpace
    assert client.get(f"/admin/v1/museums/pahma/blobs/{UNKNOWN}/preview").status_code == 404

