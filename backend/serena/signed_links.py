"""Signed links for restricted files (design: Restricted files, Signed links).

A portal vouches for a reader by adding exp, uid, kid and sig to a file's link. sig is HMAC-SHA256 over
"v1\\n<tenant>\\n<blob CSID>\\n<exp>\\n<uid>", in base64url without padding, with a key Serena shares with the portal.

Each museum's keys are one Secrets Manager secret, {"current": {"kid", "key"}, "previous": {"kid", "key"} or null};
during a rotation both are accepted. A key is used as its UTF-8 bytes; one shorter than 32 characters is ignored.
Keys, signatures and the reader's uid are never logged."""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .secret_cache import SecretCache
from .unserved import Reason

log = logging.getLogger("serena.signed_links")

PARAMETERS = ("exp", "uid", "kid", "sig")
MIN_KEY_LENGTH = 32
CLOCK_SKEW_SECONDS = 60
MAX_AHEAD_SECONDS = 60 * 60

_FORMATS = {
    "exp": re.compile(r"[0-9]{1,11}"),
    "uid": re.compile(r"[0-9]{1,20}"),
    "kid": re.compile(r"[A-Za-z0-9._-]{1,64}"),
    "sig": re.compile(r"[A-Za-z0-9_-]{43}"),
}


class SigningKeysUnavailable(Exception):
    """A museum's signing keys couldn't be read."""


@dataclass(frozen=True)
class Verdict:
    reason: Reason | None  # None: a valid signed link
    kid: str | None = None  # the key that signed a valid link; not secret

    @property
    def valid(self) -> bool:
        return self.reason is None


def signed_string(tenant: str, blob_csid: str, exp: str, uid: str) -> bytes:
    return "\n".join(("v1", tenant, blob_csid, exp, uid)).encode()


def signature(key: str, tenant: str, blob_csid: str, exp: str, uid: str) -> str:
    digest = hmac.new(key.encode(), signed_string(tenant, blob_csid, exp, uid), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class SigningKeys:
    def __init__(self, secrets: SecretCache, secret_ids: dict[str, str]):
        self.secrets = secrets
        self.secret_ids = secret_ids

    def keys(self, tenant: str) -> dict[str, str]:
        """The museum's usable keys, by key ID. Empty if it has no secret. Raises SigningKeysUnavailable if the secret
        can't be read; the error's details aren't logged, since they could carry part of the secret."""
        secret_id = self.secret_ids.get(tenant)
        if secret_id is None:
            return {}
        try:
            value = self.secrets.get_json(secret_id)
        except Exception as error:
            log.warning("could not read the signing keys", extra={"museum": tenant, "error": type(error).__name__})
            raise SigningKeysUnavailable(tenant) from error
        found: dict[str, str] = {}
        for slot in ("current", "previous"):
            entry = value.get(slot)
            if not isinstance(entry, dict):
                continue
            kid, key = entry.get("kid"), entry.get("key")
            if not isinstance(kid, str) or not _FORMATS["kid"].fullmatch(kid) or not isinstance(key, str):
                log.warning("a signing key entry is malformed", extra={"museum": tenant, "slot": slot})
                continue
            if len(key) < MIN_KEY_LENGTH:
                log.warning("a signing key is too short and is ignored", extra={"museum": tenant, "slot": slot})
                continue
            found[kid] = key
        return found


def verify(keys: SigningKeys, tenant: str, blob_csid: str, query: Mapping[str, Sequence[str]], now: int) -> Verdict:
    """Whether the link's query vouches for this file. `query` maps each parameter to all its values."""
    values = {name: query.get(name, []) for name in PARAMETERS}
    if not any(values.values()):
        return Verdict(Reason.RESTRICTED)
    if any(len(found) != 1 or not _FORMATS[name].fullmatch(found[0]) for name, found in values.items()):
        return Verdict(Reason.SIGNATURE_INVALID)
    exp, uid, kid, sig = (values[name][0] for name in PARAMETERS)
    key = keys.keys(tenant).get(kid)
    if key is None:
        return Verdict(Reason.SIGNATURE_INVALID)
    expected = signature(key, tenant, blob_csid, exp, uid)
    if not hmac.compare_digest(expected.encode(), sig.encode()):
        return Verdict(Reason.SIGNATURE_INVALID)
    expires = int(exp)
    if now > expires + CLOCK_SKEW_SECONDS or expires > now + MAX_AHEAD_SECONDS + CLOCK_SKEW_SECONDS:
        return Verdict(Reason.SIGNATURE_EXPIRED)
    return Verdict(None, kid)
