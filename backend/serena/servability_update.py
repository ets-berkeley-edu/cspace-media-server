"""The servability update: makes the servability table match a refresh's servable list (design: Servable list check
and servability update).

It reads the museum's rows from the table itself (through the by_tenant index), so it is right even after a
servability update that stopped partway (decided October 9, 2026, D35); unchanged rows aren't touched. It tightens
first and publishes last (decided October 28, 2026): first the deletes of Blobs no longer listed and every change that
makes a file less available (public to restricted, a changed Media CSID or kind), then the new rows and every change
that makes one more available. An update that stops partway then never serves a file it shouldn't: the worst is some
newly listed files not served yet. Every write is safe to repeat.

Memory stays at about the size of the servable list's rows, however many there are (November 5, 2026, after a first
load of some 970,000 rows ran a 1 GiB worker out of memory): the table's rows are compared a page at a time and not
kept, only the Blob CSIDs to write are, and each batch's requests are made just before it is sent."""
from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import chain, islice
from typing import Any

from . import tables
from .servable_list import Row, item, row_of
from .store import Store

BATCH = 25  # DynamoDB's limit per BatchWriteItem

# Told how many writes are done and how many there are, after each batch (the refresh's page shows it).
Progress = Callable[[int, int], None]


@dataclass
class Counts:
    deleted: int = 0
    written: int = 0
    unchanged: int = 0


def _current_items(store: Store, tenant: str) -> Iterator[dict[str, Any]]:
    """The museum's items in the servability table, a page at a time."""
    start: dict[str, Any] | None = None
    while True:
        options: dict[str, Any] = {"ExclusiveStartKey": start} if start else {}
        page = store.client.query(TableName=store.table(tables.SERVABILITY), IndexName="by_tenant",
                                  KeyConditionExpression="tenant = :t",
                                  ExpressionAttributeValues={":t": {"S": tenant}}, **options)
        yield from page["Items"]
        start = page.get("LastEvaluatedKey")
        if not start:
            return


def current_rows(store: Store, tenant: str) -> dict[str, Row]:
    return dict(row_of(table_item) for table_item in _current_items(store, tenant))


def _write(store: Store, requests: Iterable[dict[str, Any]], sleep: Callable[[float], None],
           written: Callable[[int], None] | None = None) -> None:
    """BatchWriteItem in batches, retrying what DynamoDB leaves unprocessed (throttling), with backoff. `requests` is
    read a batch at a time; `written` is told each batch's size once it is done."""
    name = store.table(tables.SERVABILITY)
    stream = iter(requests)
    while batch := list(islice(stream, BATCH)):
        pending = batch
        for attempt in range(8):
            unprocessed = store.client.batch_write_item(RequestItems={name: pending}).get("UnprocessedItems", {})
            pending = unprocessed.get(name, [])
            if not pending:
                break
            sleep(min(0.05 * 2 ** attempt, 5))
        else:
            raise RuntimeError("DynamoDB kept leaving writes unprocessed")
        if written is not None:
            written(len(batch))


# How available a file is by its access: public, then restricted (served only with a signed link), then anything else.
OPENNESS = {"public": 2, "restricted": 1}


def loosens(old: Row, new: Row) -> bool:
    """Whether a changed row only makes the same file more available: its Media CSID and kind are the same, and its
    access more open. Every other change tightens."""
    return (old.media_csid, old.kind) == (new.media_csid, new.kind) and \
        OPENNESS.get(new.access, 0) > OPENNESS.get(old.access, 0)


def update(store: Store, tenant: str, rows: dict[str, Row], sleep: Callable[[float], None] = time.sleep,
           listed_at: str | None = None, progress: Progress | None = None) -> Counts:
    """`listed_at` is written on each new or changed row: of a Media record listed with several Blobs (a replaced
    image's old one beside the new), a Media URL uses the one listed most recently (decided October 14, 2026, D175).
    `progress`, if given, is told how many writes are done and how many there are: once before the first, then after
    each batch."""
    listed_at = listed_at or datetime.now(UTC).isoformat(timespec="seconds")
    counts = Counts()
    # Blob CSIDs only: the requests are made a batch at a time as they are sent.
    deletes: list[str] = []
    tighten: list[str] = []
    publish: list[str] = []
    seen: set[str] = set()
    for table_item in _current_items(store, tenant):
        blob, old = row_of(table_item)
        new = rows.get(blob)
        if new is None:
            deletes.append(blob)
            continue
        seen.add(blob)
        if new == old:
            counts.unchanged += 1
        elif loosens(old, new):
            publish.append(blob)
        else:
            tighten.append(blob)
    publish.extend(blob for blob in rows if blob not in seen)
    del seen

    def put(blob: str) -> dict[str, Any]:
        return {"PutRequest": {"Item": {**item(tenant, blob, rows[blob]), "listed_at": {"S": listed_at}}}}

    def delete(blob: str) -> dict[str, Any]:
        return {"DeleteRequest": {"Key": {"pk": {"S": f"{tenant}#{blob}"}}}}

    total = len(deletes) + len(tighten) + len(publish)
    done = 0

    def written(n: int) -> None:
        nonlocal done
        done += n
        if progress is not None:
            progress(done, total)

    if progress is not None:
        progress(0, total)
    _write(store, chain(map(delete, deletes), map(put, tighten)), sleep, written)
    _write(store, map(put, publish), sleep, written)
    counts.deleted = len(deletes)
    counts.written = len(tighten) + len(publish)
    return counts
