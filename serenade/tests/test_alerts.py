"""Alerts for UCJEPS, checks T23 to T25 of the test inventory (serena-test-inventory.xlsx; docs/testing-checklist.md
sections 14, 18 and 20), and for BAMPFA, T84 and T85: finding the waiting alerts, and acknowledging all of them
(section 28). T26 (a recall's alert) is in the recall chain, in test_lookup_and_recalls.py; T27 and T28
(the watchdog's deadline and placeholder alerts) are covered by the backend's tests.

UCJEPS is a reserved museum: the dataset's second UCJEPS refresh fails its servable list check, and the worker raises
the alert at once. No other test uses UCJEPS, so where this file runs doesn't matter to the PAHMA tests. T25 changes
UCJEPS's alerts (acknowledged), which nothing else reads.

T84 raises two alerts on BAMPFA by changing its delta threshold and putting it back (as T32 does, later); T85
acknowledges them with Acknowledge all, and a fixture acknowledges any left if it fails, so the settings tests start
with none waiting. T87 to T89 check the rest of section 28 the same way: T87 raises 20 more (through the admin API,
for speed) and checks that All holds through sorting, paging and the browser's Back, and that the audit log's link
opens All; T88 acknowledges those 20 (the dialog's order, Cancel, a link to another page, one audit entry each); T89
raises two and acknowledges one in a second browser while the first has Acknowledge all open."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterator

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait

from serenade.dataset import UCJEPS, UCJEPS_FAILED, refresh_id
from serenade.pages.alerts_page import AlertsPage
from serenade.pages.audit_log_page import AuditLogPage
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


def test_t84_finding_the_waiting_alerts(driver: WebDriver, base_url: str) -> None:
    """Checklist section 28, steps 1 to 3 (D212 to D214). Two alerts raised by changing BAMPFA's delta threshold and
    putting it back, as T32 does; T85 acknowledges them."""
    page = bampfa_alerts(driver, base_url)
    settings = SettingsPage(driver, base_url)
    settings.open_page(BAMPFA)
    settings.change("delta_threshold_percent", "12.5", "serenade T84: a test change")
    settings.wait_for_text(settings.row("delta_threshold_percent"), "changed; default value 5")
    settings.use_default("delta_threshold_percent", "serenade T84: back to the default")
    # The banner's "Open alerts" opens Waiting.
    OverviewPage(driver, base_url).open(BAMPFA)
    page.click(page.OPEN_ALERTS)
    page.wait_for_address("show=waiting")
    page.wait_for(page.row_with("serenade T84: a test change"))
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


@pytest.mark.after("test_t84_finding_the_waiting_alerts")
@pytest.mark.usefixtures("none_waiting_after")
def test_t85_acknowledging_all_the_waiting_alerts(driver: WebDriver, base_url: str) -> None:
    """Checklist section 28, steps 4 to 6 (D207 to D211, D215 to D217)."""
    page = bampfa_alerts(driver, base_url)
    page.open_page(BAMPFA)
    page.wait_for(page.row_with("serenade T84: a test change"))
    waiting = page.count(page.ACKNOWLEDGE)
    assert page.text_of(page.ACKNOWLEDGE_ALL) == f"Acknowledge all ({waiting})"
    # It asks first, listing them; a listed alert's link shows its row, marked, acknowledging nothing.
    page.click(page.ACKNOWLEDGE_ALL)
    dialog = page.wait_for(page.ALL_DIALOG).text
    assert f"Acknowledge {waiting} alerts?" in dialog and "raises it again the next day" in dialog
    links = driver.find_elements(*page.ALL_DIALOG_LINKS)
    assert len(links) == waiting and all(link.text for link in links)
    # Each line says what it's about and when it was raised; only the list scrolls (D216, D217).
    listed = page.wait_for(page.ALL_DIALOG_LIST)
    assert "delta_threshold_percent" in listed.text and " UTC" in listed.text, listed.text
    assert listed.value_of_css_property("overflow-y") == "auto"
    links[-1].click()
    page.wait_until_gone(page.ALL_DIALOG)
    assert page.count(page.MARKED_ROW) == 1 and page.count(page.ACKNOWLEDGE) == waiting
    # Acknowledge them all.
    page.click(page.ACKNOWLEDGE_ALL)
    page.wait_for(page.ALL_DIALOG)
    page.click(page.CONFIRM_ALL)
    page.wait_for_count(page.ACKNOWLEDGE, 0)
    row = page.text_of(page.row_with("serenade T84: a test change"))
    assert f"{ADMIN[0]}, " in row and "UTC" in row, row
    page.wait_until_gone(page.BANNER)
    assert page.count(page.BADGE) == 0 and page.count(page.ACKNOWLEDGE_ALL) == 0
    page.click(page.SHOW_WAITING)
    page.wait_for_text(page.TABLE, "No alerts waiting.")


# --- the rest of section 28 (D207 to D218): All held, the audit log's link, the dialog in full, two admins at once

MANY = 10  # T87's changes, each put back: 20 alerts, more than the dialog's list shows without scrolling


def bampfa_badge(page: AlertsPage) -> str:
    page.wait_for(page.BADGE)
    return page.text_of(page.BADGE)


@pytest.mark.after("test_t85_acknowledging_all_the_waiting_alerts")
def test_t87_all_holds_and_the_audit_logs_link_opens_all(driver: WebDriver, base_url: str) -> None:
    """Checklist section 28, steps 2 and 3 (D212 to D214): All stays chosen through sorting and paging, and after
    another page the browser's Back finds it as it was; Waiting goes back to page 1, sorted and sized as before; the
    audit log's link to an alert opens All even while alerts wait. Raises the 20 alerts T88 acknowledges."""
    page = bampfa_alerts(driver, base_url)
    settings = SettingsPage(driver, base_url)
    for i in range(1, MANY + 1):
        settings.change_and_put_back(BAMPFA, "delta_threshold_percent", 12.5, f"serenade T87 #{i}")
    waiting = len(page.waiting_keys(BAMPFA))  # T87's, and the watchdog's deadline alert if it came since
    assert waiting >= 2 * MANY, f"expected {2 * MANY} alerts waiting, not {waiting}"
    total = len(page.alerts(BAMPFA))
    assert total > 2 * 10, "not enough alerts for three pages of 10"
    # All, sorted by Acknowledged and 10 to a page, then page 2: still All, with nothing about it in the address.
    page.open_page(BAMPFA)
    page.wait_for_count(page.WAITING_ROWS, waiting)
    assert page.showing() == "All"
    page.click(page.header("Acknowledged"))
    page.wait_for_address("sort=acknowledged_at")
    page.per_page(10)
    page.wait_for_count(page.ROWS, 10)
    page.click(page.NEXT_PAGE)
    page.wait_for_address("page=2")
    assert page.showing() == "All" and "show=" not in driver.current_url
    all_page_2 = driver.current_url.split("/admin/", 1)[1]
    # Another page, then the browser's Back: All again, as it was (All and Waiting, like sorting and paging, change
    # the address in place, so Back right after one leaves Alerts).
    page.click(OverviewPage.AUDIT)
    page.wait_for_url(f"/{BAMPFA}/audit")
    driver.back()
    page.wait_for_url(all_page_2)
    page.wait_for_count(page.ROWS, 10)
    assert page.showing() == "All", "Back didn't find All"
    # Waiting: back to page 1, only the waiting ones, sorted and sized as before.
    page.click(page.SHOW_WAITING)
    page.wait_for_address("show=waiting")
    assert "page=" not in driver.current_url and "sort=acknowledged_at" in driver.current_url, driver.current_url
    assert page.showing() == f"Waiting ({waiting})"
    page.wait_for_count(page.ROWS, 10)
    assert page.count(page.WAITING_ROWS) == 10
    # The audit log's link to an alert, with the Alerts page left on Waiting: Alerts opens on All.
    audit = AuditLogPage(driver, base_url)
    audit.click(OverviewPage.AUDIT)
    audit.wait_for(audit.ROWS)
    audit.click(audit.ALERT_TARGET)
    page.wait_for_url(f"/{BAMPFA}/alerts")
    page.wait_for(page.TABLE)
    assert page.showing() == "All" and bampfa_badge(page) == str(waiting)


@pytest.mark.after("test_t87_all_holds_and_the_audit_logs_link_opens_all")
@pytest.mark.usefixtures("none_waiting_after")
def test_t88_acknowledge_all_in_full(driver: WebDriver, base_url: str) -> None:
    """Checklist section 28, steps 4 to 6 (D207 to D211, D215, D216): T87's 20 alerts. The dialog lists them newest
    first and asks for no reason; Cancel changes nothing; in a short window only the list scrolls; a listed alert's
    link opens the table's page that holds it; acknowledging them makes one audit entry for each. The banner has no
    Acknowledge all of its own."""
    page = bampfa_alerts(driver, base_url)
    audit = AuditLogPage(driver, base_url)
    n = len(page.waiting_keys(BAMPFA))  # T87's 20, and the watchdog's deadline alert if it came since
    page.open_page(BAMPFA)  # newest first, 25 to a page: every alert on page 1
    page.wait_for_count(page.WAITING_ROWS, n)
    newest_first = page.row_keys(page.WAITING_ROWS)
    banner = page.wait_for(page.BANNER)
    assert "Acknowledge all" not in banner.text, "the banner has an Acknowledge all (D211)"
    # It asks first: every waiting alert, newest first, and no reason.
    page.open_acknowledge_all()
    assert page.text_of(page.ALL_DIALOG_TITLE) == f"Acknowledge {n} alerts?"
    assert page.listed_keys() == newest_first, "the dialog doesn't list the waiting alerts, newest first"
    assert page.count(page.ALL_DIALOG_FIELDS) == 0, "the dialog asks for something (D209: no reason)"
    assert page.text_of(page.CONFIRM_ALL) == f"Acknowledge {n}"
    # Cancel: nothing changes.
    page.click(page.CANCEL_ALL)
    page.wait_until_gone(page.ALL_DIALOG)
    assert page.count(page.WAITING_ROWS) == n and bampfa_badge(page) == str(n)
    # A short window: only the list scrolls; the title, the reminder and the buttons stay in view (D216).
    size = driver.get_window_size()
    driver.set_window_size(size["width"], 650)
    try:
        page.open_acknowledge_all()
        listed = page.wait_for(page.ALL_DIALOG_LIST)
        assert driver.execute_script("return arguments[0].scrollHeight > arguments[0].clientHeight", listed), \
            "the list fits: no scrolling to check"
        for part in (page.ALL_DIALOG_TITLE, page.CONFIRM_ALL, page.CANCEL_ALL):
            assert page.in_view(page.wait_for(part)), f"{part[1]} is out of view"
        assert "raises it again the next day" in page.text_of(page.ALL_DIALOG)
        page.click(page.CANCEL_ALL)
        page.wait_until_gone(page.ALL_DIALOG)
    finally:
        driver.set_window_size(size["width"], size["height"])
    # A listed alert is a link (D215): oldest first, 10 to a page, the newest is on the last page.
    page.click(page.header("Raised"))
    page.wait_for_address("sort=created_at.asc")
    page.per_page(10)
    total = len(page.alerts(BAMPFA))
    last_page = (total + 9) // 10
    page.open_acknowledge_all()
    driver.find_elements(*page.ALL_DIALOG_LINKS)[0].click()
    page.wait_until_gone(page.ALL_DIALOG)
    page.wait_for_address(f"page={last_page}")
    page.wait_for(page.MARKED_ROW)
    assert page.row_keys(page.MARKED_ROW) == [newest_first[0]], "the marked row isn't the newest alert"
    assert page.in_view(page.wait_for(page.MARKED_ROW)), "the marked row is out of view"
    assert bampfa_badge(page) == str(n), "the link acknowledged something"
    # Acknowledge them: every one, by admin, and one audit entry for each.
    before = audit.acknowledged(BAMPFA)
    page.open_acknowledge_all()
    page.click(page.CONFIRM_ALL)
    page.wait_until_gone(page.ALL_DIALOG)
    page.wait_until_gone(page.BANNER)
    assert page.count(page.BADGE) == 0 and page.count(page.ACKNOWLEDGE_ALL) == 0
    acknowledged = {a["key"]: a["acknowledged_by"] for a in page.alerts(BAMPFA) if a["key"] in newest_first}
    assert acknowledged == {key: ADMIN[0] for key in newest_first}, acknowledged
    added = Counter(audit.acknowledged(BAMPFA)) - Counter(before)
    assert added == Counter(newest_first), "not one audit entry for each alert"
    page.click(page.SHOW_WAITING)
    page.wait_for_text(page.TABLE, "No alerts waiting.")


@pytest.mark.after("test_t88_acknowledge_all_in_full")
@pytest.mark.usefixtures("none_waiting_after")
def test_t89_one_acknowledged_meanwhile_is_skipped(driver: WebDriver, second_driver: WebDriver,
                                                    base_url: str) -> None:
    """Checklist section 28, steps 4 and 7 (D207, D210): two alerts wait; while Acknowledge all's dialog is open in
    one browser, a second acknowledges one of them with its row's button, which leaves one waiting and so no Acknowledge
    all there. Acknowledge 2 then gives no error, and each alert has one audit entry, not two."""
    page = bampfa_alerts(driver, base_url)
    SettingsPage(driver, base_url).change_and_put_back(BAMPFA, "delta_threshold_percent", 12.5, "serenade T89")
    keys = page.waiting_keys(BAMPFA)
    assert len(keys) == 2, keys
    audit = AuditLogPage(driver, base_url)
    before = audit.acknowledged(BAMPFA)
    page.open_page(BAMPFA)
    page.open_acknowledge_all()
    assert page.text_of(page.CONFIRM_ALL) == "Acknowledge 2"
    # Meanwhile, another browser acknowledges one: one waiting there, so no Acknowledge all (its row's button does it).
    other = bampfa_alerts(second_driver, base_url)
    other.open_page(BAMPFA, waiting=True)
    other.wait_for_count(other.ACKNOWLEDGE, 2)
    other.click(other.ACKNOWLEDGE)
    other.wait_for_count(other.ACKNOWLEDGE, 1)
    assert other.count(other.ACKNOWLEDGE_ALL) == 0, "Acknowledge all with only one waiting"
    # Back in the first: Acknowledge 2, and no error.
    page.click(page.CONFIRM_ALL)
    page.wait_until_gone(page.ALL_DIALOG)
    page.wait_until_gone(page.BANNER)
    assert page.count(page.ERROR) == 0, page.text_of(page.ERROR)
    assert not page.waiting_keys(BAMPFA)
    added = Counter(audit.acknowledged(BAMPFA)) - Counter(before)
    assert added == Counter(keys), f"not one audit entry for each alert: {added}"
