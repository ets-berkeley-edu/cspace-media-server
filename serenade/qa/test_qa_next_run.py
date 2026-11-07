"""Checklist section 63, after the next ETL run: steps 23 and 24 (T131, T132) on the copies of 021-032 that
test_qa_changes.py changed, then T133 renews them for the next cycle (make-test-media.py --renew: the copy in use and
its Object soft-deleted, a fresh copy made, which the following ETL run lists). They run only once Serena has applied
an ETL run that started after the changes; otherwise they skip, saying why. Step 24's "everything in steps 2-12
unchanged" is the look-only tests (test_qa_look.py), which run first in the same run. So a cycle is every other day
(decision 8): day 1 test_qa_changes.py, day 2 this file, day 3 test_qa_changes.py on the renewed copies."""
from __future__ import annotations

from datetime import datetime

import pytest

from serenade.qa.harness import Admin, Log, Serena
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

DROPPED = (21, 22, 23, 24, 25, 26, 27, 28, 30, 31, 32)  # 029 was only recalled, and the recall cancelled


@pytest.fixture(scope="module")
def changed(admin: Admin) -> dict[int, Record]:
    """The copies in use, if test_qa_changes.py changed them and an ETL run Serena applied started after."""
    found = {n: in_use(n) for n in CHANGED}
    done = [r for r in found.values() if changes_of(r)]
    if not done:
        pytest.skip("the copies in use aren't changed yet: test_qa_changes.py changes them (or they were just renewed)")
    if len(done) < len(CHANGED) - 1:  # 029 is never changed in CollectionSpace
        pytest.fail(f"only {len(done)} of the copies in use were changed: look at changes.pahma.csv")
    last_change = max(c.at for r in done for c in changes_of(r))
    refresh = admin.last_refresh()
    started = datetime.fromisoformat(refresh["started_at"]) if refresh else None
    if started is None or started <= last_change:
        pytest.skip(f"no ETL run applied since the changes ({last_change:%Y-%m-%d %H:%M} UTC): run after the next one")
    return found


@pytest.fixture(scope="module")
def phase(changed: dict[int, Record], serena: Serena, admin: Admin, log: Log) -> dict[int, Step]:
    def step23(step: Step) -> None:
        for n in DROPPED:
            rec = changed[n]
            if n == 27 and not any(c.action == "purge" and c.ok for c in changes_of(rec)):
                continue
            step.ask(serena, f"{n} Medium", serena.blob(rec.blob, "Medium"), rec.blob, "Medium")
        step.ask(serena, "24 Small", serena.blob(changed[24].blob, "Small"), changed[24].blob, "Small")

    def step24(step: Step) -> None:
        for n in (21, 22, 23):
            new = replaced_blob(changed[n])
            assert new, f"{changed[n].idn} has no new Blob in changes.pahma.csv"
            step.facts[f"{n} blob"] = new
            step.facts[f"{n} kind"] = admin.item(new)["kind"]
            step.ask(serena, f"{n} new Medium", serena.blob(new, "Medium"), new, "Medium")
            if n != 23:
                step.ask(serena, f"{n} new original", serena.blob(new), new, None)

    return send_all([(23, step23), (24, step24)], serena, log)


def test_t131_what_the_etl_dropped(phase: dict[int, Step], serena: Serena, log: Log) -> None:
    """Section 63 step 23: the old Blobs of 021, 022 and 023, 024's Medium and Small, and the Medium of 025, 026, 027,
    028, 030, 031 and 032: the unavailable image, not_listed (030, 031 and 032 because their Object no longer
    qualifies)."""
    step = phase[23].checked()
    for label, asked in step.asked.items():
        serena.unavailable(asked.sent)
        assert log.reason(asked.sent) == "not_listed", f"{label}: {log.reason(asked.sent)}"


def test_t132_what_the_etl_added(phase: dict[int, Step], changed: dict[int, Record], serena: Serena, admin: Admin,
                                 log: Log) -> None:
    """Section 63 step 24: the new Blobs of 021 and 022 are listed as images and served, the v2 file (the original's
    S3 name is the v2 file's SHA-256); 023's new Blob isn't listed (unapproved): not_listed. And step 14's last check:
    no "placeholder image isn't set" alert from this refresh (033 is named). That 023's Object brings the placeholder
    stays a look by hand (Media look up on the placeholder Blob)."""
    step = phase[24].checked()
    for n in (21, 22):
        assert step.facts[f"{n} kind"] == "image", f"{changed[n].idn}'s new Blob: {step.facts[f'{n} kind']}"
        serena.served(step[f"{n} new Medium"])
        s3 = serena.served(step[f"{n} new original"])
        assert s3 == sha256(v2_file(changed[n])), f"{changed[n].idn}'s new Blob isn't the v2 file"
    assert step.facts["23 kind"] is None, f"023's new Blob is listed as {step.facts['23 kind']}"
    serena.unavailable(step["23 new Medium"])
    assert log.reason(step["23 new Medium"]) == "not_listed", log.reason(step["23 new Medium"])
    refresh = admin.last_refresh()
    assert refresh
    raised = [a for a in admin.alerts() if a["kind"] == "placeholder_not_set"
              and a["refresh_date"] == refresh["refresh_date"]]
    assert not raised, f"the placeholder alert came back with refresh {refresh['refresh_id']}"


@pytest.mark.after("test_t131_what_the_etl_dropped", "test_t132_what_the_etl_added")
def test_t133_renew_for_the_next_cycle(changed: dict[int, Record]) -> None:
    """Renews 021-032 (D311): each copy in use and its Object soft-deleted, a fresh copy with the next letter made. Only
    after steps 23 and 24 passed, so a failure can still be looked at on the records as they are. The next ETL run
    lists the new copies; test_qa_changes.py uses them the day after."""
    printed = run_script("--renew", ",".join(str(n) for n in CHANGED))
    print(printed)
    failed = warnings(printed)
    assert not failed, f"CollectionSpace didn't keep {len(failed)} change(s): {failed}"
    stale = [n for n in CHANGED if in_use(n).idn == changed[n].idn]
    assert not stale, f"no new copy of {[changed[n].idn for n in stale]}"
