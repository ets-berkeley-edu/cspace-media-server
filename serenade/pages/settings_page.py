"""Settings (design: Admin web app, Settings)."""
from __future__ import annotations

import json
import time

from selenium.webdriver.common.by import By

from .page import Locator, Page, by_id, dialog_button, messages_of

API = "/admin/v1/museums"


class SettingsPage(Page):
    TITLE = by_id("page-title")
    CARDS = (By.XPATH, "//div[starts-with(@id, 'settings-') and contains(@class, 'v-card')]")
    ERROR = by_id("settings-error")  # a change Serena refused
    PLACEHOLDER_THUMBNAIL = by_id("placeholder-thumbnail")
    # The Change / Use default dialog.
    VALUE = by_id("setting-value")
    VALUE_MESSAGES = messages_of("setting-value")
    REASON = by_id("reason")
    REASON_MESSAGES = messages_of("reason")
    SAVE = by_id("save-setting")
    CANCEL = dialog_button("Cancel")

    @staticmethod
    def row(name: str) -> Locator:
        """A setting's row by its name ("etl_step_timeout_seconds", "size_limit_mb.card"): label, value, default."""
        return by_id(f"setting-{name.replace('.', '-')}")

    @staticmethod
    def card(group: str) -> Locator:
        return by_id(f"settings-{group}")

    def cells(self, name: str) -> list[str]:
        """A setting's label, value and "default value" or "changed; default value …"."""
        return [td.text for td in self.wait_for(self.row(name)).find_elements(By.TAG_NAME, "td")[:3]]

    def open_page(self, museum: str) -> None:
        self.open(f"{museum}/settings")
        self.wait_for(self.row("watchdog_deadline"))

    def open_change(self, name: str, to_default: bool = False) -> None:
        button = "reset" if to_default else "change"
        self.click((By.XPATH, f"//*[@id='{self.row(name)[1]}']//button[contains(@class, '{button}')]"))
        self.wait_for(self.SAVE)

    def change(self, name: str, value: str, reason: str) -> None:
        """Change… with a value and a reason, then Save (the dialog closes when Serena answers)."""
        self.open_change(name)
        self.type(self.VALUE, value)
        self.type(self.REASON, reason)
        self.click(self.SAVE)

    def use_default(self, name: str, reason: str) -> None:
        self.open_change(name, to_default=True)
        self.type(self.REASON, reason)
        self.click(self.SAVE)
        self.wait_until_gone(self.SAVE, timeout=60)

    def change_and_put_back(self, museum: str, name: str, value: float, reason: str) -> None:
        """Changes a setting and puts its default back through the admin API, as Change… and Use default do: two
        "An admin changed a setting" alerts without the dialog (for a test that needs many alerts). An alert's
        key holds the second it was raised, so each call waits out the second before it: two in one second would be
        one alert."""
        json_body = {"Content-Type": "application/json"}
        time.sleep(1.1)
        status, text = self.call_api("PUT", f"{API}/{museum}/settings/{name}",
                                     json.dumps({"value": value, "reason": f"{reason}: a test change"}), json_body)
        if status != 200:
            raise AssertionError(f"The admin API answered {status}, not 200: {text[:300]}")
        time.sleep(1.1)
        status, text = self.call_api("POST", f"{API}/{museum}/settings/{name}/reset",
                                     json.dumps({"reason": f"{reason}: back to the default"}), json_body)
        if status != 200:
            raise AssertionError(f"The admin API answered {status}, not 200: {text[:300]}")
