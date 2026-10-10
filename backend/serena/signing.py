"""Signed URLs for stored files (design: Signed URLs).

A URL's expiry is the end of the 15-minute window after the current one, so every request for an object in the same
window gets the same URL (the browser can reuse it) and each URL lives between 15 and 30 minutes. Signed URLs are
never logged."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlencode

from botocore.signers import CloudFrontSigner
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from .secret_cache import SecretCache

WINDOW = 900  # seconds


def expiry(now: datetime) -> int:
    """Unix seconds: the end of the window after the current one."""
    start = int(now.timestamp()) // WINDOW * WINDOW
    return start + 2 * WINDOW


class Signer(Protocol):
    def url(self, tenant: str, object_key: str, expires: int) -> str: ...


class CloudFrontURLSigner:
    """CloudFront signed URLs with a canned policy, signed with the key group's private key (RSA, as CloudFront
    requires) from Secrets Manager: {"key_pair_id": ..., "private_key": "<PEM>"}. The key is read again after the
    secret cache's time, so a rotation needs no restart."""

    def __init__(self, base_url: str, secrets_cache: SecretCache, secret_id: str):
        self.base_url = base_url
        self.secrets = secrets_cache
        self.secret_id = secret_id
        self._parsed: tuple[str, rsa.RSAPrivateKey] | None = None  # the PEM last read, and its key

    def _key(self, pem: str) -> rsa.RSAPrivateKey:
        if self._parsed is None or self._parsed[0] != pem:
            key = serialization.load_pem_private_key(pem.encode(), password=None)
            if not isinstance(key, rsa.RSAPrivateKey):
                raise ValueError("the CloudFront signing key isn't an RSA key")
            self._parsed = (pem, key)
        return self._parsed[1]

    def url(self, tenant: str, object_key: str, expires: int) -> str:
        value = self.secrets.get_json(self.secret_id)
        key = self._key(value["private_key"])

        def rsa_signer(message: bytes) -> bytes:
            return key.sign(message, padding.PKCS1v15(), hashes.SHA1())  # noqa: S303 (CloudFront's algorithm)

        signer = CloudFrontSigner(value["key_pair_id"], rsa_signer)
        return str(signer.generate_presigned_url(f"{self.base_url}/{tenant}/{object_key}",
                                                 date_less_than=datetime.fromtimestamp(expires, UTC)))


class LocalSigner:
    """Local development only: an HMAC with a key made when the app starts, checked by /local-cdn."""

    PREFIX = "/local-cdn"

    def __init__(self) -> None:
        self.key = secrets.token_bytes(32)

    def _signature(self, tenant: str, object_key: str, expires: int) -> str:
        message = f"{tenant}\n{object_key}\n{expires}".encode()
        return base64.urlsafe_b64encode(hmac.new(self.key, message, hashlib.sha256).digest()).rstrip(b"=").decode()

    def url(self, tenant: str, object_key: str, expires: int) -> str:
        query = urlencode({"Expires": expires, "Signature": self._signature(tenant, object_key, expires)})
        return f"{self.PREFIX}/{tenant}/{object_key}?{query}"

    def valid(self, tenant: str, object_key: str, expires: int, signature: str, now: datetime) -> bool:
        if expires < int(now.timestamp()):
            return False
        return hmac.compare_digest(signature, self._signature(tenant, object_key, expires))
