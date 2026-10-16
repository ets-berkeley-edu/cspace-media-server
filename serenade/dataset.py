"""The suite's dataset: daily refreshes made by the fake ETL, built once per run by `./serena test`: PAHMA's, Cinefiles'
(for its PDFs), and two of UCJEPS's, the second of only 3 rows, so it fails its servable list check.

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
from typing import Any

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


# PAHMA's rows repeat image, image, catalog card (fake_etl.MIX), so rows 0, 1 and 3 are images and row 2 a card.
# T1, T2, T6, T8, T14, T15, T65 to T67, T72 to T75: looked at, never changed (T1's first request caches its Medium
# size, T14's its Small size).
SHARED_IMAGE = Record(0)
SHARED_CARD = Record(2)     # T9, T73: requested and looked up, never changed
# T77, T3, T4, T78, T79, T80, T81, T5: the recall chain. Recalled (T3), looked at while recalled, then the recall
# cancelled (T5), which puts it back as it started.
RESERVED_IMAGE = Record(1)
# T68, T69, T70: changed in CollectionSpace (taken off the web, replaced, soft-deleted), then put back with the
# simulator's hooks (approved again, restored, undeleted). Its Medium size is cached first. Put back, its file, Blob
# CSID and sizes are as they were; Media look up still marks As of, since each undo is a change in CollectionSpace.
CSPACE_CHANGES = Record(3)

# Synthetic CSIDs, never in any servable list (the inventory's Data roles sheet).
# T74: added to the simulator as a Media record, so CollectionSpace knows it and Serena doesn't. No other test uses it.
SIMULATOR_ONLY = "1a2b3c4d-0000-4000-8000-000000000074"


def unknown_csid(n: int) -> str:
    """A CSID neither Serena nor the simulator knows (T8, T15, T71, T75, T76)."""
    return f"9f9f9f9f-0000-4000-8000-{n:012d}"


# The requests the serving tests make, as Serena logs them (no query string): Past requests reads their lines.
UNKNOWN_PATH = f"/{MUSEUM}/imageserver/blobs/{unknown_csid(8)}/derivatives/Medium/content"  # T8: not listed
BAD_CSID_PATH = f"/{MUSEUM}/imageserver/blobs/not_a_csid/derivatives/Medium/content"  # T8: bad CSID; ?uid=&sig= asked
MISSPELLED_SIZE = "Thumbnial"  # T8: the shared image's path with a size Serena doesn't serve
SHARED_MEDIA_SMALL = f"/{MUSEUM}/imageserver/media/{SHARED_IMAGE.media}/blob/derivatives/Small/content"  # T14
SHARED_MEDIA_ORIGINAL = f"/{MUSEUM}/imageserver/media/{SHARED_IMAGE.media}/blob/content"  # T15
UNKNOWN_MEDIA_PATH = f"/{MUSEUM}/imageserver/media/{unknown_csid(15)}/blob/derivatives/Medium/content"  # T15


def _summary(refresh: str) -> dict[str, Any]:
    """A refresh's summary as the fake ETL printed it: PAHMA's in SERENADE_DATASET, the others beside it
    (dataset-<refresh>.json: dataset-cinefiles.json, dataset-ucjeps.json, dataset-ucjeps-failed.json)."""
    path = Path(os.environ["SERENADE_DATASET"])
    if refresh != MUSEUM:
        path = path.with_name(f"dataset-{refresh}.json")
    summary: dict[str, Any] = json.loads(path.read_text())
    return summary


def sample(museum: str, kind: str) -> str:
    """The path of a refresh's first record of a kind, as the fake ETL names them ("pdf", "pdf (restricted)")."""
    return str(_summary(museum)["samples"][kind])


def refresh_id(refresh: str) -> str:
    return str(_summary(refresh)["refresh_id"])


# The Cinefiles refresh: shared, its public and restricted PDFs (T7).
CINEFILES = "cinefiles"
# UCJEPS, a reserved museum (the inventory's Data roles): a normal refresh, then one of 3 rows that fails its servable
# list check (the delta over the threshold), which raises an alert. T23 to T25 look at its alerts and acknowledge them;
# then the refresh tests act on it: T17 looks, T18 overrides the threshold (so UCJEPS publishes 3 rows), T19 repairs a
# failed admin refresh, T21 adds admin refreshes up to 30. No PAHMA test uses UCJEPS.
UCJEPS = "ucjeps"
UCJEPS_FAILED = "ucjeps-failed"


def servable_list(name: str) -> Path:
    """A servable list ./serena test wrote beside the dataset (ucjeps-20, ucjeps-3), for an admin refresh."""
    return Path(os.environ["SERENADE_DATASET"]).with_name(f"{name}.tsv")


# How each refresh of the dataset ends.
STATES = {MUSEUM: "updated", CINEFILES: "updated", UCJEPS: "updated", UCJEPS_FAILED: "check_failed"}


def check_built() -> None:
    """Checks the dataset ./serena test built is the one these roles describe; fails the run clearly if not."""
    for refresh, expected in STATES.items():
        state = _summary(refresh).get("state")
        if state != expected:
            raise AssertionError(f"The dataset's {refresh} refresh ended {state!r}, not {expected!r}")
    summary = _summary(MUSEUM)
    if summary["samples"]["image"] != SHARED_IMAGE.path():
        raise AssertionError("The fake ETL's records aren't the ones serenade/dataset.py expects: "
                             f"{summary['samples']['image']} != {SHARED_IMAGE.path()}")
