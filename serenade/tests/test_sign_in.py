"""Signing in and sessions, checks T40 to T46 of the test inventory (serena-test-inventory.xlsx;
docs/testing-checklist.md sections 12 and 20), with the simulator's synthetic accounts (design: Admin web app,
Sign-in).

They run last (conftest.py's FILE_ORDER), and T45 last of all: it signs everyone out of PAHMA. Each test has its own
browser, so the others' sign-ins and sign-outs end with the test; T45's ends every PAHMA session, which by then are
only its own two browsers'."""
from __future__ import annotations

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from serenade.pages.overview_page import OverviewPage
from serenade.pages.page import Page
from serenade.pages.sign_in_page import SignInPage

# The simulator's synthetic accounts: each password is its username (backend/fakecspace/app.py, ADMINS). "admin" has
# every museum's Serena admin role, "pahma-admin" only PAHMA's, "viewer" none.
ADMIN = ("admin", "admin")
PAHMA_ADMIN = ("pahma-admin", "pahma-admin")
VIEWER = ("viewer", "viewer")
# The five museums by their names (backend/serena/museums/*.yaml).
MUSEUMS = ["BAMPFA", "Botanical Garden", "Cinefiles", "PAHMA", "UCJEPS"]
TITLE = (By.ID, "page-title")


def test_t42_the_sign_in_page_lists_the_five_museums(driver: WebDriver, base_url: str) -> None:
    """Checklist section 12, step 1."""
    sign_in = SignInPage(driver, base_url)
    sign_in.open("sign-in")
    sign_in.click(sign_in.MUSEUM)
    sign_in.wait_for((By.XPATH, f"{sign_in.OPTIONS[1]}[normalize-space()='UCJEPS']"))  # the list has opened
    assert [option.text for option in driver.find_elements(*sign_in.OPTIONS)] == MUSEUMS


def test_t40_sign_in_see_the_museum_and_sign_out(driver: WebDriver, base_url: str) -> None:
    """Checklist section 12, steps 1, 2 and 4."""
    sign_in, overview = SignInPage(driver, base_url), OverviewPage(driver, base_url)
    sign_in.sign_in("PAHMA", *ADMIN)
    overview.wait_for_url("/admin/pahma")
    assert overview.text_of(overview.TITLE) == "PAHMA"
    overview.click(overview.AUDIT)
    overview.wait_for(overview.SIGN_IN_ROW)
    overview.sign_out()
    sign_in.wait_for(sign_in.BUTTON)


def test_t41_an_account_without_the_role(driver: WebDriver, base_url: str) -> None:
    """Checklist section 12, step 7."""
    sign_in = SignInPage(driver, base_url)
    sign_in.sign_in("PAHMA", *VIEWER)
    assert "Serena_Admin" in sign_in.text_of(sign_in.ERROR)


def test_t43_two_museums_at_once(driver: WebDriver, base_url: str) -> None:
    """Checklist section 12, steps 5 and 6: BAMPFA signed in from the museum menu, switching, and PAHMA's sign-out
    leaving BAMPFA's session."""
    sign_in, overview = SignInPage(driver, base_url), OverviewPage(driver, base_url)
    sign_in.sign_in("PAHMA", *ADMIN)
    overview.wait_for_url("/admin/pahma")
    overview.click(overview.MUSEUM_MENU)
    overview.click(overview.SIGN_IN_ANOTHER)
    sign_in.fill_in("BAMPFA", *ADMIN)
    overview.wait_for_url("/admin/bampfa")
    overview.wait_for_text(overview.TITLE, "BAMPFA")
    assert sorted(overview.museums_in_menu()) == ["BAMPFA (admin)", "PAHMA (admin)"]
    overview.click(overview.MUSEUM_MENU)
    overview.click(overview.museum_item("PAHMA (admin)"))
    overview.wait_for_url("/admin/pahma")
    overview.wait_for_text(overview.TITLE, "PAHMA")
    assert overview.text_of(overview.SIGN_OUT) == "Sign out of PAHMA"
    overview.sign_out()
    overview.wait_for_url("/admin/bampfa")  # the museum still signed in
    overview.wait_for_text(overview.TITLE, "BAMPFA")
    assert overview.museums_in_menu() == ["BAMPFA (admin)"]


def test_t44_the_role_is_per_museum(driver: WebDriver, base_url: str) -> None:
    """Checklist section 12, step 7: pahma-admin has PAHMA's role, not BAMPFA's. The museum menu keeps PAHMA only."""
    sign_in, overview = SignInPage(driver, base_url), OverviewPage(driver, base_url)
    sign_in.sign_in("PAHMA", *PAHMA_ADMIN)
    overview.wait_for_url("/admin/pahma")
    overview.click(overview.MUSEUM_MENU)
    overview.click(overview.SIGN_IN_ANOTHER)
    sign_in.fill_in("BAMPFA", *PAHMA_ADMIN)
    assert "Serena_Admin" in sign_in.text_of(sign_in.ERROR)
    overview.open("pahma")
    overview.wait_for_text(overview.TITLE, "PAHMA")
    assert overview.museums_in_menu() == ["PAHMA (pahma-admin)"]


def test_t46_the_api_documentation_page(driver: WebDriver, base_url: str) -> None:
    """Checklist section 12, step 3: Swagger UI with the ETL API's endpoints, read-only (no "Try it out" even with an
    endpoint opened), and nothing in Chrome's console about the Content-Security-Policy. (The test stack's admin app
    is Vite's dev server, without Serena's policy header: the built app is where the policy applies.)"""
    sign_in, overview = SignInPage(driver, base_url), OverviewPage(driver, base_url)
    sign_in.sign_in("PAHMA", *ADMIN)
    overview.wait_for_url("/admin/pahma")
    overview.click((By.ID, "nav-api"))
    overview.wait_for_text(TITLE, "PAHMA ETL API documentation")
    path = "//div[@id='swagger-ui']//*[contains(@class, 'opblock-summary-path')]"
    overview.wait_for((By.XPATH, path), timeout=20)
    paths = {element.text.replace("​", "") for element in driver.find_elements(By.XPATH, path)}
    assert {"/ping", "/museums/{tenant}/refreshes", "/museums/{tenant}/refreshes/{refresh_id}/servable-list"} <= paths
    overview.click((By.XPATH, f"({path})[1]"))
    overview.wait_for((By.XPATH, "//div[@id='swagger-ui']//div[contains(@class, 'opblock-body')]"))
    assert overview.count((By.XPATH, "//div[@id='swagger-ui']//button[contains(@class, 'try-out__btn')]")) == 0
    console = [entry["message"] for entry in driver.get_log("browser")]
    assert not [line for line in console if "Content-Security-Policy" in line], console


def test_t45_sign_everyone_out_ends_another_browsers_session(driver: WebDriver, second_driver: WebDriver,
                                                             base_url: str) -> None:
    """Checklist section 20: two browsers signed in to PAHMA; the second signs everyone out; the first, opening Audit
    log, is sent to the sign-in page, and after signing in again reaches Audit log, not the Overview. Last of all: it
    ends every PAHMA session."""
    first, overview = SignInPage(driver, base_url), OverviewPage(driver, base_url)
    first.sign_in("PAHMA", *ADMIN)
    overview.wait_for_url("/admin/pahma")
    second, other = SignInPage(second_driver, base_url), OverviewPage(second_driver, base_url)
    second.sign_in("PAHMA", *ADMIN)
    other.wait_for_url("/admin/pahma")
    other.click(other.SIGN_OUT_ALL)
    other.click(other.CONFIRM_SIGN_OUT_ALL)
    second.wait_for(second.BUTTON)  # the second browser's own session ended too
    overview.click(overview.AUDIT)
    ended = first.wait_for(first.TIMED_OUT, timeout=20).text
    assert ended.startswith("Your PAHMA session ended."), ended
    assert "you'll return to the page you were on" in ended
    first.fill_in(None, *ADMIN)  # the sign-in page keeps PAHMA chosen
    Page(driver, base_url).wait_for_text(TITLE, "PAHMA Audit log")
    assert driver.current_url.endswith("/admin/pahma/audit")
