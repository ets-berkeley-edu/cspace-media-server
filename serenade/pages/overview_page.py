from __future__ import annotations

from .page import Page, by_id


class OverviewPage(Page):
    TITLE = by_id("overview-title")
    MUSEUM_MENU = by_id("museum-menu")
    SIGN_OUT = by_id("sign-out")
    AUDIT = by_id("nav-audit")
    AUDIT_TABLE = by_id("audit-table")

    def sign_out(self) -> None:
        self.click(self.SIGN_OUT)
