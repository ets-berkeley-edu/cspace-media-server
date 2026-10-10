import json
import logging
import time
from typing import Any

import pytest
from conftest import TENANTS, add_blob, take_down
from fastapi.testclient import TestClient

from serena import cache_index, tables
from serena.app import create_app
from serena.config import Settings
from serena.museum import load
from serena.secret_cache import SecretCache
from serena.signed_links import SigningKeys, SigningKeysUnavailable, signature, verify
from serena.store import Store
from serena.unserved import MemoryRecorder, Reason

# All synthetic: the CSIDs, the reader ID and the keys are made up for the tests.
BLOB = "0a1b2c3d-1111-2222-3333-444455556666"
MEDIA = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
SHA = "b" * 64
PDF = b"%PDF-1.4 synthetic"
KEY = "test-key-" + "a" * 36  # synthetic
OLD_KEY = "test-key-" + "b" * 36  # synthetic
KID, OLD_KID = "cinefiles-test-202610", "cinefiles-test-202510"
UID = "12345"
KEYS_NAME = "serena/test/cinefiles/pdf-signing-key"


# --- the signature itself

def test_the_designs_test_vector() -> None:
    sig = signature("example-key-not-a-secret", "cinefiles", BLOB, "1791590400", "12345")
    assert sig == "pZqh6CO0MnUTOb6m_KMQtytCwTauTCXr5ZZb-5aGDWg"


# --- checking a link, without the app

class FakeSecrets:
    def __init__(self, value: Any = None, error: Exception | None = None):
        self.value, self.error = value, error

    def get_json(self, secret_id: str) -> Any:
        if self.error:
            raise self.error
        return self.value


def keys(current: Any = None, previous: Any = None, error: Exception | None = None) -> SigningKeys:
    if current is None:
        current = {"kid": KID, "key": KEY}
    secrets: Any = FakeSecrets({"current": current, "previous": previous}, error)
    return SigningKeys(secrets, {"cinefiles": KEYS_NAME})


def link(exp: int, uid: str = UID, kid: str = KID, key: str = KEY, blob: str = BLOB,
         tenant: str = "cinefiles") -> dict[str, list[str]]:
    return {"exp": [str(exp)], "uid": [uid], "kid": [kid], "sig": [signature(key, tenant, blob, str(exp), uid)]}


NOW = 1_791_590_000


def check(query: dict[str, list[str]], signing: SigningKeys | None = None, now: int = NOW) -> Reason | None:
    return verify(signing or keys(), "cinefiles", BLOB, query, now).reason


def test_a_valid_link() -> None:
    verdict = verify(keys(), "cinefiles", BLOB, link(NOW + 900), NOW)
    assert verdict.valid and verdict.kid == KID


def test_no_signature_is_restricted() -> None:
    assert check({}) == Reason.RESTRICTED


@pytest.mark.parametrize("missing", ["exp", "uid", "kid", "sig"])
def test_a_missing_parameter(missing: str) -> None:
    query = link(NOW + 900)
    del query[missing]
    assert check(query) == Reason.SIGNATURE_INVALID


@pytest.mark.parametrize(("name", "value"), [
    ("uid", "reader.name"),  # digits only: never a name or an address
    ("uid", "12a45"),
    ("uid", "1" * 21),
    ("uid", ""),
    ("exp", "1" * 12),
    ("exp", "-900"),
    ("kid", "a" * 65),
    ("kid", "bad kid"),
    ("sig", "A" * 42),
    ("sig", "A" * 44),
    ("sig", "A" * 42 + "="),
])
def test_a_malformed_parameter(name: str, value: str) -> None:
    query = link(NOW + 900)
    query[name] = [value]
    assert check(query) == Reason.SIGNATURE_INVALID


def test_a_repeated_parameter() -> None:
    query = link(NOW + 900)
    query["uid"] = [UID, UID]
    assert check(query) == Reason.SIGNATURE_INVALID


def test_other_parameters_are_ignored() -> None:
    query = link(NOW + 900)
    query["utm_source"] = ["mail"]
    assert check(query) is None


def test_an_unknown_key_id() -> None:
    assert check(link(NOW + 900, kid="cinefiles-test-209901")) == Reason.SIGNATURE_INVALID


@pytest.mark.parametrize("change", ["uid", "exp", "blob", "tenant", "key"])
def test_a_link_that_doesnt_match(change: str) -> None:
    query = link(NOW + 900, blob="0a1b2c3d-1111-2222-3333-444455556667" if change == "blob" else BLOB,
                 tenant="pahma" if change == "tenant" else "cinefiles",
                 key="another-synthetic-key-0123456789abcdef" if change == "key" else KEY)
    if change == "uid":
        query["uid"] = ["12346"]
    if change == "exp":
        query["exp"] = [str(NOW + 901)]
    assert check(query) == Reason.SIGNATURE_INVALID


@pytest.mark.parametrize(("exp", "reason"), [
    (NOW, None),
    (NOW - 60, None),  # 60 seconds of clock difference
    (NOW - 61, Reason.SIGNATURE_EXPIRED),
    (NOW + 3600, None),
    (NOW + 3660, None),  # at most 60 minutes ahead, plus the clock difference
    (NOW + 3661, Reason.SIGNATURE_EXPIRED),
])
def test_the_time_window(exp: int, reason: Reason | None) -> None:
    assert check(link(exp)) == reason


def test_a_forged_expired_link_is_invalid_not_expired() -> None:
    query = link(NOW - 3600)
    query["sig"] = ["A" * 43]
    assert check(query) == Reason.SIGNATURE_INVALID


def test_the_previous_key_during_a_rotation() -> None:
    rotating = keys(previous={"kid": OLD_KID, "key": OLD_KEY})
    assert check(link(NOW + 900, kid=OLD_KID, key=OLD_KEY), rotating) is None
    assert check(link(NOW + 900), rotating) is None
    assert check(link(NOW + 900, kid=OLD_KID, key=OLD_KEY)) == Reason.SIGNATURE_INVALID  # once it's removed


def test_a_short_key_is_ignored(caplog: pytest.LogCaptureFixture) -> None:
    short = "only-twenty-chars-xx"
    assert check(link(NOW + 900, key=short), keys({"kid": KID, "key": short})) == Reason.SIGNATURE_INVALID
    assert "too short" in caplog.text and short not in caplog.text


@pytest.mark.parametrize("entry", [{"kid": KID}, {"key": KEY}, {"kid": "bad kid", "key": KEY}, "not an object"])
def test_a_malformed_key_entry_is_ignored(entry: Any) -> None:
    assert check(link(NOW + 900), keys(entry)) == Reason.SIGNATURE_INVALID


def test_a_museum_without_keys() -> None:
    assert verify(keys(), "pahma", BLOB, link(NOW + 900, tenant="pahma"), NOW).reason == Reason.SIGNATURE_INVALID


def test_keys_that_cant_be_read(caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(SigningKeysUnavailable):
        check(link(NOW + 900), keys(error=RuntimeError(f"it said {KEY}")))
    assert "could not read the signing keys" in caplog.text and KEY not in caplog.text


def test_cinefiles_allows_signed_access_to_pdfs_only() -> None:
    assert load("cinefiles").signed_access_kinds == ("pdf",)
    assert all(load(key).signed_access_kinds == () for key in TENANTS if key != "cinefiles")


# --- through the app

@pytest.fixture
def recorder() -> MemoryRecorder:
    return MemoryRecorder()


@pytest.fixture
def app_client(store: Store, s3: Any, secretsmanager: Any, recorder: MemoryRecorder) -> TestClient:
    secretsmanager.create_secret(Name=KEYS_NAME, SecretString=json.dumps(
        {"current": {"kid": KID, "key": KEY}, "previous": None}))
    settings = Settings(tenants=TENANTS, table_prefix="t", buckets={t: f"b-{t}" for t in TENANTS}, local_cdn=True,
                        dynamodb_endpoint="http://localhost:8000", signing_key_secret_ids={"cinefiles": KEYS_NAME},
                        _env_file=None)
    for tenant in ("cinefiles", "pahma"):
        s3.put_object(Bucket=f"b-{tenant}", Key=f"objects/{SHA}", Body=PDF, ContentType="application/pdf")
    return TestClient(create_app(settings, store, recorder, s3=s3, secretsmanager=secretsmanager),
                      follow_redirects=False)


def cached(store: Store, tenant: str = "cinefiles", kind: str = "pdf", access: str = "restricted") -> None:
    add_blob(store, tenant, BLOB, MEDIA, kind=kind, access=access)
    store.client.put_item(TableName=store.table(tables.CACHE_INDEX), Item={
        "pk": {"S": cache_index.key(tenant, BLOB, None)}, "sha256": {"S": SHA},
        "content_type": {"S": "application/pdf"}, "size": {"N": str(len(PDF))},
        "fetched_at": {"S": "2026-10-10T00:00:00Z"}})


def url(tail: str = "content/linked_pdf:", tenant: str = "cinefiles", query: dict[str, list[str]] | None = None) -> str:
    base = f"/{tenant}/imageserver/blobs/{BLOB}/{tail}"
    if query is None:
        return base
    return base + "?" + "&".join(f"{name}={values[0]}" for name, values in query.items())


def fresh(tenant: str = "cinefiles", key: str = KEY) -> dict[str, list[str]]:
    return link(int(time.time()) + 900, tenant=tenant, key=key)


def unavailable(response: Any, tenant: str = "cinefiles") -> bool:
    return bool(response.status_code == 302 and response.headers["location"] == f"/unavailable/{tenant}.svg")


@pytest.mark.parametrize("tail", ["content/linked_pdf:", "content/inline_pdf:", "content"])
def test_a_signed_link_serves_a_restricted_pdf(app_client: TestClient, store: Store, tail: str) -> None:
    cached(store)
    response = app_client.get(url(tail, query=fresh()))
    assert response.status_code == 302
    assert response.headers["location"].startswith(f"/local-cdn/cinefiles/objects/{SHA}?")
    assert response.headers["cache-control"] == "no-store"
    served = app_client.get(response.headers["location"])
    assert served.status_code == 200 and served.content == PDF


def test_no_signature(app_client: TestClient, store: Store, recorder: MemoryRecorder) -> None:
    cached(store)
    assert unavailable(app_client.get(url()))
    assert recorder.counts[("cinefiles", Reason.RESTRICTED)] == 1


def test_a_bad_and_an_expired_link(app_client: TestClient, store: Store, recorder: MemoryRecorder) -> None:
    cached(store)
    assert unavailable(app_client.get(url(query=fresh(key="another-synthetic-key-0123456789abcdef"))))
    assert unavailable(app_client.get(url(query=link(int(time.time()) - 120))))
    assert recorder.counts[("cinefiles", Reason.SIGNATURE_INVALID)] == 1
    assert recorder.counts[("cinefiles", Reason.SIGNATURE_EXPIRED)] == 1


def test_a_public_pdf_is_served_with_or_without_a_signature(app_client: TestClient, store: Store) -> None:
    cached(store, access="public")
    for query in (None, fresh(), {"exp": ["x"], "uid": ["x"], "kid": ["x"], "sig": ["x"]}):
        response = app_client.get(url(query=query))
        assert response.headers["location"].startswith("/local-cdn/")
        assert response.headers["cache-control"].startswith("private, max-age=")


def test_a_takedown_wins_over_a_signature(app_client: TestClient, store: Store, recorder: MemoryRecorder) -> None:
    cached(store)
    take_down(store, "cinefiles", MEDIA)
    assert unavailable(app_client.get(url(query=fresh())))
    assert recorder.counts[("cinefiles", Reason.TAKEN_DOWN)] == 1


def test_no_derivatives_of_a_signed_pdf(app_client: TestClient, store: Store, recorder: MemoryRecorder) -> None:
    cached(store)
    assert unavailable(app_client.get(url("derivatives/Medium/content", query=fresh())))
    assert recorder.counts[("cinefiles", Reason.NO_DERIVATIVES_FOR_KIND)] == 1


def test_a_kind_without_signed_access(app_client: TestClient, store: Store, recorder: MemoryRecorder) -> None:
    cached(store, kind="image")
    assert unavailable(app_client.get(url("content", query=fresh())))
    assert recorder.counts[("cinefiles", Reason.RESTRICTED)] == 1


def test_a_museum_without_signed_access(app_client: TestClient, store: Store, recorder: MemoryRecorder) -> None:
    cached(store, tenant="pahma")
    assert unavailable(app_client.get(url("content", tenant="pahma", query=fresh("pahma"))), "pahma")
    assert recorder.counts[("pahma", Reason.RESTRICTED)] == 1


def test_keys_that_cant_be_read_fail_closed(app_client: TestClient, store: Store, recorder: MemoryRecorder,
                                            secretsmanager: Any) -> None:
    cached(store)
    secretsmanager.delete_secret(SecretId=KEYS_NAME, ForceDeleteWithoutRecovery=True)
    assert unavailable(app_client.get(url(query=fresh())))
    assert recorder.counts[("cinefiles", Reason.INTERNAL_ERROR)] == 1


def test_a_rotated_key_is_picked_up(store: Store, s3: Any, secretsmanager: Any, recorder: MemoryRecorder) -> None:
    secretsmanager.create_secret(Name=KEYS_NAME, SecretString=json.dumps({"current": {"kid": OLD_KID, "key": OLD_KEY}}))
    cache = SecretCache(secretsmanager, ttl_seconds=0)
    signing = SigningKeys(cache, {"cinefiles": KEYS_NAME})
    now = int(time.time())
    assert verify(signing, "cinefiles", BLOB, link(now + 900), now).reason == Reason.SIGNATURE_INVALID
    secretsmanager.put_secret_value(SecretId=KEYS_NAME, SecretString=json.dumps(
        {"current": {"kid": KID, "key": KEY}, "previous": {"kid": OLD_KID, "key": OLD_KEY}}))
    assert verify(signing, "cinefiles", BLOB, link(now + 900), now).valid
    assert verify(signing, "cinefiles", BLOB, link(now + 900, kid=OLD_KID, key=OLD_KEY), now).valid


def test_the_reader_and_the_signature_are_never_logged_or_recorded(
        app_client: TestClient, store: Store, recorder: MemoryRecorder, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    cached(store)
    good = fresh()
    good["uid"] = ["987654321"]
    good["sig"] = [signature(KEY, "cinefiles", BLOB, good["exp"][0], "987654321")]
    app_client.get(url(query=good))
    app_client.get(url(query={**good, "uid": ["987654322"]}))  # doesn't match: recorded as unserved
    logged = caplog.text + " ".join(str(vars(record)) for record in caplog.records)
    for value in (good["uid"][0], "987654322", good["sig"][0], good["exp"][0], KEY):
        assert value not in logged
    assert KID in logged  # the key ID that signed it, which isn't secret
    assert all("?" not in entry.path and "987654" not in entry.path for entry in recorder.recent)
