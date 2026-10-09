"""Whether a Blob may be served (design: The steps, step 2; Kinds; Servability).

A Blob is servable when the last applied Blob-to-Media file lists it, its kind is one Serena serves, its access is
public, and its Media record has no active takedown. Then the request must fit the kind: a 3D file or PDF only as
its original file, and an image's original only where the museum serves originals."""
from __future__ import annotations

from dataclasses import dataclass

from .museum import SERVED_KINDS, Museum
from .paths import BlobRequest
from .store import ServabilityRecord, Store
from .unserved import Reason

ORIGINAL_ONLY_KINDS = frozenset({"3D", "pdf"})


@dataclass(frozen=True)
class Decision:
    reason: Reason | None  # None: servable
    record: ServabilityRecord | None = None

    @property
    def servable(self) -> bool:
        return self.reason is None


def decide(museum: Museum, request: BlobRequest, store: Store) -> Decision:
    record = store.servability(museum.key, request.blob_csid)
    if record is None:
        return Decision(Reason.NOT_LISTED)
    if record.kind not in SERVED_KINDS:
        return Decision(Reason.KIND_NOT_SERVED, record)
    if record.access != "public":
        return Decision(Reason.RESTRICTED, record)
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
    return Decision(None, record)
