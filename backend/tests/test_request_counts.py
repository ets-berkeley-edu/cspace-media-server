"""Daily request counts by museum: cache hits and misses, and unserved requests by reason (issue #96). Every path and
museum here is synthetic."""
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import TENANTS
from fastapi.testclient import TestClient
from test_admin import Clock, make_app, sign_in
from test_requests_log import FakeLogs, cells, served, unserved, write

from serena import museum, tables
from serena.config import Settings
from serena.museum_settings import MuseumSettings
from serena.refreshes import Refreshes
from serena.request_counts import (
    DayCount,
    RequestCounts,
    by_period,
    earliest_countable,
    latest_countable,
    period_bounds,
    period_of,
)
from serena.requests_log import MAX_LINES, CloudWatchReader, FileReader, LogUnavailable, tally_texts
from serena.store import Store
from serena.worker import COUNT_RETRY_SECONDS, Worker, WorkerServices

NOW = datetime(2026, 10, 26, 5, 0, tzinfo=UTC)  # a Monday
YESTERDAY = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


@pytest.fixture
def log_file(tmp_path: Path) -> Path:
    return tmp_path / "serena.log"


def counts(store: Store, log_file: Path, now: datetime = NOW, retention: int = 30) -> RequestCounts:
    return RequestCounts(store, FileReader(log_file), retention, clock=lambda: now)


# --- the days to count

def test_a_day_is_counted_an_hour_after_it_ends() -> None:
    assert latest_countable(datetime(2026, 10, 26, 0, 59, tzinfo=UTC)) == date(2026, 10, 24)
    assert latest_countable(datetime(2026, 10, 26, 1, 0, tzinfo=UTC)) == date(2026, 10, 25)


def test_only_days_the_log_holds_in_full() -> None:
    assert earliest_countable(NOW, 30) == date(2026, 9, 28)  # 28 days before; its oldest lines are under 29 days old


# --- the tally

def test_the_file_reader_tallies_by_day(log_file: Path) -> None:
    write(log_file, [served(YESTERDAY), served(YESTERDAY, cache="miss"), served(YESTERDAY, museum="cinefiles"),
                     unserved(YESTERDAY), unserved(YESTERDAY, "recalled"), unserved(YESTERDAY, "recalled"),
                     served(YESTERDAY - timedelta(days=1)), served(datetime(2026, 10, 26, tzinfo=UTC))])
    days = FileReader(log_file).tally("pahma", datetime(2026, 10, 25, tzinfo=UTC), datetime(2026, 10, 26, tzinfo=UTC))
    assert list(days) == ["2026-10-25"]  # the day starting at the end is left out
    assert (days["2026-10-25"].hits, days["2026-10-25"].misses) == (1, 1)
    assert days["2026-10-25"].unserved == {"not_listed": 1, "recalled": 2}


def test_cloudwatch_tallies_with_two_queries() -> None:
    class Tallying(FakeLogs):
        def get_query_results(self, queryId: str) -> dict[str, Any]:
            text = self.started[int(queryId[1:]) - 1]["queryString"]
            if "by datefloor(@timestamp, 1d) as day, cache" in text:
                rows = [cells(day="2026-10-24 00:00:00.000", cache="hit", requests="5"),
                        cells(day="2026-10-24 00:00:00.000", cache="miss", requests="2"),
                        cells(day="2026-10-26 00:00:00.000", cache="hit", requests="9")]
            else:
                rows = [cells(day="2026-10-25 00:00:00.000", reason="recalled", requests="3")]
            return {"status": "Complete", "results": rows}

    client = Tallying()
    start, end = datetime(2026, 10, 24, tzinfo=UTC), datetime(2026, 10, 26, tzinfo=UTC)
    days = CloudWatchReader(client, "/serena/app", sleep=lambda _: None).tally("pahma", start, end)
    assert sorted(q["queryString"] for q in client.started) == sorted(tally_texts("pahma").values())
    assert {(q["startTime"], q["endTime"], q["limit"]) for q in client.started} == {
        (int(start.timestamp()), int(end.timestamp()), MAX_LINES)}
    assert sorted(days) == ["2026-10-24", "2026-10-25"]
    assert (days["2026-10-24"].hits, days["2026-10-24"].misses, days["2026-10-24"].unserved) == (5, 2, {})
    assert (days["2026-10-25"].served, days["2026-10-25"].unserved) == (0, {"recalled": 3})


def test_the_tally_queries_are_limited_to_the_museum() -> None:
    for text in tally_texts("pahma").values():
        assert text.count('museum = "pahma"') == 1
    with pytest.raises(ValueError):
        tally_texts('pahma" or museum = "cinefiles')


# --- counting and storing

def test_the_first_count_backfills_the_days_the_log_holds(store: Store, log_file: Path) -> None:
    write(log_file, [served(YESTERDAY), served(YESTERDAY, cache="miss"), served(YESTERDAY, cache="miss"),
                     unserved(YESTERDAY, "recalled"), served(datetime(2026, 10, 1, 9, tzinfo=UTC)),
                     served(datetime(2026, 9, 27, 9, tzinfo=UTC)),  # partly gone from the log: not counted
                     served(NOW)])  # today: not over
    written = counts(store, log_file).count_missing("pahma")
    assert written[0] == "2026-09-28" and written[-1] == "2026-10-25" and len(written) == 28
    stored = {c.day: c for c in counts(store, log_file).days("pahma", date(2026, 9, 1), date(2026, 10, 31))}
    assert len(stored) == 28 and "2026-09-27" not in stored and "2026-10-26" not in stored
    assert (stored["2026-10-25"].hits, stored["2026-10-25"].misses) == (1, 2)
    assert stored["2026-10-25"].unserved == {"recalled": 1}
    assert stored["2026-10-25"].hit_rate == pytest.approx(1 / 3)
    assert stored["2026-10-25"].counted_at == "2026-10-26T05:00:00+00:00"
    assert (stored["2026-10-01"].hits, stored["2026-10-02"].served, stored["2026-10-02"].hit_rate) == (1, 0, None)


def test_a_counted_day_is_never_counted_again(store: Store, log_file: Path) -> None:
    write(log_file, [served(YESTERDAY)])
    counts(store, log_file).count_missing("pahma")
    write(log_file, [served(YESTERDAY), served(YESTERDAY)])  # lines that came too late are left out
    assert counts(store, log_file).count_missing("pahma") == []
    later = NOW + timedelta(days=1)
    assert counts(store, log_file, later).count_missing("pahma") == ["2026-10-26"]
    assert counts(store, log_file).days("pahma", date(2026, 10, 25), date(2026, 10, 25))[0].hits == 1


def test_a_day_counted_in_the_meantime_is_kept(store: Store, log_file: Path) -> None:
    kept = DayCount("2026-10-25", hits=7, counted_at="earlier")
    store.client.put_item(TableName=store.table(tables.REQUEST_COUNTS), Item=kept.item("pahma"))

    class Racing(RequestCounts):
        def days(self, tenant: str, first: date, last: date) -> list[DayCount]:
            return []  # as if read before the other count stored its item

    write(log_file, [served(YESTERDAY)])
    written = Racing(store, FileReader(log_file), 30, clock=lambda: NOW).count_missing("pahma")
    assert "2026-10-25" not in written and len(written) == 27
    assert counts(store, log_file).days("pahma", date(2026, 10, 25), date(2026, 10, 25)) == [kept]


def test_museums_are_counted_apart(store: Store, log_file: Path) -> None:
    write(log_file, [served(YESTERDAY, museum="cinefiles")])
    counts(store, log_file).count_missing("pahma")
    counts(store, log_file).count_missing("cinefiles")
    assert counts(store, log_file).days("pahma", date(2026, 10, 25), date(2026, 10, 25))[0].hits == 0
    assert counts(store, log_file).days("cinefiles", date(2026, 10, 25), date(2026, 10, 25))[0].hits == 1


def test_no_log_no_count(store: Store) -> None:
    with pytest.raises(LogUnavailable):
        RequestCounts(store, None, 30).count_missing("pahma")


# --- weeks, months and years

def test_periods() -> None:
    assert period_of("2026-10-25", "week") == "2026-W43"  # a Sunday ends the ISO week
    assert period_of("2026-10-26", "week") == "2026-W44"
    assert period_of("2027-01-01", "week") == "2026-W53"
    assert (period_of("2026-10-25", "month"), period_of("2026-10-25", "year")) == ("2026-10", "2026")
    with pytest.raises(ValueError):
        period_of("2026-10-25", "fortnight")


def test_sums_by_period() -> None:
    days = [DayCount("2026-10-25", 1, 2, {"recalled": 1}), DayCount("2026-10-26", 3, 0, {"recalled": 2, "x": 1}),
            DayCount("2026-11-02", 4, 4)]
    weeks = by_period(days, "week")
    assert [(w.day, w.hits, w.misses, w.unserved) for w in weeks] == [
        ("2026-W43", 1, 2, {"recalled": 1}), ("2026-W44", 3, 0, {"recalled": 2, "x": 1}), ("2026-W45", 4, 4, {})]
    months = by_period(days, "month")
    assert [(m.day, m.hits, m.misses, m.unserved) for m in months] == [
        ("2026-10", 4, 2, {"recalled": 3, "x": 1}), ("2026-11", 4, 4, {})]
    assert by_period(days, "year")[0].hit_rate == pytest.approx(8 / 14)
    assert by_period(days, "day") == days


# --- the worker

class Ticking:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def worker_with(store: Store, s3: Any, request_counts: RequestCounts | None, ticking: Ticking) -> Worker:
    settings = Settings(tenants=TENANTS, table_prefix="t", buckets={t: f"b-{t}" for t in TENANTS}, _env_file=None)
    services = WorkerServices(settings, museum.load_all(TENANTS), MuseumSettings(store, 0), Refreshes(store), store,
                              s3, counts=request_counts)
    return Worker(services, sleep=lambda _: None, monotonic=ticking)


def test_the_worker_counts_once_a_day(store: Store, s3: Any, log_file: Path) -> None:
    write(log_file, [served(YESTERDAY)])
    worker = worker_with(store, s3, counts(store, log_file), Ticking())
    assert worker.count_requests(NOW) == 28 * len(TENANTS)
    assert worker.count_requests(NOW) == 0  # nothing more today; no query of the log either
    assert worker.counted_through == "2026-10-25"


def test_a_failed_count_is_tried_again_an_hour_later(store: Store, s3: Any, log_file: Path) -> None:
    class Failing(RequestCounts):
        fail = True

        def count_missing(self, tenant: str) -> list[str]:
            if self.fail and tenant == "pahma":
                raise LogUnavailable("unreachable")
            return super().count_missing(tenant)

    failing = Failing(store, FileReader(log_file), 30, clock=lambda: NOW)
    ticking = Ticking()
    worker = worker_with(store, s3, failing, ticking)
    assert worker.count_requests(NOW) == 28 * (len(TENANTS) - 1)  # the others are counted
    assert worker.counted_through is None
    Failing.fail = False
    ticking.now = COUNT_RETRY_SECONDS - 1
    assert worker.count_requests(NOW) == 0
    ticking.now = COUNT_RETRY_SECONDS
    assert worker.count_requests(NOW) == 28  # only PAHMA's days were missing
    assert worker.counted_through == "2026-10-25"


def test_no_log_no_counting(store: Store, s3: Any) -> None:
    assert worker_with(store, s3, None, Ticking()).count_requests(NOW) == 0


# --- the Past requests page's summary

def stored(store: Store, tenant: str, *days: DayCount) -> None:
    for day in days:
        store.client.put_item(TableName=store.table(tables.REQUEST_COUNTS), Item=day.item(tenant))


def test_period_bounds() -> None:
    assert period_bounds("2026-W43", "week") == ("2026-10-19", "2026-10-25")
    assert period_bounds("2026-02", "month") == ("2026-02-01", "2026-02-28")
    assert period_bounds("2026-12", "month") == ("2026-12-01", "2026-12-31")
    assert period_bounds("2026", "year") == ("2026-01-01", "2026-12-31")
    assert period_bounds("2026-10-25", "day") == ("2026-10-25", "2026-10-25")


def test_the_summary_adds_today_from_the_log(store: Store, log_file: Path) -> None:
    stored(store, "pahma", DayCount("2026-10-20", 5, 1, {"recalled": 2}), DayCount("2026-10-25", 7, 1))
    write(log_file, [served(NOW - timedelta(hours=1)), served(NOW - timedelta(hours=2), cache="miss"),
                     unserved(NOW - timedelta(hours=1)), served(YESTERDAY)])  # yesterday's is counted already
    summary = counts(store, log_file).summary("pahma", "day")
    assert (summary.today, summary.since) == ("2026-10-26", "2026-10-20")
    assert [(r.period, r.hits, r.misses, r.unserved, r.live) for r in summary.rows] == [
        ("2026-10-26", 1, 1, 1, True), ("2026-10-25", 7, 1, 0, False), ("2026-10-20", 5, 1, 2, False)]
    assert (summary.hits, summary.misses, summary.unserved, summary.live_unavailable) == (13, 3, 3, None)
    weeks = counts(store, log_file).summary("pahma", "week")
    assert [(r.period, r.first_day, r.last_day, r.hits, r.live, r.partial) for r in weeks.rows] == [
        ("2026-W44", "2026-10-26", "2026-11-01", 1, True, False),
        ("2026-W43", "2026-10-19", "2026-10-25", 12, False, True)]  # counting began on Tuesday, Oct 20
    assert [(r.period, r.hits) for r in counts(store, log_file).summary("pahma", "month").rows] == [("2026-10", 13)]
    with pytest.raises(ValueError):
        counts(store, log_file).summary("pahma", "fortnight")


def test_yesterday_is_read_from_the_log_until_counted(store: Store, log_file: Path) -> None:
    stored(store, "pahma", DayCount("2026-10-24", 3))
    write(log_file, [served(YESTERDAY), served(YESTERDAY, cache="miss")])
    early = datetime(2026, 10, 26, 0, 30, tzinfo=UTC)  # before the worker counts the 25th
    rows = counts(store, log_file, early).summary("pahma", "day").rows
    assert [(r.period, r.hits, r.misses, r.live) for r in rows] == [
        ("2026-10-26", 0, 0, True), ("2026-10-25", 1, 1, True), ("2026-10-24", 3, 0, False)]


def test_no_counts_yet(store: Store, log_file: Path) -> None:
    summary = counts(store, log_file).summary("pahma", "year")
    assert summary.since == "2026-10-26"  # only today, live
    assert [(r.period, r.hits, r.live, r.partial) for r in summary.rows] == [("2026", 0, True, True)]


def test_when_the_log_cant_be_read_the_stored_counts_still_show(store: Store) -> None:
    stored(store, "pahma", DayCount("2026-10-25", 7, 1))
    summary = RequestCounts(store, None, 30, clock=lambda: NOW).summary("pahma", "day")
    assert [(r.period, r.hits) for r in summary.rows] == [("2026-10-25", 7)]
    assert summary.live_unavailable == "The request log isn't available in this environment."


def test_the_summary_is_kept_a_minute(store: Store, log_file: Path) -> None:
    now = [NOW]
    request_counts = RequestCounts(store, FileReader(log_file), 30, clock=lambda: now[0])
    assert request_counts.summary("pahma", "day").hits == 0
    write(log_file, [served(NOW)])
    assert request_counts.summary("pahma", "week").hits == 0  # the same days, by week: no new query
    now[0] = NOW + timedelta(seconds=61)
    assert request_counts.summary("pahma", "day").hits == 1


def test_the_api(store: Store, s3: Any, secretsmanager: Any, log_file: Path) -> None:
    app = make_app(store, s3, secretsmanager)
    app.state.admin.sessions.clock = Clock()
    app.state.request_counts = RequestCounts(store, FileReader(log_file), 30, clock=lambda: NOW)
    client = TestClient(app, base_url="http://testserver")
    stored(store, "pahma", DayCount("2026-10-25", 7, 1, {"not_listed": 1}))
    stored(store, "bampfa", DayCount("2026-10-25", 99, 99))
    url = "/admin/v1/museums/pahma/requests/counts"
    assert client.get(url).status_code == 401
    sign_in(client)
    body = client.get(url).json()
    assert body == {
        "by": "day", "today": "2026-10-26", "since": "2026-10-25",
        "totals": {"hits": 7, "misses": 1, "unserved": 1},
        "rows": [{"period": "2026-10-26", "first_day": "2026-10-26", "last_day": "2026-10-26", "hits": 0, "misses": 0,
                  "unserved": 0, "live": True, "partial": False},
                 {"period": "2026-10-25", "first_day": "2026-10-25", "last_day": "2026-10-25", "hits": 7, "misses": 1,
                  "unserved": 1, "live": False, "partial": False}],
        "live_unavailable": None}
    assert client.get(url, params={"by": "month"}).json()["rows"][0]["period"] == "2026-10"
    assert client.get(url, params={"by": "decade"}).status_code == 422
    assert client.get("/admin/v1/museums/bampfa/requests/counts").status_code in (401, 403)  # signed in to PAHMA
