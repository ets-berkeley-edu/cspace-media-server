"""One CollectionSpace client per museum, per task (design: Image fetch, Connections)."""
from __future__ import annotations

import threading
from collections.abc import Callable

import httpx

from ..config import Settings
from ..secret_cache import SecretCache
from .client import CSpaceClient, CSpaceError

HttpFactory = Callable[[str], httpx.Client]


class CSpaceClients:
    def __init__(self, settings: Settings, secrets: SecretCache, http_factory: HttpFactory | None = None):
        self.settings = settings
        self.secrets = secrets
        self.http_factory = http_factory or self._http
        self._lock = threading.Lock()
        self._clients: dict[str, CSpaceClient] = {}

    def _http(self, tenant: str) -> httpx.Client:
        s = self.settings
        timeout = httpx.Timeout(connect=s.cspace_connect_timeout_seconds, read=s.cspace_read_timeout_seconds,
                                write=s.cspace_read_timeout_seconds, pool=s.cspace_read_timeout_seconds)
        limits = httpx.Limits(max_connections=s.cspace_concurrency, max_keepalive_connections=s.cspace_concurrency)
        return httpx.Client(timeout=timeout, limits=limits, follow_redirects=False)

    def _credentials(self, tenant: str) -> tuple[str, str]:
        secret_id = self.settings.cspace_secret_ids.get(tenant)
        if not secret_id:
            raise CSpaceError(f"no CollectionSpace account configured for {tenant}")
        value = self.secrets.get_json(secret_id)
        username, password = value.get("username"), value.get("password")
        if not isinstance(username, str) or not isinstance(password, str) or not username or not password:
            raise CSpaceError(f"the CollectionSpace account secret for {tenant} needs a username and a password")
        return username, password

    def get(self, tenant: str) -> CSpaceClient:
        with self._lock:
            client = self._clients.get(tenant)
            if client is None:
                if tenant not in self.settings.tenants:
                    raise CSpaceError(f"Serena doesn't serve {tenant}")
                client = CSpaceClient(tenant, self.settings.tenants[tenant], lambda: self._credentials(tenant),
                                      self.http_factory(tenant), concurrency=self.settings.cspace_concurrency,
                                      retries=self.settings.cspace_retries)
                self._clients[tenant] = client
            return client

    def close(self) -> None:
        with self._lock:
            for client in self._clients.values():
                client.http.close()
            self._clients.clear()
