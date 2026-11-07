"""Checklist section 63, records never changed: steps 2 to 13 (T110 to T121), which only look. They hold on every run:
where the checklist expects a first request to miss Serena's cache, the test reads Media look up first and expects a
miss only for a size Serena hasn't stored yet (Serena keeps a Blob's files for good, so a second run gets hits).

Every request is sent first, in the checklist's order (4 to 11 and 13, then 2 and 3, then 12), and the web log is read
once for all of them. Step 1 (the size limit) and step 14 (the placeholder) change settings: test_qa_settings.py.
008's original is never requested here, so step 1 always finds it uncached."""
from __future__ import annotations

import threading
import urllib.parse

import pytest

from serenade.aws.target import aws_cli, serena_aws
from serenade.qa.conftest import Note
from serenade.qa.harness import Admin, Log, Sent, Serena, web_count
from serenade.qa.records import made, record, sha256
from serenade.qa.steps import Asked, Step, send_all

SIZES = ["Thumbnail", "Small", "Medium", "FullHD", "OriginalJpeg"]
NOT_LISTED_MEDIUM = [5, 11, 12, 13, 14, 15, 16, 17, 35, 37, 39, 48, 49, 50]
NOT_LISTED_ORIGINAL = [18, 19, 43, 47]
# Step 12: sizes step 2 never asks for, tried in this order until one isn't stored (one per run).
CONCURRENT = [(n, s) for n in (6, 2, 10, 20) for s in ("FullHD", "Small", "Thumbnail", "OriginalJpeg")]
TOGETHER = 6


def flipped(csid: str) -> str:
    """A CSID that differs in its last character: one no record has."""
    return csid[:-1] + ("0" if csid[-1] != "0" else "1")


@pytest.fixture(scope="module")
def phase(serena: Serena, admin: Admin, log: Log) -> dict[int, Step]:
    def twice(step: Step, n: int, size: str | None) -> None:
        rec = record(n)
        name = size or "original"
        step.facts[f"{n} {name} stored"] = admin.stored(rec.blob).get(name, False)
        for k in (1, 2):
            step.ask(serena, f"{n} {name} {k}", serena.blob(rec.blob, size), rec.blob, size)

    def step4(step: Step) -> None:
        for n in NOT_LISTED_MEDIUM:
            rec = record(n)
            step.ask(serena, f"{n} Medium", serena.blob(rec.blob, "Medium"), rec.blob, "Medium")
        img = record(44, "-IMG")
        step.ask(serena, "044-IMG Medium", serena.blob(img.blob, "Medium"), img.blob, "Medium")
        for n in NOT_LISTED_ORIGINAL:
            rec = record(n)
            step.ask(serena, f"{n} original", serena.blob(rec.blob), rec.blob, None)

    def step5(step: Step) -> None:
        for n in (34, 36):
            rec = record(n)
            step.ask(serena, f"{n} Medium", serena.blob(rec.blob, "Medium"), rec.blob, "Medium")
            step.ask(serena, f"{n} original", serena.blob(rec.blob), rec.blob, None)
        rec = record(51)
        step.ask(serena, "51 Medium", serena.blob(rec.blob, "Medium"), rec.blob, "Medium")
        step.facts["51 kind"] = admin.item(rec.blob)["kind"]

    def step6(step: Step) -> None:
        for n in (38, 40):
            rec = record(n)
            step.ask(serena, f"{n} original", serena.blob(rec.blob), rec.blob, None)
            step.ask(serena, f"{n} Medium", serena.blob(rec.blob, "Medium"), rec.blob, "Medium")

    def step7(step: Step) -> None:
        rec = record(41)
        step.ask(serena, "41 original", serena.blob(rec.blob), rec.blob, None)
        step.ask(serena, "41 Medium", serena.blob(rec.blob, "Medium"), rec.blob, "Medium")

    def step8(step: Step) -> None:
        x3d, both = record(42), record(44)
        step.facts["42 kind"] = admin.item(x3d.blob)["kind"]
        step.facts["44 kind"] = admin.item(both.blob)["kind"]
        step.ask(serena, "42 original", serena.blob(x3d.blob), x3d.blob, None)
        if step.facts["42 kind"] == "3D":
            step.ask(serena, "42 Medium", serena.blob(x3d.blob, "Medium"), x3d.blob, "Medium")
            step.ask(serena, "44 original", serena.blob(both.blob), both.blob, None)

    def step9(step: Step) -> None:
        for n in (45, 46):
            rec = record(n)
            step.facts[f"{n} kind"] = admin.item(rec.blob)["kind"]
            step.ask(serena, f"{n} original", serena.blob(rec.blob), rec.blob, None)

    def step10(step: Step) -> None:
        rec = record(1)
        step.ask(serena, "001 Medium", serena.blob(rec.blob, "Medium"), rec.blob, "Medium")
        step.ask(serena, "001 media Medium", serena.media(rec.media, "Medium"), rec.blob, "Medium")
        step.ask(serena, "made-up media Medium", serena.media(flipped(rec.media), "Medium"))

    def step11(step: Step) -> None:
        rec = record(1)
        base = f"{serena.target.url}/{serena.target.museum}/imageserver"
        step.ask(serena, "Large", serena.blob(rec.blob, "Large"))
        step.ask(serena, "medium", serena.blob(rec.blob, "medium"))
        step.ask(serena, "underscore", serena.blob(rec.blob[:-2] + "_" + rec.blob[-1], "Medium"))
        step.ask(serena, "extra", serena.blob(rec.blob, "Medium") + "/extra")
        step.ask(serena, "media content", f"{base}/media/{rec.media}/content")
        step.ask(serena, "unknown museum", f"{serena.target.url}/nomuseum/imageserver/blobs/{rec.blob}/derivatives/"
                                           "Medium/content")
        step.ask(serena, "query string", serena.blob(rec.blob, "Medium") + "?serenade=1", rec.blob, "Medium")

    def step13(step: Step) -> None:
        ours = {r.blob for r in made().values()}
        for line in serena_aws("list", "pahma", "--kind", "image", "--limit", "40").splitlines():
            words = line.split()
            if len(words) < 4 or words[0] != "image" or words[1] != "public":
                continue
            blob = urllib.parse.urlsplit(words[-1]).path.split("/blobs/", 1)[-1].split("/", 1)[0]
            if blob in ours or admin.stored(blob).get("Medium"):
                continue
            step.facts["blob"] = blob
            for k in (1, 2):
                step.ask(serena, f"Medium {k}", serena.blob(blob, "Medium"), blob, "Medium")
            return
        raise AssertionError("./serena aws list shows no public image that isn't a SERENA-TEST record and isn't cached")

    def step2(step: Step) -> None:
        for size in [*SIZES, None]:
            twice(step, 1, size)
        for n in (2, 6, 10, 20):
            twice(step, n, "Medium")
            twice(step, n, None)

    def step3(step: Step) -> None:
        for n in (3, 7, 4):
            twice(step, n, "Medium")
            twice(step, n, None)
        twice(step, 9, None)  # 008's original is step 1's (test_qa_settings.py)

    def step12(step: Step) -> None:
        for n, size in CONCURRENT:
            rec = record(n)
            if not admin.stored(rec.blob).get(size):
                break
        else:
            raise AssertionError("every size step 12 may use is stored: renew 006 (make-test-media.py --renew 6)")
        step.facts["which"] = f"{n:03d} {size}"
        step.facts["blob"], step.facts["size"] = rec.blob, size
        url = serena.blob(rec.blob, size)
        start = threading.Barrier(TOGETHER)
        answers: list[Sent] = []
        lock = threading.Lock()

        def one() -> None:
            start.wait()
            sent = serena.send(url)
            with lock:
                answers.append(sent)

        threads = [threading.Thread(target=one) for _ in range(TOGETHER)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=360)
        for k, sent in enumerate(answers):
            step.asked[f"together {k}"] = Asked(sent, rec.blob, size)

    return send_all([(4, step4), (5, step5), (6, step6), (7, step7), (8, step8), (9, step9), (10, step10),
                     (11, step11), (13, step13), (2, step2), (3, step3), (12, step12)], serena, log)


def served_twice(step: Step, serena: Serena, log: Log, n: int, size: str | None) -> str:
    """The first request served (a miss only if the size wasn't stored before), the second a hit on the same file."""
    name = size or "original"
    first, second = step[f"{n} {name} 1"], step[f"{n} {name} 2"]
    s3 = serena.served(first)
    expected = "hit" if step.facts[f"{n} {name} stored"] else "miss"
    assert log.cache(first) == expected, f"{n:03d} {name}: {log.cache(first)}, expected {expected}"
    if expected == "miss":
        assert log.fetches(record(n).blob, size), f"{n:03d} {name}: a miss with no fetch logged"
    assert serena.served(second) == s3, f"{n:03d} {name}: the second request names another file"
    assert log.cache(second) == "hit", f"{n:03d} {name}: the second request wasn't a hit"
    if size is None:
        assert s3 == sha256(record(n).file), f"{n:03d}'s original isn't the file make-test-media.py uploaded"
    return s3


# ---- the tests, in the checklist's order of steps ---------------------------------------------------------------

def test_t110_every_size_twice(phase: dict[int, Step], serena: Serena, log: Log) -> None:
    """Section 63 step 2: every size of 001, and Medium and the original of 002, 006, 010 and 020, twice: served, a
    miss (if not stored yet) then a hit on the same S3 name; each original's S3 name is its file's SHA-256."""
    step = phase[2].checked()
    for size in [*SIZES, None]:
        served_twice(step, serena, log, 1, size)
    for n in (2, 6, 10, 20):
        served_twice(step, serena, log, n, "Medium")
        served_twice(step, serena, log, n, None)


def test_t111_png_and_tiff(phase: dict[int, Step], serena: Serena, log: Log) -> None:
    """Section 63 step 3: Medium and the original of 003, 007 (PNG) and 004 (TIFF), and 009's original (192 MB):
    served, the originals' S3 names their files' SHA-256. 008's original twice is step 1's (T109)."""
    step = phase[3].checked()
    for n in (3, 7, 4):
        served_twice(step, serena, log, n, "Medium")
        served_twice(step, serena, log, n, None)
    served_twice(step, serena, log, 9, None)


def test_t112_not_listed(phase: dict[int, Step], serena: Serena, log: Log) -> None:
    """Section 63 step 4: records the ETL doesn't list (GIFs, unapproved, approvedForWeb empty, PDFs, JPEG 2000, no
    Object, an Object only "missing", a relation only from the Object, 044's unapproved JPEG): the unavailable image,
    not_listed, and no fetch from CollectionSpace."""
    step = phase[4].checked()
    for label, asked in step.asked.items():
        serena.unavailable(asked.sent)
        assert log.reason(asked.sent) == "not_listed", f"{label}: {log.reason(asked.sent)}"
        assert asked.blob and not log.fetches(asked.blob, asked.size), f"{label}: fetched from CollectionSpace"


def test_t113_cards(phase: dict[int, Step], serena: Serena, log: Log) -> None:
    """Section 63 step 5: Medium and the original of the catalog cards 034 and 036 served; 051's Medium served, and
    Media look up says kind card (the ETL's "Index" rule)."""
    step = phase[5].checked()
    for label in ("34 Medium", "34 original", "36 Medium", "36 original", "51 Medium"):
        serena.served(step[label])
        assert log.reason(step[label]) == "served", label
    assert step.facts["51 kind"] == "card", f"051 is listed as {step.facts['51 kind']}, not card"


def test_t114_cards_that_arent_images(phase: dict[int, Step], serena: Serena, log: Log) -> None:
    """Section 63 step 6: the originals of 038 (a PDF) and 040 (a JPEG 2000), listed as cards: wrong_content_type.
    Their Medium: served, a JPEG CollectionSpace made from each (pinned November 7, 2026, after the first run)."""
    step = phase[6].checked()
    for n in (38, 40):
        sent = step[f"{n} original"]
        serena.unavailable(sent)
        assert log.reason(sent) == "wrong_content_type", f"{n:03d} original: {log.reason(sent)}"
    for n in (38, 40):
        serena.served(step[f"{n} Medium"])
        assert log.reason(step[f"{n} Medium"]) == "served", f"{n:03d} Medium: {log.reason(step[f'{n} Medium'])}"


def test_t115_an_image_that_doesnt_decode(phase: dict[int, Step], serena: Serena, log: Log) -> None:
    """Section 63 step 7: 041's original (a JPEG cut in half): not_decodable. Its Medium: served, CollectionSpace made
    one from the half it could read (pinned November 7, 2026, after the first run)."""
    step = phase[7].checked()
    serena.unavailable(step["41 original"])
    assert log.reason(step["41 original"]) == "not_decodable", log.reason(step["41 original"])
    serena.served(step["41 Medium"])
    assert log.reason(step["41 Medium"]) == "served", f"041 Medium: {log.reason(step['41 Medium'])}"


def test_t116_3d(phase: dict[int, Step], serena: Serena, log: Log, note: Note) -> None:
    """Section 63 step 8: 042 (X3D) listed as 3D: its original served, its Medium no_derivatives_for_kind; 044's X3D
    original served (its Object's unapproved JPEG brings no placeholder). If CollectionSpace stored 042 as another
    type, the ETL doesn't list it: noted, not_listed, and the rest skipped."""
    step = phase[8].checked()
    if step.facts["42 kind"] != "3D":
        note(f"step 8: 042 is listed as {step.facts['42 kind']}, not 3D")
        serena.unavailable(step["42 original"])
        assert log.reason(step["42 original"]) == "not_listed", log.reason(step["42 original"])
        pytest.skip(f"042 is listed as {step.facts['42 kind']}, not 3D: the rest of step 8 doesn't apply")
    serena.served(step["42 original"])
    serena.unavailable(step["42 Medium"])
    assert log.reason(step["42 Medium"]) == "no_derivatives_for_kind", log.reason(step["42 Medium"])
    assert step.facts["44 kind"] == "3D", f"044 is listed as {step.facts['44 kind']}"
    serena.served(step["44 original"])


def test_t117_audio_and_video(phase: dict[int, Step], serena: Serena, log: Log, note: Note) -> None:
    """Section 63 step 9: the originals of 045 (WAV) and 046 (MP4): kind_not_served, no fetch. One the ETL doesn't
    list (CollectionSpace stored another type) is noted, and gets not_listed."""
    step = phase[9].checked()
    for n, kind in ((45, "audio"), (46, "video")):
        sent = step[f"{n} original"]
        serena.unavailable(sent)
        listed = step.facts[f"{n} kind"]
        if listed != kind:
            note(f"step 9: {n:03d} is listed as {listed}, not {kind}")
        expected = "kind_not_served" if listed else "not_listed"
        assert log.reason(sent) == expected, f"{n:03d}: {log.reason(sent)}, expected {expected}"
        assert not log.fetches(record(n).blob, None), f"{n:03d}: fetched from CollectionSpace"


def test_t118_media_urls(phase: dict[int, Step], serena: Serena, log: Log) -> None:
    """Section 63 step 10: 001's Medium by its Media CSID: served from 001's Blob's stored copy (the same S3 name),
    logged with the /media/ path; a made-up Media CSID: not_listed."""
    step = phase[10].checked()
    by_blob = serena.served(step["001 Medium"])
    assert serena.served(step["001 media Medium"]) == by_blob, "the Media URL names another file than the Blob's"
    assert "/media/" in log.line(step["001 media Medium"])["path"]
    serena.unavailable(step["made-up media Medium"])
    assert log.reason(step["made-up media Medium"]) == "not_listed", log.reason(step["made-up media Medium"])


def test_t119_urls_serena_doesnt_accept(phase: dict[int, Step], serena: Serena, log: Log) -> None:
    """Section 63 step 11: derivative Large and medium: derivative_not_served; a CSID with _: bad_csid; a path with
    more after content, and a Media URL's original without /blob/: unknown_path; an unknown museum: the default
    unavailable image, unknown_museum; a query string: served, and not logged."""
    step = phase[11].checked()
    for label, reason in (("Large", "derivative_not_served"), ("medium", "derivative_not_served"),
                          ("underscore", "bad_csid"), ("extra", "unknown_path"), ("media content", "unknown_path")):
        serena.unavailable(step[label])
        assert log.reason(step[label]) == reason, f"{label}: {log.reason(step[label])}, expected {reason}"
    serena.unavailable(step["unknown museum"], museum="default")
    assert log.reason(step["unknown museum"]) == "unknown_museum", log.reason(step["unknown museum"])
    serena.served(step["query string"])
    assert "?" not in log.line(step["query string"])["path"], "the query string was logged"


def test_t120_two_first_requests_at_once(phase: dict[int, Step], serena: Serena, log: Log) -> None:
    """Section 63 step 12: six requests at the same moment for a size not stored yet: all served, the same S3 name,
    and at most one fetch per web task. The bucket holds one version of the object, or one per fetch: Serena stores a
    file only if it isn't there yet, but two tasks fetching at once can both find it missing (the first run, November
    7, 2026: 2 fetches, 1 version)."""
    step = phase[12].checked()
    together = [a.sent for label, a in step.asked.items() if label.startswith("together")]
    assert len(together) == TOGETHER, f"only {len(together)} of {TOGETHER} requests answered"
    names = {serena.served(s) for s in together}
    assert len(names) == 1, f"{len(names)} different S3 names"
    fetched = [f for f in log.fetches(step.facts["blob"], step.facts["size"]) if f.get("message") == "fetched"]
    assert 1 <= len(fetched) <= web_count(), f"{len(fetched)} fetches for {step.facts['which']} ({web_count()} tasks)"
    versions = aws_cli("s3api", "list-object-versions", "--bucket", serena.target.bucket, "--prefix",
                       f"objects/{names.pop()}", "--query", "Versions[].VersionId") or []
    assert 1 <= len(versions) <= len(fetched), f"{len(versions)} versions of the object from {len(fetched)} fetches"


def test_t121_a_production_copied_record(phase: dict[int, Step], serena: Serena, log: Log, note: Note) -> None:
    """Section 63 step 13: a listed Blob that isn't a SERENA-TEST record (its file isn't in QA): the unavailable image,
    cspace_error (CollectionSpace's 500, not retried); again: the same. Whether the cspace-refused alarm emailed stays
    a check by hand."""
    step = phase[13].checked()
    for label in ("Medium 1", "Medium 2"):
        serena.unavailable(step[label])
        reason = log.reason(step[label])
        assert reason != "cspace_refused", "cspace_refused: stage 2 runs code from before pull request 202"
        assert reason == "cspace_error", f"{label}: {reason}"
    note("step 13: check by hand that no cspace-refused alarm email came")
