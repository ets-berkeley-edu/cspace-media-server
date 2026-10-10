import json
import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from conftest import TENANTS, add_blob, take_down
from fastapi.testclient import TestClient

from fakecspace import samples
from fakecspace.app import USERS
from fakecspace.app import app as fake_app
from fakecspace.app import store as fake
from serena import cache_index, fetch
from serena.app import create_app
from serena.config import Settings
from serena.cspace.client import CSpaceClient
from serena.museum import StartingSettings
from serena.store import Store
from serena.unserved import MemoryRecorder, Reason

# All synthetic: the CSIDs, files and the simulator's account are made up for the tests.
BLOB = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"
OTHER_BLOB = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5c"
MEDIA = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
OTHER_MEDIA = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5e"
FAKE_LOGIN = next(iter(USERS.items()))


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def reset_fake() -> Iterator[None]:
    fake.reset()
    yield
    fake.reset()


@pytest.fixture
def recorder() -> MemoryRecorder:
    return MemoryRecorder()


@pytest.fixture
def fetch_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def app(store: Store, s3: Any, secretsmanager: Any, recorder: MemoryRecorder, fetch_dir: Path) -> Any:
    ids = {tenant: f"serena/test/{tenant}/cspace" for tenant in TENANTS}
    for secret_id in ids.values():
        secretsmanager.create_secret(Name=secret_id, SecretString=json.dumps(
            {"username": FAKE_LOGIN[0], "password": FAKE_LOGIN[1]}))
    settings = Settings(tenants=TENANTS, table_prefix="t", buckets={t: f"b-{t}" for t in TENANTS}, local_cdn=True,
                        dynamodb_endpoint="http://localhost:8000", cspace_secret_ids=ids, cspace_retries=1,
                        fetch_dir=str(fetch_dir), _env_file=None)
    built = create_app(settings, store, recorder, s3=s3, secretsmanager=secretsmanager,
                       cspace_http=lambda tenant: TestClient(fake_app, base_url=TENANTS[tenant]))
    built.state.fetcher.clock = Clock()
    for tenant in TENANTS:  # no waiting between retries in the tests
        built.state.fetcher.clients.get(tenant).sleep = lambda seconds: None
    return built


@pytest.fixture
def client(app: Any) -> TestClient:
    return TestClient(app, follow_redirects=False)


def path(tenant: str = "pahma", size: str | None = "Medium", blob: str = BLOB) -> str:
    tail = f"derivatives/{size}/content" if size else "content"
    return f"/{tenant}/imageserver/blobs/{blob}/{tail}"


def content_calls() -> list[str]:
    return [call for call in fake.calls if call.endswith("/content")]


def unavailable(client: TestClient, recorder: MemoryRecorder, url: str, tenant: str = "pahma") -> Reason:
    response = client.get(url)
    assert response.status_code == 302 and response.headers["location"] == f"/unavailable/{tenant}.svg"
    assert response.headers["cache-control"] == "no-store"
    return recorder.recent[-1].reason


# --- a miss that is fetched, stored and served

@pytest.mark.parametrize(("tenant", "kind", "size", "content_type"), [
    ("pahma", "image", "Medium", "image/png"),
    ("pahma", "card", "Thumbnail", "image/png"),
    ("pahma", "image", None, "image/png"),  # the original, where the museum serves originals
    ("cinefiles", "pdf", None, "application/pdf"),
    ("bampfa", "3D", None, "model/x3d+xml"),
])
def test_a_miss_is_fetched_stored_and_served(client: TestClient, store: Store, s3: Any, tenant: str, kind: str,
                                             size: str | None, content_type: str) -> None:
    add_blob(store, tenant, BLOB, MEDIA, kind=kind)
    media = fake.add(MEDIA, kind=kind)
    content = media.files[size or "content"][0]
    response = client.get(path(tenant, size))
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(f"/local-cdn/{tenant}/objects/")
    entry = cache_index.lookup(store, tenant, BLOB, size)
    assert entry is not None and entry.content_type == content_type and entry.size == len(content)
    stored = s3.get_object(Bucket=f"b-{tenant}", Key=entry.key)
    assert stored["Body"].read() == content and stored["ContentType"] == content_type
    assert client.get(location).content == content
    calls = len(fake.calls)
    assert client.get(path(tenant, size)).headers["location"] == location  # now a hit
    assert len(fake.calls) == calls  # CollectionSpace isn't asked again


def test_only_the_media_service_is_called(client: TestClient, store: Store) -> None:
    add_blob(store, "pahma", BLOB, MEDIA)
    fake.add(MEDIA)
    client.get(path())
    assert fake.calls == [f"/cspace-services/media/{MEDIA}",
                          f"/cspace-services/media/{MEDIA}/blob/derivatives/Medium/content"]


def test_a_replaced_image_serves_the_current_file(client: TestClient, store: Store, s3: Any) -> None:
    add_blob(store, "pahma", BLOB, MEDIA)  # last night's Blob
    fake.add(MEDIA)
    current = samples.png(shade=32)
    fake.media[MEDIA].files["Medium"] = (current, "image/png")  # replaced in CollectionSpace since
    client.get(path())
    entry = cache_index.lookup(store, "pahma", BLOB, "Medium")
    assert entry is not None
    assert s3.get_object(Bucket="b-pahma", Key=entry.key)["Body"].read() == current


def test_the_same_bytes_are_stored_once(client: TestClient, store: Store, s3: Any,
                                        caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    add_blob(store, "pahma", BLOB, MEDIA)
    add_blob(store, "pahma", OTHER_BLOB, OTHER_MEDIA)
    fake.add(MEDIA)
    fake.add(OTHER_MEDIA)  # the same synthetic image
    client.get(path())
    client.get(path(blob=OTHER_BLOB))
    first = cache_index.lookup(store, "pahma", BLOB, "Medium")
    second = cache_index.lookup(store, "pahma", OTHER_BLOB, "Medium")
    assert first is not None and second is not None and first.sha256 == second.sha256
    assert s3.list_objects_v2(Bucket="b-pahma", Prefix="objects/")["KeyCount"] == 1
    assert "already stored" in caplog.text


def test_head_fetches_too(client: TestClient, store: Store) -> None:
    add_blob(store, "pahma", BLOB, MEDIA)
    fake.add(MEDIA)
    assert client.head(path()).headers["location"].startswith("/local-cdn/pahma/objects/")
    assert cache_index.lookup(store, "pahma", BLOB, "Medium") is not None


# --- the light check

def test_a_media_record_that_is_gone(client: TestClient, store: Store, recorder: MemoryRecorder) -> None:
    add_blob(store, "pahma", BLOB, MEDIA)
    assert unavailable(client, recorder, path()) == Reason.MEDIA_GONE
    assert content_calls() == []


def test_a_soft_deleted_media_record(client: TestClient, store: Store, recorder: MemoryRecorder) -> None:
    add_blob(store, "pahma", BLOB, MEDIA)
    fake.add(MEDIA, state="deleted")
    assert unavailable(client, recorder, path()) == Reason.MEDIA_DELETED
    assert content_calls() == []  # the file of a deleted record is never fetched


# --- the fetch

def test_no_such_file(client: TestClient, store: Store, recorder: MemoryRecorder) -> None:
    add_blob(store, "pahma", BLOB, MEDIA)
    fake.add(MEDIA).files = {}
    assert unavailable(client, recorder, path()) == Reason.NO_FILE


def test_collectionspace_unavailable_isnt_remembered(client: TestClient, store: Store,
                                                     recorder: MemoryRecorder) -> None:
    add_blob(store, "pahma", BLOB, MEDIA)
    fake.add(MEDIA)
    fake.fail("/content", 503, times=2)  # the first try and its one retry
    assert unavailable(client, recorder, path()) == Reason.CSPACE_UNAVAILABLE
    assert client.get(path()).headers["location"].startswith("/local-cdn/")  # asked again at once, and served


def test_collectionspace_refuses(client: TestClient, store: Store, recorder: MemoryRecorder) -> None:
    add_blob(store, "pahma", BLOB, MEDIA)
    fake.add(MEDIA)
    fake.fail(f"/media/{MEDIA}", 403)
    assert unavailable(client, recorder, path()) == Reason.CSPACE_REFUSED


def test_wrong_credentials(client: TestClient, store: Store, recorder: MemoryRecorder, secretsmanager: Any,
                           caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    wrong = "not-" + FAKE_LOGIN[1]
    secretsmanager.put_secret_value(SecretId="serena/test/ucjeps/cspace", SecretString=json.dumps(
        {"username": FAKE_LOGIN[0], "password": wrong}))
    add_blob(store, "ucjeps", BLOB, MEDIA)
    fake.add(MEDIA)
    assert unavailable(client, recorder, path("ucjeps"), "ucjeps") == Reason.CSPACE_REFUSED
    assert wrong not in caplog.text and "Authorization" not in caplog.text


@pytest.mark.parametrize(("kind", "content_type"), [
    ("image", "image/bmp"),
    ("image", "image/jp2"),  # libvips here can't decode JPEG 2000
    ("image", "text/html"),
    ("pdf", "text/html"),
    ("3D", "application/octet-stream"),
])
def test_a_content_type_the_kind_doesnt_allow(client: TestClient, store: Store, recorder: MemoryRecorder,
                                              kind: str, content_type: str) -> None:
    tenant, size = ("pahma", "Medium") if kind == "image" else ("cinefiles" if kind == "pdf" else "bampfa", None)
    add_blob(store, tenant, BLOB, MEDIA, kind=kind)
    media = fake.add(MEDIA, kind=kind)
    name = size or "content"
    media.files[name] = (media.files[name][0], content_type)
    assert unavailable(client, recorder, path(tenant, size), tenant) == Reason.WRONG_CONTENT_TYPE
    assert cache_index.lookup(store, tenant, BLOB, size) is None


def test_a_content_type_with_parameters(client: TestClient, store: Store) -> None:
    add_blob(store, "bampfa", BLOB, MEDIA, kind="3D")
    media = fake.add(MEDIA, kind="3D")
    media.files["content"] = (media.files["content"][0], "model/x3d+xml; charset=utf-8")
    assert client.get(path("bampfa", None)).headers["location"].startswith("/local-cdn/")


def test_an_image_that_doesnt_decode(client: TestClient, store: Store, recorder: MemoryRecorder, s3: Any) -> None:
    add_blob(store, "pahma", BLOB, MEDIA)
    fake.add(MEDIA).files["Medium"] = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "image/png")
    assert unavailable(client, recorder, path()) == Reason.NOT_DECODABLE
    assert s3.list_objects_v2(Bucket="b-pahma", Prefix="objects/")["KeyCount"] == 0


def test_a_truncated_image(client: TestClient, store: Store, recorder: MemoryRecorder) -> None:
    add_blob(store, "pahma", BLOB, MEDIA)
    whole = samples.png(64, 64)
    fake.add(MEDIA).files["Medium"] = (whole[: len(whole) // 2], "image/png")
    assert unavailable(client, recorder, path()) == Reason.NOT_DECODABLE


@pytest.mark.parametrize(("content", "served"), [
    (samples.pdf(), True),
    (b"\x00" * 100 + samples.pdf(), True),  # %PDF- within the first 1024 bytes, as readers accept
    (b"\x00" * 1100 + samples.pdf(), False),
    (b"<html>not a PDF</html>", False),
])
def test_the_pdf_marker(client: TestClient, store: Store, recorder: MemoryRecorder, content: bytes,
                        served: bool) -> None:
    add_blob(store, "cinefiles", BLOB, MEDIA, kind="pdf")
    fake.add(MEDIA, kind="pdf").files["content"] = (content, "application/pdf")
    if served:
        assert client.get(path("cinefiles", None)).headers["location"].startswith("/local-cdn/")
    else:
        assert unavailable(client, recorder, path("cinefiles", None), "cinefiles") == Reason.WRONG_CONTENT_TYPE


class TinyLimits:
    """Museum settings with a 1 MB limit for every kind."""

    def __init__(self, real: Any):
        self.real = real

    def get(self, museum: Any) -> StartingSettings:
        real: StartingSettings = self.real.get(museum)
        return real.model_copy(update={"size_limit_mb": dict.fromkeys(("image", "card", "3D",
                                                                                         "pdf"), 1)})


def test_too_large_by_its_content_length(app: Any, client: TestClient, store: Store,
                                         recorder: MemoryRecorder) -> None:
    app.state.fetcher.museum_settings = TinyLimits(app.state.fetcher.museum_settings)
    add_blob(store, "cinefiles", BLOB, MEDIA, kind="pdf")
    fake.add(MEDIA, kind="pdf").files["content"] = (b"%PDF-1.4\n" + b"0" * fetch.MB, "application/pdf")
    assert unavailable(client, recorder, path("cinefiles", None), "cinefiles") == Reason.TOO_LARGE


def test_too_large_while_streaming(fetch_dir: Path) -> None:
    """A file sent without a Content-Length is counted as it arrives."""
    class Fetched:
        status, content_type, content_length = 200, "application/pdf", None

        def chunks(self) -> Iterator[bytes]:
            while True:
                yield b"0" * 65536

    class Client:
        @contextmanager
        def fetch(self, media: str, derivative: str | None) -> Iterator[Fetched]:
            yield Fetched()

    fetcher = fetch.Fetcher(Any, None, {}, Any, Any, fetch_dir=str(fetch_dir))  # type: ignore[arg-type]
    with open(fetch_dir / "out", "wb") as out:
        assert fetcher._download(Client(), MEDIA, None, "pdf", fetch.MB, out, {}) == Reason.TOO_LARGE
    assert (fetch_dir / "out").stat().st_size <= fetch.MB


def test_not_enough_local_disk(app: Any, client: TestClient, store: Store, recorder: MemoryRecorder) -> None:
    app.state.fetcher.disk_free = lambda path: 10 * fetch.MB
    add_blob(store, "pahma", BLOB, MEDIA)
    fake.add(MEDIA)
    assert unavailable(client, recorder, path()) == Reason.FETCH_BUSY
    assert content_calls() == []
    app.state.fetcher.disk_free = lambda path: 10_000 * fetch.MB
    assert client.get(path()).headers["location"].startswith("/local-cdn/")  # not remembered


def test_local_files_are_removed(client: TestClient, store: Store, fetch_dir: Path) -> None:
    add_blob(store, "pahma", BLOB, MEDIA)
    add_blob(store, "pahma", OTHER_BLOB, OTHER_MEDIA)
    fake.add(MEDIA)
    fake.add(OTHER_MEDIA).files["Medium"] = (b"not an image", "image/png")
    client.get(path())
    client.get(path(blob=OTHER_BLOB))
    assert list(fetch_dir.iterdir()) == []


# --- remembering a failure

def test_a_failure_is_remembered_for_ten_minutes(app: Any, client: TestClient, store: Store,
                                                 recorder: MemoryRecorder) -> None:
    add_blob(store, "pahma", BLOB, MEDIA)
    assert unavailable(client, recorder, path()) == Reason.MEDIA_GONE
    calls = len(fake.calls)
    app.state.fetcher.clock.now += 599
    assert unavailable(client, recorder, path()) == Reason.MEDIA_GONE
    assert len(fake.calls) == calls  # CollectionSpace wasn't asked
    fake.add(MEDIA)  # fixed in CollectionSpace
    app.state.fetcher.clock.now += 1
    assert client.get(path()).headers["location"].startswith("/local-cdn/")


def test_a_takedown_still_comes_first(client: TestClient, store: Store, recorder: MemoryRecorder) -> None:
    add_blob(store, "pahma", BLOB, MEDIA)
    assert unavailable(client, recorder, path()) == Reason.MEDIA_GONE
    take_down(store, "pahma", MEDIA)
    assert unavailable(client, recorder, path()) == Reason.TAKEN_DOWN


# --- simultaneous requests

def test_simultaneous_requests_wait_on_one_fetch(app: Any, store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    add_blob(store, "pahma", BLOB, MEDIA)
    fake.add(MEDIA)
    real_fetch = CSpaceClient.fetch

    @contextmanager
    def slow_fetch(self: CSpaceClient, media: str, derivative: str | None) -> Iterator[Any]:
        time.sleep(0.2)
        with real_fetch(self, media, derivative) as fetched:
            yield fetched

    monkeypatch.setattr(CSpaceClient, "fetch", slow_fetch)
    museum = app.state.museums["pahma"]
    record = store.servability("pahma", BLOB)
    results: list[Any] = []
    threads = [threading.Thread(target=lambda: results.append(app.state.fetcher.get(museum, record, "Medium")))
               for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(content_calls()) == 1
    assert len({entry.sha256 for entry in results}) == 1 and all(isinstance(e, cache_index.Entry) for e in results)
    assert app.state.fetcher._locks._locks == {}  # nothing left behind
