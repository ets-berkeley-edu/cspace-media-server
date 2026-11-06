import tracemalloc
from collections.abc import Iterable
from typing import Any

import pytest

from serena import servability_update as updating
from serena.servable_list import Row, item
from serena.store import Store

# Synthetic CSIDs.
B = [f"0a1b2c3d-0000-4000-8000-{n:012d}" for n in range(8)]
M = [f"1a2b3c4d-0000-4000-8000-{n:012d}" for n in range(8)]


def test_tightens_first_and_publishes_last(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """Decided October 28, 2026: the deletes and every change that makes a file less available are written before the
    new rows and every change that makes one more available, so an update that stops between them never serves a
    file the new list restricts or drops."""
    before = {B[0]: Row(M[0], "image", "public"),  # dropped
              B[1]: Row(M[1], "image", "public"),  # now restricted: tightens
              B[2]: Row(M[2], "image", "public"),  # a new Media CSID: tightens
              B[3]: Row(M[3], "image", "restricted"),  # now public: loosens
              B[4]: Row(M[4], "image", "public")}  # unchanged
    updating.update(store, "pahma", before, sleep=lambda s: None)
    after = {B[1]: Row(M[1], "image", "restricted"), B[2]: Row(M[5], "image", "public"),
             B[3]: Row(M[3], "image", "public"), B[4]: Row(M[4], "image", "public"),
             B[6]: Row(M[6], "pdf", "public")}  # new: publishes
    batches: list[list[str]] = []
    write = updating._write

    def written(request: dict[str, Any]) -> str:
        if "DeleteRequest" in request:
            return f"delete {request['DeleteRequest']['Key']['pk']['S']}"
        return f"put {request['PutRequest']['Item']['pk']['S']}"

    def recorded(st: Store, requests: Iterable[dict[str, Any]], sleep: Any, done: Any = None) -> None:
        requests = list(requests)
        batches.append([written(r) for r in requests])
        write(st, requests, sleep, done)

    monkeypatch.setattr(updating, "_write", recorded)
    counts = updating.update(store, "pahma", after, sleep=lambda s: None)
    assert (counts.deleted, counts.written, counts.unchanged) == (1, 4, 1)
    tighten, publish = batches
    assert sorted(tighten) == sorted([f"delete pahma#{B[0]}", f"put pahma#{B[1]}", f"put pahma#{B[2]}"])
    assert sorted(publish) == sorted([f"put pahma#{B[3]}", f"put pahma#{B[6]}"])
    assert updating.current_rows(store, "pahma") == after


def test_what_loosens() -> None:
    assert updating.loosens(Row(M[0], "image", "restricted"), Row(M[0], "image", "public"))
    assert updating.loosens(Row(M[0], "image", "none"), Row(M[0], "image", "restricted"))
    assert not updating.loosens(Row(M[0], "image", "public"), Row(M[0], "image", "restricted"))
    assert not updating.loosens(Row(M[0], "image", "restricted"), Row(M[1], "image", "public"))  # another Media record
    assert not updating.loosens(Row(M[0], "image", "restricted"), Row(M[0], "pdf", "public"))  # another kind


def test_tells_its_progress(store: Store) -> None:
    """The refresh's page shows how far the update has got (November 5, 2026): told once before the first write, then
    after each batch, ending at the total."""
    before = {f"0a1b2c3d-0000-4000-8000-{n:012d}": Row(M[0], "image", "public") for n in range(30)}
    told: list[tuple[int, int]] = []
    updating.update(store, "pahma", before, sleep=lambda s: None,
                    progress=lambda done, total: told.append((done, total)))
    assert told == [(0, 30), (25, 30), (30, 30)]
    after = {blob: row for n, (blob, row) in enumerate(before.items()) if n >= 10}  # 10 dropped
    after.update({f"0b1b2c3d-0000-4000-8000-{n:012d}": Row(M[1], "pdf", "public") for n in range(40)})  # 40 new
    told.clear()
    counts = updating.update(store, "pahma", after, sleep=lambda s: None,
                             progress=lambda done, total: told.append((done, total)))
    assert (counts.deleted, counts.written, counts.unchanged) == (10, 40, 20)
    assert told[0] == (0, 50) and told[-1] == (50, 50)
    assert [done for done, _ in told] == sorted(done for done, _ in told)


class _Table:
    """A stand-in for DynamoDB that keeps nothing it's given: the update's own memory is what's measured."""

    def __init__(self, items: list[dict[str, Any]]):
        self.items, self.written = items, 0

    def query(self, **kwargs: Any) -> dict[str, Any]:
        start = int(kwargs.get("ExclusiveStartKey", {}).get("n", 0))
        page: dict[str, Any] = {"Items": self.items[start:start + 1000]}
        if start + 1000 < len(self.items):
            page["LastEvaluatedKey"] = {"n": start + 1000}
        return page

    def batch_write_item(self, RequestItems: dict[str, list[Any]]) -> dict[str, Any]:  # boto3's name
        self.written += sum(len(batch) for batch in RequestItems.values())
        return {}


def test_memory_stays_near_the_lists_size() -> None:
    """A first load of some 970,000 rows ran a 1 GiB worker out of memory (November 5, 2026): every write request was
    made before the first was sent, about 3 KB a row. Now the update holds only the Blob CSIDs to write: for 200,000
    new rows and 1,000 already in the table, a few MB beside the list's own rows."""
    rows = {f"0a1b2c3d-0000-4000-8000-{n:012d}": Row(f"1a2b3c4d-0000-4000-8000-{n:012d}", "image", "public")
            for n in range(200_000)}
    table = _Table([item("pahma", blob, row) for blob, row in list(rows.items())[:1000]])
    store = Store(table, "t")
    tracemalloc.start()
    try:
        base = tracemalloc.get_traced_memory()[0]
        counts = updating.update(store, "pahma", rows, sleep=lambda s: None)
        peak = tracemalloc.get_traced_memory()[1] - base
    finally:
        tracemalloc.stop()
    assert (counts.written, counts.unchanged, table.written) == (199_000, 1000, 199_000)
    assert peak < 20 * 2 ** 20, f"the update used {peak / 2 ** 20:.0f} MB"
