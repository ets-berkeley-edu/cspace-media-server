"""Alerts for UCJEPS, checks T23 to T25 of the test inventory (serena-test-inventory.xlsx; docs/testing-checklist.md
sections 14, 18 and 20), and for BAMPFA, T82 and T83: finding the waiting alerts, and acknowledging all of them
(section 28). T26 (a recall's alert) is in the recall chain, in test_lookup_and_recalls.py; T27 and T28
(the watchdog's deadline and placeholder alerts) are covered by the backend's tests.

UCJEPS is a reserved museum: the dataset's second UCJEPS refresh fails its servable list check, and the worker raises
the alert at once. No other test uses UCJEPS, so where this file runs doesn't matter to the PAHMA tests. T25 changes
UCJEPS's alerts (acknowledged), which nothing else reads.

T82 raises two alerts on BAMPFA by changing its delta threshold and putting it back (as T32 does, later); T83
acknowledges them with Acknowledge all, and a fixture acknowledges any left if it fails, so the settings tests start
with none waiting."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait

from serenade.dataset import UCJEPS, UCJEPS_FAILED, refresh_id
from serenade.pages.alerts_page import AlertsPage
from serenade.pages.overview_page import OverviewPage
from serenade.pages.settings_page import SettingsPage
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


# --- finding the waiting alerts, and acknowledging all of them (D207 to D215), on BAMPFA

BAMPFA = "bampfa"


def bampfa_alerts(driver: WebDriver, base_url: str) -> AlertsPage:
    SignInPage(driver, base_url).sign_in("BAMPFA", *ADMIN)
    SignInPage(driver, base_url).wait_for_url(f"/admin/{BAMPFA}")
    return AlertsPage(driver, base_url)


@pytest.fixture
def none_waiting_after(driver: WebDriver, base_url: str) -> Iterator[None]:
    """BAMPFA's alerts are all acknowledged afterwards, whatever happened, so the settings tests start with none."""
    yield
    page = AlertsPage(driver, base_url)
    page.open_page(BAMPFA)
    while (waiting := page.count(page.ACKNOWLEDGE)) > 0:
        page.click(page.ACKNOWLEDGE)
        page.wait_for_count(page.ACKNOWLEDGE, waiting - 1)


def test_t82_finding_the_waiting_alerts(driver: WebDriver, base_url: str) -> None:
    """Checklist section 28, steps 1 to 3 (D212 to D214). Two alerts raised by changing BAMPFA's delta threshold and
    putting it back, as T32 does; T83 acknowledges them."""
    page = bampfa_alerts(driver, base_url)
    settings = SettingsPage(driver, base_url)
    settings.open_page(BAMPFA)
    settings.change("delta_threshold_percent", "12.5", "serenade T82: a test change")
    settings.wait_for_text(settings.row("delta_threshold_percent"), "changed; default value 5")
    settings.use_default("delta_threshold_percent", "serenade T82: back to the default")
    # The banner's "Open alerts" opens Waiting.
    OverviewPage(driver, base_url).open(BAMPFA)
    page.click(page.OPEN_ALERTS)
    page.wait_for_address("show=waiting")
    page.wait_for(page.row_with("serenade T82: a test change"))
    waiting = page.count(page.ACKNOWLEDGE)
    assert waiting >= 2
    assert page.showing() == f"Waiting ({waiting})"
    assert page.count(page.ROWS) == waiting == page.count(page.WAITING_ROWS), "Waiting shows more than the waiting ones"
    # All: the history, the waiting rows marked with their bar; All is left out of the address.
    page.click(page.SHOW_ALL)
    WebDriverWait(driver, 10).until(lambda d: "show=" not in d.current_url)
    assert page.showing() == "All"
    assert page.count(page.WAITING_ROWS) == waiting
    # The bell opens Waiting too.
    OverviewPage(driver, base_url).open(BAMPFA)
    page.click(page.BELL)
    page.wait_for_address("show=waiting")
    assert page.showing() == f"Waiting ({waiting})"


@pytest.mark.after("test_t82_finding_the_waiting_alerts")
@pytest.mark.usefixtures("none_waiting_after")
def test_t83_acknowledging_all_the_waiting_alerts(driver: WebDriver, base_url: str) -> None:
    """Checklist section 28, steps 4 to 6 (D207 to D211, D215)."""
    page = bampfa_alerts(driver, base_url)
    page.open_page(BAMPFA)
    page.wait_for(page.row_with("serenade T82: a test change"))
    waiting = page.count(page.ACKNOWLEDGE)
    assert page.text_of(page.ACKNOWLEDGE_ALL) == f"Acknowledge all ({waiting})"
    # It asks first, listing them; a listed alert's link shows its row, marked, acknowledging nothing.
    page.click(page.ACKNOWLEDGE_ALL)
    dialog = page.wait_for(page.ALL_DIALOG).text
    assert f"Acknowledge {waiting} alerts?" in dialog and "raises it again the next day" in dialog
    links = driver.find_elements(*page.ALL_DIALOG_LINKS)
    assert len(links) == waiting and all(link.text for link in links)
    links[-1].click()
    page.wait_until_gone(page.ALL_DIALOG)
    assert page.count(page.MARKED_ROW) == 1 and page.count(page.ACKNOWLEDGE) == waiting
    # Acknowledge them all.
    page.click(page.ACKNOWLEDGE_ALL)
    page.wait_for(page.ALL_DIALOG)
    page.click(page.CONFIRM_ALL)
    page.wait_for_count(page.ACKNOWLEDGE, 0)
    row = page.text_of(page.row_with("serenade T82: a test change"))
    assert f"{ADMIN[0]}, " in row and "UTC" in row, row
    page.wait_until_gone(page.BANNER)
    assert page.count(page.BADGE) == 0 and page.count(page.ACKNOWLEDGE_ALL) == 0
    page.click(page.SHOW_WAITING)
    page.wait_for_text(page.TABLE, "No alerts waiting.")
