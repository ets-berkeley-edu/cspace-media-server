"""Requests answered with the unavailable image (design: Requests Serena doesn't serve).

Each one is logged with its reason and recorded for the admin app. The records hold the museum, the path (with the
PDF link suffix removed), the reason and the time: never an IP address, a header or an email address. In AWS they
are counted in the Unserved requests table (DynamoRecorder); MemoryRecorder keeps them in memory, for tests."""
from __future__ import annotations

import logging
import threading
from collections import Counter, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

log = logging.getLogger("serena.unserved")


class Reason(StrEnum):
    UNKNOWN_MUSEUM = "unknown_museum"
    UNKNOWN_PATH = "unknown_path"
    BAD_CSID = "bad_csid"
    DERIVATIVE_NOT_SERVED = "derivative_not_served"
    # Servability (design: The steps, step 2)
    NOT_LISTED = "not_listed"  # not in the last applied Blob-to-Media file
    KIND_NOT_SERVED = "kind_not_served"  # audio or video, for now
    RESTRICTED = "restricted"  # access restricted (Cinefiles' PDFs other than code 4)
    TAKEN_DOWN = "taken_down"
    NO_DERIVATIVES_FOR_KIND = "no_derivatives_for_kind"  # a derivative of a 3D or PDF Blob
    ORIGINAL_NOT_SERVED = "original_not_served"  # an image's original where the museum doesn't serve it
    RESTRICTED_IMAGE_NOT_UPLOADED = "restricted_image_not_uploaded"
    # Temporary: the Blob is servable, but serving files arrives with the cache (pull request 7 in the plan).
    SERVING_NOT_BUILT = "serving_not_built"
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


def report(recorder: Recorder, museum: str | None, reason: Reason, path: str) -> None:
    """Log and record one unserved request. `path` must come from paths.log_path()."""
    entry = Unserved(museum, reason, path, datetime.now(UTC))
    log.info("unserved", extra={"museum": museum, "reason": reason.value, "path": path})
    try:
        recorder.record(entry)
    except Exception:
        # Recording is for the admin app; a failure to record never changes the answer.
        log.exception("could not record an unserved request", extra={"reason": reason.value})


BUCKET_SECONDS = 300  # counts are kept in 5-minute buckets
KEEP_DAYS = 30
SAMPLES = 5  # recent paths kept per museum, bucket and reason


class DynamoRecorder:
    """Counts unserved requests in this task's memory and writes the totals to the Unserved requests table every
    unserved_flush_seconds (design: Requests Serena doesn't serve): one item per museum, 5-minute bucket and reason,
    with its count and a few recent paths, expiring after 30 days. A crash loses at most the counts since the last
    write. A museum Serena doesn't serve is counted under "default"."""

    def __init__(self, client: Any, table_name: str):
        self.client = client
        self.table_name = table_name
        self._lock = threading.Lock()
        self._pending: dict[tuple[str, int, Reason], tuple[int, deque[str]]] = {}

    def record(self, entry: Unserved) -> None:
        bucket = int(entry.at.timestamp()) // BUCKET_SECONDS * BUCKET_SECONDS
        key = (entry.museum or "default", bucket, entry.reason)
        with self._lock:
            count, samples = self._pending.get(key, (0, deque(maxlen=SAMPLES)))
            samples.append(entry.path)
            self._pending[key] = (count + 1, samples)

    def flush(self) -> int:
        """Write the pending counts; returns how many items were written. What can't be written stays pending."""
        with self._lock:
            pending, self._pending = self._pending, {}
        written = 0
        for (museum, bucket, reason), (count, samples) in pending.items():
            start = datetime.fromtimestamp(bucket, UTC).strftime("%Y-%m-%dT%H:%MZ")
            try:
                self.client.update_item(
                    TableName=self.table_name,
                    Key={"pk": {"S": f"{museum}#{start}"}, "sk": {"S": reason.value}},
                    UpdateExpression="ADD #count :n SET samples = :samples, expires_at = :expires",
                    ExpressionAttributeNames={"#count": "count"},
                    ExpressionAttributeValues={
                        ":n": {"N": str(count)},
                        ":samples": {"L": [{"S": path} for path in samples]},
                        ":expires": {"N": str(bucket + KEEP_DAYS * 86400)},
                    },
                )
                written += 1
            except Exception:
                log.warning("could not write unserved-request counts; keeping them for the next write",
                            exc_info=True, extra={"museum": museum, "reason": reason.value})
                with self._lock:
                    old_count, old_samples = self._pending.get((museum, bucket, reason), (0, deque(maxlen=SAMPLES)))
                    old_samples.extendleft(reversed(samples))
                    self._pending[(museum, bucket, reason)] = (old_count + count, old_samples)
        return written
