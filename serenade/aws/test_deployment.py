"""A deployed environment, after ./serena aws deploy or resume: T90 to T105 of the test inventory
(serena-test-inventory.xlsx; docs/testing-checklist.md sections 24, 25 and 27, the steps marked "Automated").

They run in this order (D222 to D231): the environment's status, the fake ETL's refreshes, then what Serena serves
through CloudFront (plain HTTP), the admin app (Selenium), a recall that's cancelled at the end, and last, the logs'
permission errors. What they change they undo (D227): the refreshes (personal-dev only) and the recall. Against a real
CollectionSpace only the tests that look run (conftest.py). Never: a deploy, pause, cdn-key, a setting or an alarm."""
from __future__ import annotations

import os
import re
import subprocess
import time
from typing import Any

import pytest
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.remote.webdriver import WebDriver

from serenade.aws.target import Answer, Target, aws_cli, eventually, fake_etl, get, serena_aws
from serenade.pages.audit_log_page import AuditLogPage
from serenade.pages.lookup_page import LookUpPage
from serenade.pages.page import Page, by_id
from serenade.pages.recalls_page import RecallsPage
from serenade.pages.refreshes_page import RefreshesPage
from serenade.pages.requests_page import RequestsPage
from serenade.pages.sign_in_page import SignInPage

SIGNED = re.compile(r"/objects/(?P<sha>[0-9a-f]{64})\?Expires=\d+&Signature=[^&]+&Key-Pair-Id=(?P<key>[A-Z0-9]+)$")
RECALL_REASON = "serenade T103: an AWS test recall"
CANCEL_REASON = "serenade T104: an AWS test cancel"
SVG_CSP = "default-src 'none'; style-src 'unsafe-inline'"
ENVIRONMENT = by_id("environment")  # the admin app's header chip: "<label> · <image tag>"


def signed_in(driver: WebDriver, base_url: str, target: Target, admin: tuple[str, str]) -> None:
    SignInPage(driver, base_url).sign_in(target.museum.upper(), *admin)
    SignInPage(driver, base_url).wait_for_url(f"/admin/{target.museum}")


def signed_address(answer: Answer, target: Target) -> str:
    """The signed address Serena redirects a file request to; fails if it isn't one."""
    assert answer.status == 302, f"{answer.status}, not 302"
    location = answer.header("Location")
    assert location.startswith(f"{target.url}/{target.museum}/objects/"), location
    assert SIGNED.search(location), f"not a signed address: {location}"
    return location


def unavailable(answer: Answer, target: Target) -> None:
    assert answer.status == 302, f"{answer.status}, not 302"
    assert answer.header("Location") == f"{target.url}/{target.museum}/unavailable.svg", answer.header("Location")


def max_age(answer: Answer) -> int:
    found = re.fullmatch(r"private, max-age=(\d+)", answer.header("Cache-Control"))
    assert found, f"Cache-Control: {answer.header('Cache-Control')}"
    return int(found.group(1))


# ---- the environment ------------------------------------------------------------------------------------------------

def test_t90_status(target: Target) -> None:
    """Checklist section 24, step 2; section 25, step 3: every service running, image delivery on, the alert email
    confirmed, the alarms on and none firing."""
    status = serena_aws("status")
    services = ["web", "worker"] + (["fakecspace"] if target.simulated else [])
    for service in services:
        found = re.search(rf"^  {service}: running (\d+) of (\d+)$", status, re.MULTILINE)
        assert found and found.group(1) == found.group(2) != "0", f"{service} isn't running:\n{status}"
    assert f"Image:   {target.image_tag}" in status
    assert re.search(r"^Image delivery: on; signing keys trusted: \S+", status, re.MULTILINE), status
    assert re.search(r"^Alert email: \S+@\S+$", status, re.MULTILINE), f"no confirmed alert email:\n{status}"
    alarms = re.search(r"^Alarms: .*$", status, re.MULTILINE)
    assert alarms and alarms.group(0) == "Alarms: on", (
        f"{alarms.group(0) if alarms else 'no Alarms line'}. Just after a deploy, web-down or worker-down can fire "
        "while the services restart: wait 10 minutes and run the test again.")


def test_t91_health_and_the_running_commit(target: Target) -> None:
    """Checklist section 24, steps 1 and 2: /health answers ok, and the image is this branch's commit (the code and the
    checklist come from the same branch)."""
    health = get(f"{target.url}/health")
    assert (health.status, health.body) == (200, b"ok")
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,  # noqa: S607
                            check=True).stdout.strip()
    assert target.image_tag.startswith(f"{commit}-"), (
        f"'{target.env}' runs {target.image_tag}, not this branch's commit {commit}: ./serena aws deploy first")


# ---- the fake ETL's refreshes (personal-dev) ------------------------------------------------------------------------

@pytest.mark.changes
def test_t92_a_daily_refresh_by_the_fake_etl(refresh: dict[str, Any]) -> None:
    """Checklist section 24, step 3; section 25, step 4; section 27, step 3 (the fake ETL runs from the devtools
    image): the refresh ends "updated", with a sample address for each kind of file."""
    assert refresh["state"] == "updated", refresh
    assert refresh["samples"].get("image"), refresh


@pytest.mark.changes
@pytest.mark.after("test_t92_a_daily_refresh_by_the_fake_etl")
def test_t93_the_same_refresh_again_changes_nothing(target: Target) -> None:
    """Checklist section 24, step 3: again, "updated" with 0 written and 0 deleted."""
    again = fake_etl(target.museum)
    assert again["state"] == "updated", again
    assert (again["update"]["written"], again["update"]["deleted"]) == (0, 0), again["update"]


@pytest.mark.changes
@pytest.mark.after("test_t92_a_daily_refresh_by_the_fake_etl")
def test_t94_a_failed_refresh_sends_nothing(target: Target) -> None:
    """Checklist section 24, step 4: --failed fails, and Serena is never called (no refresh)."""
    failed = fake_etl(target.museum, "--failed")
    assert failed["failed"] is True and failed["refresh_id"] is None, failed


# ---- what Serena serves through CloudFront (plain HTTP) -------------------------------------------------------------

def test_t95_a_file_request_redirects_to_a_signed_address(target: Target, sample: str) -> None:
    """Checklist section 24, step 6; section 25, step 6.1: a 302 to a signed address, kept 15 to 30 minutes."""
    answer = get(sample)
    signed_address(answer, target)
    assert 900 <= max_age(answer) <= 1800, answer.header("Cache-Control")


def test_t96_the_signed_address_delivers_the_file(target: Target, sample: str) -> None:
    """Checklist section 25, steps 5 and 6.3: the image itself, twice; the second time from CloudFront's cache (the
    signature isn't part of the cache key, D197). Its file was fetched and stored in the museum's bucket."""
    signed = signed_address(get(sample), target)
    first, second = get(signed), get(signed)
    for answer in (first, second):
        assert answer.status == 200, answer.status
        assert answer.header("Content-Type").startswith("image/"), answer.header("Content-Type")
        assert answer.header("Cache-Control") == "private, max-age=900"
    assert second.header("X-Cache") == "Hit from cloudfront", second.header("X-Cache")


def test_t97_a_bad_or_missing_signature_is_refused(target: Target, sample: str) -> None:
    """Checklist section 25, step 7."""
    signed = signed_address(get(sample), target)
    signature = re.search(r"Signature=([^&]+)", signed)
    assert signature
    value = signature.group(1)
    middle = len(value) // 2
    changed = value[:middle] + ("A" if value[middle] != "A" else "B") + value[middle + 1:]
    assert get(signed.replace(value, changed)).status == 403
    assert get(signed.split("?")[0]).status == 403


def test_t98_the_bucket_only_through_cloudfront(target: Target, sample: str) -> None:
    """Checklist section 25, step 8 (D196): the bucket refuses a direct request, and only /<museum>/objects/… goes to
    it (anything else under the museum is Serena's plain-text 404)."""
    found = SIGNED.search(signed_address(get(sample), target))
    assert found
    region = os.environ["AWS_REGION"]
    direct = get(f"https://{target.bucket}.s3.{region}.amazonaws.com/objects/{found.group('sha')}")
    assert direct.status == 403, direct.status
    other = get(f"{target.url}/{target.museum}/servable-list/x")
    assert other.status == 404, other.status
    assert other.header("Content-Type").startswith("text/plain") and other.header("Cache-Control") == "no-store"


def test_t99_the_unavailable_images(target: Target, sample: str) -> None:
    """Checklist section 25, step 9: a Blob CSID Serena doesn't list gets the museum's unavailable image, which (with
    the generic placeholder) needs no signature."""
    blob = re.search(r"/blobs/([0-9a-f-]{36})/", sample)
    assert blob
    csid = blob.group(1)
    unknown = csid[:-1] + ("0" if csid[-1] != "0" else "1")
    unavailable(get(sample.replace(csid, unknown)), target)
    for path in (f"/{target.museum}/unavailable.svg", "/default/placeholder.svg"):
        answer = get(target.url + path)
        assert answer.status == 200, f"{path}: {answer.status}"
        assert answer.header("Content-Type") == "image/svg+xml", f"{path}: {answer.header('Content-Type')}"
        csp = answer.header("Content-Security-Policy")
        assert csp == SVG_CSP, f"{path}: {csp}"


# ---- the admin app (Selenium) ---------------------------------------------------------------------------------------

def test_t100_the_header_and_past_refreshes(driver: WebDriver, base_url: str, target: Target,
                                            admin: tuple[str, str], request: pytest.FixtureRequest) -> None:
    """Checklist section 24, step 5: the header names the environment and its image; Past refreshes lists the run's
    refresh (personal-dev)."""
    signed_in(driver, base_url, target, admin)
    page = Page(driver, base_url)
    assert page.text_of(ENVIRONMENT) == f"{target.label} · {target.image_tag}"
    if target.simulated:
        refreshes = RefreshesPage(driver, base_url)
        refreshes.open_list(target.museum)
        assert refreshes.text_of(refreshes.TITLE) == f"{target.museum.upper()} Past refreshes"
        refreshes.wait_for(refreshes.row_of(request.getfixturevalue("refresh")["refresh_id"]))


@pytest.mark.after("test_t96_the_signed_address_delivers_the_file")
def test_t101_past_requests_reads_cloudwatch(driver: WebDriver, base_url: str, target: Target,
                                             admin: tuple[str, str], sample: str) -> None:
    """Checklist section 24, step 5; section 25, step 5: Past requests (CloudWatch Logs Insights) lists the sample's
    requests as served, the last from the stored copy (cache "hit"). The log reaches Logs Insights within a few
    minutes."""
    get(sample)  # one more, certainly a hit: T96 stored it
    signed_in(driver, base_url, target, admin)
    page = RequestsPage(driver, base_url)
    path = sample.removeprefix(target.url)

    def listed() -> None:
        page.open_page(target.museum)
        assert page.count(page.line_for(path)), f"no line for {path} yet"

    eventually(listed, seconds=300, every=20)
    cells = page.cells(page.line_for(path))
    assert (cells["Outcome"], cells["Kind"], cells["Cache"]) == ("served", "image", "hit"), cells


@pytest.mark.after("test_t96_the_signed_address_delivers_the_file")
def test_t102_media_look_up_says_served_and_cached(driver: WebDriver, base_url: str, target: Target,
                                                   admin: tuple[str, str], sample: str) -> None:
    """Checklist section 24, step 6: Media look up says served, with the size cached."""
    signed_in(driver, base_url, target, admin)
    page = LookUpPage(driver, base_url)
    page.look_up(target.museum, sample.removeprefix(target.url))
    assert page.wait_for_text(page.VERDICT, "Served", timeout=30).text.startswith("Served")
    assert "Serena has a cached copy" in page.text_of(page.NEXT)


# ---- a recall, then cancelled (personal-dev, D227) ------------------------------------------------------------------

@pytest.mark.changes
@pytest.mark.after("test_t95_a_file_request_redirects_to_a_signed_address")
def test_t103_a_recall_stops_the_address_but_not_a_signed_one(driver: WebDriver, base_url: str, target: Target,
                                                              admin: tuple[str, str], sample: str) -> None:
    """Checklist section 24, step 7; section 25, step 10: the recall's preview names one Media record; then the
    address gets the unavailable image at once, while a signed address handed out before keeps working."""
    signed = signed_address(get(sample), target)
    signed_in(driver, base_url, target, admin)
    page = RecallsPage(driver, base_url)
    page.preview(target.museum, sample)
    assert page.count(page.SUMMARY_ROWS) == 1, "the preview doesn't name exactly one Media record"
    page.type(page.REASON, RECALL_REASON)
    page.click(page.CONFIRM)
    page.wait_for(page.row_with("active-recalls", RECALL_REASON), timeout=30)
    eventually(lambda: unavailable(get(sample), target))
    assert get(signed).status == 200, "a signed address handed out before the recall stopped working"


@pytest.mark.changes
def test_t104_cancelling_the_recall_serves_it_again(driver: WebDriver, base_url: str, target: Target,
                                                    admin: tuple[str, str], sample: str) -> None:
    """Checklist section 24, step 7; section 25, step 10.4. Puts the sample back as it started. It runs whenever T103
    made its recall, even if T103 then failed, so the run never leaves the recall in place."""
    signed_in(driver, base_url, target, admin)
    page = RecallsPage(driver, base_url)
    page.open(f"{target.museum}/recalls")
    try:
        page.wait_for(page.row_with("active-recalls", RECALL_REASON), timeout=20)
    except TimeoutException:
        pytest.skip("T103 made no recall")
    page.cancel(target.museum, RECALL_REASON, CANCEL_REASON)
    assert "Cancelled" in page.wait_for(page.row_with("ended-recalls", CANCEL_REASON), timeout=30).text
    eventually(lambda: signed_address(get(sample), target))
    audit = AuditLogPage(driver, base_url)
    audit.open_page(target.museum)
    audit.wait_for(audit.entry("recall", RECALL_REASON))
    audit.wait_for(audit.entry("recall cancel", CANCEL_REASON))


# ---- last: the logs -------------------------------------------------------------------------------------------------

def test_t105_no_permission_errors_in_the_logs(target: Target) -> None:
    """Checklist section 24, the AccessDenied step; section 25, step 16: no permission error in the last 24 hours of
    the web, worker and (with the simulator) devtools logs. Any means iam.tf is missing a permission."""
    services = ["web", "worker"] + (["devtools"] if target.simulated else [])
    since = str((int(time.time()) - 86400) * 1000)
    found: dict[str, list[str]] = {}
    for service in services:
        events = aws_cli("logs", "filter-log-events", "--log-group-name", f"{target.log_prefix}/{service}",
                         "--start-time", since,
                         "--filter-pattern", '?AccessDenied ?AccessDeniedException ?"not authorized"',
                         "--query", "events[].message")
        if events:
            found[service] = [str(event)[:300] for event in events[:5]]
    assert not found, f"permission errors (iam.tf): {found}"
