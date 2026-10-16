"""Media look up and Recalls for PAHMA: the pilot's T1 to T6 and the Recalls feature's T74 to T81 of the test inventory
(serena-test-inventory.xlsx; docs/testing-checklist.md sections 11, 17 to 21).

They run in this order on one dataset (serenade/dataset.py), with no reset: T1, T2 and T74 to T76 only look (at the
shared image, a record only the simulator has, and unknown CSIDs); T77, T3, T4 and T78 to T81 are the recall chain on
the reserved image, which T5 puts back; T6 affects every museum, so it runs last and undoes itself. A test that builds
on an earlier one is skipped if that one didn't pass (@pytest.mark.after)."""
from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from serenade.dataset import MUSEUM, RESERVED_IMAGE, SHARED_IMAGE, SIMULATOR_ONLY, unknown_csid
from serenade.pages.audit_log_page import AuditLogPage
from serenade.pages.lookup_page import LookUpPage
from serenade.pages.page import shortened
from serenade.pages.recalls_page import RecallsPage
from serenade.pages.requests_page import RequestsPage
from serenade.pages.sign_in_page import SignInPage
from serenade.stack import SERENA_URL, calls_to_simulator, eventually, redirect_of, simulator

pytestmark = pytest.mark.usefixtures("built_dataset")

ADMIN = ("admin", "admin")  # the simulator's synthetic account: its password is its username
STORED = f"/local-cdn/{MUSEUM}/objects/"
UNAVAILABLE = f"/unavailable/{MUSEUM}.svg"
RECALL_REASON = "serenade T3: a test recall"
CANCEL_REASON = "serenade T5: a test cancel"
NO_RECALLS = "No active recalls."
GIVE_A_REASON = "Give a reason first."


def signed_in(driver: WebDriver, base_url: str) -> None:
    SignInPage(driver, base_url).sign_in("PAHMA", *ADMIN)
    SignInPage(driver, base_url).wait_for_url(f"/admin/{MUSEUM}")


def served(path: str) -> None:
    assert STORED in redirect_of(path), f"{path} isn't served from Serena's stored copy"


def unavailable(path: str) -> None:
    assert redirect_of(path).endswith(UNAVAILABLE), f"{path} doesn't get the unavailable image"


def test_t1_a_served_image_comes_from_the_stored_copy() -> None:
    """Checklist section 11, step 2; section 17, step 1."""
    served(SHARED_IMAGE.path())
    served(SHARED_IMAGE.path())
    fetch = f"media/{SHARED_IMAGE.media}/blob/derivatives/Medium/content"
    fetches = [c for c in calls_to_simulator() if c.endswith(fetch)]
    assert len(fetches) == 1, f"expected one fetch from CollectionSpace, got {fetches}"


@pytest.mark.after("test_t1_a_served_image_comes_from_the_stored_copy")
def test_t2_media_look_up_says_served(driver: WebDriver, base_url: str) -> None:
    """Checklist section 17, step 2."""
    signed_in(driver, base_url)
    page = LookUpPage(driver, base_url)
    page.look_up(MUSEUM, SHARED_IMAGE.path())
    verdict = page.wait_for_text(page.VERDICT, "Served").text
    assert "Every check passes for the Medium size." in verdict
    assert "Serena has a cached copy" in page.text_of(page.NEXT)


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
    """Checklist section 17, step 9; section 18."""
    unavailable(RESERVED_IMAGE.path())
    signed_in(driver, base_url)
    requests = RequestsPage(driver, base_url)
    requests.open(f"{MUSEUM}/requests")
    line = requests.wait_for(requests.line_with("unserved", "recalled", shortened(RESERVED_IMAGE.blob)), timeout=30)
    assert line.text
    audit = AuditLogPage(driver, base_url)
    audit.open(f"{MUSEUM}/audit")
    audit.wait_for(audit.entry("recall", RECALL_REASON))


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
