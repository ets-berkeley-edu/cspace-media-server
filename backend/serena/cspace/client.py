"""Calls to a museum's CollectionSpace (design: Image fetch).

Every call goes through the Media service, by the Media CSID from the servability record:

    GET /cspace-services/media/<media CSID>                                        the light check
    GET /cspace-services/media/<media CSID>/blob/content                           the original file
    GET /cspace-services/media/<media CSID>/blob/derivatives/<derivative>/content   a derivative

One pooled HTTP session per museum per task, HTTP Basic with the museum's read-only service account (its password
read from Secrets Manager, never logged), timeouts, retries for transient failures only, and a cap on simultaneous
calls per museum per task. A call never names a Blob CSID: the Media service returns the record's current file."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum

import httpx
from defusedxml import ElementTree

log = logging.getLogger("serena.cspace")
SERVICES = "/cspace-services"
TRANSIENT_STATUSES = frozenset({429, 502, 503, 504})
CHUNK = 64 * 1024


class MediaState(StrEnum):
    EXISTS = "exists"
    GONE = "gone"  # 404: no such Media record
    DELETED = "deleted"  # soft-deleted: the Media service still returns it, so the light check must catch it


class CSpaceError(Exception):
    """CollectionSpace answered with an error that isn't transient, or couldn't be asked."""

    def __init__(self, detail: str, status: int | None = None):
        super().__init__(detail)
        self.detail = detail
        self.status = status


class CSpaceUnavailable(CSpaceError):
    """No answer, or a transient error, after the retries."""


@dataclass
class Fetched:
    """A file being fetched: read it with chunks(), while the call is open."""

    status: int
    content_type: str
    content_length: int | None
    response: httpx.Response

    def chunks(self) -> Iterator[bytes]:
        yield from self.response.iter_bytes(CHUNK)


Credentials = Callable[[], tuple[str, str]]


class CSpaceClient:
    def __init__(self, tenant: str, base_url: str, credentials: Credentials, http: httpx.Client, *,
                 concurrency: int = 4, retries: int = 2, sleep: Callable[[float], None] = time.sleep):
        self.tenant = tenant
        self.base = base_url.rstrip("/") + SERVICES
        self.credentials = credentials
        self.http = http
        self.slots = threading.BoundedSemaphore(concurrency)
        self.retries = retries
        self.sleep = sleep

    def _send(self, path: str, *, stream: bool) -> httpx.Response:
        """GET, retrying transient failures with backoff. The caller holds a slot."""
        username, password = self.credentials()
        auth = httpx.BasicAuth(username, password)
        request = self.http.build_request("GET", self.base + path, headers={"User-Agent": "serena"})
        for attempt in range(self.retries + 1):
            try:
                response = self.http.send(request, auth=auth, stream=stream)
            except httpx.TransportError as error:  # no connection, a timeout, a dropped connection
                failure = type(error).__name__
            else:
                if response.status_code not in TRANSIENT_STATUSES:
                    return response
                failure = str(response.status_code)
                response.close()
            if attempt < self.retries:
                self.sleep(0.5 * 2 ** attempt)
        log.warning("CollectionSpace unavailable", extra={"museum": self.tenant, "path": path, "failure": failure,
                                                          "attempts": self.retries + 1})
        raise CSpaceUnavailable(f"GET {path}: {failure} after {self.retries + 1} attempts")

    def media_state(self, media_csid: str) -> MediaState:
        """The light check (design: The steps, step 4): whether the Media record exists and isn't soft-deleted.
        Its blobCsid is never read."""
        path = f"/media/{media_csid}"
        with self.slots:
            response = self._send(path, stream=False)
        if response.status_code == 404:
            return MediaState.GONE
        if response.status_code != 200:
            raise CSpaceError(f"GET {path} returned {response.status_code}", response.status_code)
        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError as error:
            raise CSpaceError(f"GET {path}: the answer isn't XML") from error
        states = [el.text or "" for el in root.iter() if el.tag.rsplit("}", 1)[-1] == "workflowState"]
        if any("deleted" in state.lower() for state in states):  # deleted, locked_deleted, replicated_deleted
            return MediaState.DELETED
        return MediaState.EXISTS

    @contextmanager
    def fetch(self, media_csid: str, derivative: str | None) -> Iterator[Fetched]:
        """The Media record's current file: the original (derivative None) or a derivative. Holds a slot while the
        file is read. The caller checks the status and content type."""
        tail = f"derivatives/{derivative}/content" if derivative else "content"
        path = f"/media/{media_csid}/blob/{tail}"
        with self.slots:
            response = self._send(path, stream=True)
            try:
                length = response.headers.get("content-length")
                yield Fetched(response.status_code,
                              response.headers.get("content-type", "").split(";")[0].strip().lower(),
                              int(length) if length and length.isdigit() else None, response)
            finally:
                response.close()
