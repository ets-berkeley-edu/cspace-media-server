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

    @staticmethod
    def row_with(text: str) -> Locator:
        """An alert's row holding the text (its message, or its refresh ID)."""
        return (By.XPATH, f"//*[@id='alerts-table']//tbody/tr[contains(normalize-space(), '{text}')]")

    def open_page(self, museum: str) -> None:
        self.open(f"{museum}/alerts")
        self.wait_for(self.TABLE)
