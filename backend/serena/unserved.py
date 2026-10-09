"""Requests answered with the unavailable image (design: Requests Serena doesn't serve).

Each one is logged with its reason and recorded for the admin app. The records hold the museum, the path (with the
PDF link suffix removed), the reason and the time: never an IP address, a header or an email address. This keeps
them in memory; the DynamoDB table (counts in short time buckets, a few samples, expiry after 30 days) replaces it
with the other tables."""
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
    NOT_SERVABLE = "not_servable"
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
