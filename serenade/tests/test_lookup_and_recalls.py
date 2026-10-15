"""The pilot: Media look up and Recalls for PAHMA, checks T1 to T6 of the test inventory (serena-test-inventory.xlsx;
docs/testing-checklist.md sections 11, 17 and 19).

They run in this order on one dataset (serenade/dataset.py), with no reset: T1 and T2 only look at the shared image;
T3 to T5 change the reserved image and put it back; T6 affects every museum, so it runs last and undoes itself. A test
that builds on an earlier one is skipped if that one didn't pass (@pytest.mark.after)."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from selenium.webdriver.remote.webdriver import WebDriver

from serenade.dataset import MUSEUM, RESERVED_IMAGE, SHARED_IMAGE
from serenade.pages.lookup_page import LookUpPage
from serenade.pages.recalls_page import RecallsPage
from serenade.pages.sign_in_page import SignInPage
from serenade.stack import calls_to_simulator, eventually, redirect_of, simulator

pytestmark = pytest.mark.usefixtures("built_dataset")

ADMIN = ("admin", "admin")  # the simulator's synthetic account: its password is its username
STORED = f"/local-cdn/{MUSEUM}/objects/"
UNAVAILABLE = f"/unavailable/{MUSEUM}.svg"
RECALL_REASON = "serenade T3: a test recall"
CANCEL_REASON = "serenade T5: a test cancel"


def signed_in(driver: WebDriver, base_url: str) -> None:
    SignInPage(driver, base_url).sign_in("PAHMA", *ADMIN)
    SignInPage(driver, base_url).wait_for_url(f"/admin/{MUSEUM}")


def served(path: str) -> None:
    assert STORED in redirect_of(path), f"{path} isn't served from Serena's stored copy"


def unavailable(path: str) -> None:
    assert redirect_of(path).endswith(UNAVAILABLE), f"{path} doesn't get the unavailable image"


def test_t1_a_served_image_comes_from_the_stored_copy() -> None:
    """Checklist section 11, step 2; section 17, step 1."""
    served(SHARED_IMAGE.path())
    served(SHARED_IMAGE.path())
    fetch = f"media/{SHARED_IMAGE.media}/blob/derivatives/Medium/content"
    fetches = [c for c in calls_to_simulator() if c.endswith(fetch)]
    assert len(fetches) == 1, f"expected one fetch from CollectionSpace, got {fetches}"


@pytest.mark.after("test_t1_a_served_image_comes_from_the_stored_copy")
def test_t2_media_look_up_says_served(driver: WebDriver, base_url: str) -> None:
    """Checklist section 17, step 2."""
    signed_in(driver, base_url)
    page = LookUpPage(driver, base_url)
    page.look_up(MUSEUM, SHARED_IMAGE.path())
    verdict = page.wait_for_text(page.VERDICT, "Served").text
    assert "Every check passes for the Medium size." in verdict
    assert "Serena has a cached copy" in page.text_of(page.NEXT)


def test_t3_a_recall_stops_serving(driver: WebDriver, base_url: str) -> None:
    """Checklist section 17, steps 5, 7 and 8. Changes the reserved image."""
    served(RESERVED_IMAGE.path())
    signed_in(driver, base_url)
    page = RecallsPage(driver, base_url)
    page.recall(MUSEUM, RESERVED_IMAGE.media, RECALL_REASON)
    row = page.wait_for(page.row_with("active-recalls", RECALL_REASON)).text
    assert "Waiting for a later refresh" in row and "admin" in row
    eventually(lambda: unavailable(RESERVED_IMAGE.path()))


@pytest.mark.after("test_t3_a_recall_stops_serving")
def test_t4_media_look_up_says_recalled(driver: WebDriver, base_url: str) -> None:
    """Checklist section 17, step 8."""
    signed_in(driver, base_url)
    page = LookUpPage(driver, base_url)
    page.look_up(MUSEUM, RESERVED_IMAGE.path())
    assert "Not served: recalled" in page.wait_for_text(page.VERDICT, "Not served: recalled").text
    assert RECALL_REASON in page.text_of(page.VERDICT)
    assert "Open Recalls" in page.text_of(page.NEXT)


@pytest.mark.after("test_t3_a_recall_stops_serving")
def test_t5_cancelling_the_recall_serves_it_again(driver: WebDriver, base_url: str) -> None:
    """Checklist section 17, "Cancel a recall made by mistake". Puts the reserved image back as it started."""
    signed_in(driver, base_url)
    page = RecallsPage(driver, base_url)
    page.cancel(MUSEUM, RECALL_REASON, CANCEL_REASON)
    row = page.wait_for(page.row_with("ended-recalls", CANCEL_REASON)).text
    assert "Cancelled" in row
    eventually(lambda: served(RESERVED_IMAGE.path()))


@pytest.fixture
def outage() -> Iterator[None]:
    """The simulator's outage switch: every CollectionSpace call answers 503 while it's on. Always switched off
    again, even when the test fails, so the dataset is left as it was."""
    simulator("POST", "/_fake/unreachable", {"on": True})
    try:
        yield
    finally:
        simulator("POST", "/_fake/unreachable", {"on": False})


@pytest.mark.usefixtures("outage")
def test_t6_media_look_up_while_collectionspace_cant_be_reached(driver: WebDriver, base_url: str) -> None:
    """Checklist section 19, the outage step. Museum-wide, so last."""
    signed_in(driver, base_url)
    page = LookUpPage(driver, base_url)
    page.look_up(MUSEUM, SHARED_IMAGE.path())
    # Serena retries CollectionSpace first, so the answer takes a few seconds.
    down = page.wait_for(page.CSPACE_DOWN, timeout=60).text
    assert "CollectionSpace can't be reached, so there's nothing to compare with" in down
    assert page.text_of(page.HEADING).startswith(f"Media {SHARED_IMAGE.media}")
    assert "Served" in page.text_of(page.VERDICT)
