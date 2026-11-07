"""Checklist section 63, the two steps that change PAHMA's settings: step 1, the image size limit (T109, put back
however the test ends), and step 14, the placeholder image (T122, left on record 033 as the checklist leaves it; the
next run first puts it back to not set). They run after the look-only tests (FILE_ORDER).

A setting reaches every web task within settings_cache_seconds (60 s by default; the task that saved it at once), so
each test waits that out after a change before asking: a request answered by a task with the old limit would fetch and
store 008's original, and step 1 could never run again."""
from __future__ import annotations

import time
from typing import Any

import pytest

from serenade.qa import progress
from serenade.qa.conftest import Note
from serenade.qa.harness import PLACEHOLDER_BLOB, Admin, Log, Serena
from serenade.qa.records import record

SETTLE = 65  # seconds: settings_cache_seconds (60) and a little more
LIMIT = "size_limit_mb.image"
PLACEHOLDER = "placeholder_media_csid"


def audited(admin: Admin, target: str, reason: str) -> bool:
    """Whether the audit log has the settings change with this reason."""
    def matches(entry: dict[str, Any]) -> bool:
        return (entry.get("action") == "settings_change" and entry.get("target") == target
                and entry.get("details", {}).get("reason") == reason)
    return any(matches(e) for e in admin.audit())


def test_t109_over_the_size_limit(serena: Serena, admin: Admin, log: Log, note: Note) -> None:
    """Section 63 step 1: with PAHMA's image size limit at 100 MB, 008's original (about 130 MB) gets the unavailable
    image, too_large, while its Medium is served; the limit is put back, and the audit log has both changes. How long
    the refusal took is noted (PAHMA QA sends no Content-Length, so Serena reads up to the limit first)."""
    rec = record(8)
    if admin.stored(rec.blob).get("original"):
        pytest.fail("008's original is stored, so a request no longer fetches it: step 1 needs another large TIFF "
                    "never requested (make-test-media.py --renew 8, listed after the next ETL run)")
    stamp = time.strftime("%Y-%m-%d %H:%M")
    lower, back = f"serenade T109 {stamp}: section 63 step 1", f"serenade T109 {stamp}: put back"
    before = admin.setting(LIMIT)
    admin.change(LIMIT, 100, lower)
    try:
        progress.wait(SETTLE, "the setting reaching every web task")
        original = serena.send(serena.blob(rec.blob))
        medium = serena.send(serena.blob(rec.blob, "Medium"))
    finally:
        admin.put_back(LIMIT, before, back)
    note(f"step 1: 008's original was refused in {original.seconds:.1f} s")
    log.catch_up([original, medium])
    serena.unavailable(original)
    assert log.reason(original) == "too_large", log.reason(original)
    serena.served(medium)
    assert admin.setting(LIMIT)["value"] == before["value"], "the limit isn't back"
    assert audited(admin, LIMIT, lower) and audited(admin, LIMIT, back), "the audit log lacks a change"


def test_t122_the_placeholder_image(serena: Serena, admin: Admin, log: Log) -> None:
    """Section 63 step 14: with no Media record named, the placeholder image's Medium and Thumbnail get the generic
    placeholder picture, placeholder_not_set. Settings, Placeholder image: 033's Media record, with a reason; the save
    warns that 033's Blob isn't the configured placeholder Blob, and the audit log has it. Both again: served, 033's
    picture (the same S3 name as 033's own Medium). Left on 033, as the checklist does (step 25 puts it back); a run
    that finds it on 033 sets it back to not set first. Whether the alert stays away is checked after the next ETL
    run (T132)."""
    ours = record(33)
    before = admin.setting(PLACEHOLDER)
    if before["value"] and before["value"] != ours.media:
        pytest.fail("PAHMA's placeholder image names a Media record that isn't SERENA-TEST-033: not this test's to "
                    "change")
    stamp = time.strftime("%Y-%m-%d %H:%M")
    if before["value"]:
        admin.use_default(PLACEHOLDER, f"serenade T122 {stamp}: not set again, for section 63 step 14")
        progress.wait(SETTLE, "the setting reaching every web task")
    not_set = [serena.send(serena.blob(PLACEHOLDER_BLOB, size)) for size in ("Medium", "Thumbnail")]
    reason = f"serenade T122 {stamp}: section 63 step 14, SERENA-TEST-033"
    answer = admin.change(PLACEHOLDER, ours.media, reason)
    assert "isn't the one the ETL lists" in str(answer.get("warning", "")), f"no warning: {answer.get('warning')}"
    progress.wait(SETTLE, "the setting reaching every web task")
    now_set = [serena.send(serena.blob(PLACEHOLDER_BLOB, size)) for size in ("Medium", "Thumbnail")]
    own = serena.send(serena.blob(ours.blob, "Medium"))
    log.catch_up([*not_set, *now_set, own])
    for sent in not_set:
        serena.generic_placeholder(sent)
        assert log.reason(sent) == "placeholder_not_set", f"{sent.path}: {log.reason(sent)}"
    names = [serena.served(sent) for sent in now_set]
    assert names[0] == serena.served(own), "the placeholder's Medium isn't 033's picture"
    assert audited(admin, PLACEHOLDER, reason), "the audit log lacks the change"
