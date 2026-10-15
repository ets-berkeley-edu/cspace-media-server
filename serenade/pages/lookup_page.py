"""Media look up (design: Admin web app, Media look up)."""
from __future__ import annotations

from .page import Page, by_id


class LookUpPage(Page):
    INPUT = by_id("lookup-input")
    GO = by_id("lookup-go")
    HEADING = by_id("lookup-heading")
    VERDICT = by_id("lookup-verdict")
    NEXT = by_id("lookup-next")
    SERENA_DETAILS = by_id("serena-details")
    CSPACE_DOWN = by_id("lookup-cspace-down")

    def look_up(self, museum: str, what: str) -> None:
        self.open(f"{museum}/lookup")
        self.type(self.INPUT, what)
        self.click(self.GO)
