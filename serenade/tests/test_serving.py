"""Serving: what Serena answers a file request with, checks T1, T7, T8, T9, T14 and T15 of the test inventory
(serena-test-inventory.xlsx; docs/testing-checklist.md sections 11, 16, 17, 21 and 23). Plain HTTP, no browser.

They run first (conftest.py: FILE_ORDER) and only look: T1 caches the shared image's Medium size and T14 its Small
size, and the refused requests (T8, T15) give Past requests its unserved lines. T10 to T13 are covered by the
backend's own tests (the inventory's "Skip: covered")."""
from __future__ import annotations

import pytest

from serenade.dataset import CINEFILES, MUSEUM, SHARED_CARD, SHARED_IMAGE, sample, unknown_csid
from serenade.stack import calls_to_simulator, redirect_of

pytestmark = pytest.mark.usefixtures("built_dataset")


def served(path: str, museum: str = MUSEUM) -> None:
    assert f"/local-cdn/{museum}/objects/" in redirect_of(path), f"{path} isn't served from Serena's stored copy"


def unavailable(path: str, museum: str = MUSEUM) -> None:
    assert redirect_of(path).endswith(f"/unavailable/{museum}.svg"), f"{path} doesn't get the unavailable image"


def fetches_of(media: str, size: str) -> int:
    """How many times Serena has fetched a size of a Media record from CollectionSpace (through the Media service)."""
    tail = f"media/{media}/blob/derivatives/{size}/content" if size != "original" else f"media/{media}/blob/content"
    return sum(1 for call in calls_to_simulator() if call.endswith(tail))


def test_t1_a_served_image_comes_from_the_stored_copy() -> None:
    """Checklist section 11, step 2; section 17, step 1."""
    served(SHARED_IMAGE.path())
    served(SHARED_IMAGE.path())
    assert fetches_of(SHARED_IMAGE.media, "Medium") == 1, "expected one fetch from CollectionSpace"


def test_t7_cinefiles_pdfs_public_served_restricted_not_without_a_signed_link() -> None:
    """Checklist section 11, step 3."""
    served(sample(CINEFILES, "pdf"), CINEFILES)
    unavailable(sample(CINEFILES, "pdf (restricted)"), CINEFILES)


def test_t8_requests_serena_refuses_get_the_unavailable_image() -> None:
    """Checklist section 16, step 1; section 21, step 1. Not listed, a bad CSID (with signed-link parameters, which
    Past requests must never show), and a size Serena doesn't serve."""
    unavailable(f"/{MUSEUM}/imageserver/blobs/{unknown_csid(8)}/derivatives/Medium/content")
    unavailable(f"/{MUSEUM}/imageserver/blobs/not_a_csid/derivatives/Medium/content?uid=serenade&sig=0000")
    unavailable(SHARED_IMAGE.path("Thumbnial"))


def test_t9_a_catalog_card_is_served() -> None:
    """Checklist section 11, step 2."""
    served(SHARED_CARD.path())


def test_t14_a_media_url_is_served_as_its_listed_blobs_sharing_its_cache() -> None:
    """Checklist section 23, step 1. Small, which nothing else requests, so the fetch can be counted."""
    before = fetches_of(SHARED_IMAGE.media, "Small")
    served(f"/{MUSEUM}/imageserver/media/{SHARED_IMAGE.media}/blob/derivatives/Small/content")
    served(SHARED_IMAGE.path("Small"))
    assert fetches_of(SHARED_IMAGE.media, "Small") - before == 1, "the Media and Blob URLs didn't share one fetch"


def test_t15_media_urls_the_original_and_an_unknown_media_csid() -> None:
    """Checklist section 23, steps 2 and 3. PAHMA serves originals (museums/pahma.yaml), so the Media URL's original is
    served, as the Blob's would be."""
    served(f"/{MUSEUM}/imageserver/media/{SHARED_IMAGE.media}/blob/content")
    unavailable(f"/{MUSEUM}/imageserver/media/{unknown_csid(15)}/blob/derivatives/Medium/content")
