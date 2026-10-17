"""What every page of the admin app shares: the left-hand menu, the app bar, "← Back to …" and column help (design:
Admin web app; App.vue, navigation.ts, ColumnHeader.vue)."""
from __future__ import annotations

from selenium.webdriver.common.by import By

from .page import Locator, Page, by_id


class LayoutPage(Page):
    TITLE = by_id("page-title")
    OVERVIEW_TITLE = by_id("overview-title")  # the Overview's title is the museum's name
    NAV_GROUPS = (By.XPATH, "//nav//div[contains(@class, 'nav-group')]")
    NAV_ITEMS = (By.XPATH, "//nav//a[starts-with(@id, 'nav-')]")
    BELL = by_id("alerts-bell")
    GEAR = by_id("settings-gear")
    MUSEUM_MENU = by_id("museum-menu")
    BACK = by_id("back-link")

    @staticmethod
    def nav(name: str) -> Locator:
        """A menu item by its route's name ("requests", "lookup", …)."""
        return by_id(f"nav-{name}")

    @staticmethod
    def column_help(table_id: str, title: str) -> Locator:
        return (By.XPATH, f"//*[@id='{table_id}']//thead//span[contains(@class, 'column-help') and "
                          f"normalize-space()='{title}']")

    @staticmethod
    def tooltip(text: str) -> Locator:
        """A column's description, while it shows (Vuetify keeps a closed one in the page, hidden)."""
        return (By.XPATH, "//div[contains(@class, 'v-tooltip')]//div[contains(@class, 'v-overlay__content') and "
                          f"normalize-space()=\"{text}\"]")

    @staticmethod
    def overview_link(text: str) -> Locator:
        """A link in the Overview's sentence ("Past requests", "Media look up")."""
        return (By.XPATH, f"//*[@id='overview-pages']//a[normalize-space()='{text}']")
