import json
import logging

import pytest
from fastapi.testclient import TestClient

from serena import logs, paths
from serena.app import create_app
from serena.config import Settings
from serena.unserved import MemoryRecorder, Reason

CSID = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"  # synthetic
EMAIL = "visitor" + "@" + "example.org"  # built from parts: no address in the repository as written


@pytest.fixture
def recorder() -> MemoryRecorder:
    return MemoryRecorder()


@pytest.fixture
def client(settings: Settings, recorder: MemoryRecorder) -> TestClient:
    return TestClient(create_app(settings, recorder), follow_redirects=False)


def _last(recorder: MemoryRecorder) -> tuple[str | None, Reason, str]:
    entry = recorder.recent[-1]
    return entry.museum, entry.reason, entry.path


@pytest.mark.parametrize(
    "path",
    [
        f"/pahma/imageserver/blobs/{CSID}/derivatives/Medium/content",
        f"/pahma/imageserver/blobs/{CSID}/content",
        "/pahma/imageserver/blobs/59a733dd-d641-4e1a-8552/derivatives/Thumbnail/content",
        f"/cinefiles/imageserver/blobs/{CSID}/content/linked_pdf:{EMAIL}",
        f"/cinefiles/imageserver/blobs/{CSID}/content/inline_pdf:{EMAIL}",
        f"/cinefiles/imageserver/blobs/{CSID}/content/linked_pdf:",
        f"/bampfa/imageserver/blobs/{CSID}/content",  # the original: decided by the Blob's kind, with servability
    ],
)
def test_well_formed_requests_are_not_servable_yet(client: TestClient, recorder: MemoryRecorder, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 302
    tenant = path.split("/")[1]
    assert response.headers["location"] == f"/unavailable/{tenant}.svg"
    assert response.headers["cache-control"] == "no-store"
    assert _last(recorder)[:2] == (tenant, Reason.NOT_SERVABLE)


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        (f"/pahma/imageserver/blobs/{CSID}/derivatives/Huge/content", Reason.DERIVATIVE_NOT_SERVED),
        (f"/pahma/imageserver/blobs/{CSID}/derivatives/medium/content", Reason.DERIVATIVE_NOT_SERVED),  # exact names
        (f"/bampfa/imageserver/blobs/{CSID}/derivatives/FullHD/content", Reason.DERIVATIVE_NOT_SERVED),
        ("/pahma/imageserver/blobs/not.a.csid/content", Reason.BAD_CSID),
        (f"/pahma/imageserver/blobs/{'a' * 65}/content", Reason.BAD_CSID),
        (f"/pahma/imageserver/blobs/{CSID}/content/linked_pdf:{EMAIL}", Reason.UNKNOWN_PATH),  # Cinefiles only
        (f"/cinefiles/imageserver/blobs/{CSID}/content/linked_pdf:{'x' * 513}", Reason.UNKNOWN_PATH),
        (f"/cinefiles/imageserver/blobs/{CSID}/content/other_pdf:x", Reason.UNKNOWN_PATH),
        (f"/pahma/imageserver/blobs/{CSID}/derivatives/Medium", Reason.UNKNOWN_PATH),
        (f"/pahma/imageserver/blobs/{CSID}/content/", Reason.UNKNOWN_PATH),
        (f"/pahma/imageserver/media/{CSID}/blob/content", Reason.UNKNOWN_PATH),  # the Media-CSID URLs come later
        ("/pahma/imageserver/", Reason.UNKNOWN_PATH),
        ("/pahma/imageserver/blobs/../content", Reason.UNKNOWN_PATH),
    ],
)
def test_refused_requests(client: TestClient, recorder: MemoryRecorder, path: str, reason: Reason) -> None:
    response = client.get(path)
    assert response.status_code == 302
    assert response.headers["cache-control"] == "no-store"
    if response.headers["location"] != "/unavailable/default.svg":  # a path the client normalised away
        assert _last(recorder)[1] == reason


def test_a_museum_serena_doesnt_serve_gets_the_default_image(client: TestClient, recorder: MemoryRecorder) -> None:
    response = client.get(f"/nowhere/imageserver/blobs/{CSID}/content")
    assert response.status_code == 302
    assert response.headers["location"] == "/unavailable/default.svg"
    assert _last(recorder)[:2] == (None, Reason.UNKNOWN_MUSEUM)


def test_head_is_answered_like_get(client: TestClient) -> None:
    response = client.head(f"/pahma/imageserver/blobs/{CSID}/content")
    assert response.status_code == 302
    assert response.headers["location"] == "/unavailable/pahma.svg"


def test_the_query_string_is_ignored(client: TestClient, recorder: MemoryRecorder) -> None:
    response = client.get(f"/pahma/imageserver/blobs/{CSID}/content?x=1")
    assert response.status_code == 302
    assert _last(recorder)[1] == Reason.NOT_SERVABLE


def test_the_unavailable_base_url_in_aws(recorder: MemoryRecorder) -> None:
    settings = Settings(tenants={"pahma": "https://pahma.cspace.test"}, unavailable_base_url="https://cdn.test/u/",
                        _env_file=None)
    client = TestClient(create_app(settings, recorder), follow_redirects=False)
    response = client.get(f"/pahma/imageserver/blobs/{CSID}/content")
    assert response.headers["location"] == "https://cdn.test/u/pahma/unavailable.svg"


def test_the_pdf_suffix_is_never_logged_or_recorded(
    client: TestClient, recorder: MemoryRecorder, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    for path in (f"/cinefiles/imageserver/blobs/{CSID}/content/linked_pdf:{EMAIL}",
                 f"/pahma/imageserver/blobs/{CSID}/content/inline_pdf:{EMAIL}",  # refused, still not logged
                 f"/nowhere/imageserver/x/linked_pdf:{EMAIL}"):
        client.get(path)
    assert all(EMAIL not in entry.path and "visitor" not in entry.path for entry in recorder.recent)
    assert recorder.recent[0].path == f"/cinefiles/imageserver/blobs/{CSID}/content/linked_pdf:"
    formatter = logs.JsonFormatter()
    for record in caplog.records:
        assert "visitor" not in formatter.format(record)
        if record.name.startswith("serena"):  # Serena's own records hold no suffix even before formatting
            assert "visitor" not in json.dumps({k: str(v) for k, v in vars(record).items()})


def test_an_internal_error_fails_closed(
    client: TestClient, recorder: MemoryRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(paths, "parse", broken)
    response = client.get(f"/pahma/imageserver/blobs/{CSID}/content")
    assert response.status_code == 302
    assert response.headers["location"] == "/unavailable/pahma.svg"
    assert _last(recorder)[1] == Reason.INTERNAL_ERROR
    assert "boom" not in response.text


def test_a_failure_to_record_doesnt_change_the_answer(settings: Settings) -> None:
    class Broken:
        def record(self, entry: object) -> None:
            raise RuntimeError("table unavailable")

    client = TestClient(create_app(settings, Broken()), follow_redirects=False)
    response = client.get(f"/pahma/imageserver/blobs/{CSID}/content")
    assert response.status_code == 302


@pytest.mark.parametrize("name", ["pahma", "default"])
def test_the_unavailable_image(client: TestClient, name: str) -> None:
    response = client.get(f"/unavailable/{name}.svg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/svg+xml"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.content.startswith(b"<?xml")


def test_no_unavailable_image_for_an_unknown_museum(client: TestClient) -> None:
    assert client.get("/unavailable/nowhere.svg").status_code == 404


def test_log_path() -> None:
    assert paths.log_path(f"/a/content/linked_pdf:{EMAIL}") == "/a/content/linked_pdf:"
    assert paths.log_path("/a/content/inline_pdf%3Avisitor" + "%40" + "example.org/y") == "/a/content/inline_pdf:/y"
    assert len(paths.log_path("/" + "a" * 1000)) == paths.LOG_PATH_MAX + 1
