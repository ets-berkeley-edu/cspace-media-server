"""Whether a Blob may be served (design: The steps, step 2; Kinds; Servability).

A Blob is servable when the last applied Blob-to-Media file lists it, its kind is one Serena serves, its access is
public (or restricted, with a valid signed link, for a kind the museum allows signed access to), and its Media record
has no active takedown. Then the request must fit the kind: a 3D file or PDF only as
its original file, and an image's original only where the museum serves originals."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .museum import SERVED_KINDS, Museum
from .paths import BlobRequest
from .signed_links import Verdict
from .store import ServabilityRecord, Store
from .unserved import Reason

ORIGINAL_ONLY_KINDS = frozenset({"3D", "pdf"})


@dataclass(frozen=True)
class Decision:
    reason: Reason | None  # None: servable
    record: ServabilityRecord | None = None
    signed_kid: str | None = None  # a restricted file vouched for by a signed link: the key ID that signed it

    @property
    def servable(self) -> bool:
        return self.reason is None


def decide(museum: Museum, request: BlobRequest, store: Store,
           vouch: Callable[[], Verdict] | None = None) -> Decision:
    """`vouch` checks the request's signed link (design: Signed links); it's called only for a restricted Blob of a
    kind the museum allows signed access to. A valid link lets the rest of the checks run, so a takedown still wins."""
    record = store.servability(museum.key, request.blob_csid)
    if record is None:
        return Decision(Reason.NOT_LISTED)
    if record.kind not in SERVED_KINDS:
        return Decision(Reason.KIND_NOT_SERVED, record)
    signed_kid = None
    if record.access != "public":
        if record.access != "restricted" or record.kind not in museum.signed_access_kinds or vouch is None:
            return Decision(Reason.RESTRICTED, record)
        verdict = vouch()
        if verdict.reason is not None:
            return Decision(verdict.reason, record)
        signed_kid = verdict.kid
    if request.derivative is not None and record.kind in ORIGINAL_ONLY_KINDS:
        return Decision(Reason.NO_DERIVATIVES_FOR_KIND, record)
    if request.derivative is None and record.kind not in ORIGINAL_ONLY_KINDS and not museum.original:
        return Decision(Reason.ORIGINAL_NOT_SERVED, record)
    if record.media_csid is not None:
        takedown = store.takedown(museum.key, record.media_csid)
        if takedown is not None and takedown.active:
            return Decision(Reason.TAKEN_DOWN, record)
    if request.blob_csid == museum.restricted_image_blob_csid:
        # Served from the files an admin uploads (pull request 14 in the plan); none yet.
        return Decision(Reason.RESTRICTED_IMAGE_NOT_UPLOADED, record)
    return Decision(None, record, signed_kid)
