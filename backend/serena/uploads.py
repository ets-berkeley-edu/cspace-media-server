"""Receiving a Blob-to-Media file (design: The ETL API, PUT …/blob-media).

The body is streamed to the task's disk while it's decompressed (if gzip), hashed and counted, and written there
gzip-compressed; nothing is held whole in memory. Only then, if it matches its headers, is it stored in S3. Its
format is checked by the preflight, not here."""
from __future__ import annotations

import gzip
import hashlib
import os
import tempfile
import zlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any


class TooLarge(Exception):
    pass


class BadGzip(Exception):
    pass


@dataclass
class Received:
    path: str  # the gzip-compressed copy on local disk; the caller removes it
    sha256: str  # of the uncompressed bytes
    rows: int  # data rows: lines after the header
    size: int  # uncompressed bytes


PIECE = 1024 * 1024  # decompressed in pieces of at most 1 MB, so a small compressed chunk can't fill memory


def _inflate(inflater: Any, chunk: bytes) -> list[bytes]:
    pieces = []
    try:
        data = inflater.decompress(chunk, PIECE)
        while data:
            pieces.append(data)
            data = inflater.decompress(inflater.unconsumed_tail, PIECE) if inflater.unconsumed_tail else b""
    except zlib.error as error:
        raise BadGzip from error
    return pieces


async def receive(chunks: AsyncIterator[bytes], *, gzipped: bool, max_bytes: int, directory: str | None) -> Received:
    digest = hashlib.sha256()
    size = 0
    newlines = 0
    last = b""
    inflater = zlib.decompressobj(wbits=31) if gzipped else None
    fd, path = tempfile.mkstemp(prefix="blob-media-", suffix=".tsv.gz", dir=directory)
    try:
        with os.fdopen(fd, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as out:
            async for chunk in chunks:
                for data in _inflate(inflater, chunk) if inflater is not None else [chunk]:
                    if not data:
                        continue
                    size += len(data)
                    if size > max_bytes:
                        raise TooLarge
                    digest.update(data)
                    newlines += data.count(b"\n")
                    last = data[-1:]
                    out.write(data)
            if inflater is not None and size and not inflater.eof:
                raise BadGzip
    except BaseException:
        os.unlink(path)
        raise
    lines = newlines + (1 if size and last != b"\n" else 0)
    return Received(path, digest.hexdigest(), max(lines - 1, 0), size)


def store(s3: Any, bucket: str, key: str, received: Received) -> None:
    """Upload the compressed copy (multipart for a large file). The bucket's default encryption (KMS) applies."""
    s3.upload_file(received.path, bucket, key, ExtraArgs={
        "ContentType": "text/tab-separated-values", "ContentEncoding": "gzip",
        "Metadata": {"sha256": received.sha256, "rows": str(received.rows)}})
