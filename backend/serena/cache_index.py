"""The cache index (design: Storage): which stored object answers a Blob and derivative.

Keyed <tenant>#<blob CSID>#<derivative>, with "original" for the original file. Each entry names the object's
SHA-256 (its key is objects/<sha256> in the museum's bucket), content type, size, when it was fetched, and when it was
last served, to the day (decided October 13, 2026, D142): written when it's fetched, then on a request at most once a
day, so a file requested months apart still shows when, without a write on every request."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import tables
from .store import Store

log = logging.getLogger("serena.cache_index")
ORIGINAL = "original"
LAST_SERVED_EVERY = timedelta(days=1)
STAMP = "%Y-%m-%dT%H:%M:%SZ"  # as fetched_at


@dataclass(frozen=True)
class Entry:
    sha256: str
    content_type: str
    size: int
    fetched_at: str
    last_served: str | None = None

    @property
    def key(self) -> str:
        return f"objects/{self.sha256}"


def key(tenant: str, blob_csid: str, derivative: str | None) -> str:
    return f"{tenant}#{blob_csid}#{derivative or ORIGINAL}"


def record(store: Store, tenant: str, blob_csid: str, derivative: str | None, entry: Entry) -> None:
    store.client.put_item(TableName=store.table(tables.CACHE_INDEX), Item={
        "pk": {"S": key(tenant, blob_csid, derivative)}, "sha256": {"S": entry.sha256},
        "content_type": {"S": entry.content_type}, "size": {"N": str(entry.size)},
        "fetched_at": {"S": entry.fetched_at}, "last_served": {"S": entry.last_served or entry.fetched_at}})


def lookup(store: Store, tenant: str, blob_csid: str, derivative: str | None) -> Entry | None:
    item = store.client.get_item(TableName=store.table(tables.CACHE_INDEX),
                                 Key={"pk": {"S": key(tenant, blob_csid, derivative)}}).get("Item")
    if item is None:
        return None
    return Entry(item["sha256"]["S"], item["content_type"]["S"], int(item["size"]["N"]), item["fetched_at"]["S"],
                 item.get("last_served", {}).get("S"))


def served(store: Store, tenant: str, blob_csid: str, derivative: str | None, entry: Entry, now: datetime) -> None:
    """Records that a stored copy was served, at most once a day (D142). A failure is logged and never fails the
    request: the time is for Media look up only."""
    stamp = now.strftime(STAMP)
    cutoff = (now - LAST_SERVED_EVERY).strftime(STAMP)
    if entry.last_served is not None and entry.last_served > cutoff:
        return
    try:
        store.client.update_item(
            TableName=store.table(tables.CACHE_INDEX), Key={"pk": {"S": key(tenant, blob_csid, derivative)}},
            UpdateExpression="SET last_served = :now",
            ConditionExpression="attribute_exists(pk) AND (attribute_not_exists(last_served) OR last_served < :cutoff)",
            ExpressionAttributeValues={":now": {"S": stamp}, ":cutoff": {"S": cutoff}})
    except store.client.exceptions.ConditionalCheckFailedException:
        pass  # another task recorded it first
    except Exception as error:
        log.warning("last served not recorded", extra={"museum": tenant, "error": type(error).__name__})
