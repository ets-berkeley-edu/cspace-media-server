"""Checklist section 63, records changed after an ETL run: steps 15 to 22 (T123 to T130), on the copies of 021-032 in
use (the originals, or the latest --renew's: records.in_use). Each copy can be changed only once (D311), so these run
only while every copy in use is listed and unchanged: on the day after the copies were made or renewed, before that
evening's ETL run (21:01). Otherwise they skip, saying why; test_qa_next_run.py checks the changes the morning after
and renews the copies.

T124 changes PAHMA QA through make-test-media.py, as the account ./serena aws test --synthetic asked the password of:
021-023 replaced, 023-024 unapproved, 025-026 soft-deleted, 027 deleted for good (the test types the script's PURGE;
D312: if the account may not, 027 is skipped), 028's file removed, 030's Object and 031's relations soft-deleted, 032's
Object "culturally affiliated". None of it can be undone; the next run uses renewed copies."""
from __future__ import annotations

import time

import pytest

from serenade.qa.conftest import Note
from serenade.qa.harness import Admin, Log, Sent, Serena
from serenade.qa.records import (
    CHANGED,
    Record,
    changes_of,
    in_use,
    replaced_blob,
    run_script,
    sha256,
    v2_file,
    warnings,
)
from serenade.qa.steps import Step, send_all

CACHED = (22, 24, 26, 29)          # step 15 caches their Medium
UNTOUCHED = (21, 23, 25, 27, 28, 30, 31, 32)  # never requested before the change
before_change: dict[int, str] = {}  # step 15's S3 names, by record number


def tail(rec: Record) -> str:
    return f"{rec.number:03d}{rec.suffix}"


@pytest.fixture(scope="module")
def copies(admin: Admin) -> dict[int, Record]:
    """The copies in use, if they're ready for this phase: listed (an ETL run since they were made) and unchanged."""
    found = {n: in_use(n) for n in CHANGED}
    changed = [r.idn for r in found.values() if changes_of(r)]
    if changed:
        pytest.skip(f"{len(changed)} of the copies in use are already changed ({changed[0]}...): after the next ETL "
                    "run, test_qa_next_run.py checks them and renews them")
    unlisted = [r.idn for r in found.values() if admin.item(r.blob)["kind"] != "image"]
    if unlisted:
        pytest.skip(f"{len(unlisted)} of the copies in use aren't listed as images yet ({unlisted[0]}...): they're "
                    "listed after the ETL run that follows their making")
    return found


def test_t123_before_the_changes(copies: dict[int, Record], serena: Serena, admin: Admin, log: Log) -> None:
    """Section 63 step 15: each of 021-032 is listed as an image (the fixture); the Medium of 022, 024, 026 and 029 is
    cached (served, a miss); the other eight have nothing stored yet."""
    stored = [copies[n].idn for n in UNTOUCHED if any(admin.stored(copies[n].blob).values())]
    assert not stored, f"already requested, so their first request after the change wouldn't miss: {stored}"
    sent = {n: serena.send(serena.blob(copies[n].blob, "Medium")) for n in CACHED}
    log.catch_up(sent.values())
    for n, one in sent.items():
        before_change[n] = serena.served(one)
        assert log.cache(one) == "miss", f"{copies[n].idn}: {log.cache(one)}"


@pytest.mark.after("test_t123_before_the_changes")
def test_t124_the_changes(copies: dict[int, Record], note: Note) -> None:
    """Section 63 step 16: every change in one run of make-test-media.py (it orders them itself, and reads each one
    back: a WARNING is a change CollectionSpace didn't keep). If only 027's purge failed (the account may not delete
    for good), 027 is skipped (D312)."""
    t = {n: tail(r) for n, r in copies.items()}
    printed = run_script("--replace", f"{t[21]},{t[22]},{t[23]}", "--unapprove", f"{t[23]},{t[24]}",
                         "--soft-delete", f"{t[25]},{t[26]}", "--purge", t[27], "--remove-file", t[28],
                         "--delete-object", t[30], "--delete-relation", t[31],
                         "--add-status", "culturally affiliated", "--to", t[32], typed="PURGE\n")
    print(printed)
    failed = warnings(printed)
    if failed and all(copies[27].idn in line for line in failed):
        note(f"step 16: {copies[27].idn} wasn't deleted for good (the account may not): step 19 skips it")
        failed = []
    assert not failed, f"CollectionSpace didn't keep {len(failed)} change(s): {failed}"
    for n in (21, 22, 23):
        assert replaced_blob(copies[n]), f"{copies[n].idn} has no new Blob in changes.pahma.csv"


def purged(rec: Record) -> bool:
    return any(c.action == "purge" and c.ok for c in changes_of(rec))


@pytest.fixture(scope="module")
def phase(copies: dict[int, Record], serena: Serena, log: Log) -> dict[int, Step]:
    def medium(step: Step, n: int, label: str = "") -> Sent:
        rec = copies[n]
        return step.ask(serena, label or f"{n} Medium", serena.blob(rec.blob, "Medium"), rec.blob, "Medium")

    def step17(step: Step) -> None:
        for n in (21, 22, 23):
            medium(step, n)
        for n in (21, 23):  # the original too: its S3 name says which file the fetch got
            rec = copies[n]
            step.ask(serena, f"{n} original", serena.blob(rec.blob), rec.blob, None)

    def step18(step: Step) -> None:
        medium(step, 24)
        step.ask(serena, "24 Small", serena.blob(copies[24].blob, "Small"), copies[24].blob, "Small")

    def step19(step: Step) -> None:
        medium(step, 25, "25 Medium 1")
        medium(step, 25, "25 Medium 2")
        medium(step, 26)
        if purged(copies[27]):
            medium(step, 27)

    def step20(step: Step) -> None:
        medium(step, 28)

    def step21(step: Step) -> None:
        for n in (30, 31, 32):
            medium(step, n)

    return send_all([(17, step17), (18, step18), (19, step19), (20, step20), (21, step21)], serena, log)


@pytest.mark.after("test_t124_the_changes")
def test_t125_replaced_images(phase: dict[int, Step], copies: dict[int, Record], serena: Serena, log: Log) -> None:
    """Section 63 step 17, the old Blob's Medium: 021 (not cached) served, fetched through its Media record, which now
    gives the v2 file (the original's S3 name is the SHA-256 of the v2 file the script uploaded); 022 (cached) served
    from the cache, the v1 file; 023 (not cached, now unapproved) served, v2: the accepted window until the next ETL
    list. That nothing is asked by the old Blob CSID can't be read from the log: the checklist's look stays by hand."""
    step = phase[17].checked()
    for n in (21, 23):
        serena.served(step[f"{n} Medium"])
        assert log.cache(step[f"{n} Medium"]) == "miss", f"{copies[n].idn}: not fetched"
        assert serena.served(step[f"{n} original"]) == sha256(v2_file(copies[n])), f"{copies[n].idn}: not the v2 file"
    assert serena.served(step["22 Medium"]) == before_change[22], "022: not the file cached before the change"
    assert log.cache(step["22 Medium"]) == "hit"


@pytest.mark.after("test_t124_the_changes")
def test_t126_unapproved_after_the_run(phase: dict[int, Step], serena: Serena, log: Log) -> None:
    """Section 63 step 18: 024's Medium (cached) and Small (not): both served; the light check doesn't read approval."""
    step = phase[18].checked()
    assert serena.served(step["24 Medium"]) == before_change[24]
    assert log.cache(step["24 Medium"]) == "hit"
    serena.served(step["24 Small"])
    assert log.cache(step["24 Small"]) == "miss"


@pytest.mark.after("test_t124_the_changes")
def test_t127_deleted(phase: dict[int, Step], copies: dict[int, Record], serena: Serena, log: Log) -> None:
    """Section 63 step 19: 025's Medium (soft-deleted, not cached): the unavailable image, media_deleted, nothing
    stored; again: the same. 026's Medium (cached): served from the cache. 027's (deleted for good): media_gone."""
    step = phase[19].checked()
    for label in ("25 Medium 1", "25 Medium 2"):
        serena.unavailable(step[label])
        assert log.reason(step[label]) == "media_deleted", f"{label}: {log.reason(step[label])}"
    assert not [f for f in log.fetches(copies[25].blob, "Medium") if f.get("message") == "fetched"]
    assert serena.served(step["26 Medium"]) == before_change[26]
    assert log.cache(step["26 Medium"]) == "hit"
    if "27 Medium" not in step.asked:
        pytest.skip(f"{copies[27].idn} wasn't deleted for good (D312)")
    serena.unavailable(step["27 Medium"])
    assert log.reason(step["27 Medium"]) == "media_gone", log.reason(step["27 Medium"])


@pytest.mark.after("test_t124_the_changes")
def test_t128_no_file(phase: dict[int, Step], serena: Serena, log: Log, note: Note) -> None:
    """Section 63 step 20: 028's Medium (its file removed, the record kept): the unavailable image, not an error page;
    no_file if CollectionSpace answers 404. The reason is noted until the first run shows it."""
    step = phase[20].checked()
    serena.unavailable(step["28 Medium"])
    reason = log.reason(step["28 Medium"])
    note(f"step 20: 028's Medium: {reason}")


@pytest.mark.after("test_t124_the_changes")
def test_t129_only_the_media_record_is_checked(phase: dict[int, Step], serena: Serena) -> None:
    """Section 63 step 21: 030 (its Object soft-deleted), 031 (its relations soft-deleted) and 032 ("culturally
    affiliated"): each Medium served."""
    step = phase[21].checked()
    for n in (30, 31, 32):
        serena.served(step[f"{n} Medium"])


@pytest.mark.after("test_t123_before_the_changes")
def test_t130_a_recall(copies: dict[int, Record], serena: Serena, admin: Admin, log: Log) -> None:
    """Section 63 step 22: 029's Media record recalled, with a reason: its Medium (cached) and Small (not) get the
    unavailable image, recalled, nothing fetched. The recall is cancelled, with a reason, however the test ends; then
    Medium is served from the cache and Small fetched."""
    rec = copies[29]
    stamp = time.strftime("%Y-%m-%d %H:%M")
    reason = f"serenade T130 {stamp}: section 63 step 22"
    admin.recall(rec.media, reason)
    try:
        recalled = [serena.send(serena.blob(rec.blob, size)) for size in ("Medium", "Small")]
    finally:
        if any(r["media_csid"] == rec.media for r in admin.active_recalls()):
            admin.cancel(rec.media, f"serenade T130 {stamp}: cancelled")
    again = [serena.send(serena.blob(rec.blob, size)) for size in ("Medium", "Small")]
    log.catch_up([*recalled, *again])
    for sent in recalled:
        serena.unavailable(sent)
        assert log.reason(sent) == "recalled", f"{sent.path}: {log.reason(sent)}"
    assert serena.served(again[0]) == before_change[29]
    assert log.cache(again[0]) == "hit"
    serena.served(again[1])
    assert log.cache(again[1]) == "miss", "029's Small: fetched while recalled?"
