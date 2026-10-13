"""Requests answered with the unavailable image (design: Requests Serena doesn't serve).

Each one is logged with the museum, its reason and the path (with the PDF link suffix removed): never an IP address,
a header or an email address. The admin app's Past requests page reads these lines from the log (requests_log.py;
decided October 12, 2026, D102, which replaced the Unserved requests table). Tests may pass a recorder
(MemoryRecorder) to see each one as it happens."""
from __future__ import annotations

import logging
import threading
from collections import Counter, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

log = logging.getLogger("serena.unserved")


class Reason(StrEnum):
    UNKNOWN_MUSEUM = "unknown_museum"
    UNKNOWN_PATH = "unknown_path"
    BAD_CSID = "bad_csid"
    DERIVATIVE_NOT_SERVED = "derivative_not_served"
    # Servability (design: The steps, step 2)
    NOT_LISTED = "not_listed"  # not in the servable list of the last servability update
    KIND_NOT_SERVED = "kind_not_served"  # audio or video, for now
    RESTRICTED = "restricted"  # access restricted, without a signed link or of a kind without signed access
    SIGNATURE_INVALID = "signature_invalid"  # a signed link that is malformed, has an unknown key ID or doesn't match
    SIGNATURE_EXPIRED = "signature_expired"  # a signed link that has expired, or expires too far ahead
    RECALLED = "recalled"
    NO_DERIVATIVES_FOR_KIND = "no_derivatives_for_kind"  # a derivative of a 3D or PDF Blob
    ORIGINAL_NOT_SERVED = "original_not_served"  # an image's original where the museum doesn't serve it
    PLACEHOLDER_NOT_UPLOADED = "placeholder_not_uploaded"
    # Temporary: a size the museum watermarks, until watermarking is built (pull request 16 in the plan).
    WATERMARK_NOT_BUILT = "watermark_not_built"
    # A miss (design: Image fetch): the light check, then the fetch and its checks
    MEDIA_GONE = "media_gone"  # the Media record isn't in CollectionSpace (404)
    MEDIA_DELETED = "media_deleted"  # the Media record is soft-deleted
    NO_FILE = "no_file"  # the Media record exists, but CollectionSpace has no such file or size (404)
    CSPACE_UNAVAILABLE = "cspace_unavailable"  # no answer, or 429 or 5xx after the retries
    CSPACE_REFUSED = "cspace_refused"  # 401, 403 or another unexpected answer: Serena's account or configuration
    WRONG_CONTENT_TYPE = "wrong_content_type"  # not a type the kind allows, or a "PDF" without %PDF-
    TOO_LARGE = "too_large"  # over the museum's size limit for the kind
    NOT_DECODABLE = "not_decodable"  # an image or card that doesn't decode
    FETCH_BUSY = "fetch_busy"  # not enough local disk to fetch it now
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True)
class Unserved:
    museum: str | None  # None: a museum Serena doesn't serve
    reason: Reason
    path: str  # already cleaned by paths.log_path()
    at: datetime


class Recorder(Protocol):
    def record(self, entry: Unserved) -> None: ...


class MemoryRecorder:
    """The most recent unserved requests and a count per museum and reason, in this task's memory."""

    def __init__(self, keep: int = 1000):
        self._lock = threading.Lock()
        self.recent: deque[Unserved] = deque(maxlen=keep)
        self.counts: Counter[tuple[str | None, Reason]] = Counter()

    def record(self, entry: Unserved) -> None:
        with self._lock:
            self.recent.append(entry)
            self.counts[(entry.museum, entry.reason)] += 1


def report(recorder: Recorder | None, museum: str | None, reason: Reason, path: str) -> None:
    """Log one unserved request, and hand it to the recorder if there is one (tests). `path` must come from
    paths.log_path()."""
    log.info("unserved", extra={"museum": museum, "reason": reason.value, "path": path})
    if recorder is None:
        return
    try:
        recorder.record(Unserved(museum, reason, path, datetime.now(UTC)))
    except Exception:
        # A failure to record never changes the answer.
        log.exception("could not record an unserved request", extra={"reason": reason.value})
