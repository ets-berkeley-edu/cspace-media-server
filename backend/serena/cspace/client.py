"""Calls to a museum's CollectionSpace (design: Image fetch).

Every call goes through the Media service, by the Media CSID from the servability record:

    GET /cspace-services/media/<media CSID>                                        the light check
    GET /cspace-services/media/<media CSID>/blob/content                           the original file
    GET /cspace-services/media/<media CSID>/blob/derivatives/<derivative>/content   a derivative

For the recall form only (design: Recalls, Recalling), to tell a Media CSID from a Blob CSID that Serena's
servability table doesn't know, and to show a thumbnail of a file Serena hasn't stored:

    GET /cspace-services/media/<csid>                                              a Media record, with its blobCsid
    GET /cspace-services/blobs/<csid>                                              whether a Blob exists
    GET /cspace-services/media?as=media_common:blobCsid="<csid>"                   the Media record of a Blob

Media look up (design: Admin web app, Media look up; D139) reads the same Media record for what CollectionSpace says
now: whether it exists, its Blob, when it last changed and the museum's lookup fields.

One pooled HTTP session per museum per task, HTTP Basic with the museum's read-only service account (its password
read from Secrets Manager, never logged), timeouts, retries for transient failures only, and a cap on simultaneous
calls per museum per task. A fetch never names a Blob CSID: the Media service returns the record's current file."""
from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import quote

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


@dataclass(frozen=True)
class MediaRecord:
    """What Media look up shows of a Media record (D139, D140)."""

    state: MediaState
    blob_csid: str | None = None
    updated_at: str | None = None
    fields: tuple[tuple[str, str], ...] = ()  # (label, value), in the museum's order; "" when the field is empty
    identification_number: str | None = None  # media_common's identificationNumber: the page's heading (D153)


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

    def media_blob(self, media_csid: str) -> tuple[MediaState, str | None]:
        """For the recall form: whether a Media record exists, and its Blob CSID (its blobCsid)."""
        path = f"/media/{media_csid}"
        with self.slots:
            response = self._send(path, stream=False)
        if response.status_code == 404:
            return MediaState.GONE, None
        if response.status_code != 200:
            raise CSpaceError(f"GET {path} returned {response.status_code}", response.status_code)
        root = _xml(response.content, path)
        states = [el.text or "" for el in root.iter() if _local(el.tag) == "workflowState"]
        blob = next((el.text.strip() for el in root.iter() if _local(el.tag) == "blobCsid" and el.text), None)
        deleted = any("deleted" in state.lower() for state in states)
        return (MediaState.DELETED if deleted else MediaState.EXISTS), blob or None

    def media_record(self, media_csid: str, fields: Iterable[tuple[str, str, str]] = ()) -> MediaRecord:
        """For Media look up: the Media record's state, Blob, last change and the given fields, each (part, field,
        label). A field with several values (a repeating field) shows them joined; a vocabulary term shows its
        display name."""
        path = f"/media/{media_csid}"
        with self.slots:
            response = self._send(path, stream=False)
        if response.status_code == 404:
            return MediaRecord(MediaState.GONE)
        if response.status_code != 200:
            raise CSpaceError(f"GET {path} returned {response.status_code}", response.status_code)
        root = _xml(response.content, path)
        states = [el.text or "" for el in root.iter() if _local(el.tag) == "workflowState"]
        blob = next((el.text.strip() for el in root.iter() if _local(el.tag) == "blobCsid" and el.text), None)
        updated = next((el.text.strip() for el in root.iter() if _local(el.tag) == "updatedAt" and el.text), None)
        number = next((el.text.strip() for section in root if _local(section.tag) == "media_common"
                       for el in section if _local(el.tag) == "identificationNumber" and el.text and el.text.strip()),
                      None)
        shown = []
        for part, name, label in fields:
            values = [_display(el.text) for section in root if _local(section.tag) == part
                      for el in section.iter() if _local(el.tag) == name and el.text and el.text.strip()]
            shown.append((label, ", ".join(values)))
        deleted = any("deleted" in state.lower() for state in states)
        return MediaRecord(MediaState.DELETED if deleted else MediaState.EXISTS, blob or None, updated, tuple(shown),
                           number)

    def blob_exists(self, blob_csid: str) -> bool:
        path = f"/blobs/{blob_csid}"
        with self.slots:
            response = self._send(path, stream=False)
        if response.status_code == 404:
            return False
        if response.status_code != 200:
            raise CSpaceError(f"GET {path} returned {response.status_code}", response.status_code)
        return True

    def media_of_blob(self, blob_csid: str) -> str | None:
        """The CSID of the Media record whose blobCsid is this Blob's, if any."""
        query = quote(f'media_common:blobCsid="{blob_csid}"', safe="")
        path = f"/media?as={query}&pgSz=2"
        with self.slots:
            response = self._send(path, stream=False)
        if response.status_code != 200:
            raise CSpaceError(f"GET /media (search by blobCsid) returned {response.status_code}",
                              response.status_code)
        root = _xml(response.content, "/media (search)")
        for item in root.iter():
            if _local(item.tag) == "list-item":
                csid: str | None = next((el.text.strip() for el in item if _local(el.tag) == "csid" and el.text),
                                        None)
                if csid:
                    return csid
        return None

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


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


_TERM = re.compile(r"^urn:cspace:.*'(.*)'$", re.DOTALL)


def _display(text: str) -> str:
    """A field's value as people read it: a vocabulary term's refName shows as its display name, a boolean as Yes or
    No."""
    text = text.strip()
    found = _TERM.match(text)
    if found:
        return found.group(1)
    return {"true": "Yes", "false": "No"}.get(text.lower(), text)


def _xml(content: bytes, path: str) -> Any:
    try:
        return ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise CSpaceError(f"GET {path}: the answer isn't XML") from error
