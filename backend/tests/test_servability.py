import pytest
from conftest import add_blob, take_down
from fastapi.testclient import TestClient

from serena.app import create_app
from serena.config import Settings
from serena.store import Store
from serena.unserved import MemoryRecorder, Reason

BLOB = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"  # synthetic
MEDIA = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
RESTRICTED_IMAGE = "59a733dd-d641-4e1a-8552"  # PAHMA's, from its configuration


@pytest.fixture
def recorder() -> MemoryRecorder:
    return MemoryRecorder()


@pytest.fixture
def client(settings: Settings, store: Store, recorder: MemoryRecorder) -> TestClient:
    return TestClient(create_app(settings, store, recorder), follow_redirects=False)


def _reason(client: TestClient, recorder: MemoryRecorder, path: str) -> Reason:
    response = client.get(path)
    assert response.status_code == 302
    assert response.headers["cache-control"] == "no-store"
    return recorder.recent[-1].reason


def derivative(tenant: str, size: str = "Medium", blob: str = BLOB) -> str:
    return f"/{tenant}/imageserver/blobs/{blob}/derivatives/{size}/content"


def original(tenant: str, blob: str = BLOB) -> str:
    return f"/{tenant}/imageserver/blobs/{blob}/content"


@pytest.mark.parametrize(
    ("tenant", "kind", "access", "path", "reason"),
    [
        # listed, public, a kind Serena serves, asked for in a way that fits it: servable
        ("pahma", "image", "public", derivative("pahma"), Reason.SERVING_NOT_BUILT),
        ("pahma", "card", "public", derivative("pahma", "Thumbnail"), Reason.SERVING_NOT_BUILT),
        ("pahma", "image", "public", original("pahma"), Reason.SERVING_NOT_BUILT),
        ("bampfa", "3D", "public", original("bampfa"), Reason.SERVING_NOT_BUILT),
        ("cinefiles", "pdf", "public", original("cinefiles"), Reason.SERVING_NOT_BUILT),
        ("cinefiles", "pdf", "public", original("cinefiles") + "/linked_pdf:x", Reason.SERVING_NOT_BUILT),
        # not
        ("pahma", "audio", "public", original("pahma"), Reason.KIND_NOT_SERVED),
        ("pahma", "video", "public", original("pahma"), Reason.KIND_NOT_SERVED),
        ("cinefiles", "pdf", "restricted", original("cinefiles"), Reason.RESTRICTED),
        ("cinefiles", "pdf", "public", derivative("cinefiles"), Reason.NO_DERIVATIVES_FOR_KIND),
        ("pahma", "3D", "public", derivative("pahma", "Thumbnail"), Reason.NO_DERIVATIVES_FOR_KIND),
        ("bampfa", "image", "public", original("bampfa"), Reason.ORIGINAL_NOT_SERVED),
        ("botgarden", "card", "public", original("botgarden"), Reason.ORIGINAL_NOT_SERVED),
    ],
)
def test_decisions(client: TestClient, store: Store, recorder: MemoryRecorder, tenant: str, kind: str,
                   access: str, path: str, reason: Reason) -> None:
    add_blob(store, tenant, BLOB, MEDIA, kind, access)
    assert _reason(client, recorder, path) == reason


def test_not_listed(client: TestClient, store: Store, recorder: MemoryRecorder) -> None:
    add_blob(store, "ucjeps", BLOB, MEDIA)  # listed for another museum only
    assert _reason(client, recorder, derivative("pahma")) == Reason.NOT_LISTED


def test_takedowns(client: TestClient, store: Store, recorder: MemoryRecorder) -> None:
    add_blob(store, "pahma", BLOB, MEDIA)
    take_down(store, "ucjeps", MEDIA)  # another museum's takedown changes nothing here
    assert _reason(client, recorder, derivative("pahma")) == Reason.SERVING_NOT_BUILT
    take_down(store, "pahma", MEDIA)
    assert _reason(client, recorder, derivative("pahma")) == Reason.TAKEN_DOWN  # on the very next request
    take_down(store, "pahma", MEDIA, state="unlocked")
    assert _reason(client, recorder, derivative("pahma")) == Reason.SERVING_NOT_BUILT


def test_restricted_image_blob(client: TestClient, store: Store, recorder: MemoryRecorder) -> None:
    path = derivative("pahma", "Thumbnail", RESTRICTED_IMAGE)
    assert _reason(client, recorder, path) == Reason.NOT_LISTED  # it must be in the nightly file like any other
    add_blob(store, "pahma", RESTRICTED_IMAGE, None)  # listed with no Media CSID
    assert _reason(client, recorder, path) == Reason.RESTRICTED_IMAGE_NOT_UPLOADED


def test_a_failing_table_fails_closed(client: TestClient, store: Store, recorder: MemoryRecorder,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    add_blob(store, "pahma", BLOB, MEDIA)

    def unreachable(*args: object) -> None:
        raise ConnectionError("DynamoDB unreachable")

    monkeypatch.setattr(store, "takedown", unreachable)
    response = client.get(derivative("pahma"))
    assert response.headers["location"] == "/unavailable/pahma.svg"
    assert recorder.recent[-1].reason == Reason.INTERNAL_ERROR
