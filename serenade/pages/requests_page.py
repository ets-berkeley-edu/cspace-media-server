"""Past requests (design: Admin web app, Past requests)."""
from __future__ import annotations

from selenium.webdriver.common.by import By

from .page import Locator, Page, by_id


class RequestsPage(Page):
    TABLE = by_id("requests-table")

    @staticmethod
    def line_with(*texts: str) -> Locator:
        """A request's line holding every one of the texts (its outcome, reason, shortened Blob CSID…)."""
        has = " and ".join(f"contains(normalize-space(), '{t}')" for t in texts)
        return (By.XPATH, f"//*[@id='requests-table']//tbody/tr[{has}]")
