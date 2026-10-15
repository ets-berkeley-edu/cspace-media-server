"""Audit log (design: Admin web app, Audit log)."""
from __future__ import annotations

from selenium.webdriver.common.by import By

from .page import Locator, Page, by_id


class AuditLogPage(Page):
    TABLE = by_id("audit-table")

    @staticmethod
    def entry(action: str, text: str) -> Locator:
        """An entry by its action as the page shows it ("recall", "recall cancel") and a text in it (a reason)."""
        return (By.XPATH, f"//*[@id='audit-table']//tbody/tr[td[normalize-space()='{action}'] and "
                          f"contains(normalize-space(), '{text}')]")
