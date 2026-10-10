"""Fetching a file on a cache miss (design: The steps, steps 4 and 5; Image fetch).

The light check first (the Media record exists and isn't soft-deleted), then the file through the Media service,
written to local disk while it's hashed and counted, checked for its kind, uploaded to objects/<sha256> in the
museum's bucket if it isn't there already, and indexed. Within a task, simultaneous requests for the same file wait on
one fetch. A failure that would repeat is remembered for a while, so CollectionSpace isn't asked again and again."""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import httpx
import pyvips
from botocore.exceptions import ClientError

from . import cache_index
from .cspace.client import CSpaceError, CSpaceUnavailable, MediaState
from .cspace.clients import CSpaceClients
from .museum import Museum
from .museum_settings import MuseumSettings
from .store import ServabilityRecord, Store
from .unserved import Reason

log = logging.getLogger("serena.fetch")

MB = 1024 * 1024
# No image/jp2: the bundled libvips can't decode JPEG 2000, so it couldn't be checked (decided with D49, October 10).
IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/tiff", "image/gif", "image/webp"})
# The content types each kind allows (design: Kinds; decided October 10, 2026). A new type is a small code change.
ALLOWED_TYPES: dict[str, frozenset[str]] = {
    "image": IMAGE_TYPES,
    "card": IMAGE_TYPES,
    "3D": frozenset({"model/x3d+xml", "model/x3d-vrml", "model/gltf-binary", "model/gltf+json", "model/obj",
                     "model/stl", "model/vnd.collada+xml", "model/ply"}),
    "pdf": frozenset({"application/pdf"}),
}
PDF_MARKER, PDF_MARKER_WITHIN = b"%PDF-", 1024  # where PDF readers look for it
# Failures that would repeat if asked again at once. Not CollectionSpace being unavailable, or a full disk.
REMEMBERED = frozenset({Reason.MEDIA_GONE, Reason.MEDIA_DELETED, Reason.NO_FILE, Reason.CSPACE_REFUSED,
                        Reason.WRONG_CONTENT_TYPE, Reason.TOO_LARGE, Reason.NOT_DECODABLE})


class _KeyedLocks:
    """One lock per key, dropped once nobody holds or waits on it."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, tuple[threading.Lock, int]] = {}

    @contextmanager
    def hold(self, key: str) -> Iterator[bool]:
        """Yields True if another request was already fetching this key (this one waited)."""
        with self._guard:
            lock, users = self._locks.get(key, (threading.Lock(), 0))
            self._locks[key] = (lock, users + 1)
        waited = not lock.acquire(blocking=False)
        if waited:
            lock.acquire()
        try:
            yield waited
        finally:
            lock.release()
            with self._guard:
                lock, users = self._locks[key]
                if users == 1:
                    del self._locks[key]
                else:
                    self._locks[key] = (lock, users - 1)


def decodes(path: str) -> bool:
    """Whether the whole image decodes. libvips reads it sequentially, so a large TIFF needs little memory."""
    try:
        image = pyvips.Image.new_from_file(path, access="sequential", fail=True)
        image.avg()  # forces every pixel to be decoded
    except pyvips.Error:
        return False
    return True


def is_pdf(path: str) -> bool:
    with open(path, "rb") as file:
        return PDF_MARKER in file.read(PDF_MARKER_WITHIN)


class Fetcher:
    def __init__(self, clients: CSpaceClients, s3: Any, buckets: dict[str, str], museum_settings: MuseumSettings,
                 store: Store, *, fetch_dir: str | None = None, free_margin_mb: int = 1024,
                 failure_seconds: float = 600.0, clock: Callable[[], float] = time.monotonic,
                 disk_free: Callable[[str], int] | None = None):
        self.clients = clients
        self.s3 = s3
        self.buckets = buckets
        self.museum_settings = museum_settings
        self.store = store
        self.fetch_dir = fetch_dir or tempfile.gettempdir()
        self.free_margin = free_margin_mb * MB
        self.failure_seconds = failure_seconds
        self.clock = clock
        self.disk_free = disk_free or (lambda path: shutil.disk_usage(path).free)
        self._locks = _KeyedLocks()
        self._failures: dict[str, tuple[Reason, float]] = {}
        self._failures_guard = threading.Lock()

    def get(self, museum: Museum, record: ServabilityRecord, derivative: str | None) -> cache_index.Entry | Reason:
        """The cache entry for a servable Blob that missed, fetched and stored now, or the reason it can't be."""
        index_key = cache_index.key(museum.key, record.blob_csid, derivative)
        with self._locks.hold(index_key) as waited:
            if waited:  # another request fetched it (or failed) while this one waited
                entry = cache_index.lookup(self.store, museum.key, record.blob_csid, derivative)
                if entry is not None:
                    return entry
            remembered = self._remembered(index_key)
            if remembered is not None:
                return remembered
            result = self._fetch(museum, record, derivative)
            if isinstance(result, Reason) and result in REMEMBERED:
                with self._failures_guard:
                    self._failures[index_key] = (result, self.clock() + self.failure_seconds)
            return result

    def _remembered(self, index_key: str) -> Reason | None:
        with self._failures_guard:
            found = self._failures.get(index_key)
            if found is None:
                return None
            if self.clock() >= found[1]:
                del self._failures[index_key]
                return None
            return found[0]

    def _fetch(self, museum: Museum, record: ServabilityRecord, derivative: str | None) -> cache_index.Entry | Reason:
        tenant, kind = museum.key, record.kind
        context = {"museum": tenant, "blob": record.blob_csid, "derivative": derivative or cache_index.ORIGINAL}
        if record.media_csid is None:
            log.warning("a servable Blob without a Media CSID", extra=context)
            return Reason.MEDIA_GONE
        try:
            client = self.clients.get(tenant)
            state = client.media_state(record.media_csid)
        except CSpaceUnavailable:
            return Reason.CSPACE_UNAVAILABLE
        except CSpaceError as error:
            log.warning("CollectionSpace refused the light check", extra={**context, "status": error.status})
            return Reason.CSPACE_REFUSED
        if state is MediaState.GONE:
            return Reason.MEDIA_GONE
        if state is MediaState.DELETED:
            return Reason.MEDIA_DELETED

        limit = self.museum_settings.get(museum).size_limit_mb[kind] * MB  # type: ignore[index]
        if self.disk_free(self.fetch_dir) < limit + self.free_margin:
            log.warning("not enough local disk to fetch", extra=context)
            return Reason.FETCH_BUSY

        started = time.monotonic()
        handle, path = tempfile.mkstemp(prefix="fetch-", dir=self.fetch_dir)
        try:
            with os.fdopen(handle, "wb") as out:
                result = self._download(client, record.media_csid, derivative, kind, limit, out, context)
            if isinstance(result, Reason):
                return result
            sha256, size, content_type = result
            if kind == "pdf" and not is_pdf(path):
                log.info("refused: not a PDF", extra=context)
                return Reason.WRONG_CONTENT_TYPE
            if kind in ("image", "card") and not decodes(path):
                log.info("refused: the image doesn't decode", extra={**context, "content_type": content_type})
                return Reason.NOT_DECODABLE
            self._upload(tenant, path, sha256, content_type, context)
            entry = cache_index.Entry(sha256, content_type, size,
                                      datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
            cache_index.record(self.store, tenant, record.blob_csid, derivative, entry)
            log.info("fetched", extra={**context, "kind": kind, "size": size,
                                       "seconds": round(time.monotonic() - started, 3)})
            return entry
        finally:
            os.unlink(path)

    def _download(self, client: Any, media_csid: str, derivative: str | None, kind: str, limit: int, out: Any,
                  context: dict[str, Any]) -> tuple[str, int, str] | Reason:
        """Streams the file to `out`, hashing and counting it. Returns (sha256, size, content type) or a reason."""
        try:
            with client.fetch(media_csid, derivative) as fetched:
                if fetched.status == 404:
                    return Reason.NO_FILE
                if fetched.status != 200:
                    log.warning("CollectionSpace refused the fetch", extra={**context, "status": fetched.status})
                    return Reason.CSPACE_REFUSED
                if fetched.content_type not in ALLOWED_TYPES[kind]:
                    log.info("refused: content type", extra={**context, "content_type": fetched.content_type})
                    return Reason.WRONG_CONTENT_TYPE
                if fetched.content_length is not None and fetched.content_length > limit:
                    log.info("refused: too large", extra={**context, "size": fetched.content_length})
                    return Reason.TOO_LARGE
                digest, size = hashlib.sha256(), 0
                for chunk in fetched.chunks():
                    size += len(chunk)
                    if size > limit:
                        log.info("refused: too large", extra={**context, "size": f">{limit}"})
                        return Reason.TOO_LARGE
                    digest.update(chunk)
                    out.write(chunk)
                return digest.hexdigest(), size, fetched.content_type
        except CSpaceUnavailable:
            return Reason.CSPACE_UNAVAILABLE
        except httpx.HTTPError as error:  # the connection dropped or stalled part-way through the file
            log.warning("the fetch broke off", extra={**context, "error": type(error).__name__})
            return Reason.CSPACE_UNAVAILABLE

    def _upload(self, tenant: str, path: str, sha256: str, content_type: str, context: dict[str, Any]) -> None:
        """objects/<sha256>, unless it's there already (the same bytes, fetched for another Blob or by another task)."""
        bucket, key = self.buckets[tenant], f"objects/{sha256}"
        try:
            self.s3.head_object(Bucket=bucket, Key=key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") not in ("404", "NoSuchKey", "NotFound"):
                raise
        else:
            log.info("already stored", extra=context)
            return
        # upload_file switches to a multipart upload for large files. The bucket's default encryption applies.
        self.s3.upload_file(path, bucket, key, ExtraArgs={"ContentType": content_type})
