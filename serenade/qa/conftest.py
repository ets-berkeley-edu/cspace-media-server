"""The synthetic-record tests' fixtures (checklist section 63): ucb-stage2's PAHMA, its admin API, the requests and
their log lines, and what the tests noted.

They run only through ./serena aws test --synthetic, which checks the environment, asks for both passwords and sets
everything (deploy/aws.sh: run_tests). serenade/conftest.py still applies (the browser, failure screenshots,
@pytest.mark.after, FILE_ORDER); the AWS tests (serenade/aws/) never run in the same run. Unlike the AWS tests (D224,
D227), these change things in QA, by Richard's decision (November 6, 2026): PAHMA QA's synthetic records, through
make-test-media.py; PAHMA's image size limit (put back) and placeholder image (left on record 033, as the checklist
does); a recall (cancelled). Nothing else, and only SERENA-TEST- records."""
from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator

import pytest
from selenium.webdriver.remote.webdriver import WebDriver

from serenade.aws.target import Target, from_environment
from serenade.conftest import new_browser
from serenade.pages.sign_in_page import SignInPage
from serenade.qa import progress
from serenade.qa.harness import Admin, Log, Serena

TARGET = from_environment()
if TARGET.env != "ucb-stage2" or TARGET.museum != "pahma" or TARGET.simulated:
    raise SystemExit("The synthetic-record tests run only against ucb-stage2's PAHMA, with PAHMA QA's CollectionSpace.")
for name in ("SERENADE_CSPACE_BASE", "SERENADE_CSPACE_USER", "SERENADE_CSPACE_PASSWORD",
             "SERENADE_TEST_MEDIA_SCRIPT"):
    if not os.environ.get(name):
        raise SystemExit(f"{name} isn't set: run them with ./serena aws test --synthetic.")

# --check-records (SERENADE_CHECK_RECORDS=1): only the dataset's report (test_qa_records.py), none of the tests.
TESTS = ["test_qa_look.py", "test_qa_settings.py", "test_qa_changes.py", "test_qa_next_run.py"]
collect_ignore = TESTS if os.environ.get("SERENADE_CHECK_RECORDS") == "1" else ["test_qa_records.py"]

STARTED = time.time()
_noted: list[str] = []
REPORT: list[str] = []  # test_qa_records.py's report on the dataset


def pytest_configure(config: pytest.Config) -> None:
    progress.setup(config)


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """What the tests noted rather than checked (decision 5: outcomes not known until the first run), to be pinned."""
    if REPORT:
        terminalreporter.section("dataset (checklist section 63)")
        for line in REPORT:
            terminalreporter.write_line(line)
    if _noted:
        terminalreporter.section("noted (checklist section 63)")
        for line in _noted:
            terminalreporter.write_line(line)


Note = Callable[[str], None]


@pytest.fixture(scope="session")
def note() -> Note:
    def noting(text: str) -> None:
        _noted.append(text)
        print(text)  # also in the test's own report

    return noting


@pytest.fixture(scope="session")
def report() -> list[str]:
    """test_qa_records.py's lines, printed at the end (a fixture, so it's this module's list however it's imported)."""
    return REPORT


@pytest.fixture(scope="session")
def target() -> Target:
    return TARGET


@pytest.fixture(scope="session")
def base_url() -> str:
    return TARGET.admin_url


@pytest.fixture(scope="session")
def admin_account() -> tuple[str, str]:
    """PAHMA's admin account for the admin app (D228), asked by ./serena aws test; never written anywhere."""
    return os.environ["SERENADE_ADMIN_USER"], os.environ["SERENADE_ADMIN_PASSWORD"]


@pytest.fixture(scope="session")
def api_browser(request: pytest.FixtureRequest, admin_account: tuple[str, str]) -> Iterator[WebDriver]:
    """One browser for the whole run, signed in to PAHMA, for the admin API."""
    progress.say(f"signing in to {TARGET.admin_url} as PAHMA's admin ...")
    browser = new_browser(request.config)
    SignInPage(browser, TARGET.admin_url).sign_in("PAHMA", *admin_account)
    SignInPage(browser, TARGET.admin_url).wait_for_url("/admin/pahma")
    progress.say("signed in")
    yield browser
    browser.quit()


@pytest.fixture(scope="session")
def admin(api_browser: WebDriver) -> Admin:
    return Admin(api_browser, TARGET.admin_url, TARGET.museum)


@pytest.fixture(scope="session")
def serena() -> Serena:
    return Serena(TARGET)


@pytest.fixture(scope="session")
def log() -> Log:
    return Log(TARGET, STARTED)
