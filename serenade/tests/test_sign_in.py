"""Signing in to the admin app with the simulator's synthetic accounts (design: Admin web app, Sign-in)."""
from __future__ import annotations

from selenium.webdriver.remote.webdriver import WebDriver

from serenade.pages.overview_page import OverviewPage
from serenade.pages.sign_in_page import SignInPage

# The simulator's synthetic accounts: each password is its username (backend/fakecspace/app.py, ADMINS).
ADMIN = ("admin", "admin")
VIEWER = ("viewer", "viewer")


def test_sign_in_see_the_museum_and_sign_out(driver: WebDriver, base_url: str) -> None:
    sign_in, overview = SignInPage(driver, base_url), OverviewPage(driver, base_url)
    sign_in.sign_in("PAHMA", *ADMIN)
    overview.wait_for_url("/admin/pahma")
    assert overview.text_of(overview.TITLE) == "PAHMA"
    overview.click(overview.AUDIT)
    assert "sign in" in overview.text_of(overview.AUDIT_TABLE)
    overview.sign_out()
    sign_in.wait_for(sign_in.BUTTON)


def test_an_account_without_the_role(driver: WebDriver, base_url: str) -> None:
    sign_in = SignInPage(driver, base_url)
    sign_in.sign_in("PAHMA", *VIEWER)
    assert "Serena_Admin" in sign_in.text_of(sign_in.ERROR)
