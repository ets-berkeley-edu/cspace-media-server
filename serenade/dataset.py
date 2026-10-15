"""The suite's dataset: one PAHMA daily refresh made by the fake ETL, built once per run by `./serena test`.

The fake ETL makes its synthetic CSIDs from the museum and a row number (backend/devtools/fake_etl.py: csid()), so
every run has the same records. Records are given roles, so tests can share one dataset without resets:

- a shared record: tests may look at it, never change it;
- a reserved record: set aside for the tests that change it, which put it back where they can.

Add a role here when a test needs a record of its own, and say which tests use it."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

# The same namespace as backend/devtools/fake_etl.py (NAMESPACE): not a secret, only how the synthetic CSIDs are made.
_NAMESPACE = uuid.UUID("3f6b0c55-2c4e-4f6e-9d4b-6a1c0b6e5a10")
MUSEUM = "pahma"
ROWS = 20  # the fake ETL's default; ./serena test uses it


def _csid(what: str, n: int) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{MUSEUM}/{what}/{n}"))


@dataclass(frozen=True)
class Record:
    row: int

    @property
    def blob(self) -> str:
        return _csid("blob", self.row)

    @property
    def media(self) -> str:
        return _csid("media", self.row)

    def path(self, size: str = "Medium") -> str:
        return f"/{MUSEUM}/imageserver/blobs/{self.blob}/derivatives/{size}/content"


# PAHMA's rows repeat image, image, catalog card (fake_etl.MIX), so rows 0 and 1 are images.
SHARED_IMAGE = Record(0)    # T1, T2, T6: looked at, never changed (T1's first request caches its Medium size)
RESERVED_IMAGE = Record(1)  # T3, T4, T5: recalled, looked at while recalled, then the recall cancelled


def check_built() -> None:
    """Checks the dataset ./serena test built is the one these roles describe; fails the run clearly if not."""
    summary = json.loads(Path(os.environ["SERENADE_DATASET"]).read_text())
    if summary.get("state") != "updated":
        raise AssertionError(f"The dataset's refresh ended {summary.get('state')!r}, not 'updated': {summary}")
    if summary["samples"]["image"] != SHARED_IMAGE.path():
        raise AssertionError("The fake ETL's records aren't the ones serenade/dataset.py expects: "
                             f"{summary['samples']['image']} != {SHARED_IMAGE.path()}")
