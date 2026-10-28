"""The servability update: makes the servability table match a refresh's servable list (design: Servable list check
and servability update).

It reads the museum's rows from the table itself (through the by_tenant index), so it is right even after a
servability update that stopped partway (decided October 9, 2026, D35); unchanged rows aren't touched. It tightens
first and publishes last (decided October 28, 2026): first the deletes of Blobs no longer listed and every change that
makes a file less available (public to restricted, a changed Media CSID or kind), then the new rows and every change
that makes one more available. An update that stops partway then never serves a file it shouldn't: the worst is some
newly listed files not served yet. Every write is safe to repeat."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from . import tables
from .servable_list import Row, item, row_of
from .store import Store

BATCH = 25  # DynamoDB's limit per BatchWriteItem


@dataclass
class Counts:
    deleted: int = 0
    written: int = 0
    unchanged: int = 0


def current_rows(store: Store, tenant: str) -> dict[str, Row]:
    rows: dict[str, Row] = {}
    start: dict[str, Any] | None = None
    while True:
        options: dict[str, Any] = {"ExclusiveStartKey": start} if start else {}
        page = store.client.query(TableName=store.table(tables.SERVABILITY), IndexName="by_tenant",
                                  KeyConditionExpression="tenant = :t",
                                  ExpressionAttributeValues={":t": {"S": tenant}}, **options)
        for table_item in page["Items"]:
            blob, row = row_of(table_item)
            rows[blob] = row
        start = page.get("LastEvaluatedKey")
        if not start:
            return rows


def _write(store: Store, requests: list[dict[str, Any]], sleep: Callable[[float], None]) -> None:
    """BatchWriteItem in batches, retrying what DynamoDB leaves unprocessed (throttling), with backoff."""
    name = store.table(tables.SERVABILITY)
    for start in range(0, len(requests), BATCH):
        pending = requests[start:start + BATCH]
        for attempt in range(8):
            unprocessed = store.client.batch_write_item(RequestItems={name: pending}).get("UnprocessedItems", {})
            pending = unprocessed.get(name, [])
            if not pending:
                break
            sleep(min(0.05 * 2 ** attempt, 5))
        else:
            raise RuntimeError("DynamoDB kept leaving writes unprocessed")


# How available a file is by its access: public, then restricted (served only with a signed link), then anything else.
OPENNESS = {"public": 2, "restricted": 1}


def loosens(old: Row, new: Row) -> bool:
    """Whether a changed row only makes the same file more available: its Media CSID and kind are the same, and its
    access more open. Every other change tightens."""
    return (old.media_csid, old.kind) == (new.media_csid, new.kind) and \
        OPENNESS.get(new.access, 0) > OPENNESS.get(old.access, 0)


def update(store: Store, tenant: str, rows: dict[str, Row], sleep: Callable[[float], None] = time.sleep,
           listed_at: str | None = None) -> Counts:
    """`listed_at` is written on each new or changed row: of a Media record listed with several Blobs (a replaced
    image's old one beside the new), a Media URL uses the one listed most recently (decided October 14, 2026, D175)."""
    listed_at = listed_at or datetime.now(UTC).isoformat(timespec="seconds")
    now = current_rows(store, tenant)
    counts = Counts()
    deletes = [{"DeleteRequest": {"Key": {"pk": {"S": f"{tenant}#{blob}"}}}} for blob in now if blob not in rows]

    def put(blob: str, row: Row) -> dict[str, Any]:
        return {"PutRequest": {"Item": {**item(tenant, blob, row), "listed_at": {"S": listed_at}}}}
    changed = {blob: row for blob, row in rows.items() if now.get(blob) != row}
    tighten = [put(blob, row) for blob, row in changed.items() if blob in now and not loosens(now[blob], row)]
    publish = [put(blob, row) for blob, row in changed.items() if blob not in now or loosens(now[blob], row)]
    _write(store, deletes + tighten, sleep)
    _write(store, publish, sleep)
    counts.deleted = len(deletes)
    counts.written = len(changed)
    counts.unchanged = len(rows) - len(changed)
    return counts
