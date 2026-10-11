from __future__ import annotations

from selenium.webdriver.common.by import By

from .page import Page, by_id


class SignInPage(Page):
    # Vuetify puts the id on a hidden input inside the select; the visible field around it takes the click.
    MUSEUM = (By.XPATH, "//input[@id='museum']/ancestor::div[contains(concat(' ', normalize-space(@class), ' '), "
                        "' v-field ')][1]")
    USERNAME = by_id("username")
    PASSWORD = by_id("password")
    BUTTON = by_id("sign-in-button")
    ERROR = by_id("sign-in-error")

    def choose_museum(self, name: str) -> None:
        self.click(self.MUSEUM)
        self.click((By.XPATH, f"//div[contains(@class, 'v-list-item-title') and normalize-space()='{name}']"))

    def sign_in(self, museum: str, username: str, password: str) -> None:
        self.open("sign-in")
        self.choose_museum(museum)
        self.type(self.USERNAME, username)
        self.type(self.PASSWORD, password)
        self.click(self.BUTTON)
