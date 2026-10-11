from __future__ import annotations

from selenium.webdriver.common.by import By

from .page import Page, by_id


class OverviewPage(Page):
    TITLE = by_id("overview-title")
    MUSEUM_MENU = by_id("museum-menu")
    SIGN_OUT = by_id("sign-out")
    AUDIT = by_id("nav-audit")
    AUDIT_TABLE = by_id("audit-table")
    # The audit log's rows arrive after the page opens: wait for one, by its action.
    SIGN_IN_ROW = (By.XPATH, "//*[@id='audit-table']//td[normalize-space()='sign in']")

    def sign_out(self) -> None:
        self.click(self.SIGN_OUT)
