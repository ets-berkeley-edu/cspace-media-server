"""Recalls (design: Recalls; Admin web app)."""
from __future__ import annotations

from selenium.webdriver.common.by import By

from .page import DIALOG, Locator, Page, by_id, dialog_button, messages_of


class RecallsPage(Page):
    RECALL = by_id("recall")
    ACTIVE = by_id("active-recalls")
    ENDED = by_id("ended-recalls")
    # The recall form: CSIDs, paths or URLs in the box or a text file, then the preview (the summary).
    CSIDS = by_id("recall-csids")
    FILE = by_id("recall-file")
    PREVIEW = by_id("recall-summarize")
    FORM_ERROR = (By.XPATH, f"{DIALOG}//div[contains(@class, 'v-alert')]")
    SUMMARY = by_id("recall-summary")
    SUMMARY_ROWS = (By.XPATH, "//*[@id='recall-summary']//tbody/tr")
    THUMBNAILS = (By.XPATH, "//*[@id='recall-summary']//img[contains(@class, 'thumbnail')]")
    NOT_RECALLED = by_id("recall-not-found")
    NOT_RECALLED_LINES = (By.XPATH, "//*[@id='recall-not-found']/li")
    CHANGE = by_id("recall-change")
    REASON = by_id("recall-reason")
    REASON_MESSAGES = messages_of("recall-reason")
    CONFIRM = by_id("recall-confirm")
    FORM_CANCEL = dialog_button("Cancel")
    # Cancelling a recall.
    CANCEL_REASON = by_id("cancel-reason")
    CANCEL_REASON_MESSAGES = messages_of("cancel-reason")
    CANCEL_CONFIRM = by_id("cancel-confirm")
    KEEP = dialog_button("Keep the recall")
    # A file shown from an opened row (FileDialog.vue).
    FILE_DIALOG = by_id("file-dialog")
    FILE_DIALOG_PICTURE = (By.XPATH, "//*[@id='file-dialog']//div[contains(@class, 'file-dialog-picture')]//img")
    FILE_DIALOG_LOOKUP = by_id("file-dialog-lookup")
    FILE_DIALOG_DISMISS = by_id("file-dialog-dismiss")

    @staticmethod
    def row_with(table_id: str, text: str) -> Locator:
        """A table row holding the text: a recall is found by its reason, which each test makes unique."""
        return (By.XPATH, f"//*[@id='{table_id}']//tr[td[contains(normalize-space(), '{text}')]]")

    @classmethod
    def details_of(cls, table_id: str, text: str) -> Locator:
        """The opened row under a recall's row (▸): its CSIDs, each with View file, and Media look up."""
        row = cls.row_with(table_id, text)[1]
        return (By.XPATH, f"{row}/following-sibling::tr[1][contains(@class, 'row-details')]")

    @staticmethod
    def summary_row(text: str) -> Locator:
        """A row of the preview holding the text (a whole CSID counts, though the row shows it shortened)."""
        return (By.XPATH, f"//*[@id='recall-summary']//tbody/tr[contains(., '{text}')]")

    @staticmethod
    def view_file(what: str, csid: str) -> Locator:
        """An opened row's View file after a CSID; what is "Media CSID" or "Blob CSID"."""
        return (By.XPATH, f"//button[@aria-label='View file: {what} {csid}']")

    def open_form(self, museum: str) -> None:
        self.open(f"{museum}/recalls")
        self.click(self.RECALL)
        self.wait_for(self.CSIDS)

    def preview(self, museum: str, csids: str) -> None:
        """Opens the form, gives the CSIDs and previews the recall; nothing is recalled yet."""
        self.open_form(museum)
        self.type(self.CSIDS, csids)
        self.click(self.PREVIEW)
        self.wait_for(self.SUMMARY)

    def close_form(self) -> None:
        self.click(self.FORM_CANCEL)
        self.wait_until_gone(self.FORM_CANCEL)

    def recall(self, museum: str, csid: str, reason: str) -> None:
        self.preview(museum, csid)
        self.type(self.REASON, reason)
        self.click(self.CONFIRM)

    def open_row(self, table_id: str, text: str) -> None:
        self.click((By.XPATH, self.row_with(table_id, text)[1] + "//button[contains(@class, 'row-expand')]"))
        self.wait_for(self.details_of(table_id, text))

    def open_cancel(self, museum: str, recall_reason: str) -> None:
        """Opens Cancel recall… for the active recall with that reason."""
        self.open(f"{museum}/recalls")
        row = self.row_with("active-recalls", recall_reason)
        self.click((By.XPATH, row[1] + "//button[contains(@class, 'cancel-recall')]"))
        self.wait_for(self.CANCEL_REASON)

    def cancel(self, museum: str, recall_reason: str, reason: str) -> None:
        self.open_cancel(museum, recall_reason)
        self.type(self.CANCEL_REASON, reason)
        self.click(self.CANCEL_CONFIRM)
