import json
import logging
import threading
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from fakecspace import samples
from fakecspace.app import USERS
from fakecspace.app import app as fake_app
from fakecspace.app import store as fake
from serena.config import Settings
from serena.cspace.client import CSpaceClient, CSpaceError, CSpaceUnavailable, MediaState
from serena.cspace.clients import CSpaceClients
from serena.secret_cache import SecretCache

MEDIA = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"  # synthetic


@pytest.fixture(autouse=True)
def reset() -> Iterator[None]:
    fake.reset()
    yield
    fake.reset()


FAKE_LOGIN = next(iter(USERS.items()))  # the simulator's synthetic account


def client(login: tuple[str, str] = FAKE_LOGIN, retries: int = 2) -> CSpaceClient:
    return CSpaceClient("pahma", "http://fake", lambda: login, TestClient(fake_app, base_url="http://fake"),
                        retries=retries, sleep=lambda seconds: None)


# --- the light check

def test_an_existing_media_record() -> None:
    fake.add(MEDIA)
    assert client().media_state(MEDIA) == MediaState.EXISTS


def test_a_media_record_that_isnt_there() -> None:
    assert client().media_state(MEDIA) == MediaState.GONE


@pytest.mark.parametrize("state", ["deleted", "locked_deleted", "replicated_deleted"])
def test_a_soft_deleted_media_record(state: str) -> None:
    fake.add(MEDIA, state=state)
    assert client().media_state(MEDIA) == MediaState.DELETED


def test_wrong_credentials() -> None:
    fake.add(MEDIA)
    with pytest.raises(CSpaceError) as caught:
        client(login=(FAKE_LOGIN[0], "not-" + FAKE_LOGIN[1])).media_state(MEDIA)
    assert caught.value.status == 401


# --- fetching

@pytest.mark.parametrize(("kind", "derivative", "content_type", "starts"), [
    ("image", "Medium", "image/png", b"\x89PNG"),
    ("image", None, "image/png", b"\x89PNG"),
    ("pdf", None, "application/pdf", b"%PDF-"),
    ("3D", None, "model/x3d+xml", b"<?xml"),
])
def test_fetch(kind: str, derivative: str | None, content_type: str, starts: bytes) -> None:
    fake.add(MEDIA, kind=kind)
    with client().fetch(MEDIA, derivative) as fetched:
        assert (fetched.status, fetched.content_type) == (200, content_type)
        body = b"".join(fetched.chunks())
    assert body.startswith(starts)
    assert fetched.content_length == len(body)


def test_a_record_with_no_file() -> None:
    fake.add(MEDIA)
    fake.media[MEDIA].files = {}
    with client().fetch(MEDIA, "Medium") as fetched:
        assert fetched.status == 404  # the caller decides what that means


def test_every_call_goes_through_the_media_service() -> None:
    fake.add(MEDIA)
    c = client()
    c.media_state(MEDIA)
    with c.fetch(MEDIA, "Thumbnail"):
        pass
    with c.fetch(MEDIA, None):
        pass
    assert fake.calls == [f"/cspace-services/media/{MEDIA}",
                          f"/cspace-services/media/{MEDIA}/blob/derivatives/Thumbnail/content",
                          f"/cspace-services/media/{MEDIA}/blob/content"]  # never a Blob CSID


def test_a_replaced_image_is_the_records_current_file() -> None:
    fake.add(MEDIA)
    with client().fetch(MEDIA, "Medium") as before:
        old = b"".join(before.chunks())
    fake.media[MEDIA].files = {k: (samples.png(shade=32), "image/png") for k in ("content", "Medium")}
    with client().fetch(MEDIA, "Medium") as after:
        assert b"".join(after.chunks()) != old


# --- failures

def test_transient_errors_are_retried() -> None:
    fake.add(MEDIA)
    fake.fail(MEDIA, 503, times=2)
    assert client(retries=2).media_state(MEDIA) == MediaState.EXISTS
    assert len(fake.calls) == 3


def test_transient_errors_that_last() -> None:
    fake.add(MEDIA)
    fake.fail(MEDIA, 502, times=5)
    with pytest.raises(CSpaceUnavailable):
        client(retries=2).media_state(MEDIA)
    assert len(fake.calls) == 3


@pytest.mark.parametrize("status", [500, 403, 400])
def test_other_errors_arent_retried(status: int) -> None:
    fake.add(MEDIA)
    fake.fail(MEDIA, status, times=5)
    with pytest.raises(CSpaceError) as caught:
        client().media_state(MEDIA)
    assert caught.value.status == status
    assert len(fake.calls) == 1


def test_no_answer_at_all(caplog: pytest.LogCaptureFixture) -> None:
    attempts = []

    def timeout(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url.path)
        raise httpx.ConnectTimeout("no answer", request=request)

    c = CSpaceClient("pahma", "http://cspace.test", lambda: ("serena", "a-password-value"),
                     httpx.Client(transport=httpx.MockTransport(timeout)), retries=2, sleep=lambda s: None)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(CSpaceUnavailable):
        c.media_state(MEDIA)
    assert len(attempts) == 3
    logged = json.dumps([str(vars(r)) for r in caplog.records])
    assert "a-password-value" not in logged and "Authorization" not in logged


def test_simultaneous_calls_are_capped() -> None:
    lock = threading.Lock()
    running = [0, 0]  # now, most

    def slow(request: httpx.Request) -> httpx.Response:
        with lock:
            running[0] += 1
            running[1] = max(running[1], running[0])
        time.sleep(0.05)
        with lock:
            running[0] -= 1
        return httpx.Response(404)

    c = CSpaceClient("pahma", "http://cspace.test", lambda: ("serena", "x"),
                     httpx.Client(transport=httpx.MockTransport(slow)), concurrency=2, sleep=lambda s: None)
    threads = [threading.Thread(target=c.media_state, args=(MEDIA,)) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert running[1] == 2


# --- the museums' clients

def test_credentials_come_from_secrets_manager(secretsmanager: Any) -> None:
    arn = secretsmanager.create_secret(Name="cspace/pahma", SecretString=json.dumps(
        {"username": "serena", "password": "serena"}))["ARN"]
    settings = Settings(tenants={"pahma": "http://fake"}, cspace_secret_ids={"pahma": arn}, _env_file=None)
    clients = CSpaceClients(settings, SecretCache(secretsmanager, 300),
                            lambda tenant: TestClient(fake_app, base_url="http://fake"))
    fake.add(MEDIA)
    assert clients.get("pahma").media_state(MEDIA) == MediaState.EXISTS
    assert clients.get("pahma") is clients.get("pahma")  # one per museum, per task
    with pytest.raises(CSpaceError, match="doesn't serve"):
        clients.get("nowhere")


@pytest.mark.parametrize("secret", [None, {"username": "serena"}, {"username": "", "password": "x"}])
def test_missing_or_incomplete_credentials(secretsmanager: Any, secret: dict[str, str] | None) -> None:
    ids = {}
    if secret is not None:
        ids["pahma"] = secretsmanager.create_secret(Name="cspace/p", SecretString=json.dumps(secret))["ARN"]
    settings = Settings(tenants={"pahma": "http://fake"}, cspace_secret_ids=ids, _env_file=None)
    clients = CSpaceClients(settings, SecretCache(secretsmanager, 300),
                            lambda tenant: TestClient(fake_app, base_url="http://fake"))
    with pytest.raises(CSpaceError):
        clients.get("pahma").media_state(MEDIA)


def test_the_samples() -> None:
    assert samples.png().startswith(b"\x89PNG\r\n\x1a\n")
    document = samples.pdf()
    assert document.startswith(b"%PDF-1.4") and document.rstrip().endswith(b"%%EOF")
    assert b"<X3D" in samples.x3d()
