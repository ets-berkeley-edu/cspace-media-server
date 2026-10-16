"""Past requests for PAHMA, checks T54 to T64 of the test inventory (serena-test-inventory.xlsx;
docs/testing-checklist.md sections 16, 19 to 21 and 23).

They read the lines the serving tests' requests made (test_serving.py runs first: conftest.py's FILE_ORDER) and only
look. They check that lines are there, never exact totals, so later requests don't upset them."""
from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from serenade.dataset import (
    BAD_CSID_PATH,
    MISSPELLED_SIZE,
    MUSEUM,
    SHARED_IMAGE,
    SHARED_MEDIA_ORIGINAL,
    SHARED_MEDIA_SMALL,
    UNKNOWN_MEDIA_PATH,
    UNKNOWN_PATH,
)
from serenade.pages.lookup_page import LookUpPage
from serenade.pages.page import shortened
from serenade.pages.requests_page import RequestsPage
from serenade.pages.sign_in_page import SignInPage

pytestmark = pytest.mark.usefixtures("built_dataset")

ADMIN = ("admin", "admin")  # the simulator's synthetic account: its password is its username
MEDIUM = SHARED_IMAGE.path()
THUMBNIAL = SHARED_IMAGE.path(MISSPELLED_SIZE)
# PAHMA's sizes smallest to largest (its derivatives, then the original file), as the Size column sorts them; then
# any other name ("(invalid)"), then a path with no size.
SIZE_ORDER = ["Thumbnail", "Small", "Medium", "FullHD", "OriginalJpeg", "original"]


def requests_page(driver: WebDriver, base_url: str, museum: str = "PAHMA") -> RequestsPage:
    SignInPage(driver, base_url).sign_in(museum, *ADMIN)
    SignInPage(driver, base_url).wait_for_url(f"/admin/{museum.lower()}")
    page = RequestsPage(driver, base_url)
    page.open_page(museum.lower())
    return page


def size_rank(shown: str) -> int:
    """Where the Size column should put a size as it shows it ("Medium", "Thumbnial (invalid)", or blank)."""
    if not shown:
        return len(SIZE_ORDER) + 1
    return SIZE_ORDER.index(shown) if shown in SIZE_ORDER else len(SIZE_ORDER)


def test_t54_the_page_opens_on_the_last_24_hours(driver: WebDriver, base_url: str) -> None:
    """Checklist section 16, step 2. (The spinner shows while the log is read; locally that's too quick to check.)"""
    page = requests_page(driver, base_url)
    assert page.text_of(page.TITLE) == "PAHMA Past requests"
    assert "v-btn--active" in str(page.wait_for(page.range_button("Last 24 hours")).get_attribute("class"))
    page.wait_for(page.line_for(MEDIUM))


def test_t55_by_day_most_requested_and_served_by_size(driver: WebDriver, base_url: str) -> None:
    """Checklist section 16, step 3; section 21, step 2."""
    page = requests_page(driver, base_url)
    today = datetime.now(UTC).date().isoformat()
    days = [row.find_elements(By.TAG_NAME, "td") for row in page.driver.find_elements(*page.BY_DAY_ROWS)]
    day = next(cells for cells in days if cells[0].text == today)
    assert int(day[1].text) > 0 and int(day[2].text) > 0, f"today's counts: {day[1].text}, {day[2].text}"
    assert "not listed" in day[3].text and "bad csid" in day[3].text
    top = [row.get_attribute("textContent") or "" for row in page.driver.find_elements(*page.TOP_ROWS)[:3]]
    assert any(shortened(SHARED_IMAGE.blob) in row for row in top), f"the shared image isn't near the top: {top}"
    assert page.text_of(page.BY_SIZE).startswith("by size:") and "Medium" in page.text_of(page.BY_SIZE)


def test_t56_the_tables_lines(driver: WebDriver, base_url: str) -> None:
    """Checklist section 16, step 4; section 20. No signed-link parameters anywhere on the table."""
    page = requests_page(driver, base_url)
    for path, reason in ((UNKNOWN_PATH, "not listed"), (BAD_CSID_PATH, "bad csid"),
                         (THUMBNIAL, "derivative not served"), (UNKNOWN_MEDIA_PATH, "not listed")):
        cells = page.cells(page.line_for(path))
        assert (cells["Outcome"], cells["Reason"]) == ("unserved", reason), f"{path}: {cells}"
    # An unknown file's Kind stays blank (a known file's unserved line has its kind: T80, the recalled image's).
    assert page.cells(page.line_for(UNKNOWN_PATH))["Kind"] == ""
    page.wait_for(page.line_for(MEDIUM))
    count = page.count(page.line_for(MEDIUM))
    served = [page.cells((By.XPATH, f"({page.line_for(MEDIUM)[1]})[{n}]")) for n in range(1, count + 1)]
    assert all((c["Outcome"], c["Kind"]) == ("served", "image") for c in served), served
    assert {c["Cache"] for c in served} == {"hit", "miss"}, served  # T1's first request fetched it; later ones hit
    html = page.wait_for(page.TABLE).get_attribute("innerHTML") or ""
    assert "uid=" not in html and "sig=" not in html, "a signed link's parameters are shown"


def test_t57_the_blob_csid_and_size_columns(driver: WebDriver, base_url: str) -> None:
    """Checklist section 16, step 5; section 21, step 2."""
    page = requests_page(driver, base_url)
    line = page.wait_for(page.line_for(MEDIUM))
    cells = page.cells(page.line_for(MEDIUM))
    assert cells["Blob CSID"].startswith(shortened(SHARED_IMAGE.blob)) and cells["Size"] == "Medium"
    assert line.find_elements(By.CSS_SELECTOR, "button.copy-button"), "no ⧉ beside the shortened Blob CSID"
    assert line.find_elements(By.XPATH, f".//*[@title='View this file: {MEDIUM}']"), "no path on hover"
    assert page.cells(page.line_for(THUMBNIAL))["Size"] == f"{MISSPELLED_SIZE} (invalid)"
    page.click(page.header("Size"))
    ranks = [size_rank(shown) for shown in page.column("Size")]
    assert ranks == sorted(ranks), f"not smallest to largest, others last: {page.column('Size')}"


def test_t58_media_urls_on_past_requests(driver: WebDriver, base_url: str) -> None:
    """Checklist section 23, step 4."""
    page = requests_page(driver, base_url)
    for path, size in ((SHARED_MEDIA_SMALL, "Small"), (SHARED_MEDIA_ORIGINAL, "original")):
        cells = page.cells(page.line_for(path))
        assert cells["Blob CSID"].startswith(f"Media {shortened(SHARED_IMAGE.media)}"), cells
        assert "(not a Blob path)" not in cells["Blob CSID"] and cells["Size"] == size, cells


def test_t59_filtering(driver: WebDriver, base_url: str) -> None:
    """Checklist section 16, step 7."""
    page = requests_page(driver, base_url)
    page.choose(page.OUTCOME, "Unserved")
    assert set(page.column("Outcome")) == {"unserved"}
    page.choose(page.REASON, "not listed")
    assert set(page.column("Reason")) == {"not listed"}
    page.choose(page.OUTCOME, "Served")
    assert set(page.column("Outcome")) == {"served"}
    reason = page.wait_for(page.field_of(page.REASON))
    assert "v-input--disabled" in str(reason.get_attribute("class")), "the Reason filter isn't greyed"
    assert "Any" in reason.text, f"the Reason filter isn't cleared: {reason.text}"


def test_t60_ranges(driver: WebDriver, base_url: str) -> None:
    """Checklist section 16, step 9: each range reads the log again, with today's lines."""
    page = requests_page(driver, base_url)
    for title, value in (("Last hour", "1h"), ("Last 7 days", "7d")):
        page.click(page.range_button(title))
        page.wait_for_address(f"range={value}")
        page.wait_for(page.line_for(MEDIUM), timeout=30)


def test_t61_the_csv_export_follows_the_filters(driver: WebDriver, base_url: str) -> None:
    """Checklist section 16, step 8; section 23, step 4. The file Export CSV links to, read with the browser's
    session (no download folder needed)."""
    page = requests_page(driver, base_url)
    page.choose(page.OUTCOME, "Unserved")
    status, disposition, text = page.fetch_text(str(page.wait_for(page.EXPORT).get_attribute("href")))
    assert status == 200
    assert f'filename="serena-requests-{MUSEUM}-{datetime.now(UTC).date().isoformat()}.csv"' in disposition
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["time (UTC)", "outcome", "reason", "path", "kind", "cache", "signed link"]
    assert rows[1:] and {row[1] for row in rows[1:]} == {"unserved"}
    paths = {row[3] for row in rows[1:]}
    assert {UNKNOWN_PATH, BAD_CSID_PATH, THUMBNIAL, UNKNOWN_MEDIA_PATH} <= paths, paths  # as requested, no query
    assert "uid=" not in text and "sig=" not in text


def test_t62_another_museum_sees_none_of_pahmas_requests(driver: WebDriver, base_url: str) -> None:
    """Checklist section 16, step 11: a privacy boundary between museums."""
    page = requests_page(driver, base_url, "BAMPFA")
    assert page.text_of(page.TITLE) == "BAMPFA Past requests"
    assert "No requests match." in page.text_of(page.TABLE)
    html = page.driver.page_source
    assert f"/{MUSEUM}/" not in html and shortened(SHARED_IMAGE.blob) not in html


def test_t63_opening_a_file_from_a_request(driver: WebDriver, base_url: str) -> None:
    """Checklist sections 19, 20; section 23, step 4."""
    page = requests_page(driver, base_url)
    bad = page.wait_for(page.line_for(BAD_CSID_PATH))
    assert not bad.find_elements(By.CSS_SELECTOR, "button.file-link"), "a bad CSID's line shouldn't open a file"
    page.click((By.XPATH, f"({page.line_for(MEDIUM)[1]})[1]//button[contains(@class, 'file-link')]"))
    dialog = page.wait_for(page.FILE_DIALOG)
    page.wait_for_picture(page.FILE_DIALOG_PICTURE)
    assert MEDIUM in dialog.text
    assert "This request, " in dialog.text and ": served." in dialog.text
    page.wait_for(page.FILE_DIALOG_DISMISS)
    page.click(page.FILE_DIALOG_LOOKUP)
    look_up = LookUpPage(driver, base_url)
    look_up.wait_for_answer(MEDIUM)
    assert look_up.text_of(look_up.VERDICT).startswith("Served")


def test_t64_a_file_serena_cant_show(driver: WebDriver, base_url: str) -> None:
    """Checklist section 20: the unknown CSID's request (T8) opened from its line."""
    page = requests_page(driver, base_url)
    page.click((By.XPATH, f"{page.line_for(UNKNOWN_PATH)[1]}//button[contains(@class, 'file-link')]"))
    why = page.wait_for(page.FILE_DIALOG_NONE, timeout=20).text
    assert why == "Nothing to show: Serena has no cached copy, and CollectionSpace has no file with this CSID.", why
