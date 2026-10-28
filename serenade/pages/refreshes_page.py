"""Past refreshes, a refresh's page and Manual refresh (design: Admin web app; Refreshes)."""
from __future__ import annotations

import json
import time
from typing import Any

from selenium.webdriver.common.by import By

from .page import Locator, Page, by_id, dialog_button, messages_of

API = "/admin/v1/museums"


class RefreshesPage(Page):
    TITLE = by_id("page-title")
    # Past refreshes.
    TABLE = by_id("refreshes-table")
    ROWS = (By.XPATH, "//*[@id='refreshes-table']//tbody/tr[contains(@class, 'v-data-table__tr')]")  # not "Loading"
    PER_PAGE = (By.XPATH, "//*[@id='refreshes-table']//div[contains(@class, 'v-data-table-footer__items-per-page')]"
                          "//div[contains(concat(' ', normalize-space(@class), ' '), ' v-field ')]")
    # A refresh's page.
    STATE = by_id("refresh-state")
    # Issue #120: a refresh's reasons in two lists.
    WENT_WRONG = by_id("refresh-problems")
    ADMINS_DID = by_id("refresh-admin-actions")
    CHECK_PROBLEMS = by_id("check-problems")
    OVERRIDE_BANNER = by_id("override-banner")  # issue #108: who overrode the delta threshold, when and why
    CHECK_OVERRIDDEN = by_id("check-overridden")  # only when a re-check fails on something else (issue #110)
    CHECK_HEADING = by_id("check-heading")  # issue #110: "failed, overridden by admin" after an override
    OVERRIDE = by_id("override-threshold")
    CONFIRM = by_id("confirm-action")
    REASON = by_id("reason")  # the action's reason (ReasonField's own id)
    REASON_MESSAGES = messages_of("reason")
    # Issue #120: an override says why the change is expected (a kind) before its reason.
    KIND_TESTING = (By.XPATH, "//input[@id='override-kind-testing']"
                              "/ancestor::div[contains(@class, 'v-selection-control')][1]")
    KIND_MESSAGES = messages_of("override-kind-first_load")
    CANCEL = dialog_button("Cancel")
    # Manual refresh (issue #118; mockup version 55): "Replace with:", a dry run, then Apply and its summary.
    SOURCE_ETL = (By.XPATH, "//input[@id='source-etl']/ancestor::div[contains(@class, 'v-selection-control')][1]")
    SOURCE_UPLOAD = (By.XPATH, "//input[@id='source-upload']/ancestor::div[contains(@class, 'v-selection-control')][1]")
    CHECK = by_id("manual-check")  # the dry run: shown once an ETL list is chosen
    DRY_HEAD = by_id("manual-dry-head")
    APPLY = by_id("manual-apply")
    MANUAL_CONFIRM = by_id("manual-confirm")  # stopping the pending refresh, or applying an older list
    APPLIED = by_id("manual-applied")
    FILE = by_id("file")
    CONFIRM_LIVE_CORE = (By.XPATH, "//input[@id='confirm-live-core']/ancestor::div[contains(@class, "
                                   "'v-selection-control')][1]")
    CONFIRM_MESSAGES = messages_of("confirm-live-core")

    COLUMNS = ("Refresh", "Refresh date", "State", "Rows", "Last change")

    @staticmethod
    def row_of(refresh_id: str) -> Locator:
        return (By.XPATH, f"//*[@id='refreshes-table']//tbody/tr[td[1][normalize-space()='{refresh_id}']]")

    @staticmethod
    def header(title: str) -> Locator:
        return (By.XPATH, f"//*[@id='refreshes-table']//thead//th[.//span[normalize-space()='{title}']]")

    def cells(self, row: Locator) -> dict[str, str]:
        tds = self.wait_for(row).find_elements(By.TAG_NAME, "td")
        return {name: td.text for name, td in zip(self.COLUMNS, tds, strict=False)}

    def first_column(self) -> list[str]:
        return [td.text for td in self.driver.find_elements(By.XPATH, "//*[@id='refreshes-table']//tbody/tr/td[1]")]

    def open_list(self, museum: str) -> None:
        self.open(f"{museum}/refreshes")
        self.wait_for(self.TABLE)
        self.wait_for(self.ROWS)

    def open_refresh(self, museum: str, refresh_id: str) -> None:
        self.open(f"{museum}/refreshes/{refresh_id}")
        self.wait_for(self.STATE)

    def wait_for_state(self, museum: str, refresh_id: str, state: str, seconds: float = 60) -> None:
        """Opens the refresh's page again until it shows the state: the worker checks and updates on its own, and the
        page shows a refresh as it was when it opened."""
        deadline = time.monotonic() + seconds
        while True:
            self.open_refresh(museum, refresh_id)
            if self.text_of(self.STATE) == state or time.monotonic() > deadline:
                if self.text_of(self.STATE) != state:
                    raise AssertionError(f"{refresh_id} is {self.text_of(self.STATE)!r}, not {state!r}")
                return
            time.sleep(1)

    # The admin API, with the browser's session: for setting up refreshes a test needs before it looks.

    def refreshes(self, museum: str) -> list[dict[str, Any]]:
        status, text = self.call_api("GET", f"{API}/{museum}/refreshes")
        _expect(status, 200, text)
        found: list[dict[str, Any]] = json.loads(text)["refreshes"]
        return found

    def refresh(self, museum: str, refresh_id: str) -> dict[str, Any]:
        status, text = self.call_api("GET", f"{API}/{museum}/refreshes/{refresh_id}")
        _expect(status, 200, text)
        found: dict[str, Any] = json.loads(text)
        return found

    def admin_refresh(self, museum: str, servable_list: str, reason: str, seconds: float = 60) -> dict[str, Any]:
        """Applies an uploaded ETL list, as Manual refresh's Apply does, replacing the museum's pending refresh if
        there is one, and waits until the worker has checked it and, on a pass, updated. Returns the refresh."""
        status, text = self.call_api("GET", f"{API}/{museum}/status")
        _expect(status, 200, text)
        pending = json.loads(text)["pending"]
        open_refresh = pending["refresh_id"] if pending else ""
        status, text = self.call_api("POST", f"{API}/{museum}/refreshes", servable_list, {
            "X-Live-Core-Confirmed": "yes", "X-File-Name": "serenade.tsv", "X-Reason": reason,
            "X-Open-Refresh": open_refresh})
        _expect(status, 201, text)
        refresh_id = json.loads(text)["refresh_id"]
        return self._settled(museum, refresh_id, seconds)

    def _settled(self, museum: str, refresh_id: str, seconds: float) -> dict[str, Any]:
        deadline = time.monotonic() + seconds
        while (found := self.refresh(museum, refresh_id))["state"] in ("started", "received", "checking", "updating"):
            if time.monotonic() > deadline:
                raise AssertionError(f"{refresh_id} is still {found['state']}")
            time.sleep(0.5)
        return found


def _expect(status: int, expected: int, text: str) -> None:
    if status != expected:
        raise AssertionError(f"The admin API answered {status}, not {expected}: {text[:300]}")
