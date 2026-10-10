"""The cache index (design: Storage): which stored object answers a Blob and derivative.

Keyed <tenant>#<blob CSID>#<derivative>, with "original" for the original file. Each entry names the object's
SHA-256 (its key is objects/<sha256> in the museum's bucket), content type, size and when it was fetched."""
from __future__ import annotations

from dataclasses import dataclass

from . import tables
from .store import Store

ORIGINAL = "original"


@dataclass(frozen=True)
class Entry:
    sha256: str
    content_type: str
    size: int
    fetched_at: str

    @property
    def key(self) -> str:
        return f"objects/{self.sha256}"


def key(tenant: str, blob_csid: str, derivative: str | None) -> str:
    return f"{tenant}#{blob_csid}#{derivative or ORIGINAL}"


def record(store: Store, tenant: str, blob_csid: str, derivative: str | None, entry: Entry) -> None:
    store.client.put_item(TableName=store.table(tables.CACHE_INDEX), Item={
        "pk": {"S": key(tenant, blob_csid, derivative)}, "sha256": {"S": entry.sha256},
        "content_type": {"S": entry.content_type}, "size": {"N": str(entry.size)},
        "fetched_at": {"S": entry.fetched_at}})


def lookup(store: Store, tenant: str, blob_csid: str, derivative: str | None) -> Entry | None:
    item = store.client.get_item(TableName=store.table(tables.CACHE_INDEX),
                                 Key={"pk": {"S": key(tenant, blob_csid, derivative)}}).get("Item")
    if item is None:
        return None
    return Entry(item["sha256"]["S"], item["content_type"]["S"], int(item["size"]["N"]), item["fetched_at"]["S"])
