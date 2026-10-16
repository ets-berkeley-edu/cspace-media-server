"""Alerts for UCJEPS, checks T23 to T25 of the test inventory (serena-test-inventory.xlsx; docs/testing-checklist.md
sections 14, 18 and 20). T26 (a recall's alert) is in the recall chain, in test_lookup_and_recalls.py; T27 and T28
(the watchdog's deadline and placeholder alerts) are covered by the backend's tests.

UCJEPS is a reserved museum: the dataset's second UCJEPS refresh fails its servable list check, and the worker raises
the alert at once. No other test uses UCJEPS, so where this file runs doesn't matter to the PAHMA tests. T25 changes
UCJEPS's alerts (acknowledged), which nothing else reads."""
from __future__ import annotations

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from serenade.dataset import UCJEPS, UCJEPS_FAILED, refresh_id
from serenade.pages.alerts_page import AlertsPage
from serenade.pages.sign_in_page import SignInPage

pytestmark = pytest.mark.usefixtures("built_dataset")

ADMIN = ("admin", "admin")  # the simulator's synthetic account: its password is its username
CHECK_FAILED = "A servable list check failed"


def alerts_page(driver: WebDriver, base_url: str) -> AlertsPage:
    SignInPage(driver, base_url).sign_in("UCJEPS", *ADMIN)
    SignInPage(driver, base_url).wait_for_url(f"/admin/{UCJEPS}")
    page = AlertsPage(driver, base_url)
    page.open_page(UCJEPS)
    return page


def test_t23_a_failed_check_raises_an_alert_on_the_bell_and_the_banner(driver: WebDriver, base_url: str) -> None:
    """Checklist section 14, step 2; section 18."""
    page = alerts_page(driver, base_url)
    failed = refresh_id(UCJEPS_FAILED)
    row = page.wait_for(page.row_with(failed)).text
    assert CHECK_FAILED in row and "Acknowledge" in row
    page.wait_for(page.BANNER)
    waiting = page.count(page.ACKNOWLEDGE)
    # The banner names the newest unacknowledged alert: the failed check, unless the watchdog raised one since.
    assert page.text_of(page.BANNER).startswith(f"{waiting} alert")
    assert page.text_of(page.BADGE) == str(waiting), "the bell's badge doesn't count the unacknowledged alerts"


def test_t24_the_alerts_text_in_words_with_its_refresh_id_as_a_link(driver: WebDriver, base_url: str) -> None:
    """Checklist section 20."""
    page = alerts_page(driver, base_url)
    failed = refresh_id(UCJEPS_FAILED)
    row = page.wait_for(page.row_with(failed)).text
    assert f"Refresh {failed} failed its servable list check: " in row
    assert "check_failed" not in row
    page.click((By.XPATH, f"{page.row_with(failed)[1]}//div[contains(@class, 'alert-message')]"
                          f"//a[normalize-space()='{failed}']"))
    page.wait_for_address(f"/{UCJEPS}/refreshes/{failed}")
    assert page.text_of(page.BACK) == "← Back to Alerts"


@pytest.mark.after("test_t23_a_failed_check_raises_an_alert_on_the_bell_and_the_banner")
def test_t25_acknowledging_alerts(driver: WebDriver, base_url: str) -> None:
    """Checklist section 14, step 4; section 18. UCJEPS's own alerts only, one by one: the watchdog's deadline alert
    (after 08:00 Pacific) may be among them."""
    page = alerts_page(driver, base_url)
    page.wait_for(page.row_with(refresh_id(UCJEPS_FAILED)))
    while (waiting := page.count(page.ACKNOWLEDGE)) > 0:
        page.click(page.ACKNOWLEDGE)
        page.wait_for_count(page.ACKNOWLEDGE, waiting - 1)
    row = page.text_of(page.row_with(refresh_id(UCJEPS_FAILED)))
    assert f"{ADMIN[0]}, " in row and "UTC" in row, f"the acknowledgement doesn't show the admin and the time: {row}"
    page.wait_until_gone(page.BANNER)
    assert page.count(page.BADGE) == 0
