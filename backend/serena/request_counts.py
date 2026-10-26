"""Daily request counts by museum (issue #96): for each UTC day, the served requests answered from the cache (hits)
and those that needed a fetch from CollectionSpace (misses), and the unserved requests by reason.

The app's log is kept only log_retention_days (30 in AWS), so the worker counts each day once it's over and keeps the
count in the request-counts table for good (one item per museum per day: pk <museum>, sk <YYYY-MM-DD>). Weeks (ISO,
Monday start), months and years are sums of days, all in UTC. Once an hour until it succeeds, and then once a UTC
day, it counts every day still in the log that has no item yet: so its first run backfills the days the log still
holds, and a day missed while the worker was down is counted on its next run. Each count is two Logs Insights queries
for a museum, however many days they cover; a day already counted is never counted again."""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from . import tables
from .requests_log import LogUnavailable, Reader, Tally
from .store import Store

log = logging.getLogger("serena.request_counts")

# A day is counted this long after it ends, so the log has every line of it (CloudWatch Logs can take minutes).
SETTLE = timedelta(hours=1)
# Days whose oldest lines are this close to the log's retention aren't counted: part of them may be gone already.
RETENTION_MARGIN_DAYS = 2


@dataclass(frozen=True)
class DayCount:
    day: str  # YYYY-MM-DD, UTC
    hits: int = 0
    misses: int = 0
    unserved: dict[str, int] = field(default_factory=dict)  # by reason
    counted_at: str = ""  # ISO time, UTC

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


class RequestCounts:
    def __init__(self, store: Store, reader: Reader | None, retention_days: int,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.store = store
        self.reader = reader
        self.retention_days = retention_days
        self.clock = clock

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
