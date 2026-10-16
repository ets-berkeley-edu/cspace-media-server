"""Media look up (design: Admin web app, Media look up)."""
from __future__ import annotations

from selenium.webdriver.common.by import By

from .page import Locator, Page, by_id


class LookUpPage(Page):
    INPUT = by_id("lookup-input")
    GO = by_id("lookup-go")
    PROBLEM = by_id("load-error")  # a path or text Media look up can't read (another museum's path, say)
    BARE_URL = by_id("lookup-bare-blob")  # "This URL isn't one Serena serves …"
    HEADING = by_id("lookup-heading")
    VERDICT = by_id("lookup-verdict")
    NEXT = by_id("lookup-next")
    LOOKED_UP = by_id("lookup-refresh")  # "Looked up <the path as read> · last servability update: …"
    # The file in Serena and in CollectionSpace, each with its Details.
    SERENA_DETAILS = by_id("serena-details")
    CSPACE_DETAILS = by_id("cspace-details")
    CSPACE_PANEL = (By.XPATH, "//section[@aria-label='In CollectionSpace now']")
    # The sizes, folded under a line ("Sizes (6): all served · cached: Medium") when there's more than one.
    SIZES_BOX = by_id("lookup-sizes-box")
    SIZES_LINE = (By.XPATH, "//*[@id='lookup-sizes-box']/summary")
    SIZE_ROWS = (By.XPATH, "//*[@id='lookup-sizes']//tbody/tr")
    # Serena and CollectionSpace side by side.
    SYNC = by_id("lookup-sync")  # "✓ (No differences)" or "⚠ (1 difference: As of)"
    COMPARE = by_id("lookup-compare")
    NEXT_REFRESH = by_id("lookup-next-refresh")
    CSPACE_DOWN = by_id("lookup-cspace-down")
    # A size's file (FileDialog.vue).
    FILE_DIALOG = by_id("file-dialog")
    FILE_DIALOG_PICTURE = (By.XPATH, "//*[@id='file-dialog']//div[contains(@class, 'file-dialog-picture')]//img")
    FILE_DIALOG_LOOKUP = by_id("file-dialog-lookup")
    FILE_DIALOG_DISMISS = by_id("file-dialog-dismiss")

    @staticmethod
    def size_row(size: str) -> Locator:
        """A size's row: its name, Served (Yes or No), Why not, Cached copy, Last served, First cached."""
        return (By.XPATH, f"//*[@id='lookup-sizes']//tbody/tr[td[1][normalize-space()='{size}']]")

    @staticmethod
    def size_link(size: str) -> Locator:
        return (By.XPATH, f"//*[@id='lookup-sizes']//button[normalize-space()='{size}']")

    @staticmethod
    def compare_row(label: str) -> Locator:
        """A row of Serena and CollectionSpace: Media CSID, Blob CSID, Access or As of."""
        return (By.XPATH, f"//*[@id='lookup-compare']//tbody/tr[th[contains(normalize-space(), '{label}')]]")

    @staticmethod
    def details_summary(details: Locator) -> Locator:
        return (By.XPATH, f"//*[@id='{details[1]}']/summary")

    def look_up(self, museum: str, what: str) -> None:
        self.open(f"{museum}/lookup")
        self.look_up_here(what)

    def look_up_here(self, what: str) -> None:
        """Looks up from the page already open, as an admin does one look up after another."""
        self.type(self.INPUT, what)
        self.click(self.GO)

    def wait_for_answer(self, what: str) -> str:
        """Waits for the answer to a look up (the page's last line names what was looked up); returns that line."""
        return self.wait_for_text(self.LOOKED_UP, what, timeout=30).text

    def is_open(self, details: Locator) -> bool:
        return self.wait_for(details).get_attribute("open") is not None
