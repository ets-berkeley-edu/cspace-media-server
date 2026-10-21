"""Alerts, and the app bar's bell and the banner that every page shows (design: Watchdog and alerts; Admin web app)."""
from __future__ import annotations

import json
from typing import Any

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement

from .page import DIALOG, Locator, Page, by_id

API = "/admin/v1/museums"


class AlertsPage(Page):
    TABLE = by_id("alerts-table")
    ROWS = (By.XPATH, "//*[@id='alerts-table']//tbody/tr")
    ACKNOWLEDGE = (By.XPATH, "//*[@id='alerts-table']//tbody/tr//button[normalize-space()='Acknowledge']")
    # On every page, while an alert waits to be acknowledged (App.vue, AlertBanner.vue).
    BANNER = by_id("alert-banner")
    BANNER_TITLE = by_id("alert-banner-title")
    BADGE = (By.XPATH, "//*[@id='alerts-badge']//span[contains(@class, 'v-badge__badge')]")
    BACK = by_id("back-link")  # "← Back to Alerts" on the page an alert's link opens
    BELL = by_id("alerts-bell")
    OPEN_ALERTS = by_id("open-alerts")  # the banner's button
    # All · Waiting (D212), the waiting rows' bar (D214), and Acknowledge all with its dialog (D207 to D211, D215).
    SHOW_ALL = by_id("alerts-show-all")
    SHOW_WAITING = by_id("alerts-show-waiting")
    WAITING_ROWS = (By.XPATH, "//*[@id='alerts-table']//tbody/tr[contains(concat(' ', @class, ' '), ' waiting ')]")
    MARKED_ROW = (By.XPATH, "//*[@id='alerts-table']//tbody/tr[contains(concat(' ', @class, ' '), ' marked ')]")
    ACKNOWLEDGE_ALL = by_id("acknowledge-all")
    ALL_DIALOG = by_id("acknowledge-all-dialog")
    ALL_DIALOG_LIST = by_id("acknowledge-all-list")
    ALL_DIALOG_LINKS = (By.XPATH, "//*[@id='acknowledge-all-dialog']//a[contains(@class, 'alert-jump')]")
    CONFIRM_ALL = by_id("confirm-acknowledge-all")
    ALL_DIALOG_TITLE = (By.XPATH, "//*[@id='acknowledge-all-dialog']//div[contains(@class, 'v-card-title')]")
    ALL_DIALOG_FIELDS = (By.XPATH, f"{DIALOG}//input | {DIALOG}//textarea")  # none: it asks for no reason (D209)
    CANCEL_ALL = (By.XPATH, "//*[@id='acknowledge-all-dialog']//button[normalize-space()='Cancel']")
    # The table's footer: its page size, and the next page.
    PER_PAGE = (By.XPATH, "//*[@id='alerts-table']//div[contains(@class, 'v-data-table-footer__items-per-page')]"
                          "//div[contains(concat(' ', normalize-space(@class), ' '), ' v-field ')]")
    NEXT_PAGE = (By.XPATH, "//*[@id='alerts-table']//div[contains(@class, 'v-data-table-footer__pagination')]"
                           "//button[@aria-label='Next page']")
    ERROR = by_id("load-error")  # a call Serena refused

    @staticmethod
    def row_with(text: str) -> Locator:
        """An alert's row holding the text (its message, or its refresh ID)."""
        return (By.XPATH, f"//*[@id='alerts-table']//tbody/tr[contains(normalize-space(), '{text}')]")

    @staticmethod
    def header(title: str) -> Locator:
        """A column's header, to sort by it ("Raised", "Acknowledged")."""
        return (By.XPATH, f"//*[@id='alerts-table']//thead//th[.//span[normalize-space()='{title}']]")

    def open_page(self, museum: str, waiting: bool = False) -> None:
        self.open(f"{museum}/alerts" + ("?show=waiting" if waiting else ""))
        self.wait_for(self.TABLE)

    def showing(self) -> str:
        """Which of All · Waiting is chosen: "All" or "Waiting (<n>)"."""
        return self.text_of((By.XPATH, "//*[@id='alerts-show']//button[contains(@class, 'v-btn--active')]"))

    def per_page(self, n: int) -> None:
        """Chooses the table's "Items per page"."""
        self.click(self.PER_PAGE)
        self.click((By.XPATH, "//div[contains(@class, 'v-overlay--active')]//div[contains(@class, 'v-list-item-title')"
                              f" and normalize-space()='{n}']"))
        self.wait_for_address(f"rows={n}")

    def open_acknowledge_all(self) -> None:
        self.click(self.ACKNOWLEDGE_ALL)
        self.wait_for(self.ALL_DIALOG)

    def row_keys(self, locator: Locator) -> list[str]:
        """The alert keys of the rows the locator finds, in the table's order (each row's id is "alert-<key>")."""
        return [str(row.get_attribute("id")).removeprefix("alert-") for row in self.driver.find_elements(*locator)]

    def listed_keys(self) -> list[str]:
        """The alert keys Acknowledge all's dialog lists, in its order (each link's address is "#alert-<key>")."""
        return [str(link.get_attribute("href")).split("#alert-", 1)[1]
                for link in self.driver.find_elements(*self.ALL_DIALOG_LINKS)]

    def in_view(self, element: WebElement) -> bool:
        """Whether the whole element is inside the browser's window (not scrolled or cut off)."""
        return bool(self.driver.execute_script(
            "const r = arguments[0].getBoundingClientRect();"
            "return r.height > 0 && r.top >= 0 && r.bottom <= window.innerHeight", element))

    # The admin API, with the browser's session: what Serena holds, beside what the page shows.

    def alerts(self, museum: str) -> list[dict[str, Any]]:
        status, text = self.call_api("GET", f"{API}/{museum}/alerts")
        if status != 200:
            raise AssertionError(f"The admin API answered {status}, not 200: {text[:300]}")
        found: list[dict[str, Any]] = json.loads(text)["alerts"]
        return found

    def waiting_keys(self, museum: str) -> list[str]:
        return [a["key"] for a in self.alerts(museum) if not a["acknowledged_at"]]
