"""PAHMA QA's synthetic test records (SERENA-TEST-001 to -051) as make-test-media.py made and changed them.

The script is kept outside this repository (its absolute path in SERENADE_TEST_MEDIA_SCRIPT). Everything here is read
from its git-ignored out/: test-media.pahma.<stamp>.csv (one file per run that made records: identification number,
Media, Blob and Object CSIDs, the file), changes.pahma.csv (every change, with its time) and test-files/ (the files it
uploaded, so an original's S3 name, the SHA-256 of its bytes, can be checked). No CSID of a test record is written in
this repository (D314): the tests name records by number.

Records 021-032 are used once (D311): `--renew` soft-deletes the copy in use and makes the next (021B, 021C...), which
the next ETL run lists. The copy in use is the newest one made."""
from __future__ import annotations

import csv
import hashlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from pathlib import Path

TENANT = "pahma"
PREFIX = "SERENA-TEST-"
CHANGED = range(21, 33)  # 021-032: each changed once after an ETL run
NUMBER = re.compile(r"^SERENA-TEST-(\d{3})(-IMG|[B-Z])?$")


@dataclass(frozen=True)
class Record:
    idn: str        # SERENA-TEST-021B
    number: int     # 21
    suffix: str     # "", "B"..., or "-IMG" (044's JPEG)
    media: str      # the Media CSID
    blob: str       # the Blob CSID it was made with
    fmt: str        # jpeg, png, tiff, ...
    file: Path      # the file uploaded, in out/test-files/
    made: str       # the stamp of the run that made it (test-media.pahma.<stamp>.csv)


@dataclass(frozen=True)
class Change:
    at: datetime    # UTC
    idn: str
    action: str     # replace, unapprove, remove_file, ... renew
    before: str
    after: str
    ok: bool


def script() -> Path:
    path = Path(os.environ.get("SERENADE_TEST_MEDIA_SCRIPT", ""))
    if not path.is_absolute() or not path.is_file():
        raise SystemExit("SERENADE_TEST_MEDIA_SCRIPT isn't make-test-media.py's absolute path (./serena aws test "
                         "--synthetic checks it).")
    return path


def out() -> Path:
    return script().parent / "out"


@cache
def made() -> dict[str, Record]:
    """Every record the script made, by identification number: the newest row of each (a rerun over records that
    exist writes their row again, with the same Media and Blob CSIDs)."""
    found: dict[str, Record] = {}
    for path in sorted(out().glob(f"test-media.{TENANT}.*.csv")):  # 2026-11-06.csv sorts before 2026-11-06T…
        stamp = path.name.removeprefix(f"test-media.{TENANT}.").removesuffix(".csv")
        with path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                idn = row["identification_number"]
                parsed = NUMBER.match(idn)
                if not parsed or not row["media_csid"] or not row["blob_csid"]:
                    continue
                found[idn] = Record(idn=idn, number=int(parsed.group(1)), suffix=parsed.group(2) or "",
                                    media=row["media_csid"], blob=row["blob_csid"], fmt=row["format"],
                                    file=out() / "test-files" / Path(row["file"]).name, made=stamp)
    if not found:
        raise SystemExit(f"No test-media.{TENANT}.*.csv with records in {out()}: has make-test-media.py made them?")
    return found


def changes() -> list[Change]:
    """Every change the script logged, oldest first (read afresh: the tests make changes)."""
    path = out() / f"changes.{TENANT}.csv"
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return [Change(at=datetime.fromisoformat(row["time_utc"]), idn=row["record"], action=row["action"],
                       before=row["before"], after=row["after"], ok=row["result"] == "done")
                for row in csv.DictReader(f)]


def record(number: int, suffix: str = "") -> Record:
    """A record never changed (001-020, 033-051), or 044's JPEG with suffix "-IMG"."""
    idn = f"{PREFIX}{number:03d}{suffix}"
    found = made().get(idn)
    if found is None:
        raise AssertionError(f"{idn} isn't in make-test-media.py's out/ CSVs")
    return found


def in_use(number: int) -> Record:
    """The copy of 021-032 in use: the newest one made (the original, or the latest --renew)."""
    copies = [r for r in made().values() if r.number == number and r.suffix != "-IMG"]
    if not copies:
        raise AssertionError(f"no copy of {PREFIX}{number:03d} in make-test-media.py's out/ CSVs")
    return max(copies, key=lambda r: (r.made, r.suffix))


def changes_of(rec: Record) -> list[Change]:
    """The changes made to this copy (a renew names the copy it made, which isn't a change to it)."""
    return [c for c in changes() if c.idn == rec.idn and c.action != "renew"]


def replaced_blob(rec: Record) -> str | None:
    """The Blob a --replace gave the record, if it was replaced."""
    found = [c.after for c in changes_of(rec) if c.action == "replace" and c.ok]
    return found[-1] if found else None


def v2_file(rec: Record) -> Path:
    """The file --replace uploaded (make_file(rec, version=2): <idn>-v2.<ext>)."""
    return rec.file.with_name(f"{rec.idn}-v2{rec.file.suffix}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_script(*options: str, typed: str = "", timeout: float = 3600, exits: tuple[int, ...] = (0,)) -> str:
    """Runs make-test-media.py with these options against PAHMA QA, as SERENADE_CSPACE_USER, and returns what it
    printed. The password goes in its environment (MAKE_TEST_MEDIA_PASSWORD), never in an argument, and isn't in
    anything this returns or raises. `typed` is what it reads from the keyboard (--purge asks for PURGE). Fails on an
    exit code not in `exits` (--check exits 1 when a record differs from the plan)."""
    env = {**os.environ, "MAKE_TEST_MEDIA_PASSWORD": os.environ["SERENADE_CSPACE_PASSWORD"]}
    done = subprocess.run([sys.executable, str(script()), "--base", os.environ["SERENADE_CSPACE_BASE"],  # noqa: S603
                           "--tenant", TENANT, "--user", os.environ["SERENADE_CSPACE_USER"], *options],
                          capture_output=True, text=True, timeout=timeout, env=env, input=typed, check=False)
    made.cache_clear()  # a renew adds a test-media CSV
    if done.returncode not in exits:
        raise AssertionError(f"make-test-media.py {' '.join(options)} ended with {done.returncode}:\n"
                             f"{done.stdout[-3000:]}\n{done.stderr[-2000:]}")
    return done.stdout


def warnings(printed: str) -> list[str]:
    """The lines where the script says CollectionSpace didn't keep a change."""
    return [line.strip() for line in printed.splitlines() if line.rstrip().endswith("WARNING") or "  WARNING (" in line]
