"""What the admin app says while Serena can't be reached, check T47 of the test inventory (serena-test-inventory.xlsx;
docs/testing-checklist.md sections 20 and 21).

It stops Serena's web service (the test stack's web container) and starts it again, so it runs last of all
(conftest.py's FILE_ORDER), and starts Serena again however it ends. Serena's data and sessions are in moto, which
keeps running, so nothing is lost."""
from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from selenium.webdriver.remote.webdriver import WebDriver

from serenade.dataset import MUSEUM, SHARED_IMAGE
from serenade.pages.lookup_page import LookUpPage
from serenade.pages.overview_page import OverviewPage
from serenade.pages.page import dialog_button
from serenade.pages.sign_in_page import SignInPage
from serenade.stack import start_serena, stop_serena

pytestmark = pytest.mark.usefixtures("built_dataset")

ADMIN = ("admin", "admin")  # the simulator's synthetic account: its password is its username
# The admin app's words for 502, 503 and 504 (admin/src/api.ts): the dev server in front of Serena answers 502.
UNREACHABLE = re.compile(r"^Serena can't be reached right now\. Try again in a minute\. \((502|503|504)\)$")


@pytest.fixture
def serena_stopped() -> Iterator[None]:
    stop_serena()
    try:
        yield
    finally:
        start_serena()


def test_t47_errors_keep_their_code_when_serena_cant_be_reached(driver: WebDriver, base_url: str,
                                                                 request: pytest.FixtureRequest) -> None:
    """Checklist section 20 ("Sign everyone out" while the backend is stopped) and section 21 (Media look up while
    it's stopped): the error keeps its code, and the dialog stays open, saying why."""
    sign_in, overview = SignInPage(driver, base_url), OverviewPage(driver, base_url)
    sign_in.sign_in(MUSEUM.upper(), *ADMIN)
    overview.wait_for_url(f"/admin/{MUSEUM}")
    overview.wait_for(overview.SIGN_OUT_ALL)
    request.getfixturevalue("serena_stopped")
    overview.click(overview.SIGN_OUT_ALL)
    overview.click(overview.CONFIRM_SIGN_OUT_ALL)
    error = overview.wait_for(overview.SIGN_OUT_ALL_ERROR, timeout=30).text
    assert UNREACHABLE.match(error), error
    assert overview.wait_for(overview.CONFIRM_SIGN_OUT_ALL).is_displayed(), "the dialog closed"
    overview.click(dialog_button("Cancel"))
    overview.wait_until_gone(overview.CONFIRM_SIGN_OUT_ALL)
    overview.click(overview.LOOKUP)
    look_up = LookUpPage(driver, base_url)
    look_up.look_up_here(SHARED_IMAGE.blob)
    problem = look_up.wait_for(look_up.PROBLEM, timeout=30).text
    assert UNREACHABLE.match(problem), problem
