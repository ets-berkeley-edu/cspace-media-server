"""The Blob-to-Media file (design: The Blob-to-Media file) and the servability rows made from it.

Reading never holds the compressed file whole; the rows themselves are kept in a dict, about a few hundred bytes each
(PAHMA's few hundred thousand rows: some tens of MB)."""
from __future__ import annotations

import gzip
from collections.abc import Iterator
from dataclasses import dataclass
from typing import IO, Any

HEADER = "blob_csid\tmedia_csid\tkind\taccess"
KINDS = frozenset({"image", "card", "audio", "video", "3D", "pdf"})
ACCESS = frozenset({"public", "restricted"})


@dataclass(frozen=True)
class Row:
    media_csid: str  # "" only for the museum's restricted-image Blob
    kind: str
    access: str


def lines(compressed: IO[bytes]) -> Iterator[tuple[int, bytes]]:
    """(line number, line without its LF) for each line of a gzip-compressed file; line 1 is the header."""
    with gzip.GzipFile(fileobj=compressed, mode="rb") as raw:
        for number, line in enumerate(raw, start=1):
            yield number, line[:-1] if line.endswith(b"\n") else line


def read_rows(compressed: IO[bytes]) -> dict[str, Row]:
    """The rows of a file that passed the preflight (no checks here)."""
    rows = {}
    for number, line in lines(compressed):
        if number == 1:
            continue
        blob, media, kind, access = line.decode("utf-8").split("\t")
        rows[blob] = Row(media, kind, access)
    return rows


def item(tenant: str, blob: str, row: Row) -> dict[str, Any]:
    """The servability table's item for a row (design: Records)."""
    value: dict[str, Any] = {"pk": {"S": f"{tenant}#{blob}"}, "tenant": {"S": tenant}, "blob_csid": {"S": blob},
                             "kind": {"S": row.kind}, "access": {"S": row.access}}
    if row.media_csid:
        value["media_csid"] = {"S": row.media_csid}
        value["media_key"] = {"S": f"{tenant}#{row.media_csid}"}
    return value


def row_of(table_item: dict[str, Any]) -> tuple[str, Row]:
    return table_item["blob_csid"]["S"], Row(table_item.get("media_csid", {}).get("S", ""),
                                             table_item["kind"]["S"], table_item["access"]["S"])
