"""Alerts, and the app bar's bell and the banner that every page shows (design: Watchdog and alerts; Admin web app)."""
from __future__ import annotations

from selenium.webdriver.common.by import By

from .page import Locator, Page, by_id


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
    ALL_DIALOG_LINKS = (By.XPATH, "//*[@id='acknowledge-all-dialog']//a[contains(@class, 'alert-jump')]")
    CONFIRM_ALL = by_id("confirm-acknowledge-all")

    @staticmethod
    def row_with(text: str) -> Locator:
        """An alert's row holding the text (its message, or its refresh ID)."""
        return (By.XPATH, f"//*[@id='alerts-table']//tbody/tr[contains(normalize-space(), '{text}')]")

    def open_page(self, museum: str, waiting: bool = False) -> None:
        self.open(f"{museum}/alerts" + ("?show=waiting" if waiting else ""))
        self.wait_for(self.TABLE)

    def showing(self) -> str:
        """Which of All · Waiting is chosen: "All" or "Waiting (<n>)"."""
        return self.text_of((By.XPATH, "//*[@id='alerts-show']//button[contains(@class, 'v-btn--active')]"))
