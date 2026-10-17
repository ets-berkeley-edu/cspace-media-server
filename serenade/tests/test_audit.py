"""Audit log, checks T37 to T39 of the test inventory (serena-test-inventory.xlsx; docs/testing-checklist.md sections
14, 15 and 20). T36 (a sign-in in the audit log) is in test_sign_in.py.

They read what the earlier tests recorded, so they run after them (conftest.py's FILE_ORDER): UCJEPS's refresh actions
(T37), PAHMA's recall and the ETL's calls (T39). They only look, except that T38's export is itself audited."""
from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from serenade.dataset import MUSEUM, RESERVED_IMAGE, UCJEPS, UCJEPS_FAILED, refresh_id
from serenade.pages.audit_log_page import AuditLogPage
from serenade.pages.lookup_page import LookUpPage
from serenade.pages.page import shortened
from serenade.pages.sign_in_page import SignInPage

pytestmark = pytest.mark.usefixtures("built_dataset")

ADMIN = ("admin", "admin")  # the simulator's synthetic account: its password is its username
BAMPFA = "bampfa"


def audit_log(driver: WebDriver, base_url: str, museum: str) -> AuditLogPage:
    SignInPage(driver, base_url).sign_in(museum.upper(), *ADMIN)
    SignInPage(driver, base_url).wait_for_url(f"/admin/{museum}")
    page = AuditLogPage(driver, base_url)
    page.open_page(museum)
    return page


@pytest.mark.after("test_t21_sorting_and_paging_past_refreshes")
def test_t37_refresh_actions_and_the_etls_calls(driver: WebDriver, base_url: str) -> None:
    """Checklist section 14, step 7; section 20. After UCJEPS's alerts and refresh tests."""
    page = audit_log(driver, base_url, UCJEPS)
    failed = refresh_id(UCJEPS_FAILED)
    # The admin's actions: the override, the acknowledgements, the admin refreshes.
    override = page.cells(page.entry("threshold override", "serenade T18"))
    assert (override["By"], override["Target"]) == (ADMIN[0], failed), override
    acknowledged = page.cells(page.entry("alert acknowledge", failed))
    assert acknowledged["By"] == ADMIN[0] and acknowledged["Target"].startswith("Check failed"), acknowledged
    repair = page.cells(page.entry("admin refresh", "serenade T19: a test admin refresh"))
    assert repair["By"] == ADMIN[0] and "SHA-256: " in repair["Details"], repair
    # The ETL's calls, with the key it used.
    for action in ("etl refresh start", "etl servable list upload", "etl check request"):
        calls = page.driver.find_elements(*page.entries_by(f"ETL ({UCJEPS})", action))
        assert len(calls) == 2, f"{action}: {len(calls)} entries, not one per ETL refresh"
        assert all("Which key: current" in call.text for call in calls), action
    # Each refresh's outcome, by Serena, its target the refresh (a link to it).
    outcome = page.cells(page.entry("refresh outcome", failed))
    assert outcome["By"] == "Serena" and "State: updated" in outcome["Details"], outcome
    row = page.entry("refresh outcome", failed)[1]
    assert page.driver.find_elements(By.XPATH, f"{row}//a[contains(@class, 'refresh-link') and "
                                               f"normalize-space()='{failed}']"), "the refresh isn't a link"


def test_t38_the_audit_logs_csv_export(driver: WebDriver, base_url: str) -> None:
    """Checklist section 15, step 10; section 20. BAMPFA's (its sign-ins so far). The file Export CSV links to,
    read with the browser's session; then the export is in the log."""
    page = audit_log(driver, base_url, BAMPFA)
    status, disposition, text = page.fetch_text(str(page.wait_for(page.EXPORT).get_attribute("href")))
    assert status == 200
    assert f'filename="serena-audit-{BAMPFA}-{datetime.now(UTC).date().isoformat()}.csv"' in disposition
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["time (UTC)", "by", "action", "target", "details"]
    times = [row[0] for row in rows[1:]]
    assert times and times == sorted(times), "not oldest first"
    assert all(row[1] for row in rows[1:]), "an entry without its By"
    page.open_page(BAMPFA)
    export = page.cells(page.entry("audit export", f"Entries: {len(rows) - 1}"))
    assert export["By"] == ADMIN[0], export


def test_t39_the_by_column_links_and_shortened_values(driver: WebDriver, base_url: str) -> None:
    """Checklist section 20. PAHMA's log after the recall chain and the ETL's refresh."""
    page = audit_log(driver, base_url, MUSEUM)
    assert {ADMIN[0], f"ETL ({MUSEUM})", "Serena"} <= set(page.column("By"))
    # Refresh IDs link to their refresh.
    pahma = refresh_id(MUSEUM)
    assert page.driver.find_elements(By.XPATH, f"//*[@id='audit-table']//a[contains(@class, 'refresh-link') and "
                                               f"normalize-space()='{pahma}']")
    # A SHA-256 shortened, with ⧉ for the whole.
    upload = page.wait_for(page.entries_by(f"ETL ({MUSEUM})", "etl servable list upload"))
    sha = upload.find_element(By.XPATH, ".//span[contains(@class, 'mono') and contains(., '…')]")
    assert len(sha.text) == 13 and len(str(sha.get_attribute("title"))) == 64, "not 12 characters and …"
    assert upload.find_elements(By.CSS_SELECTOR, "button.copy-button")
    # A Media CSID target, shortened, opens Media look up.
    recall = page.entry("recall", "serenade T3")
    link = page.wait_for(recall).find_element(By.XPATH, f".//a[@title='Media look up: {RESERVED_IMAGE.media}']")
    assert link.text == shortened(RESERVED_IMAGE.media)
    link.click()
    look_up = LookUpPage(driver, base_url)
    look_up.wait_for_answer(RESERVED_IMAGE.media)
