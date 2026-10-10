import base64
import json
import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from conftest import TENANTS, add_blob
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient
from pydantic import ValidationError

from serena import cache_index, museum, signing, tables
from serena.app import create_app
from serena.config import Settings
from serena.secret_cache import SecretCache
from serena.store import Store
from serena.unserved import MemoryRecorder, Reason

BLOB = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"  # synthetic
MEDIA = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
SHA = "a" * 64
BYTES = b"\xff\xd8 not really a JPEG"


def cache(store: Store, tenant: str, derivative: str | None, sha: str = SHA) -> None:
    store.client.put_item(TableName=store.table(tables.CACHE_INDEX), Item={
        "pk": {"S": cache_index.key(tenant, BLOB, derivative)}, "sha256": {"S": sha},
        "content_type": {"S": "image/jpeg"}, "size": {"N": str(len(BYTES))},
        "fetched_at": {"S": "2026-10-09T00:00:00Z"}})


@pytest.fixture
def recorder() -> MemoryRecorder:
    return MemoryRecorder()


@pytest.fixture
def local(store: Store, s3: Any, recorder: MemoryRecorder) -> TestClient:
    settings = Settings(tenants=TENANTS, table_prefix="t", buckets={t: f"b-{t}" for t in TENANTS}, local_cdn=True,
                        dynamodb_endpoint="http://localhost:8000", _env_file=None)
    s3.put_object(Bucket="b-pahma", Key=f"objects/{SHA}", Body=BYTES, ContentType="image/jpeg")
    return TestClient(create_app(settings, store, recorder, s3=s3), follow_redirects=False)


def path(tenant: str = "pahma", size: str | None = "Medium") -> str:
    tail = f"derivatives/{size}/content" if size else "content"
    return f"/{tenant}/imageserver/blobs/{BLOB}/{tail}"


# --- the windows

@pytest.mark.parametrize(("now", "expires"), [
    (datetime(2026, 10, 10, 12, 0, 0, tzinfo=UTC), datetime(2026, 10, 10, 12, 30, tzinfo=UTC)),
    (datetime(2026, 10, 10, 12, 14, 59, tzinfo=UTC), datetime(2026, 10, 10, 12, 30, tzinfo=UTC)),
    (datetime(2026, 10, 10, 12, 15, 0, tzinfo=UTC), datetime(2026, 10, 10, 12, 45, tzinfo=UTC)),
])
def test_urls_expire_at_the_end_of_the_next_window(now: datetime, expires: datetime) -> None:
    assert signing.expiry(now) == int(expires.timestamp())
    assert 900 < signing.expiry(now) - int(now.timestamp()) <= 1800


# --- a hit, through the local signer

def test_a_hit_redirects_to_a_signed_url(local: TestClient, store: Store) -> None:
    add_blob(store, "pahma", BLOB, MEDIA)
    cache(store, "pahma", "Medium")
    response = local.get(path())
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(f"/local-cdn/pahma/objects/{SHA}?")
    cache_control = response.headers["cache-control"]
    assert cache_control.startswith("private, max-age=")
    assert 0 < int(cache_control.split("=")[1]) <= 1800
    assert local.get(path()).headers["location"] == location  # the same URL within the window
    served = local.get(location)
    assert served.status_code == 200
    assert served.content == BYTES
    assert served.headers["content-type"] == "image/jpeg"


def test_the_original_file(local: TestClient, store: Store) -> None:
    add_blob(store, "pahma", BLOB, MEDIA)
    cache(store, "pahma", None)
    assert local.get(path(size=None)).status_code == 302
    assert local.get(path(size="Thumbnail")).status_code == 302  # no entry: unavailable image, still a 302
    assert local.get(path(size="Thumbnail")).headers["location"] == "/unavailable/pahma.svg"


def test_a_tampered_or_expired_local_url_is_refused(local: TestClient, store: Store) -> None:
    add_blob(store, "pahma", BLOB, MEDIA)
    cache(store, "pahma", "Medium")
    location = local.get(path()).headers["location"]
    query = parse_qs(urlparse(location).query)
    base = urlparse(location).path
    assert local.get(f"{base}?Expires={query['Expires'][0]}&Signature=forged").status_code == 403
    assert local.get(f"{base}?Expires=1&Signature={query['Signature'][0]}").status_code == 403
    assert local.get(f"/local-cdn/pahma/objects/{'b' * 64}?Expires={query['Expires'][0]}"
                     f"&Signature={query['Signature'][0]}").status_code == 403


def test_a_miss_goes_to_the_fetch(local: TestClient, store: Store, recorder: MemoryRecorder) -> None:
    add_blob(store, "pahma", BLOB, MEDIA)
    assert local.get(path()).headers["location"] == "/unavailable/pahma.svg"
    assert recorder.recent[-1].reason == Reason.CSPACE_REFUSED  # no CollectionSpace account here; see test_fetch.py


def test_watermarked_sizes_until_watermarking_is_built(local: TestClient, store: Store,
                                                       recorder: MemoryRecorder) -> None:
    add_blob(store, "botgarden", BLOB, MEDIA)
    cache(store, "botgarden", "Medium")
    assert local.get(path("botgarden")).headers["location"] == "/unavailable/botgarden.svg"
    assert recorder.recent[-1].reason == Reason.WATERMARK_NOT_BUILT


def test_watermark_sizes_must_be_derivatives() -> None:
    config = museum.load("botgarden").model_dump()
    config["watermark_sizes"] = ["FullHD"]
    with pytest.raises(ValidationError, match="watermark_sizes"):
        museum.Museum.model_validate(config)


def test_without_a_signer_nothing_is_served(store: Store, s3: Any, recorder: MemoryRecorder) -> None:
    settings = Settings(tenants=TENANTS, table_prefix="t", _env_file=None)
    client = TestClient(create_app(settings, store, recorder, s3=s3), follow_redirects=False)
    add_blob(store, "pahma", BLOB, MEDIA)
    cache(store, "pahma", "Medium")
    assert client.get(path()).headers["location"] == "/unavailable/pahma.svg"
    assert recorder.recent[-1].reason == Reason.INTERNAL_ERROR
    assert client.get(f"/local-cdn/pahma/objects/{SHA}").status_code == 404  # no local CDN either


def test_the_local_cdn_is_only_for_local_development() -> None:
    with pytest.raises(ValidationError, match="local development"):
        Settings(local_cdn=True, _env_file=None)


def test_signed_urls_are_never_logged(local: TestClient, store: Store, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    add_blob(store, "pahma", BLOB, MEDIA)
    cache(store, "pahma", "Medium")
    location = local.get(path()).headers["location"]
    signature = parse_qs(urlparse(location).query)["Signature"][0]
    assert all(signature not in r.getMessage() and "Signature" not in str(vars(r)) for r in caplog.records
               if r.name.startswith("serena"))


# --- CloudFront

def test_cloudfront_signed_url(secretsmanager: Any) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)  # made here: no key in the repository
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    arn = secretsmanager.create_secret(Name="cloudfront", SecretString=json.dumps(
        {"key_pair_id": "KTESTKEYPAIR", "private_key": pem}))["ARN"]
    signer = signing.CloudFrontURLSigner("https://cdn.test", SecretCache(secretsmanager, 300), arn)
    expires = 1791591000
    url = signer.url("pahma", f"objects/{SHA}", expires)
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == f"https://cdn.test/pahma/objects/{SHA}"
    query = parse_qs(parsed.query)
    assert query["Expires"] == [str(expires)] and query["Key-Pair-Id"] == ["KTESTKEYPAIR"]
    # Verify as CloudFront does: the canned policy, signed with RSA-SHA1, in CloudFront's base64.
    policy = json.dumps({"Statement": [{"Resource": f"https://cdn.test/pahma/objects/{SHA}",
                                        "Condition": {"DateLessThan": {"AWS:EpochTime": expires}}}]},
                        separators=(",", ":")).encode()
    raw = base64.b64decode(query["Signature"][0].replace("-", "+").replace("_", "=").replace("~", "/"))
    key.public_key().verify(raw, policy, padding.PKCS1v15(), hashes.SHA1())  # noqa: S303
