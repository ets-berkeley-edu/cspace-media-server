"""Settings, checks T29 to T35 and T86 of the test inventory (serena-test-inventory.xlsx; docs/testing-checklist.md
sections 15, 19, 21, 22 and 29).

T29 to T34 use BAMPFA, the museum reserved for settings tests (the inventory's Data roles): each change is put back
("Use default"), so they leave BAMPFA as they found it, apart from its audit entries and alerts. T35 names PAHMA's
placeholder image's Media record and puts the default back at the end. They run after the PAHMA look up and recall
tests (conftest.py's FILE_ORDER): T35 changes what a PAHMA request for the placeholder image gets while it runs."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from serenade.dataset import MUSEUM, unknown_csid
from serenade.pages.alerts_page import AlertsPage
from serenade.pages.audit_log_page import AuditLogPage
from serenade.pages.lookup_page import LookUpPage
from serenade.pages.settings_page import SettingsPage
from serenade.pages.sign_in_page import SignInPage
from serenade.stack import eventually, redirect_of

pytestmark = pytest.mark.usefixtures("built_dataset")

ADMIN = ("admin", "admin")  # the simulator's synthetic account: its password is its username
BAMPFA = "bampfa"
GIVE_A_REASON = "Give a reason first."
# BAMPFA's starting values (museums/bampfa.yaml), as the page shows them.
DEFAULTS = {
    "watchdog_deadline": "08:00", "etl_poll_interval_seconds": "15", "etl_step_timeout_seconds": "1800",
    "delta_threshold_percent": "5", "size_limit_mb.image": "500", "size_limit_mb.card": "500",
    "size_limit_mb.3D": "1024", "size_limit_mb.pdf": "200", "audit_retention_days": "90 days",
    "placeholder_media_csid": "none: the generic picture",
}
SIZE_LABELS = {
    "size_limit_mb.image": "Largest image file fetched (MB)",
    "size_limit_mb.card": "Largest catalog card file fetched (MB)",
    "size_limit_mb.3D": "Largest 3D model file fetched (MB)",
    "size_limit_mb.pdf": "Largest PDF file fetched (MB)",
}
# PAHMA's placeholder image (museums/pahma.yaml) and the synthetic Media record the fake ETL adds for it
# (backend/devtools/fake_etl.py: PLACEHOLDER_MEDIA).
PLACEHOLDER_BLOB = "59a733dd-d641-4e1a-8552"
PLACEHOLDER_MEDIA = "9e8d7c6b-5a49-4382-9170-6f5e4d3c2b1a"
PLACEHOLDER_PATH = f"/{MUSEUM}/imageserver/blobs/{PLACEHOLDER_BLOB}/derivatives/Medium/content"


def settings_page(driver: WebDriver, base_url: str, museum: str = BAMPFA) -> SettingsPage:
    SignInPage(driver, base_url).sign_in(museum.upper(), *ADMIN)
    SignInPage(driver, base_url).wait_for_url(f"/admin/{museum}")
    page = SettingsPage(driver, base_url)
    page.open_page(museum)
    return page


def test_t29_the_settings_page_and_its_default_values(driver: WebDriver, base_url: str) -> None:
    """Checklist section 15, step 1; section 22. The size limits name the kinds in words (pull request 56)."""
    page = settings_page(driver, base_url)
    assert page.text_of(page.TITLE) == "BAMPFA Settings"
    assert page.count(page.CARDS) == 6
    for name, value in DEFAULTS.items():
        label, shown, default = page.cells(name)
        assert (shown, default) == (value, "default value"), f"{name}: {shown!r}, {default!r}"
        if name in SIZE_LABELS:
            assert label == SIZE_LABELS[name]


def test_t30_a_value_out_of_bounds_is_refused(driver: WebDriver, base_url: str) -> None:
    """Checklist section 15, step 2; section 29 (D219). Said under the field, the dialog open; nothing changes."""
    page = settings_page(driver, base_url)
    page.change("etl_step_timeout_seconds", "10", "serenade T30: out of bounds")
    page.wait_for_text(page.VALUE_MESSAGES, "Give a whole number from 60 to 7,200.")
    assert page.focused_id() == "setting-value"
    page.click(page.CANCEL)
    page.wait_until_gone(page.SAVE)
    assert page.count(page.ERROR) == 0
    assert page.cells("etl_step_timeout_seconds")[1:] == ["1800", "default value"]


def test_t86_a_value_that_isnt_one_is_caught_on_save(driver: WebDriver, base_url: str) -> None:
    """Checklist section 29 (D219 to D221): a value that isn't a number or a time is said under the field, in words,
    and nothing is sent: no change, no audit entry."""
    page = settings_page(driver, base_url)
    for name, value, problem in (
        ("delta_threshold_percent", "5d", "Give a number from 0.1 to 100."),
        ("etl_poll_interval_seconds", "12.5", "Give a whole number from 5 to 300."),
        ("watchdog_deadline", "8am", "Give a time as HH:MM, from 00:00 to 23:59."),
    ):
        page.change(name, value, "serenade T86: not a value")
        page.wait_for_text(page.VALUE_MESSAGES, problem)
        assert page.focused_id() == "setting-value"
        page.click(page.CANCEL)
        page.wait_until_gone(page.SAVE)
        assert page.cells(name)[1:] == [DEFAULTS[name], "default value"]
    audit = AuditLogPage(driver, base_url)
    audit.open_page(BAMPFA)
    assert "serenade T86" not in audit.text_of(audit.TABLE)


def test_t31_changing_a_setting_and_using_the_default_again(driver: WebDriver, base_url: str) -> None:
    """Checklist section 15, steps 2 to 4. Put back as it was."""
    page = settings_page(driver, base_url)
    page.change("etl_step_timeout_seconds", "900", "serenade T31: a test change")
    page.wait_for_text(page.row("etl_step_timeout_seconds"), "changed; default value 1800")
    assert page.cells("etl_step_timeout_seconds")[1] == "900"
    audit = AuditLogPage(driver, base_url)
    audit.open_page(BAMPFA)
    entry = audit.cells(audit.entry("settings change", "serenade T31: a test change"))
    assert entry["Target"] == "etl_step_timeout_seconds", entry
    assert "Before: 1800" in entry["Details"] and "After: 900" in entry["Details"], entry
    page.open_page(BAMPFA)
    page.use_default("etl_step_timeout_seconds", "serenade T31: back to the default")
    assert page.wait_for_text(page.row("etl_step_timeout_seconds"), "default value")
    assert page.cells("etl_step_timeout_seconds")[1:] == ["1800", "default value"]


@pytest.fixture
def acknowledged(driver: WebDriver, base_url: str) -> Iterator[None]:
    """The alerts a test raises on BAMPFA are acknowledged afterwards, so the banner doesn't stay."""
    yield
    page = AlertsPage(driver, base_url)
    page.open_page(BAMPFA)
    while (waiting := page.count(page.ACKNOWLEDGE)) > 0:
        page.click(page.ACKNOWLEDGE)
        page.wait_for_count(page.ACKNOWLEDGE, waiting - 1)


@pytest.mark.usefixtures("acknowledged")
def test_t32_a_setting_that_weakens_a_protection_raises_an_alert(driver: WebDriver, base_url: str) -> None:
    """Checklist section 15, step 5. Put back as it was, and its alerts acknowledged."""
    page = settings_page(driver, base_url)
    page.change("delta_threshold_percent", "12.5", "serenade T32: a test change")
    page.wait_for_text(page.row("delta_threshold_percent"), "changed; default value 5")
    page.use_default("delta_threshold_percent", "serenade T32: back to the default")
    alerts = AlertsPage(driver, base_url)
    alerts.open_page(BAMPFA)
    raised = alerts.wait_for(alerts.row_with("serenade T32: a test change")).text
    assert "An admin changed a setting" in raised
    assert "Delta threshold (%), from 5.0 to 12.5. Reason: serenade T32: a test change" in raised
    back = alerts.wait_for(alerts.row_with("serenade T32: back to the default")).text
    assert "from 12.5 to 5.0" in back


@pytest.mark.usefixtures("acknowledged")
def test_t33_the_audit_retentions_choices(driver: WebDriver, base_url: str) -> None:
    """Checklist section 15, step 6. Put back to 90 days."""
    page = settings_page(driver, base_url)
    page.open_change("audit_retention_days")
    page.click((By.XPATH, "//input[@id='setting-value']/ancestor::div[contains(concat(' ', normalize-space(@class), "
                          "' '), ' v-field ')][1]"))
    option = "//div[contains(@class, 'v-overlay--active')]//div[contains(@class, 'v-list-item-title')]"
    page.wait_for((By.XPATH, f"{option}[normalize-space()='36 months']"))  # the menu has opened
    options = page.driver.find_elements(By.XPATH, option)
    assert [o.text for o in options] == ["90 days", "6 months", "12 months", "18 months", "24 months", "36 months"]
    page.click((By.XPATH, "//div[contains(@class, 'v-overlay--active')]//div[contains(@class, 'v-list-item-title') "
                          "and normalize-space()='6 months']"))
    page.type(page.REASON, "serenade T33: a test change")
    page.click(page.SAVE)
    page.wait_for_text(page.row("audit_retention_days"), "changed; default value 90 days")
    assert page.cells("audit_retention_days")[1] == "6 months"
    page.use_default("audit_retention_days", "serenade T33: back to the default")
    assert page.cells("audit_retention_days")[1:] == ["90 days", "default value"]


def test_t34_save_without_a_reason(driver: WebDriver, base_url: str) -> None:
    """Checklist section 21. Nothing changes."""
    page = settings_page(driver, base_url)
    page.open_change("etl_poll_interval_seconds")
    page.type(page.VALUE, "30")
    page.click(page.SAVE)
    page.wait_for_text(page.REASON_MESSAGES, GIVE_A_REASON)
    assert page.focused_id() == "reason"
    page.click(page.CANCEL)
    page.wait_until_gone(page.SAVE)
    assert page.cells("etl_poll_interval_seconds")[1:] == ["15", "default value"]


def generic_picture() -> None:
    assert redirect_of(PLACEHOLDER_PATH).endswith("/placeholder.svg"), "not Serena's generic picture"


def served() -> None:
    assert f"/local-cdn/{MUSEUM}/objects/" in redirect_of(PLACEHOLDER_PATH), "not served from the stored copy"


def test_t35_the_placeholder_images_media_record(driver: WebDriver, base_url: str) -> None:
    """Checklist section 22; section 19 (the placeholder image). PAHMA's setting, put back to the default at the end
    (saving the record takes a few seconds: Serena fetches every size)."""
    generic_picture()
    page = settings_page(driver, base_url, MUSEUM)
    look_up = LookUpPage(driver, base_url)
    look_up.look_up(MUSEUM, PLACEHOLDER_BLOB)
    look_up.wait_for_answer(PLACEHOLDER_BLOB)
    assert look_up.text_of(look_up.VERDICT).startswith("Not served: Serena's generic picture instead")
    # An unknown CSID is refused in the dialog, which stays open.
    page.open_page(MUSEUM)
    page.change("placeholder_media_csid", unknown_csid(35), "serenade T35: an unknown record")
    page.wait_for_text(page.VALUE_MESSAGES, "CollectionSpace has no Media record with this CSID.", timeout=30)
    page.click(page.CANCEL)
    page.wait_until_gone(page.SAVE)
    # The synthetic record: named with its thumbnail, and its picture served.
    try:
        page.change("placeholder_media_csid", PLACEHOLDER_MEDIA, "serenade T35: the synthetic record")
        page.wait_until_gone(page.SAVE, timeout=60)
        assert page.cells("placeholder_media_csid")[1].startswith(PLACEHOLDER_MEDIA)
        page.wait_for_picture((By.ID, "placeholder-thumbnail"))
        eventually(served)
    finally:
        page.open_page(MUSEUM)
        if "changed" in page.cells("placeholder_media_csid")[2]:
            page.use_default("placeholder_media_csid", "serenade T35: back to the default")
    eventually(generic_picture)
    assert page.cells("placeholder_media_csid")[1:] == ["none: the generic picture", "default value"]
