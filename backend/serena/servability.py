"""Whether a Blob may be served (design: The steps, step 2; Kinds; Servability).

A Blob is servable when the servable list of the last servability update includes it, its kind is one Serena serves,
its access is public (or restricted, with a valid signed link, for a kind the museum allows signed access to), and its
Media record has no active recall. Then the request must fit the kind: a 3D file or PDF only as its original file,
and an image's original only where the museum serves originals."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from . import tables
from .museum import SERVED_KINDS, Museum
from .paths import BlobRequest, MediaRequest
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
           vouch: Callable[[], Verdict] | None = None, placeholder_media: str | None = None) -> Decision:
    """`vouch` checks the request's signed link (design: Signed links); it's called only for a restricted Blob of a
    kind the museum allows signed access to. A valid link lets the rest of the checks run, so a recall still wins.

    `placeholder_media` is the Media record an admin named for the museum's placeholder image (D166): its files are
    served for the placeholder's Blob, which the servable list lists without a Media CSID. Without one, the placeholder
    gets Serena's generic picture (D168)."""
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
        recall = store.recall(museum.key, record.media_csid)
        if recall is not None:
            return Decision(Reason.RECALLED, record)
    if request.blob_csid == museum.placeholder_blob_csid:
        if placeholder_media is None:
            return Decision(Reason.PLACEHOLDER_NOT_SET, record)
        record = replace(record, media_csid=placeholder_media)  # fetched through the named Media record
    return Decision(None, record, signed_kid)


def listed_blobs(store: Store, tenant: str, media_csid: str) -> list[str]:
    """A Media record's Blobs in the servability table, the one listed most recently first (D175); rows written before
    `listed_at` was recorded come last, by Blob CSID."""
    page = store.client.query(TableName=store.table(tables.SERVABILITY), IndexName="by_media",
                              KeyConditionExpression="media_key = :m",
                              ExpressionAttributeValues={":m": {"S": f"{tenant}#{media_csid}"}})
    found = [(item.get("listed_at", {}).get("S", ""), item["pk"]["S"].partition("#")[2]) for item in page["Items"]]
    return [blob for _, blob in sorted(found, key=lambda pair: (pair[0], pair[1]), reverse=True)]


def resolve(museum: Museum, request: MediaRequest, store: Store) -> tuple[BlobRequest | None, Decision]:
    """A request by Media CSID, answered as one for its listed Blob (decided October 14, 2026, D174 to D177): the first
    of its Blobs, newest first, that passes every check a Blob request gets; if none passes, the newest one's reason.
    No signed link: a Media URL serves public files only (D177)."""
    blobs = listed_blobs(store, museum.key, request.media_csid)
    if not blobs:
        return None, Decision(Reason.NOT_LISTED)
    tried = []
    for blob in blobs:
        as_blob = BlobRequest(museum.key, blob, request.derivative)
        decision = decide(museum, as_blob, store)
        if decision.servable:
            return as_blob, decision
        tried.append((as_blob, decision))
    return tried[0]
