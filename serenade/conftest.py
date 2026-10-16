"""The browser, the address the tests use, the dataset, and what the suite does around each test.

SERENADE_BASE_URL points at the admin app (default: the local stack's Vite dev server); SERENADE_HEADED=1 or
--headed shows the browser. `./serena test` sets the test stack's addresses (serenade/stack.py)."""
from __future__ import annotations

import os
import re
from collections.abc import Generator, Iterator
from pathlib import Path

import pytest
from selenium import webdriver

from serenade import dataset
from serenade.stack import ON_TEST_STACK

BASE_URL = os.environ.get("SERENADE_BASE_URL", "http://localhost:5373/admin/")
# Screenshots and page HTML of failed browser tests (synthetic data only: the stack never holds real data).
FAILURES = Path(__file__).parent / ".run" / "failures"

# Each test's outcome so far, for @pytest.mark.after.
_outcomes: dict[str, str] = {}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--headed", action="store_true", help="show the browser")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "after(*tests): run only if these earlier tests passed; otherwise skip")


# The test files in the order they run (the rest after them, alphabetically): what only looks first, then what
# changes one record, then what affects a museum or every museum (README: How the tests share one dataset).
FILE_ORDER = ["test_serving.py", "test_requests.py", "test_lookup_and_recalls.py", "test_sign_in.py"]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    def rank(item: pytest.Item) -> int:
        name = item.path.name
        return FILE_ORDER.index(name) if name in FILE_ORDER else len(FILE_ORDER)

    items.sort(key=rank)  # a stable sort: each file's tests keep their own order


def pytest_runtest_setup(item: pytest.Item) -> None:
    # A test that builds on an earlier test's change is skipped, not failed, when that test didn't pass: its own
    # failure would only repeat the first one.
    for marker in item.iter_markers("after"):
        for name in marker.args:
            if _outcomes.get(name) != "passed":
                pytest.skip(f"needs {name}, which didn't pass")


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Generator[None, pytest.TestReport,
                                                                                           pytest.TestReport]:
    report = yield
    if report.when == "call":
        _outcomes[item.name] = report.outcome
    elif report.outcome != "passed":
        _outcomes[item.name] = "skipped" if report.skipped else "failed"
    driver = getattr(item, "funcargs", {}).get("driver")
    if report.when == "call" and report.failed and driver is not None:
        FAILURES.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", item.name)
        driver.save_screenshot(str(FAILURES / f"{name}.png"))
        (FAILURES / f"{name}.html").write_text(driver.page_source)
        report.sections.append(("serenade", f"Screenshot and page HTML in {FAILURES}/{name}.*"))
    return report


@pytest.fixture(scope="session")
def base_url() -> str:
    if not BASE_URL.startswith(("http://localhost", "http://127.0.0.1")):
        pytest.exit("serenade runs only against the local stack (SERENADE_BASE_URL on localhost).", returncode=2)
    return BASE_URL


@pytest.fixture(scope="session")
def built_dataset() -> None:
    """The dataset ./serena test built (serenade/dataset.py). Only on the test stack: these tests change records,
    so they never run against a tester's stack."""
    if not ON_TEST_STACK:
        pytest.skip("needs the test stack and its dataset: run ./serena test")
    dataset.check_built()


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
