"""Audit log (design: Admin web app, Audit log)."""
from __future__ import annotations

from selenium.webdriver.common.by import By

from .page import Locator, Page, by_id


class AuditLogPage(Page):
    TITLE = by_id("page-title")
    TABLE = by_id("audit-table")
    ROWS = (By.XPATH, "//*[@id='audit-table']//tbody/tr[contains(@class, 'v-data-table__tr')]")  # not "Loading"
    EXPORT = by_id("export-audit")

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
