"""The ETL API's bearer tokens (design: The ETL API).

Each museum has one secret, {"current": ..., "previous": ...}; during a rotation both are accepted. Tokens are compared
in constant time and never logged."""
from __future__ import annotations

import hmac
import logging

from .secret_cache import SecretCache

log = logging.getLogger("serena.tokens")
MIN_LENGTH = 32


class TokenStoreUnavailable(Exception):
    """A museum's tokens couldn't be read."""


class Tokens:
    def __init__(self, secrets: SecretCache, secret_ids: dict[str, str]):
        self.secrets = secrets
        self.secret_ids = secret_ids

    def _tokens(self, tenant: str) -> list[str]:
        secret_id = self.secret_ids.get(tenant)
        if secret_id is None:
            return []
        try:
            value = self.secrets.get_json(secret_id)
        except Exception as error:
            log.warning("could not read the ETL tokens", extra={"museum": tenant, "error": type(error).__name__})
            raise TokenStoreUnavailable(tenant) from error
        return [t for t in (value.get("current"), value.get("previous")) if isinstance(t, str) and len(t) >= MIN_LENGTH]

    def museum_of(self, token: str) -> str | None:
        """The museum whose current or previous token this is, or None. Every museum's tokens are compared, each in
        constant time, so the answer's timing doesn't depend on which museum (if any) matched. A museum whose secret
        can't be read is skipped; if no museum matched and one was skipped, Serena can't tell, so it raises."""
        found = None
        unavailable = False
        candidate = token.encode()
        for tenant in sorted(self.secret_ids):
            try:
                known_tokens = self._tokens(tenant)
            except TokenStoreUnavailable:
                unavailable = True
                continue
            for known in known_tokens:
                if hmac.compare_digest(candidate, known.encode()):
                    found = tenant
        if found is None and unavailable:
            raise TokenStoreUnavailable("a museum's tokens couldn't be read")
        return found
