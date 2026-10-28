"""Layout and navigation, checks T48 to T53 of the test inventory (serena-test-inventory.xlsx;
docs/testing-checklist.md sections 15, 16, 18, 20 and 21).

They only look, at PAHMA. They run after the audit tests (conftest.py's FILE_ORDER): Keeping your place needs the
serving tests' unserved lines, and the Audit log's back link needs the recall tests' Media CSID targets."""
from __future__ import annotations

import pytest
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver

from serenade.dataset import MUSEUM, UNKNOWN_PATH
from serenade.pages.audit_log_page import AuditLogPage
from serenade.pages.layout_page import LayoutPage
from serenade.pages.requests_page import RequestsPage
from serenade.pages.sign_in_page import SignInPage

pytestmark = pytest.mark.usefixtures("built_dataset")

ADMIN = ("admin", "admin")  # the simulator's synthetic account: its password is its username
# The menu's groups and their pages, in order (App.vue's NAV), by each item's route name and title.
MENU = {
    "DAILY REFRESH": [("overview", "Overview"), ("refreshes", "Past refreshes")],
    "MEDIA RECORDS": [("requests", "Past requests"), ("lookup", "Media look up"), ("recalls", "Recalls")],
    "ADMIN": [("manual-refresh", "Manual refresh"), ("audit", "Audit log"), ("api", "API documentation")],
}
# Each page's title, opened from the menu (checklist section 18).
TITLES = {
    "refreshes": "PAHMA Past refreshes", "manual-refresh": "PAHMA Manual refresh", "requests": "PAHMA Past requests",
    "lookup": "PAHMA Media look up", "recalls": "PAHMA Recalls", "audit": "PAHMA Audit log",
    "api": "PAHMA ETL API documentation",
}
# Past requests' column descriptions (Requests.vue), for the columns the help test uses.
HELP = {
    "Time": "When the request reached Serena (UTC).",
    "Reason": "Why an unserved request wasn't served. Media look up says more for any one file.",
}
# Keeping your place: Last 7 days, Unserved, sorted by Reason (checklist section 20).
PLACE = ("range=7d", "outcome=unserved", "sort=reason.asc")


def signed_in(driver: WebDriver, base_url: str) -> LayoutPage:
    SignInPage(driver, base_url).sign_in(MUSEUM.upper(), *ADMIN)
    SignInPage(driver, base_url).wait_for_url(f"/admin/{MUSEUM}")
    return LayoutPage(driver, base_url)


def test_t48_page_titles_start_with_the_museum(driver: WebDriver, base_url: str) -> None:
    """Checklist section 15, step 8; section 18. Each page opened from the menu."""
    page = signed_in(driver, base_url)
    assert page.text_of(page.OVERVIEW_TITLE) == "PAHMA"
    for name, title in TITLES.items():
        page.click(page.nav(name))
        page.wait_for_text(page.TITLE, title, timeout=20)
        assert page.text_of(page.TITLE) == title


def test_t49_the_menus_groups_the_bell_and_the_gear(driver: WebDriver, base_url: str) -> None:
    """Checklist section 18."""
    page = signed_in(driver, base_url)
    page.wait_for(page.NAV_ITEMS)
    groups = [group.text.upper() for group in driver.find_elements(*page.NAV_GROUPS)]
    assert groups == list(MENU), groups
    items = [(str(item.get_attribute("id")).removeprefix("nav-"), item.text)
             for item in driver.find_elements(*page.NAV_ITEMS)]
    assert items == [item for group in MENU.values() for item in group], items
    assert str(page.wait_for(page.BELL).get_attribute("aria-label")).startswith("Alerts")
    assert page.wait_for(page.GEAR).get_attribute("title") == "PAHMA settings"
    assert page.text_of(page.MUSEUM_MENU) == "PAHMA · admin"
    page.click(page.GEAR)
    page.wait_for_text(page.TITLE, "PAHMA Settings")


def kept_its_place(page: RequestsPage) -> None:
    """Past requests as the test left it: the address, the range, the filter and the sort."""
    page.wait_for(page.line_for(UNKNOWN_PATH), timeout=30)
    url = page.driver.current_url
    assert all(part in url for part in PLACE), url
    assert "v-btn--active" in str(page.wait_for(page.range_button("Last 7 days")).get_attribute("class"))
    assert "Unserved" in page.text_of(page.field_of(page.OUTCOME))
    assert set(page.column("Outcome")) == {"unserved"}
    reasons = page.column("Reason")
    assert reasons == sorted(reasons, key=str.lower), reasons


def open_in_look_up(page: RequestsPage) -> None:
    """Opens the unknown CSID's request (T8) from its line, then Media look up from the dialog."""
    page.click((By.XPATH, f"({page.line_for(UNKNOWN_PATH)[1]})[1]//button[contains(@class, 'file-link')]"))
    page.click(page.FILE_DIALOG_LOOKUP)
    page.wait_for_text(page.TITLE, "PAHMA Media look up")
    assert page.text_of(LayoutPage.BACK) == "← Back to Past requests"


def test_t50_keeping_your_place_on_past_requests(driver: WebDriver, base_url: str) -> None:
    """Checklist section 20 (Keeping your place): back by the link, by the browser's Back, and the address in a new
    tab. (The scroll position and the spinner stay for the checklist.)"""
    signed_in(driver, base_url)
    page = RequestsPage(driver, base_url)
    page.open(f"{MUSEUM}/requests")
    page.click(page.range_button("Last 7 days"))
    page.wait_for_address("range=7d")
    page.choose(page.OUTCOME, "Unserved")
    page.click(page.header("Reason"))
    page.wait_for_address("sort=reason.asc")
    kept_its_place(page)
    open_in_look_up(page)
    page.click((By.XPATH, "//*[@id='back-link']/a"))
    kept_its_place(page)
    open_in_look_up(page)
    driver.back()
    kept_its_place(page)
    address = driver.current_url
    first = driver.current_window_handle
    driver.switch_to.new_window("tab")
    try:
        driver.get(address)
        kept_its_place(page)
    finally:
        driver.close()
        driver.switch_to.window(first)


def test_t51_back_links_and_none_from_the_menu(driver: WebDriver, base_url: str) -> None:
    """Checklist section 20. "← Back to Alerts" from an alert's refresh ID is T24's (test_alerts.py)."""
    page = signed_in(driver, base_url)
    audit = AuditLogPage(driver, base_url)
    audit.open_page(MUSEUM)
    audit.click((By.XPATH, "(//*[@id='audit-table']//tbody//a[starts-with(@title, 'Media look up: ')])[1]"))
    page.wait_for_text(page.TITLE, "PAHMA Media look up")
    assert page.text_of(page.BACK) == "← Back to Audit log"
    page.click(page.nav("lookup"))
    page.wait_until_gone(page.BACK)
    assert driver.current_url.endswith(f"/{MUSEUM}/lookup")


def test_t52_the_overviews_links(driver: WebDriver, base_url: str) -> None:
    """Checklist section 16; section 20."""
    page = signed_in(driver, base_url)
    for text, title in (("Past requests", "PAHMA Past requests"), ("Media look up", "PAHMA Media look up")):
        page.open(MUSEUM)
        page.click(page.overview_link(text))
        page.wait_for_text(page.TITLE, title, timeout=20)


def test_t53_column_help(driver: WebDriver, base_url: str) -> None:
    """Checklist section 20; section 21. On Past requests: by the pointer, then by the keyboard."""
    signed_in(driver, base_url)
    page = RequestsPage(driver, base_url)
    page.open_page(MUSEUM)
    page.wait_for(page.LINES, timeout=30)
    layout = LayoutPage(driver, base_url)
    # The pointer: the description shows, stays while the pointer moves onto it, and closes with Esc.
    tooltip = layout.hover(layout.column_help("requests-table", "Reason"), layout.tooltip(HELP["Reason"]))
    ActionChains(driver).move_to_element(tooltip).pause(1).perform()
    assert tooltip.is_displayed(), "the description closed under the pointer"
    ActionChains(driver).send_keys(Keys.ESCAPE).perform()
    layout.wait_until_gone(layout.tooltip(HELP["Reason"]))
    # The keyboard: Tab from the page's title to the first column's name.
    ActionChains(driver).move_to_element(page.wait_for(page.TITLE)).click().perform()
    for _ in range(60):
        ActionChains(driver).send_keys(Keys.TAB).perform()
        if "column-help" in str(driver.switch_to.active_element.get_attribute("class")):
            break
    focused = driver.switch_to.active_element.text
    assert focused == "Time", f"Tab reached {focused!r} first"
    layout.wait_for(layout.tooltip(HELP["Time"]))
    ActionChains(driver).send_keys(Keys.ESCAPE).perform()
    layout.wait_until_gone(layout.tooltip(HELP["Time"]))
