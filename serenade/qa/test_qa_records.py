"""The synthetic records' state, before a run of checklist section 63: ./serena aws test --synthetic --check-records
runs this file alone, and none of the tests (serenade/qa/conftest.py). It only reads: Media look up for each record (no
image is requested, so nothing is cached) and make-test-media.py --check, which reads PAHMA QA's records against the
plan (decisions/serena-synthetic-records-decisions.md, Records). The report is printed at the end ("dataset"); the
test fails if anything would make a section 63 test fail or skip for a reason that isn't Serena's.

What Serena should list for each record is the plan's "ETL list row" column. Where the plan says the stored type is
"to confirm" (JPEG 2000, X3D, WAV, MP4), a different listing is reported but isn't a problem. 021-032 are their copies
in use, with what's expected depending on where the cycle is (decision 8): made but not yet listed, listed and
unchanged, changed but not yet seen by an ETL run, or changed and seen."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from serenade.qa.harness import Admin
from serenade.qa.records import (
    CHANGED,
    PREFIX,
    Record,
    changes_of,
    in_use,
    made,
    record,
    replaced_blob,
    run_script,
)

IMAGE = (1, 2, 3, 4, 6, 7, 8, 9, 10, 20, 33)
CARD = (34, 36, 38, 40, 51)
NOT_LISTED = (5, 11, 12, 13, 14, 15, 16, 17, 18, 19, 35, 37, 39, 43, 47, 48, 49, 50)
LISTED: dict[tuple[int, str], str | None] = {
    **{(n, ""): "image" for n in IMAGE}, **{(n, ""): "card" for n in CARD}, **{(n, ""): None for n in NOT_LISTED},
    (42, ""): "3D", (44, ""): "3D", (44, "-IMG"): None, (45, ""): "audio", (46, ""): "video", (41, ""): "image",
}
TO_CONFIRM = {39, 40, 42, 44, 45, 46}  # the plan's "(to confirm)" stored types decide whether the ETL lists them
UNTOUCHED = (21, 23, 25, 27, 28, 30, 31, 32)  # step 15 needs them never requested
AFTER_CHANGE: dict[int, str | None] = {n: None for n in CHANGED} | {29: "image"}  # the old Blobs, after the next run


def made_at(rec: Record) -> datetime:
    """When the run that made the record ran (its CSV's stamp, this computer's time)."""
    for shape in ("%Y-%m-%dT%H%M%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(rec.made, shape).astimezone()
        except ValueError:
            continue
    raise AssertionError(f"{rec.idn}: no time in its CSV's name ({rec.made})")


def shown(item: dict[str, Any]) -> str:
    kind = item.get("kind")
    stored = [s["size"] for s in item.get("sizes", []) if s.get("stored") is not None]
    return (f"{kind} {item.get('access')}" if kind else "not listed") + (f"; stored: {', '.join(stored)}"
                                                                          if stored else "")


def test_records_as_planned(admin: Admin, report: list[str]) -> None:
    """Serena's view of every record, then CollectionSpace's (make-test-media.py --check), in one report."""
    problems: list[str] = []

    def line(idn: str, ok: bool | None, text: str) -> None:
        report.append(f"  {idn:<20} {'OK  ' if ok else 'NOTE' if ok is None else 'PROBLEM'}  {text}")
        if ok is False:
            problems.append(f"{idn}: {text}")

    def look(blob: str) -> dict[str, Any] | None:
        try:
            return admin.item(blob)
        except AssertionError:
            return None

    refresh = admin.last_refresh()
    started = datetime.fromisoformat(refresh["started_at"]) if refresh else None
    report.append("Serena (Media look up on ucb-stage2's PAHMA):")
    report.append(f"  last ETL run applied: {refresh['refresh_date'] if refresh else 'none'}"
                  + (f", started {started:%Y-%m-%d %H:%M %Z}" if started else ""))

    for (n, suffix), want in sorted(LISTED.items(), key=lambda kv: kv[0]):
        idn = f"{PREFIX}{n:03d}{suffix}"
        try:
            rec = record(n, suffix)
        except AssertionError:
            line(idn, False, "not in make-test-media.py's out/ CSVs")
            continue
        item = look(rec.blob)
        if item is None:
            line(idn, False, "Media look up found nothing for its Blob")
            continue
        kind = item.get("kind")
        ok: bool | None = kind == want and (kind is None or item.get("access") == "public")
        if not ok and n in TO_CONFIRM:
            ok = None
        text = shown(item) + ("" if ok else f" (planned: {f'{want} public' if want else 'not listed'})")
        if n == 8 and any(s["size"] == "original" and s.get("stored") is not None for s in item.get("sizes", [])):
            ok, text = False, text + ": its original is stored, so step 1 can't refuse it (it needs an uncached TIFF)"
        line(idn, ok, text)

    for n in CHANGED:
        try:
            rec = in_use(n)
        except AssertionError:
            line(f"{PREFIX}{n:03d}", False, "no copy in make-test-media.py's out/ CSVs")
            continue
        item = look(rec.blob)
        if item is None:
            line(rec.idn, False, "Media look up found nothing for its Blob")
            continue
        kind, done = item.get("kind"), [c for c in changes_of(rec) if c.ok]
        if not done:
            if started is None or started <= made_at(rec):
                line(rec.idn, None if kind is None else False,
                     shown(item) + ": made after the last ETL run, so listed after the next one"
                     + ("" if kind is None else " (yet it's listed?)"))
                continue
            stored = n in UNTOUCHED and item.get("sizes") and any(s.get("stored") is not None for s in item["sizes"])
            ok = kind == "image" and not stored
            line(rec.idn, ok, shown(item) + ": unchanged" + ("" if kind == "image" else " (planned: image public)")
                 + (": already requested, so step 15 can't expect its first request to miss" if stored else ""))
            continue
        last = max(c.at for c in done)
        seen = started is not None and started > last
        want = AFTER_CHANGE[n] if seen else "image"
        when = "seen by the last ETL run" if seen else "not yet seen by an ETL run"
        line(rec.idn, kind == want, f"{shown(item)}: changed ({', '.join(c.action for c in done)}), {when}"
             + ("" if kind == want else f" (planned: {want or 'not listed'})"))
        new = replaced_blob(rec)
        if seen and new and n in (21, 22, 23):
            new_item = look(new)
            want_new = None if n == 23 else "image"
            got = new_item.get("kind") if new_item else None
            line(f"{rec.idn} (new Blob)", got == want_new,
                 (shown(new_item) if new_item else "Media look up found nothing")
                 + ("" if got == want_new else f" (planned: {want_new or 'not listed'})"))

    placeholder = admin.setting("placeholder_media_csid").get("value")
    ours = made().get(f"{PREFIX}033")
    if not placeholder:
        line("placeholder image", True, "not set (step 14 sets it to 033)")
    elif ours and placeholder == ours.media:
        line("placeholder image", True, "033 (step 14 resets it, then sets it again)")
    else:
        line("placeholder image", False, "names a Media record that isn't 033: step 14 won't touch it")

    printed = run_script("--check", exits=(0, 1))
    report.append("CollectionSpace (make-test-media.py --check on PAHMA QA):")
    report.extend(f"  {text}" for text in printed.rstrip().splitlines())
    cspace = [text.strip() for text in printed.splitlines() if " PROBLEM " in text]
    problems.extend(f"CollectionSpace: {text}" for text in cspace)

    assert not problems, f"{len(problems)} problem(s) with the dataset (the report follows the run)"
