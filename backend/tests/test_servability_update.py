from typing import Any

import pytest

from serena import servability_update as updating
from serena.servable_list import Row
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

    def recorded(st: Store, requests: list[dict[str, Any]], sleep: Any) -> None:
        batches.append([written(r) for r in requests])
        write(st, requests, sleep)

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
