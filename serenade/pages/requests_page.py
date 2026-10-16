"""Past requests (design: Admin web app, Past requests)."""
from __future__ import annotations

from selenium.webdriver.common.by import By

from .page import Locator, Page, by_id


class RequestsPage(Page):
    TITLE = by_id("page-title")
    LOADING = by_id("requests-loading")  # "Reading Serena's log…"
    SERVED = by_id("requests-served")
    BY_SIZE = by_id("requests-by-size")  # "by size: Small 1 · Medium 2 · …"
    UNSERVED = by_id("requests-unserved")
    BY_DAY_ROWS = (By.XPATH, "//*[@id='requests-by-day']//tbody/tr")
    TOP_ROWS = (By.XPATH, "//*[@id='requests-top-paths']//tbody/tr")
    OUTCOME = "request-outcome"  # the filters: Vuetify selects, chosen with Page.choose
    REASON = "request-reason"
    EXPORT = by_id("export-requests")
    TABLE = by_id("requests-table")
    LINES = (By.XPATH, "//*[@id='requests-table']//tbody/tr")
    # A file opened from a line (FileDialog.vue).
    FILE_DIALOG = by_id("file-dialog")
    FILE_DIALOG_PICTURE = (By.XPATH, "//*[@id='file-dialog']//div[contains(@class, 'file-dialog-picture')]//img")
    FILE_DIALOG_NONE = by_id("file-dialog-none")  # why there's no picture
    FILE_DIALOG_LOOKUP = by_id("file-dialog-lookup")
    FILE_DIALOG_DISMISS = by_id("file-dialog-dismiss")

    # The table's columns, in order (Signed link only for a museum with signed access).
    COLUMNS = ("Time", "Outcome", "Reason", "Blob CSID", "Size", "Kind", "Cache")

    @staticmethod
    def line_with(*texts: str) -> Locator:
        """A request's line holding every one of the texts (its outcome, reason, shortened Blob CSID…)."""
        has = " and ".join(f"contains(normalize-space(), '{t}')" for t in texts)
        return (By.XPATH, f"//*[@id='requests-table']//tbody/tr[{has}]")

    @staticmethod
    def line_for(path: str) -> Locator:
        """A request's line by its path as requested (the Blob CSID column's hover text)."""
        titled = f"@title='{path}' or @title='View this file: {path}'"
        return (By.XPATH, f"//*[@id='requests-table']//tbody/tr[.//*[{titled}]]")

    @staticmethod
    def range_button(title: str) -> Locator:
        return (By.XPATH, f"//*[@id='request-range']//button[normalize-space()='{title}']")

    @staticmethod
    def header(title: str) -> Locator:
        return (By.XPATH, f"//*[@id='requests-table']//thead//th[.//span[normalize-space()='{title}']]")

    @staticmethod
    def field_of(field_id: str) -> Locator:
        """A filter's whole field (whose classes say whether it's disabled)."""
        return (By.XPATH, f"//input[@id='{field_id}']/ancestor::div[contains(concat(' ', @class, ' '), ' v-input ')]"
                          "[1]")

    def cells(self, line: Locator) -> dict[str, str]:
        """A line's cells by column name."""
        tds = self.wait_for(line).find_elements(By.TAG_NAME, "td")
        return {name: td.text for name, td in zip(self.COLUMNS, tds, strict=False)}

    def column(self, name: str) -> list[str]:
        """One column's text, line by line, as the table shows them now."""
        i = self.COLUMNS.index(name) + 1
        return [td.text for td in self.driver.find_elements(By.XPATH, f"//*[@id='requests-table']//tbody/tr/td[{i}]")]

    def open_page(self, museum: str) -> None:
        """Opens the page showing 100 lines (25 to start), so a test finds its lines however many came before."""
        self.open(f"{museum}/requests?rows=100")
        self.wait_for(self.TABLE, timeout=30)
