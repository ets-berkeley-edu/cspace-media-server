"""The servability update: makes the servability table match a refresh's servable list (design: Servable list check
and servability update).

It reads the museum's rows from the table itself (through the by_tenant index), so it is right even after a
servability update that stopped partway (decided October 9, 2026, D35). It deletes the rows of Blobs no longer listed
first, then writes the new and changed rows; unchanged rows aren't touched. Deleting first means a servability update
that stops halfway never serves a Blob the new servable list dropped. Every write is safe to repeat."""
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


def update(store: Store, tenant: str, rows: dict[str, Row], sleep: Callable[[float], None] = time.sleep,
           listed_at: str | None = None) -> Counts:
    """`listed_at` is written on each new or changed row: of a Media record listed with several Blobs (a replaced
    image's old one beside the new), a Media URL uses the one listed most recently (decided October 14, 2026, D175)."""
    listed_at = listed_at or datetime.now(UTC).isoformat(timespec="seconds")
    now = current_rows(store, tenant)
    counts = Counts()
    deletes = [{"DeleteRequest": {"Key": {"pk": {"S": f"{tenant}#{blob}"}}}} for blob in now if blob not in rows]
    _write(store, deletes, sleep)
    counts.deleted = len(deletes)
    puts = [{"PutRequest": {"Item": {**item(tenant, blob, row), "listed_at": {"S": listed_at}}}}
            for blob, row in rows.items() if now.get(blob) != row]
    _write(store, puts, sleep)
    counts.written = len(puts)
    counts.unchanged = len(rows) - len(puts)
    return counts
