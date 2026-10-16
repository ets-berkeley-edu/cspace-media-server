"""Media look up and Recalls for PAHMA: the pilot's T2 to T6 (its T1 is in test_serving.py), the Recalls feature's
T74 to T81, the Media look up feature's T65 to T73 and a recall's alert, T26, of the test inventory
(serena-test-inventory.xlsx; docs/testing-checklist.md sections 11 and 17 to 21).

They run in this order on one dataset (serenade/dataset.py), with no reset, after the files before them in
conftest.py's FILE_ORDER: T2, T65 to T67, T71 to T73 and T74 to T76 only look (at the shared records, a record only
the simulator has, and unknown CSIDs); T77, T3, T4, T78 to T80, T26 and T81 are the recall chain on the reserved
image, which T5 puts back; T68 to T70 change another reserved image in CollectionSpace and put it back afterwards; T6
affects every museum, so it runs last and undoes itself. A test that builds on an earlier one is skipped if that one
didn't pass (@pytest.mark.after)."""
from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from serenade.dataset import (
    CSPACE_CHANGES,
    MUSEUM,
    RESERVED_IMAGE,
    SHARED_CARD,
    SHARED_IMAGE,
    SIMULATOR_ONLY,
    unknown_csid,
)
from serenade.pages.alerts_page import AlertsPage
from serenade.pages.audit_log_page import AuditLogPage
from serenade.pages.lookup_page import LookUpPage
from serenade.pages.page import shortened
from serenade.pages.recalls_page import RecallsPage
from serenade.pages.requests_page import RequestsPage
from serenade.pages.sign_in_page import SignInPage
from serenade.stack import SERENA_URL, eventually, redirect_of, simulator

pytestmark = pytest.mark.usefixtures("built_dataset")

ADMIN = ("admin", "admin")  # the simulator's synthetic account: its password is its username
STORED = f"/local-cdn/{MUSEUM}/objects/"
UNAVAILABLE = f"/unavailable/{MUSEUM}.svg"
RECALL_REASON = "serenade T3: a test recall"
CANCEL_REASON = "serenade T5: a test cancel"
NO_RECALLS = "No active recalls."
GIVE_A_REASON = "Give a reason first."
SIZES = ("original", "Thumbnail", "Small", "Medium", "FullHD", "OriginalJpeg")  # PAHMA's (museums/pahma.yaml)
SHARED_CACHED = ("original", "Small", "Medium")  # the shared image's sizes the serving tests cache (T15, T14, T1)


def signed_in(driver: WebDriver, base_url: str) -> None:
    SignInPage(driver, base_url).sign_in("PAHMA", *ADMIN)
    SignInPage(driver, base_url).wait_for_url(f"/admin/{MUSEUM}")


def served(path: str) -> None:
    assert STORED in redirect_of(path), f"{path} isn't served from Serena's stored copy"


def unavailable(path: str) -> None:
    assert redirect_of(path).endswith(UNAVAILABLE), f"{path} doesn't get the unavailable image"


@pytest.mark.after("test_t1_a_served_image_comes_from_the_stored_copy")
def test_t2_media_look_up_says_served(driver: WebDriver, base_url: str) -> None:
    """Checklist section 17, step 2."""
    signed_in(driver, base_url)
    page = LookUpPage(driver, base_url)
    page.look_up(MUSEUM, SHARED_IMAGE.path())
    verdict = page.wait_for_text(page.VERDICT, "Served").text
    assert "Every check passes for the Medium size." in verdict
    assert "Serena has a cached copy" in page.text_of(page.NEXT)


def test_t65_a_media_csid_alone_every_size(driver: WebDriver, base_url: str) -> None:
    """Checklist section 17, step 3; section 21. After the serving tests, which cache three of its sizes."""
    signed_in(driver, base_url)
    page = LookUpPage(driver, base_url)
    page.look_up(MUSEUM, SHARED_IMAGE.media)
    page.wait_for_answer(SHARED_IMAGE.media)
    assert page.text_of(page.VERDICT).startswith("Served")
    # All served, so the sizes start folded away under one line.
    assert page.text_of(page.SIZES_LINE) == f"Sizes (6): all served · cached: {', '.join(SHARED_CACHED)}"
    assert not page.is_open(page.SIZES_BOX)
    page.click(page.SIZES_LINE)
    for size in SIZES:
        cells = page.wait_for(page.size_row(size)).find_elements(By.TAG_NAME, "td")
        assert cells[1].text == "Yes", f"{size} isn't served"
        assert (cells[3].text != "—") == (size in SHARED_CACHED), f"{size}'s cached copy: {cells[3].text}"


def test_t66_beside_collectionspace_with_no_differences(driver: WebDriver, base_url: str) -> None:
    """Checklist section 19, step 1; section 20."""
    signed_in(driver, base_url)
    page = LookUpPage(driver, base_url)
    page.look_up(MUSEUM, SHARED_IMAGE.path())
    page.wait_for_answer(SHARED_IMAGE.path())
    heading = page.text_of(page.HEADING)
    assert re.match(r"Media 2026\.1\.\d+\s*Media CSID " + SHARED_IMAGE.media + "$", heading), heading
    page.click(page.details_summary(page.SERENA_DETAILS))
    serena = page.text_of(page.SERENA_DETAILS)
    for field in ("Media CSID", SHARED_IMAGE.media, "Blob CSID", SHARED_IMAGE.blob, "Kind", "Access", "public",
                  "First cached", "Last served", "Checks"):
        assert field in serena, f"Serena's Details has no {field!r}"
    page.click(page.details_summary(page.CSPACE_DETAILS))
    cspace = page.text_of(page.CSPACE_DETAILS)
    for field in ("State", "Exists", "Blob CSID", SHARED_IMAGE.blob, "Approved for web", "Last changed"):
        assert field in cspace, f"CollectionSpace's Details has no {field!r}"
    assert "differs" not in cspace
    assert page.text_of(page.SYNC) == "✓ (No differences)"
    assert "Nothing has changed in CollectionSpace since the last refresh." in page.text_of(page.NEXT_REFRESH)


def test_t67_the_answer_from_the_address(driver: WebDriver, base_url: str) -> None:
    """Checklist section 19, step 2: the page's address, opened in a new tab, gives the same answer."""
    signed_in(driver, base_url)
    page = LookUpPage(driver, base_url)
    page.look_up(MUSEUM, SHARED_IMAGE.path())
    page.wait_for_answer(SHARED_IMAGE.path())
    address, verdict, heading = driver.current_url, page.text_of(page.VERDICT), page.text_of(page.HEADING)
    assert "?q=" in address
    driver.switch_to.new_window("tab")
    driver.get(address)
    page.wait_for_answer(SHARED_IMAGE.path())
    assert page.text_of(page.VERDICT) == verdict
    assert page.text_of(page.HEADING) == heading


def test_t71_an_unknown_csid(driver: WebDriver, base_url: str) -> None:
    """Checklist section 19, step 6."""
    unknown = unknown_csid(0)
    signed_in(driver, base_url)
    page = LookUpPage(driver, base_url)
    page.look_up(MUSEUM, unknown)
    page.wait_for_answer(unknown)
    assert page.text_of(page.VERDICT).startswith("Not served: not in the servable list")
    assert "Not in CollectionSpace" in page.text_of(page.CSPACE_PANEL)
    assert "CollectionSpace has no Blob or Media record with this CSID either." in page.text_of(page.NEXT)
    assert page.count(page.HEADING) == 0


def test_t72_paths_it_forgives_and_paths_it_doesnt_serve(driver: WebDriver, base_url: str) -> None:
    """Checklist sections 20 and 21; section 23, step 5. Several look ups, one after another."""
    full = SHARED_IMAGE.path()
    signed_in(driver, base_url)
    page = LookUpPage(driver, base_url)
    page.open(f"{MUSEUM}/lookup")
    # A path without its leading slash, or without the museum, is read as the full PAHMA path.
    for forgiven in (full.lstrip("/"), full.split("/imageserver/", 1)[1]):
        page.look_up_here(forgiven)
        page.wait_for_answer(full)
        assert "Every check passes for the Medium size." in page.text_of(page.VERDICT)
        assert page.count(page.BARE_URL) == 0
    # Another museum's path.
    page.look_up_here(full.replace(f"/{MUSEUM}/", "/cinefiles/", 1))
    assert "That's a Cinefiles path; you're looking up PAHMA's files." in page.wait_for(page.PROBLEM).text
    # A Blob's URL without /content, and a /media/ URL in a shape Serena doesn't serve: why, then every size.
    bare_blob = f"/{MUSEUM}/imageserver/blobs/{SHARED_IMAGE.blob}"
    media_content = f"/{MUSEUM}/imageserver/media/{SHARED_IMAGE.media}/content"
    for bare, needs in ((bare_blob, "it needs /content or"), (media_content, "it needs /blob/content or")):
        page.look_up_here(bare)
        page.wait_for_answer(bare)
        assert "This URL isn't one Serena serves" in page.text_of(page.BARE_URL)
        assert needs in page.text_of(page.BARE_URL)
        assert page.text_of(page.SIZES_LINE).startswith("Sizes (6): all served")
    # A Media URL Serena serves: answered as its Blob's, with no note.
    media_url = f"/{MUSEUM}/imageserver/media/{SHARED_IMAGE.media}/blob/derivatives/Medium/content"
    page.look_up_here(SERENA_URL + media_url)
    page.wait_for_answer(media_url)
    assert "Every check passes for the Medium size." in page.text_of(page.VERDICT)
    assert SHARED_IMAGE.blob in page.all_text_of(page.SERENA_DETAILS)
    assert page.count(page.BARE_URL) == 0


def test_t73_the_sizes_box_and_size_links(driver: WebDriver, base_url: str) -> None:
    """Checklist section 21."""
    signed_in(driver, base_url)
    page = LookUpPage(driver, base_url)
    page.look_up(MUSEUM, SHARED_IMAGE.media)
    page.wait_for_answer(SHARED_IMAGE.media)
    assert page.text_of(page.SIZES_LINE).startswith("Sizes (6): ")
    page.click(page.SIZES_LINE)
    page.click(page.size_link("Medium"))
    page.wait_for_picture(page.FILE_DIALOG_PICTURE)
    assert page.count(page.FILE_DIALOG_LOOKUP) == 0, "a size's file shouldn't offer Media look up: this is it"
    page.click(page.FILE_DIALOG_DISMISS)
    page.wait_until_gone(page.FILE_DIALOG)
    # The box stays as the admin left it: open for another record, and when coming back.
    page.look_up_here(SHARED_CARD.media)
    page.wait_for_answer(SHARED_CARD.media)
    assert page.is_open(page.SIZES_BOX)
    driver.back()
    page.wait_for_answer(SHARED_IMAGE.media)
    assert page.is_open(page.SIZES_BOX)


def test_t74_previewing_a_recall_shows_what_serena_finds(driver: WebDriver, base_url: str) -> None:
    """Checklist section 17, steps 4 and 5. Looks only: the preview is cancelled. Adds a Media record to the
    simulator that no other test uses."""
    simulator("POST", "/_fake/media", {"csid": SIMULATOR_ONLY, "kind": "image"})
    signed_in(driver, base_url)
    page = RecallsPage(driver, base_url)
    page.preview(MUSEUM, f"{SHARED_IMAGE.blob}\n{SHARED_IMAGE.media}\n{SIMULATOR_ONLY}\nnot-a-csid!")
    assert page.count(page.SUMMARY_ROWS) == 2
    shared = page.all_text_of(page.summary_row(SHARED_IMAGE.media))
    assert "Serena" in shared and "CollectionSpace" not in shared
    you_gave = shared.split("Serena", 1)[1]  # the last column, after "Found in"
    assert SHARED_IMAGE.blob in you_gave and SHARED_IMAGE.media in you_gave
    assert "CollectionSpace (not served today)" in page.text_of(page.summary_row(SIMULATOR_ONLY))
    assert page.text_of(page.NOT_RECALLED) == "not-a-csid!: Not a CSID."
    page.wait_for_picture(page.THUMBNAILS)
    page.close_form()
    assert NO_RECALLS in page.text_of(page.ACTIVE)
    served(SHARED_IMAGE.path())


def test_t75_paths_and_urls_in_the_recall_form(driver: WebDriver, base_url: str) -> None:
    """Checklist sections 20 and 21. Looks only: the preview is cancelled."""
    signed_in(driver, base_url)
    page = RecallsPage(driver, base_url)
    page.open_form(MUSEUM)
    page.paste(page.CSIDS, SERENA_URL + SHARED_IMAGE.path())
    page.wait_for_value(page.CSIDS, SHARED_IMAGE.blob)
    assert page.value_of(page.CSIDS) == SHARED_IMAGE.blob, "the pasted URL wasn't cut down to its Blob CSID at once"
    cinefiles = f"/cinefiles/imageserver/blobs/{unknown_csid(75)}/derivatives/Medium/content"
    page.add_text(page.CSIDS, "\n" + cinefiles)
    page.click(page.PREVIEW)
    row = page.wait_for(page.summary_row(SHARED_IMAGE.media))
    assert row.find_elements(By.XPATH, f".//span[@title='{SHARED_IMAGE.path()}']"), "You gave doesn't show the path"
    assert "That's a Cinefiles path; you're recalling PAHMA's files." in page.text_of(page.NOT_RECALLED)
    page.click(page.CHANGE)
    kept = page.value_of(page.CSIDS)
    assert SHARED_IMAGE.blob in kept and cinefiles in kept
    page.close_form()
    assert NO_RECALLS in page.text_of(page.ACTIVE)


def test_t76_more_than_12_csids_and_a_text_file(driver: WebDriver, base_url: str, tmp_path: Path) -> None:
    """Checklist section 17, step 10. Looks only: unknown CSIDs, and the preview is cancelled."""
    csids = "\n".join(unknown_csid(n) for n in range(1, 14))
    signed_in(driver, base_url)
    page = RecallsPage(driver, base_url)
    page.open_form(MUSEUM)
    page.type(page.CSIDS, csids)
    page.click(page.PREVIEW)
    assert page.text_of(page.FORM_ERROR) == "More than 12 CSIDs: use a text file instead."
    listed = tmp_path / "csids.txt"  # synthetic CSIDs only
    listed.write_text(csids + "\n")
    page.choose_file(page.FILE, str(listed))
    page.click(page.PREVIEW)
    page.wait_for(page.NOT_RECALLED, timeout=30)  # Serena asks CollectionSpace about each
    lines = [line.text for line in page.driver.find_elements(*page.NOT_RECALLED_LINES)]
    assert len(lines) == 13 and all("Not found" in line for line in lines), lines
    assert page.count(page.CONFIRM) == 0
    page.close_form()


def test_t77_recall_without_a_reason(driver: WebDriver, base_url: str) -> None:
    """Checklist section 17, step 7; section 21. Looks only: nothing is recalled. Just before T3."""
    signed_in(driver, base_url)
    page = RecallsPage(driver, base_url)
    page.preview(MUSEUM, RESERVED_IMAGE.media)
    assert "Required. Recorded in the audit log" in page.text_of(page.REASON_MESSAGES)  # the hint
    page.click(page.CONFIRM)
    page.wait_for_text(page.REASON_MESSAGES, GIVE_A_REASON)
    assert page.focused_id() == "recall-reason"
    page.close_form()
    assert NO_RECALLS in page.text_of(page.ACTIVE)


def test_t3_a_recall_stops_serving(driver: WebDriver, base_url: str) -> None:
    """Checklist section 17, steps 5, 7 and 8. Changes the reserved image."""
    served(RESERVED_IMAGE.path())
    signed_in(driver, base_url)
    page = RecallsPage(driver, base_url)
    page.recall(MUSEUM, RESERVED_IMAGE.media, RECALL_REASON)
    row = page.wait_for(page.row_with("active-recalls", RECALL_REASON)).text
    assert "Waiting for a later refresh" in row and "admin" in row
    eventually(lambda: unavailable(RESERVED_IMAGE.path()))


@pytest.mark.after("test_t3_a_recall_stops_serving")
def test_t4_media_look_up_says_recalled(driver: WebDriver, base_url: str) -> None:
    """Checklist section 17, step 8."""
    signed_in(driver, base_url)
    page = LookUpPage(driver, base_url)
    page.look_up(MUSEUM, RESERVED_IMAGE.path())
    assert "Not served: recalled" in page.wait_for_text(page.VERDICT, "Not served: recalled").text
    assert RECALL_REASON in page.text_of(page.VERDICT)
    assert "Open Recalls" in page.text_of(page.NEXT)


@pytest.mark.after("test_t3_a_recall_stops_serving")
def test_t78_an_already_recalled_record_in_the_preview(driver: WebDriver, base_url: str) -> None:
    """Checklist section 17, step 9."""
    signed_in(driver, base_url)
    page = RecallsPage(driver, base_url)
    page.preview(MUSEUM, RESERVED_IMAGE.media)
    row = page.wait_for(page.summary_row(RESERVED_IMAGE.media))
    assert "already recalled" in row.text
    assert "text-disabled" in str(row.get_attribute("class")), "the recalled record isn't greyed"
    assert page.count(page.CONFIRM) == 0
    page.close_form()


@pytest.mark.after("test_t3_a_recall_stops_serving")
def test_t79_a_recalls_row_its_csids_and_its_files(driver: WebDriver, base_url: str) -> None:
    """Checklist section 19, last step; sections 20 and 21."""
    signed_in(driver, base_url)
    page = RecallsPage(driver, base_url)
    page.open(f"{MUSEUM}/recalls")
    row = page.wait_for(page.row_with("active-recalls", RECALL_REASON)).text
    assert re.search(r"\b2026\.1\.\d+\b", row), f"no identification number in {row!r}"
    page.open_row("active-recalls", RECALL_REASON)
    details = page.text_of(page.details_of("active-recalls", RECALL_REASON))
    assert RESERVED_IMAGE.media in details and RESERVED_IMAGE.blob in details
    # Admins see a recalled file: the dialog shows its picture.
    page.click(page.view_file("Blob CSID", RESERVED_IMAGE.blob))
    page.wait_for_picture(page.FILE_DIALOG_PICTURE)
    page.click(page.FILE_DIALOG_DISMISS)
    page.wait_until_gone(page.FILE_DIALOG)
    page.click(page.view_file("Media CSID", RESERVED_IMAGE.media))
    page.wait_for_picture(page.FILE_DIALOG_PICTURE)
    page.click(page.FILE_DIALOG_LOOKUP)
    look_up = LookUpPage(driver, base_url)
    assert "Not served: recalled" in look_up.wait_for_text(look_up.VERDICT, "Not served: recalled").text


@pytest.mark.after("test_t3_a_recall_stops_serving")
def test_t80_the_recall_in_past_requests_and_the_audit_log(driver: WebDriver, base_url: str) -> None:
    """Checklist section 17, step 9; section 18. The recalled image's unserved line has its kind (T56's other half)."""
    unavailable(RESERVED_IMAGE.path())
    signed_in(driver, base_url)
    requests = RequestsPage(driver, base_url)
    requests.open(f"{MUSEUM}/requests")
    line = requests.line_with("unserved", "recalled", shortened(RESERVED_IMAGE.blob))
    requests.wait_for(line, timeout=30)
    assert requests.cells(line)["Kind"] == "image", "an unserved line of a file Serena knows has its kind"
    audit = AuditLogPage(driver, base_url)
    audit.open(f"{MUSEUM}/audit")
    audit.wait_for(audit.entry("recall", RECALL_REASON))


@pytest.mark.after("test_t3_a_recall_stops_serving")
def test_t26_a_recalls_alert_names_its_record(driver: WebDriver, base_url: str) -> None:
    """Checklist section 21, step 5. The alert names the record by its identification number and shortened Media
    CSID; its About opens Media look up."""
    signed_in(driver, base_url)
    page = AlertsPage(driver, base_url)
    page.open_page(MUSEUM)
    row = page.wait_for(page.row_with(RECALL_REASON)).text
    named = re.search(r"An admin recalled Media record 2026\.1\.\d+ \(([^)]*)\) for PAHMA\. Reason: (.*)", row)
    assert named, f"the alert doesn't name the record: {row!r}"
    assert named.group(1) == shortened(RESERVED_IMAGE.media) and named.group(2).startswith(RECALL_REASON)
    page.click((By.XPATH, f"{page.row_with(RECALL_REASON)[1]}//a[@title='Media look up: {RESERVED_IMAGE.media}']"))
    look_up = LookUpPage(driver, base_url)
    look_up.wait_for_answer(RESERVED_IMAGE.media)
    assert look_up.text_of(look_up.VERDICT).startswith("Not served: recalled")


@pytest.mark.after("test_t3_a_recall_stops_serving")
def test_t81_cancel_recall_without_a_reason(driver: WebDriver, base_url: str) -> None:
    """Checklist section 21. The recall is kept."""
    signed_in(driver, base_url)
    page = RecallsPage(driver, base_url)
    page.open_cancel(MUSEUM, RECALL_REASON)
    page.click(page.CANCEL_CONFIRM)
    page.wait_for_text(page.CANCEL_REASON_MESSAGES, GIVE_A_REASON)
    page.click(page.KEEP)
    page.wait_until_gone(page.CANCEL_REASON)
    assert "Waiting for a later refresh" in page.text_of(page.row_with("active-recalls", RECALL_REASON))
    unavailable(RESERVED_IMAGE.path())


@pytest.mark.after("test_t3_a_recall_stops_serving")
def test_t5_cancelling_the_recall_serves_it_again(driver: WebDriver, base_url: str) -> None:
    """Checklist section 17, "Cancel a recall made by mistake". Puts the reserved image back as it started."""
    signed_in(driver, base_url)
    page = RecallsPage(driver, base_url)
    page.cancel(MUSEUM, RECALL_REASON, CANCEL_REASON)
    row = page.wait_for(page.row_with("ended-recalls", CANCEL_REASON)).text
    assert "Cancelled" in row
    eventually(lambda: served(RESERVED_IMAGE.path()))


@pytest.fixture(scope="class")
def put_back() -> Iterator[None]:
    """T68 to T70 change the reserved record in CollectionSpace; afterwards, even when one fails, it's put back with
    the simulator's hooks (each leaves a record it didn't change as it is)."""
    yield
    simulator("POST", f"/_fake/undelete/{CSPACE_CHANGES.media}")
    simulator("POST", f"/_fake/restore/{CSPACE_CHANGES.media}")
    simulator("POST", f"/_fake/approve/{CSPACE_CHANGES.media}", {"approved": True})


@pytest.mark.usefixtures("put_back")
class TestCollectionSpaceChanges:
    """Checklist section 19, steps 3 to 5, on the reserved record for CollectionSpace changes, in this order."""

    def test_t68_taken_off_the_web_in_collectionspace(self, driver: WebDriver, base_url: str) -> None:
        served(CSPACE_CHANGES.path())  # caches its Medium size, for T70
        simulator("POST", f"/_fake/approve/{CSPACE_CHANGES.media}", {"approved": False})
        signed_in(driver, base_url)
        page = LookUpPage(driver, base_url)
        page.look_up(MUSEUM, CSPACE_CHANGES.path())
        page.wait_for_answer(CSPACE_CHANGES.path())
        assert page.text_of(page.VERDICT).startswith("Served")  # Serena's answer comes from the last refresh
        page.click(page.details_summary(page.CSPACE_DETAILS))
        assert "Approved for web\nNo" in page.text_of(page.CSPACE_DETAILS)
        assert "differs" in page.text_of(page.compare_row("As of"))
        assert page.text_of(page.SYNC) == "⚠ (1 difference: As of)"
        assert "The Media record changed in CollectionSpace after the last refresh." in page.text_of(page.NEXT_REFRESH)

    @pytest.mark.after("test_t68_taken_off_the_web_in_collectionspace")
    def test_t69_replaced_in_collectionspace(self, driver: WebDriver, base_url: str) -> None:
        simulator("POST", f"/_fake/replace/{CSPACE_CHANGES.media}")
        signed_in(driver, base_url)
        page = LookUpPage(driver, base_url)
        page.look_up(MUSEUM, CSPACE_CHANGES.path())
        page.wait_for_answer(CSPACE_CHANGES.path())
        assert "differs" in page.text_of(page.compare_row("Blob CSID"))
        page.click(page.details_summary(page.CSPACE_DETAILS))
        assert "differs" in page.text_of(page.CSPACE_DETAILS)
        assert ("The Media record has a new Blob in CollectionSpace since the last refresh."
                in page.text_of(page.NEXT_REFRESH))

    @pytest.mark.after("test_t69_replaced_in_collectionspace")
    def test_t70_soft_deleted_in_collectionspace(self, driver: WebDriver, base_url: str) -> None:
        simulator("POST", f"/_fake/delete/{CSPACE_CHANGES.media}")
        signed_in(driver, base_url)
        page = LookUpPage(driver, base_url)
        page.look_up(MUSEUM, CSPACE_CHANGES.media)
        page.wait_for_answer(CSPACE_CHANGES.media)
        assert page.text_of(page.VERDICT).startswith("Served (cached sizes only)")
        assert page.is_open(page.SIZES_BOX)  # opens by itself when the sizes differ
        for size in SIZES:
            cells = page.wait_for(page.size_row(size)).find_elements(By.TAG_NAME, "td")
            expected = ("Yes", "") if size == "Medium" else ("No", "media deleted")
            assert (cells[1].text, cells[2].text) == expected, f"{size}: {cells[1].text}, {cells[2].text}"
        page.click(page.details_summary(page.CSPACE_DETAILS))
        assert "Soft-deleted" in page.text_of(page.CSPACE_DETAILS)


@pytest.fixture
def outage() -> Iterator[None]:
    """The simulator's outage switch: every CollectionSpace call answers 503 while it's on. Always switched off
    again, even when the test fails, so the dataset is left as it was."""
    simulator("POST", "/_fake/unreachable", {"on": True})
    try:
        yield
    finally:
        simulator("POST", "/_fake/unreachable", {"on": False})


@pytest.mark.usefixtures("outage")
def test_t6_media_look_up_while_collectionspace_cant_be_reached(driver: WebDriver, base_url: str) -> None:
    """Checklist section 19, the outage step. Museum-wide, so last."""
    signed_in(driver, base_url)
    page = LookUpPage(driver, base_url)
    page.look_up(MUSEUM, SHARED_IMAGE.path())
    # Serena retries CollectionSpace first, so the answer takes a few seconds.
    down = page.wait_for(page.CSPACE_DOWN, timeout=60).text
    assert "CollectionSpace can't be reached, so there's nothing to compare with" in down
    assert page.text_of(page.HEADING).startswith(f"Media {SHARED_IMAGE.media}")
    assert "Served" in page.text_of(page.VERDICT)
