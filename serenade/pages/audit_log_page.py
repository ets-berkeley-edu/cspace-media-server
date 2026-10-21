"""Audit log (design: Admin web app, Audit log)."""
from __future__ import annotations

import json
from typing import Any

from selenium.webdriver.common.by import By

from .page import Locator, Page, by_id


class AuditLogPage(Page):
    TITLE = by_id("page-title")
    TABLE = by_id("audit-table")
    ROWS = (By.XPATH, "//*[@id='audit-table']//tbody/tr[contains(@class, 'v-data-table__tr')]")  # not "Loading"
    EXPORT = by_id("export-audit")
    # An "alert acknowledge" entry's target: a link to Alerts while the alert is listed there (30 days).
    ALERT_TARGET = (By.XPATH, "//*[@id='audit-table']//tbody/tr[td[3][normalize-space()='alert acknowledge']]"
                              "//span[contains(@class, 'audit-target')]//a")

    COLUMNS = ("When (UTC)", "By", "Action", "Target", "Details")

    @staticmethod
    def entry(action: str, text: str) -> Locator:
        """An entry by its action as the page shows it ("recall", "recall cancel") and a text in it (a reason)."""
        return (By.XPATH, f"//*[@id='audit-table']//tbody/tr[td[normalize-space()='{action}'] and "
                          f"contains(normalize-space(), '{text}')]")

    @staticmethod
    def entries_by(by: str, action: str) -> Locator:
        """The entries one actor made with one action ("ETL (ucjeps)", "etl refresh start")."""
        return (By.XPATH, f"//*[@id='audit-table']//tbody/tr[td[2][normalize-space()='{by}'] and "
                          f"td[3][normalize-space()='{action}']]")

    def open_page(self, museum: str) -> None:
        """Opens the page showing 100 entries (25 to start), so a test finds its entries however many came before."""
        self.open(f"{museum}/audit?rows=100")
        self.wait_for(self.ROWS)

    def cells(self, row: Locator) -> dict[str, str]:
        tds = self.wait_for(row).find_elements(By.TAG_NAME, "td")
        return {name: td.text for name, td in zip(self.COLUMNS, tds, strict=False)}

    def column(self, name: str) -> list[str]:
        i = self.COLUMNS.index(name) + 1
        return [td.text for td in self.driver.find_elements(
            By.XPATH, f"//*[@id='audit-table']//tbody/tr[contains(@class, 'v-data-table__tr')]/td[{i}]")]

    def entries(self, museum: str) -> list[dict[str, Any]]:
        """The museum's audit entries, through the admin API with the browser's session (every one, not a page's)."""
        status, text = self.call_api("GET", f"/admin/v1/museums/{museum}/audit")
        if status != 200:
            raise AssertionError(f"The admin API answered {status}, not 200: {text[:300]}")
        found: list[dict[str, Any]] = json.loads(text)["entries"]
        return found

    def acknowledged(self, museum: str) -> list[str]:
        """The alert keys the "alert acknowledge" entries name, one per entry."""
        return [e["target"] for e in self.entries(museum) if e["action"] == "alert_acknowledge"]
