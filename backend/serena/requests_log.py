"""What Serena served and couldn't serve, read from its log, for the admin app's Past requests page (design: The
Past requests page; decided October 12, 2026, D100 to D113).

The app logs one line per request: "served" (with the path, kind, cache hit or miss and whether a signed link was
used) or "unserved" (with the reason and the path). Paths never carry the PDF link suffix or a query string, and no
line holds an IP address, a signed link's uid or sig, or an email address. A report runs four fixed queries for one
museum over one range: the lines, newest first (at most MAX_LINES), served requests by day, unserved requests by day
and reason, and the most-requested paths.

In AWS, CloudWatchReader runs them with CloudWatch Logs Insights on the app's log group. Locally and in tests,
FileReader runs the same queries in Python over the JSON lines the app also writes to a file (SERENA_LOG_FILE).
Logs Insights can't limit a query to one museum; the museum filter in every query does, and the museum in it always
comes from Serena's list of museums."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger("serena.requests_log")

RANGES = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7)}  # D106
DEFAULT_RANGE = "24h"
MAX_LINES = 10_000  # the most a Logs Insights query returns (D107)
TOP_PATHS = 20
CACHE_SECONDS = 60.0  # D108: reloads within a minute don't start new queries
WAIT_SECONDS = 30.0  # D108: past this, the queries are stopped and the admin is asked for a shorter range
LOGGERS = {"served": "serena.imageserver", "unserved": "serena.unserved"}
_MUSEUM = re.compile(r"^[a-z]+$")


class QueryKind(StrEnum):
    LINES = "lines"
    SERVED_BY_DAY = "served_by_day"
    UNSERVED_BY_DAY = "unserved_by_day"
    TOP_PATHS = "top_paths"


class LogUnavailable(Exception):
    """The log couldn't be read: not configured here, a failed query, or one that took too long."""


class TooSlow(LogUnavailable):
    pass


@dataclass(frozen=True)
class Line:
    at: str  # ISO time, UTC
    outcome: str  # served or unserved
    reason: str  # unserved only; "" when served
    path: str
    kind: str  # "" when not known (an unserved request)
    cache: str  # hit or miss; "" when unserved
    signed: bool


@dataclass(frozen=True)
class Day:
    day: str  # YYYY-MM-DD, UTC
    served: int
    unserved: dict[str, int]  # by reason


@dataclass(frozen=True)
class Report:
    museum: str
    range: str
    start: datetime
    end: datetime
    days: list[Day]
    top_paths: list[tuple[str, int]]
    lines: list[Line]

    @property
    def truncated(self) -> bool:
        return len(self.lines) >= MAX_LINES


Row = dict[str, str]


class Reader(Protocol):
    def run(self, museum: str, start: datetime, end: datetime) -> dict[QueryKind, list[Row]]: ...


def _checked(museum: str) -> str:
    if not _MUSEUM.match(museum):
        raise ValueError("a museum key is lowercase letters only")
    return museum


def query_text(kind: QueryKind, museum: str) -> str:
    """The Logs Insights query. `museum` comes from Serena's list of museums and is checked again here, so nothing
    an admin types can change a query."""
    base = (f'filter museum = "{_checked(museum)}" and '
            f'((message = "served" and logger = "{LOGGERS["served"]}") or '
            f'(message = "unserved" and logger = "{LOGGERS["unserved"]}"))')
    if kind is QueryKind.LINES:
        return (f"fields time, message, reason, path, kind, cache, signed | {base} "
                f"| sort @timestamp desc | limit {MAX_LINES}")
    if kind is QueryKind.SERVED_BY_DAY:
        return f'{base} | filter message = "served" | stats count(*) as requests by datefloor(@timestamp, 1d) as day'
    if kind is QueryKind.UNSERVED_BY_DAY:
        return (f'{base} | filter message = "unserved" '
                "| stats count(*) as requests by datefloor(@timestamp, 1d) as day, reason")
    return f"{base} | stats count(*) as requests by path | sort requests desc | limit {TOP_PATHS}"


class CloudWatchReader:
    """Runs the four queries with CloudWatch Logs Insights, at the same time, and waits for them (D108)."""

    def __init__(self, client: Any, log_group: str, wait_seconds: float = WAIT_SECONDS, poll_seconds: float = 1.0,
                 sleep: Callable[[float], None] = time.sleep, monotonic: Callable[[], float] = time.monotonic):
        self.client = client
        self.log_group = log_group
        self.wait_seconds = wait_seconds
        self.poll_seconds = poll_seconds
        self.sleep = sleep
        self.monotonic = monotonic

    def run(self, museum: str, start: datetime, end: datetime) -> dict[QueryKind, list[Row]]:
        ids: dict[QueryKind, str] = {}
        try:
            for kind in QueryKind:
                ids[kind] = self.client.start_query(
                    logGroupName=self.log_group, startTime=int(start.timestamp()), endTime=int(end.timestamp()),
                    queryString=query_text(kind, museum), limit=MAX_LINES)["queryId"]
            return self._wait(ids)
        except LogUnavailable:
            raise
        except Exception as error:
            log.warning("could not query the log", extra={"museum": museum, "error": type(error).__name__})
            self._stop(ids)
            raise LogUnavailable("Serena couldn't read its log just now. Try again in a minute.") from error

    def _wait(self, ids: dict[QueryKind, str]) -> dict[QueryKind, list[Row]]:
        deadline = self.monotonic() + self.wait_seconds
        done: dict[QueryKind, list[Row]] = {}
        while True:
            for kind, query_id in ids.items():
                if kind in done:
                    continue
                answer = self.client.get_query_results(queryId=query_id)
                status = answer["status"]
                if status == "Complete":
                    done[kind] = [{cell["field"]: cell["value"] for cell in row} for row in answer["results"]]
                elif status not in ("Scheduled", "Running"):
                    self._stop({k: v for k, v in ids.items() if k not in done})
                    raise LogUnavailable(f"A query of the log ended {status.lower()}. Try again in a minute.")
            if len(done) == len(ids):
                return done
            if self.monotonic() >= deadline:
                self._stop({k: v for k, v in ids.items() if k not in done})
                raise TooSlow("Reading the log took too long. Choose a shorter range, or try again in a minute.")
            self.sleep(self.poll_seconds)

    def _stop(self, ids: dict[QueryKind, str]) -> None:
        for query_id in ids.values():
            try:
                self.client.stop_query(queryId=query_id)
            except Exception as error:  # it may have finished in the meantime
                log.info("could not stop a query of the log", extra={"error": type(error).__name__})


class FileReader:
    """Local development and tests (D109): the same four queries, in Python, over the JSON lines the app writes to
    a file (and its one rotated copy, <file>.1)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def entries(self) -> Iterator[dict[str, Any]]:
        for file in (Path(f"{self.path}.1"), self.path):
            if not file.exists():
                continue
            with file.open(encoding="utf-8") as lines:
                for text in lines:
                    try:
                        entry = json.loads(text)
                    except ValueError:
                        continue
                    if isinstance(entry, dict):
                        yield entry

    def run(self, museum: str, start: datetime, end: datetime) -> dict[QueryKind, list[Row]]:
        _checked(museum)
        chosen = []
        for entry in self.entries():
            message = entry.get("message")
            if entry.get("museum") != museum or LOGGERS.get(str(message)) != entry.get("logger"):
                continue
            try:
                at = datetime.fromisoformat(str(entry["time"]))
            except (KeyError, ValueError):
                continue
            if start <= at <= end:
                chosen.append((at, entry))
        chosen.sort(key=lambda pair: pair[0], reverse=True)
        lines = [{key: _text(entry.get(key)) for key in ("time", "message", "reason", "path", "kind", "cache",
                                                          "signed") if entry.get(key) is not None}
                 for _, entry in chosen[:MAX_LINES]]
        served: Counter[str] = Counter()
        unserved: Counter[tuple[str, str]] = Counter()
        paths: Counter[str] = Counter()
        for at, entry in chosen:
            day = f"{at.astimezone(UTC).date().isoformat()} 00:00:00.000"
            if entry["message"] == "served":
                served[day] += 1
            else:
                unserved[(day, _text(entry.get("reason")))] += 1
            paths[_text(entry.get("path"))] += 1
        return {
            QueryKind.LINES: lines,
            QueryKind.SERVED_BY_DAY: [{"day": day, "requests": str(n)} for day, n in served.items()],
            QueryKind.UNSERVED_BY_DAY: [{"day": day, "reason": reason, "requests": str(n)}
                                        for (day, reason), n in unserved.items()],
            QueryKind.TOP_PATHS: [{"path": path, "requests": str(n)}
                                  for path, n in sorted(paths.items(), key=lambda p: (-p[1], p[0]))[:TOP_PATHS]],
        }


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _day(value: str) -> str:
    return value[:10]  # "2026-10-12 00:00:00.000" from datefloor


def build(museum: str, range_: str, start: datetime, end: datetime, rows: dict[QueryKind, list[Row]]) -> Report:
    days: dict[str, tuple[int, dict[str, int]]] = {}
    for row in rows[QueryKind.SERVED_BY_DAY]:
        day = _day(row.get("day", ""))
        served, unserved = days.get(day, (0, {}))
        days[day] = (served + int(row.get("requests", "0")), unserved)
    for row in rows[QueryKind.UNSERVED_BY_DAY]:
        day = _day(row.get("day", ""))
        served, unserved = days.get(day, (0, {}))
        reason = row.get("reason", "")
        unserved[reason] = unserved.get(reason, 0) + int(row.get("requests", "0"))
        days[day] = (served, unserved)
    lines = [Line(
        at=row.get("time", ""), outcome=row.get("message", ""), reason=row.get("reason", ""),
        path=row.get("path", ""), kind=row.get("kind", ""), cache=row.get("cache", ""),
        signed=row.get("signed", "").lower() in ("true", "1")) for row in rows[QueryKind.LINES]]
    return Report(
        museum=museum, range=range_, start=start, end=end,
        days=[Day(day, served, dict(sorted(unserved.items()))) for day, (served, unserved) in sorted(days.items(),
                                                                                                   reverse=True)],
        top_paths=[(row.get("path", ""), int(row.get("requests", "0"))) for row in rows[QueryKind.TOP_PATHS]],
        lines=lines)


@dataclass
class Requests:
    """Reports by museum and range, each kept CACHE_SECONDS so reloads don't start new queries (D108)."""

    reader: Reader | None
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    cache_seconds: float = CACHE_SECONDS
    _cache: dict[tuple[str, str], tuple[datetime, Report]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def report(self, museum: str, range_: str) -> Report:
        if self.reader is None:
            raise LogUnavailable("The request log isn't available in this environment.")
        if range_ not in RANGES:
            raise ValueError(f"range must be one of {', '.join(RANGES)}")
        now = self.clock()
        with self._lock:
            kept = self._cache.get((museum, range_))
            if kept is not None and kept[0] > now:
                return kept[1]
        start = now - RANGES[range_]
        report = build(museum, range_, start, now, self.reader.run(museum, start, now))
        with self._lock:
            self._cache[(museum, range_)] = (now + timedelta(seconds=self.cache_seconds), report)
        return report


def lines_matching(report: Report, outcome: str | None, reason: str | None) -> Iterable[Line]:
    """The lines a filter on the page shows (D113): by outcome (served or unserved) and by reason."""
    for line in report.lines:
        if outcome and line.outcome != outcome:
            continue
        if reason and line.reason != reason:
            continue
        yield line
