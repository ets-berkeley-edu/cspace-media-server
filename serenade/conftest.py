"""The browser and the address the tests use. SERENADE_BASE_URL points at the admin app (default: the local stack's
Vite dev server); SERENADE_HEADED=1 shows the browser."""
from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from selenium import webdriver

BASE_URL = os.environ.get("SERENADE_BASE_URL", "http://localhost:5373/admin/")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--headed", action="store_true", help="show the browser")


@pytest.fixture(scope="session")
def base_url() -> str:
    if not BASE_URL.startswith(("http://localhost", "http://127.0.0.1")):
        pytest.exit("serenade runs only against the local stack (SERENADE_BASE_URL on localhost).", returncode=2)
    return BASE_URL


@pytest.fixture
def driver(request: pytest.FixtureRequest) -> Iterator[webdriver.Chrome]:
    options = webdriver.ChromeOptions()
    if not (request.config.getoption("--headed") or os.environ.get("SERENADE_HEADED") == "1"):
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1400,1000")
    browser = webdriver.Chrome(options=options)
    browser.implicitly_wait(0)
    yield browser
    browser.quit()
