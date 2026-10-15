"""Recalls (design: Recalls; Admin web app)."""
from __future__ import annotations

from selenium.webdriver.common.by import By

from .page import Locator, Page, by_id


class RecallsPage(Page):
    RECALL = by_id("recall")
    CSIDS = by_id("recall-csids")
    PREVIEW = by_id("recall-summarize")
    SUMMARY = by_id("recall-summary")
    REASON = by_id("recall-reason")
    CONFIRM = by_id("recall-confirm")
    ACTIVE = by_id("active-recalls")
    ENDED = by_id("ended-recalls")
    CANCEL_REASON = by_id("cancel-reason")
    CANCEL_CONFIRM = by_id("cancel-confirm")

    @staticmethod
    def row_with(table_id: str, text: str) -> Locator:
        """A table row holding the text: a recall is found by its reason, which each test makes unique."""
        return (By.XPATH, f"//*[@id='{table_id}']//tr[td[contains(normalize-space(), '{text}')]]")

    def recall(self, museum: str, csid: str, reason: str) -> None:
        self.open(f"{museum}/recalls")
        self.click(self.RECALL)
        self.type(self.CSIDS, csid)
        self.click(self.PREVIEW)
        self.wait_for(self.SUMMARY)
        self.type(self.REASON, reason)
        self.click(self.CONFIRM)

    def cancel(self, museum: str, recall_reason: str, reason: str) -> None:
        self.open(f"{museum}/recalls")
        row = self.row_with("active-recalls", recall_reason)
        self.click((By.XPATH, row[1] + "//button[contains(@class, 'cancel-recall')]"))
        self.type(self.CANCEL_REASON, reason)
        self.click(self.CANCEL_CONFIRM)
