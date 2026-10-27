"""Daily request counts by museum (issue #96): for each UTC day, the served requests answered from the cache (hits)
and those that needed a fetch from CollectionSpace (misses), and the unserved requests by reason.

The app's log is kept only log_retention_days (30 in AWS), so the worker counts each day once it's over and keeps the
count in the request-counts table for good (one item per museum per day: pk <museum>, sk <YYYY-MM-DD>). Weeks (ISO,
Monday start), months and years are sums of days, all in UTC. Once an hour until it succeeds, and then once a UTC
day, it counts every day still in the log that has no item yet: so its first run backfills the days the log still
holds, and a day missed while the worker was down is counted on its next run. Each count is two Logs Insights queries
for a museum, however many days they cover; a day already counted is never counted again.

The admin app's Past requests page reads them by day, ISO week, month or year (summary()): the stored days, and the
days not counted yet (today, and yesterday until the worker has counted it) tallied from the log as the page asks,
each summary kept LIVE_CACHE_SECONDS."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from . import tables
from .requests_log import FreshReads, LogUnavailable, Reader, Tally, TooSlow
from .store import Store

log = logging.getLogger("serena.request_counts")

# A day is counted this long after it ends, so the log has every line of it (CloudWatch Logs can take minutes).
SETTLE = timedelta(hours=1)
# Days whose oldest lines are this close to the log's retention aren't counted: part of them may be gone already.
RETENTION_MARGIN_DAYS = 2
# The page's summaries are kept this long per museum, so reloads and the Day / Week / Month / Year switch don't start
# new queries of the log (as D108 for the rest of the page).
LIVE_CACHE_SECONDS = 60.0
# How many periods the page lists, newest first: 31 days, 13 weeks, 12 months, 10 years.
SHOWN = {"day": 31, "week": 13, "month": 12, "year": 10}


@dataclass(frozen=True)
class DayCount:
    day: str  # YYYY-MM-DD, UTC
    hits: int = 0
    misses: int = 0
    unserved: dict[str, int] = field(default_factory=dict)  # by reason
    counted_at: str = ""  # ISO time, UTC
    live: bool = False  # tallied from the log just now, not stored: today, or a day the worker hasn't counted yet

    @property
    def served(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float | None:
        """Hits / served; None when nothing was served."""
        return self.hits / self.served if self.served else None

    def item(self, tenant: str) -> dict[str, Any]:
        return {"pk": {"S": tenant}, "sk": {"S": self.day}, "hits": {"N": str(self.hits)},
                "misses": {"N": str(self.misses)},
                "unserved": {"M": {reason: {"N": str(n)} for reason, n in sorted(self.unserved.items())}},
                "counted_at": {"S": self.counted_at}}

    @classmethod
    def of(cls, item: dict[str, Any]) -> DayCount:
        return cls(item["sk"]["S"], int(item.get("hits", {}).get("N", "0")), int(item.get("misses", {}).get("N", "0")),
                   {reason: int(n["N"]) for reason, n in item.get("unserved", {}).get("M", {}).items()},
                   item.get("counted_at", {}).get("S", ""))


def latest_countable(now: datetime) -> date:
    """The latest UTC day that's over and settled."""
    return (now.astimezone(UTC) - SETTLE).date() - timedelta(days=1)


def earliest_countable(now: datetime, retention_days: int) -> date:
    """The earliest UTC day the log still holds in full."""
    return now.astimezone(UTC).date() - timedelta(days=retention_days - RETENTION_MARGIN_DAYS)


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time(), tzinfo=UTC)


@dataclass(frozen=True)
class PeriodCount:
    period: str  # "2026-10-25", "2026-W43", "2026-10" or "2026"
    first_day: str  # the period's first and last days (a whole week, month or year)
    last_day: str
    hits: int
    misses: int
    unserved: int
    live: bool  # holds a day not counted yet: today's period, so far
    partial: bool  # the first period counted, and counting began after its first day


@dataclass(frozen=True)
class Summary:
    period: str
    today: str
    since: str | None  # the first day counted; None before any count
    hits: int  # every day counted, and the live days
    misses: int
    unserved: int
    rows: list[PeriodCount]  # newest first, SHOWN[period] at most
    live_unavailable: str | None = None  # why today's (and any uncounted day's) counts couldn't be read
    read_at: str = ""  # when today's (and any uncounted day's) counts were read from the log, ISO, UTC (issue #100)
    try_again_in: int | None = None  # a refused fresh read (issue #100): the seconds until the next one


class RequestCounts:
    def __init__(self, store: Store, reader: Reader | None, retention_days: int,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 cache_seconds: float = LIVE_CACHE_SECONDS, fresh: FreshReads | None = None):
        self.store = store
        self.reader = reader
        self.retention_days = retention_days
        self.clock = clock
        self.cache_seconds = cache_seconds
        self.fresh = fresh or FreshReads()  # Past requests' Refresh (issue #100), as for its report
        self._cache: dict[str, tuple[datetime, list[DayCount], str | None, datetime]] = {}
        self._lock = threading.Lock()

    def summary(self, tenant: str, period: str, fresh: bool = False) -> Summary:
        """The museum's counts by period for the Past requests page, newest first, with the totals of every day. A
        fresh summary (Refresh, issue #100) reads the days not counted yet from the log again, at most once per
        museum every FRESH_SECONDS; inside that, the kept one stands, with the seconds until the next."""
        if period not in PERIODS:
            raise ValueError(f"period must be one of {', '.join(PERIODS)}")
        now = self.clock()
        wait = self.fresh.wait(tenant, now) if fresh else None
        days, unavailable, read_at = self._all_days(tenant, now, fresh and wait is None)
        rows: dict[str, list[DayCount]] = {}
        for count in days:
            rows.setdefault(period_of(count.day, period), []).append(count)
        since = days[0].day if days else None
        shown = [PeriodCount(key, *period_bounds(key, period), sum(d.hits for d in kept), sum(d.misses for d in kept),
                             sum(sum(d.unserved.values()) for d in kept), any(d.live for d in kept),
                             since is not None and period != "day" and since in {d.day for d in kept}
                             and since != period_bounds(key, period)[0])
                 for key, kept in sorted(rows.items(), reverse=True)][:SHOWN[period]]
        return Summary(period, now.astimezone(UTC).date().isoformat(), since, sum(d.hits for d in days),
                       sum(d.misses for d in days), sum(sum(d.unserved.values()) for d in days), shown, unavailable,
                       read_at.isoformat(), wait)

    def _all_days(self, tenant: str, now: datetime, fresh: bool = False) -> tuple[list[DayCount], str | None, datetime]:
        with self._lock:
            kept = self._cache.get(tenant)
            if kept is not None and kept[0] > now and not fresh:
                return kept[1], kept[2], kept[3]
        today = now.astimezone(UTC).date()
        stored = self.days(tenant, date(2000, 1, 1), today)
        # Not counted yet: today, and yesterday until the worker has counted it (an hour after it ends).
        first_live = today - timedelta(days=1)
        if stored and date.fromisoformat(stored[-1].day) >= first_live:
            first_live = date.fromisoformat(stored[-1].day) + timedelta(days=1)
        live: list[DayCount] = []
        unavailable = None
        try:
            if self.reader is None:
                raise LogUnavailable("The request log isn't available in this environment.")
            tallies = self.reader.tally(tenant, _midnight(first_live), now)
            for day in _each_day(first_live, today):
                tally = tallies.get(day.isoformat())
                if tally is not None or day == today or stored:  # a day before Serena ran here isn't shown
                    tally = tally or Tally()
                    live.append(DayCount(day.isoformat(), tally.hits, tally.misses, dict(tally.unserved), live=True))
        except (LogUnavailable, TooSlow) as error:
            unavailable = str(error)
        days = stored + live
        with self._lock:
            self._cache[tenant] = (now + timedelta(seconds=self.cache_seconds), days, unavailable, now)
        return days, unavailable, now

    def days(self, tenant: str, first: date, last: date) -> list[DayCount]:
        """The stored counts from first to last (inclusive), oldest first. A day with no item isn't listed."""
        found: list[DayCount] = []
        start: dict[str, Any] | None = None
        while True:
            page = self.store.client.query(
                TableName=self.store.table(tables.REQUEST_COUNTS),
                KeyConditionExpression="pk = :t AND sk BETWEEN :first AND :last",
                ExpressionAttributeValues={":t": {"S": tenant}, ":first": {"S": first.isoformat()},
                                           ":last": {"S": last.isoformat()}},
                **({"ExclusiveStartKey": start} if start else {}))
            found += [DayCount.of(item) for item in page.get("Items", [])]
            start = page.get("LastEvaluatedKey")
            if not start:
                return found

    def count_missing(self, tenant: str) -> list[str]:
        """Counts the days still in the log that have no item yet; returns the days it stored. Raises LogUnavailable
        when the log can't be read."""
        if self.reader is None:
            raise LogUnavailable("The request log isn't available in this environment.")
        now = self.clock()
        first, last = earliest_countable(now, self.retention_days), latest_countable(now)
        if first > last:
            return []
        stored = {count.day for count in self.days(tenant, first, last)}
        missing = [day for day in _each_day(first, last) if day.isoformat() not in stored]
        if not missing:
            return []
        tallies = self.reader.tally(tenant, _midnight(missing[0]), _midnight(missing[-1] + timedelta(days=1)))
        counted_at = now.astimezone(UTC).isoformat(timespec="seconds")
        written = []
        for day in missing:
            tally = tallies.get(day.isoformat(), Tally())
            count = DayCount(day.isoformat(), tally.hits, tally.misses, dict(tally.unserved), counted_at)
            try:
                self.store.client.put_item(TableName=self.store.table(tables.REQUEST_COUNTS), Item=count.item(tenant),
                                           ConditionExpression="attribute_not_exists(pk)")
            except self.store.client.exceptions.ConditionalCheckFailedException:
                continue  # counted in the meantime
            written.append(count.day)
        log.info("requests counted", extra={"museum": tenant, "days": len(written),
                                            "first": missing[0].isoformat(), "last": missing[-1].isoformat()})
        return written


def _each_day(first: date, last: date) -> Iterable[date]:
    day = first
    while day <= last:
        yield day
        day += timedelta(days=1)


PERIODS = ("day", "week", "month", "year")


def period_of(day: str, period: str) -> str:
    """The period a UTC day is in: the day itself, its ISO week ("2026-W43", Monday start), month ("2026-10") or year
    ("2026")."""
    when = date.fromisoformat(day)
    if period == "day":
        return day
    if period == "week":
        year, week, _ = when.isocalendar()
        return f"{year}-W{week:02d}"
    if period == "month":
        return day[:7]
    if period == "year":
        return day[:4]
    raise ValueError(f"period must be one of {', '.join(PERIODS)}")


def period_bounds(key: str, period: str) -> tuple[str, str]:
    """A period's first and last days, from period_of()'s key."""
    if period == "day":
        return key, key
    if period == "week":
        year, _, week = key.partition("-W")
        monday = date.fromisocalendar(int(year), int(week), 1)
        return monday.isoformat(), (monday + timedelta(days=6)).isoformat()
    if period == "month":
        first = date.fromisoformat(f"{key}-01")
        following = date(first.year + first.month // 12, first.month % 12 + 1, 1)
        return first.isoformat(), (following - timedelta(days=1)).isoformat()
    if period == "year":
        return f"{key}-01-01", f"{key}-12-31"
    raise ValueError(f"period must be one of {', '.join(PERIODS)}")


def by_period(counts: Iterable[DayCount], period: str) -> list[DayCount]:
    """Days summed by period, oldest first; each sum's `day` is the period ("2026-W43", "2026-10", "2026")."""
    sums: dict[str, DayCount] = {}
    for count in counts:
        key = period_of(count.day, period)
        kept = sums.get(key, DayCount(key))
        unserved = dict(kept.unserved)
        for reason, n in count.unserved.items():
            unserved[reason] = unserved.get(reason, 0) + n
        sums[key] = DayCount(key, kept.hits + count.hits, kept.misses + count.misses, unserved)
    return [sums[key] for key in sorted(sums)]
