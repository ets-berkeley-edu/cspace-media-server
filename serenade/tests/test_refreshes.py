"""Refreshes: Past refreshes, a refresh's page and Start a refresh, checks T16 to T21 of the test inventory
(serena-test-inventory.xlsx; docs/testing-checklist.md sections 11, 14, 15 and 21). T22 is covered by the backend's
tests.

T16 and T20 only look, at PAHMA. T17 to T21 act on UCJEPS, a reserved museum no PAHMA test uses, after the alerts
tests have read its failed refresh's alert (conftest.py's FILE_ORDER): T17 looks at the dataset's failed refresh, T18
overrides its threshold (so UCJEPS publishes 3 rows), T19 repairs a failed admin refresh with the 3-row list, and T21
adds admin refreshes until UCJEPS has 30."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from serenade.dataset import MUSEUM, UCJEPS, UCJEPS_FAILED, refresh_id, servable_list
from serenade.pages.refreshes_page import RefreshesPage
from serenade.pages.sign_in_page import SignInPage

pytestmark = pytest.mark.usefixtures("built_dataset")

ADMIN = ("admin", "admin")  # the simulator's synthetic account: its password is its username
GIVE_A_REASON = "Give a reason first."
OVERRIDE_REASON = "serenade T18: a test override"
REPAIR_REASON = "serenade T19: a test admin refresh"


def signed_in(driver: WebDriver, base_url: str, museum: str) -> RefreshesPage:
    SignInPage(driver, base_url).sign_in(museum.upper(), *ADMIN)
    SignInPage(driver, base_url).wait_for_url(f"/admin/{museum}")
    return RefreshesPage(driver, base_url)


def test_t16_past_refreshes_lists_the_datasets_refresh(driver: WebDriver, base_url: str) -> None:
    """Checklist section 14, step 1."""
    page = signed_in(driver, base_url, MUSEUM)
    page.open_list(MUSEUM)
    assert page.text_of(page.TITLE) == "PAHMA Past refreshes"
    cells = page.cells(page.row_of(refresh_id(MUSEUM)))
    assert (cells["State"], cells["Rows"]) == ("Updated", "21"), cells  # 20 rows and the placeholder image


def test_t20_start_a_refresh_says_whats_missing(driver: WebDriver, base_url: str) -> None:
    """Checklist section 21. Nothing is started."""
    page = signed_in(driver, base_url, MUSEUM)
    before = len(page.refreshes(MUSEUM))
    page.open(f"{MUSEUM}/start-refresh")
    page.click(page.START)
    assert page.wait_for_text(page.FILE_MESSAGES, "Choose the servable list first.")
    assert GIVE_A_REASON in page.text_of(page.REASON_MESSAGES)
    assert "Confirm the list was made from the live public core." in page.text_of(page.CONFIRM_MESSAGES)
    assert driver.current_url.endswith(f"/{MUSEUM}/start-refresh")
    assert len(page.refreshes(MUSEUM)) == before


def test_t17_a_failed_servable_list_check_on_its_refreshs_page(driver: WebDriver, base_url: str) -> None:
    """Checklist section 11, step 6; section 14, step 2."""
    page = signed_in(driver, base_url, UCJEPS)
    page.open_refresh(UCJEPS, refresh_id(UCJEPS_FAILED))
    assert page.text_of(page.STATE) == "Servable list check failed"
    assert re.search(r"\d+(\.\d+)?% of the rows would change; the threshold is \d", page.text_of(page.CHECK_PROBLEMS))
    override = page.wait_for(page.OVERRIDE)
    assert override.text == "Override the delta threshold"
    assert "bg-error" in str(override.get_attribute("class")), "the Override button isn't red"


@pytest.mark.after("test_t17_a_failed_servable_list_check_on_its_refreshs_page")
def test_t18_overriding_the_delta_threshold(driver: WebDriver, base_url: str) -> None:
    """Checklist section 14, step 3; section 21. The failed refresh is checked again without the threshold and
    updates, so UCJEPS then publishes its 3 rows."""
    failed = refresh_id(UCJEPS_FAILED)
    page = signed_in(driver, base_url, UCJEPS)
    page.open_refresh(UCJEPS, failed)
    page.click(page.OVERRIDE)
    page.click(page.CONFIRM)
    page.wait_for_text(page.REASON_MESSAGES, GIVE_A_REASON)
    assert page.refresh(UCJEPS, failed)["state"] == "check_failed", "overridden without a reason"
    page.type(page.REASON, OVERRIDE_REASON)
    page.click(page.CONFIRM)
    # Issue #108: the banner says who, when and why at once, and the page checks again by itself until it's updated.
    banner = page.wait_for_text(page.OVERRIDE_BANNER, f"Reason: {OVERRIDE_REASON}").text
    assert banner.startswith("Delta threshold overridden by "), banner
    page.wait_for_text(page.STATE, "Updated", timeout=60)
    assert page.text_of(page.CHECK_OVERRIDDEN) == "Delta threshold overridden"
    assert OVERRIDE_REASON not in page.text_of(page.REASONS), "the reason is in the banner, not under Reasons"


@pytest.mark.after("test_t18_overriding_the_delta_threshold")
def test_t19_an_admin_refresh_repairs_an_open_failed_refresh(driver: WebDriver, base_url: str) -> None:
    """Checklist section 14, steps 5 and 6. First a failed refresh to repair: an admin refresh with the 20-row list,
    which fails against the 3 rows UCJEPS publishes. Then Start a refresh with the 3-row list repairs it."""
    page = signed_in(driver, base_url, UCJEPS)
    failed = page.admin_refresh(UCJEPS, servable_list("ucjeps-20").read_text(), "serenade T19: a refresh to repair")
    assert failed["state"] == "check_failed", failed["state"]
    page.open(f"{UCJEPS}/start-refresh")
    page.choose_file(page.FILE, str(Path(servable_list("ucjeps-3")).resolve()))
    page.type(page.REASON, REPAIR_REASON)
    page.click(page.CONFIRM_LIVE_CORE)
    page.click(page.START)
    page.wait_for((By.XPATH, "//h1[@id='page-title'][contains(normalize-space(), 'refresh ucjeps-')]"))
    repaired = driver.current_url.rstrip("/").rsplit("/", 1)[1]
    assert repaired != failed["refresh_id"]
    page.wait_for_state(UCJEPS, repaired, "Updated")
    assert REPAIR_REASON in page.text_of(page.REASONS)
    page.open_refresh(UCJEPS, failed["refresh_id"])
    assert page.text_of(page.STATE) == "Abandoned"
    assert "closed by an admin refresh" in page.text_of(page.REASONS)


@pytest.mark.after("test_t19_an_admin_refresh_repairs_an_open_failed_refresh")
def test_t21_sorting_and_paging_past_refreshes(driver: WebDriver, base_url: str) -> None:
    """Checklist section 15, step 7. UCJEPS is brought up to 30 refreshes with admin refreshes of the list it already
    publishes (each passes and updates): the slowest set-up in the suite, so it runs last of UCJEPS's tests."""
    page = signed_in(driver, base_url, UCJEPS)
    three_rows = servable_list("ucjeps-3").read_text()
    for n in range(30 - len(page.refreshes(UCJEPS))):
        assert page.admin_refresh(UCJEPS, three_rows, f"serenade T21: refresh {n + 1}")["state"] == "updated"
    every = page.refreshes(UCJEPS)
    assert len(every) == 30
    # A refresh's last change is kept to the second, so two can tie (an abandoned refresh and the admin refresh that
    # closed it): the order is checked by the times, and the oldest and newest are each the only one at their time.
    changed = {r["refresh_id"]: r["updated_at"] for r in every}
    by_change = sorted(changed, key=lambda refresh: changed[refresh])
    page.open_list(UCJEPS)
    assert page.count(page.ROWS) == 25, "25 rows a page to start"
    page.click(page.header("Last change"))  # newest first to start: one click, oldest first
    page.wait_for_text((By.XPATH, "//*[@id='refreshes-table']//tbody/tr[1]/td[1]"), by_change[0])
    page.click(page.header("Last change"))
    page.wait_for_text((By.XPATH, "//*[@id='refreshes-table']//tbody/tr[1]/td[1]"), by_change[-1])
    page.click(page.PER_PAGE)
    page.click((By.XPATH, "//div[contains(@class, 'v-overlay--active')]//div[contains(@class, 'v-list-item-title')"
                          " and normalize-space()='100']"))
    page.wait_for_count(page.ROWS, 30)
    shown = page.first_column()
    assert sorted(shown) == sorted(changed), "not all 30 on one page"
    assert [changed[refresh] for refresh in shown] == sorted(changed.values(), reverse=True), "not newest change first"
