"""The Past requests page: what Serena served and couldn't serve, from its log (decided October 12, 2026, D100 to D113).
Every CSID, path and museum here is synthetic."""
import csv
import io
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import add_blob
from fastapi.testclient import TestClient
from test_admin import Clock, make_app, sign_in
from test_signed_redirect import BLOB, BYTES, MEDIA, SHA, cache

from serena import logs, requests_log
from serena.requests_log import (
    MAX_LINES,
    TOP_PATHS,
    CloudWatchReader,
    FileReader,
    LogUnavailable,
    QueryKind,
    Requests,
    TooSlow,
    query_text,
)
from serena.store import Store

NOW = datetime(2026, 10, 12, 18, 0, tzinfo=UTC)
URL = "/admin/v1/museums/pahma/requests"


def line(at: datetime, message: str, museum: str = "pahma", **fields: Any) -> dict[str, Any]:
    logger = "serena.imageserver" if message == "served" else "serena.unserved"
    return {"time": at.isoformat(timespec="milliseconds"), "level": "INFO", "logger": logger, "message": message,
            "museum": museum, **fields}


def served(at: datetime, n: int = 1, museum: str = "pahma", **fields: Any) -> dict[str, Any]:
    return line(at, "served", museum, **{"path": f"/pahma/imageserver/blobs/b{n}/content", "size": "original",
                                         "kind": "image", "cache": "hit", "signed": False, **fields})


def unserved(at: datetime, reason: str = "not_listed", n: int = 9) -> dict[str, Any]:
    return line(at, "unserved", reason=reason, path=f"/pahma/imageserver/blobs/b{n}/content")


def write(path: Path, entries: list[dict[str, Any]]) -> None:
    with path.open("a", encoding="utf-8") as out:
        for entry in entries:
            out.write(json.dumps(entry) + "\n")


# --- the queries

def test_every_query_is_limited_to_the_museum_and_the_two_lines() -> None:
    for kind in QueryKind:
        text = query_text(kind, "pahma")
        assert text.count('museum = "pahma"') == 1
        assert 'message = "served" and logger = "serena.imageserver"' in text
        assert 'message = "unserved" and logger = "serena.unserved"' in text
    assert query_text(QueryKind.LINES, "pahma").endswith(f"| sort @timestamp desc | limit {MAX_LINES}")
    assert f"| limit {TOP_PATHS}" in query_text(QueryKind.TOP_PATHS, "pahma")


@pytest.mark.parametrize("museum", ['pahma" or museum = "bampfa', "PAHMA", "", "pahma "])
def test_a_museum_that_isnt_a_key_never_reaches_a_query(museum: str) -> None:
    with pytest.raises(ValueError):
        query_text(QueryKind.LINES, museum)
    with pytest.raises(ValueError):
        FileReader("/nonexistent").run(museum, NOW - timedelta(hours=1), NOW)


# --- the local stand-in, and the report

def test_the_file_reader_answers_the_six_queries(tmp_path: Path) -> None:
    log_file = tmp_path / "serena.log"
    write(Path(f"{log_file}.1"), [served(NOW - timedelta(days=1, hours=2), 1)])  # the rotated copy is read too
    write(log_file, [
        served(NOW - timedelta(hours=3), 1), served(NOW - timedelta(hours=2), 2, cache="miss", size="Medium",
                                                     path="/pahma/imageserver/blobs/b2/derivatives/Medium/content"),
        unserved(NOW - timedelta(hours=1), "too_large"), unserved(NOW - timedelta(minutes=5), "not_listed"),
        served(NOW - timedelta(hours=1), 1, museum="bampfa"),  # another museum
        line(NOW - timedelta(hours=1), "fetched", logger="serena.fetch"),  # another line
        {**served(NOW - timedelta(hours=1), 3), "logger": "serena.other"},  # the right words from another logger
        served(NOW - timedelta(days=8), 1),  # out of range
    ])
    with log_file.open("a") as out:
        out.write("not JSON\n")
    report = Requests(FileReader(log_file), clock=lambda: NOW).report("pahma", "7d")
    assert [(ln.outcome, ln.reason, ln.path, ln.cache) for ln in report.lines] == [
        ("unserved", "not_listed", "/pahma/imageserver/blobs/b9/content", ""),
        ("unserved", "too_large", "/pahma/imageserver/blobs/b9/content", ""),
        ("served", "", "/pahma/imageserver/blobs/b2/derivatives/Medium/content", "miss"),
        ("served", "", "/pahma/imageserver/blobs/b1/content", "hit"),
        ("served", "", "/pahma/imageserver/blobs/b1/content", "hit"),
    ]
    assert [(d.day, d.served, d.unserved) for d in report.days] == [
        ("2026-10-12", 2, {"not_listed": 1, "too_large": 1}), ("2026-10-11", 1, {})]
    assert report.top_paths == [("/pahma/imageserver/blobs/b1/content", 2), ("/pahma/imageserver/blobs/b9/content", 2),
                                ("/pahma/imageserver/blobs/b2/derivatives/Medium/content", 1)]
    assert report.by_size == {"original": 2, "Medium": 1}  # served requests only
    assert report.by_cache == {"hit": 2, "miss": 1}
    assert not report.truncated
    last_hour = Requests(FileReader(log_file), clock=lambda: NOW).report("pahma", "1h")
    assert len(last_hour.lines) == 2  # from exactly an hour ago


def test_reports_are_kept_a_minute(tmp_path: Path) -> None:
    clock = [NOW]
    calls = []

    class Counting(FileReader):
        def run(self, museum: str, start: datetime, end: datetime) -> Any:
            calls.append((museum, start, end))
            return super().run(museum, start, end)

    requests = Requests(Counting(tmp_path / "none"), clock=lambda: clock[0])
    requests.report("pahma", "24h")
    requests.report("pahma", "24h")
    requests.report("pahma", "1h")  # another range: its own query
    assert len(calls) == 2
    clock[0] = NOW + timedelta(seconds=61)
    requests.report("pahma", "24h")
    assert len(calls) == 3


def test_a_fresh_read_skips_the_kept_report_at_most_every_10_seconds(tmp_path: Path) -> None:
    """Past requests' Refresh (issue #100): the log now, once per museum every 10 seconds; inside that, the kept report
    and the seconds to wait."""
    clock = [NOW]
    calls = []

    class Counting(FileReader):
        def run(self, museum: str, start: datetime, end: datetime) -> Any:
            calls.append((museum, end))
            return super().run(museum, start, end)

    requests = Requests(Counting(tmp_path / "none"), clock=lambda: clock[0])
    kept = requests.report("pahma", "24h")
    clock[0] = NOW + timedelta(seconds=3)
    fresh, wait = requests.read("pahma", "24h", fresh=True)  # within the minute, but fresh: read again, and kept
    assert (len(calls), fresh.end, wait) == (2, clock[0], None)
    assert requests.report("pahma", "24h") is fresh
    clock[0] = NOW + timedelta(seconds=8)
    again, wait = requests.read("pahma", "24h", fresh=True)  # 5 seconds later: refused
    assert (len(calls), again, wait) == (2, fresh, 5)
    _, wait = requests.read("bampfa", "24h", fresh=True)  # another museum has its own 10 seconds
    assert (len(calls), wait) == (3, None)
    _, wait = requests.read("pahma", "1h", fresh=True)  # refused, but nothing kept for the range: read it
    assert (len(calls), wait) == (4, 5)
    clock[0] = NOW + timedelta(seconds=13.5)
    assert requests.read("pahma", "24h", fresh=True)[1] is None and len(calls) == 5
    assert kept is not fresh


def test_no_log_reader_here() -> None:
    with pytest.raises(LogUnavailable):
        Requests(None).report("pahma", "24h")


# --- CloudWatch Logs Insights

def cells(**fields: str) -> list[dict[str, str]]:
    return [{"field": name, "value": value} for name, value in fields.items()]


class FakeLogs:
    """A stand-in for boto3's CloudWatch Logs client: each query runs for `polls` polls, then ends with `status`."""

    def __init__(self, polls: int = 1, status: str = "Complete", fail_start: bool = False, paths: int = 1):
        self.polls = polls
        self.paths = paths
        self.status = status
        self.fail_start = fail_start
        self.started: list[dict[str, Any]] = []
        self.stopped: list[str] = []
        self.asked: dict[str, int] = {}

    def start_query(self, **kwargs: Any) -> dict[str, str]:
        if self.fail_start:
            raise ConnectionError("unreachable")
        self.started.append(kwargs)
        return {"queryId": f"q{len(self.started)}"}

    def get_query_results(self, queryId: str) -> dict[str, Any]:
        self.asked[queryId] = self.asked.get(queryId, 0) + 1
        if self.asked[queryId] <= self.polls:
            return {"status": "Running", "results": []}
        text = self.started[int(queryId[1:]) - 1]["queryString"]
        rows: list[list[dict[str, str]]] = []
        if text.startswith("fields"):
            rows = [cells(time="2026-10-12T17:00:00.000+00:00", message="served", kind="image", cache="hit",
                          signed="1", path="/pahma/imageserver/blobs/b1/content", **{"@ptr": "opaque"})]
        elif "by datefloor(@timestamp, 1d) as day, reason" in text:
            rows = [cells(day="2026-10-12 00:00:00.000", reason="recalled", requests="4")]
        elif "by datefloor" in text:
            rows = [cells(day="2026-10-12 00:00:00.000", requests="7")]
        elif text.endswith("by cache"):
            rows = [cells(cache="hit", requests="6"), cells(cache="miss", requests="1")]
        elif text.endswith("by size"):
            rows = [cells(size="Medium", requests="5"), cells(size="original", requests="2")]
        else:
            # like Logs Insights, ignores the query's own limit (issue #95)
            rows = [cells(path=f"/pahma/imageserver/blobs/b{n}/content", requests=str(8 - n if n < 8 else 1))
                    for n in range(1, self.paths + 1)]
        return {"status": self.status, "results": rows}

    def stop_query(self, queryId: str) -> dict[str, bool]:
        self.stopped.append(queryId)
        return {"success": True}


def reader(client: FakeLogs, wait: float = 30) -> CloudWatchReader:
    ticks = iter(range(10_000))
    return CloudWatchReader(client, "/serena/app", wait_seconds=wait, sleep=lambda _: None,
                            monotonic=lambda: float(next(ticks)))


def test_cloudwatch_runs_the_six_queries_on_the_app_log_group() -> None:
    client = FakeLogs(polls=2)
    report = Requests(reader(client), clock=lambda: NOW).report("pahma", "24h")
    assert {q["logGroupName"] for q in client.started} == {"/serena/app"}
    assert {(q["startTime"], q["endTime"]) for q in client.started} == {
        (int((NOW - timedelta(hours=24)).timestamp()), int(NOW.timestamp()))}
    assert len(client.started) == 6
    assert [(ln.outcome, ln.path, ln.signed) for ln in report.lines] == [
        ("served", "/pahma/imageserver/blobs/b1/content", True)]
    assert [(d.day, d.served, d.unserved) for d in report.days] == [("2026-10-12", 7, {"recalled": 4})]
    assert report.top_paths == [("/pahma/imageserver/blobs/b1/content", 7)]
    assert report.by_size == {"Medium": 5, "original": 2}
    assert report.by_cache == {"hit": 6, "miss": 1}


def test_most_requested_keeps_only_the_top_paths() -> None:
    client = FakeLogs(paths=35)
    report = Requests(reader(client), clock=lambda: NOW).report("pahma", "24h")
    assert len(report.top_paths) == TOP_PATHS == 10
    assert report.top_paths[0] == ("/pahma/imageserver/blobs/b1/content", 7)
    top = [q for q in client.started if "by path" in q["queryString"]]
    assert [q["limit"] for q in top] == [TOP_PATHS]
    assert {q["limit"] for q in client.started if q not in top} == {MAX_LINES}


def test_a_slow_query_is_stopped() -> None:
    client = FakeLogs(polls=1000)
    with pytest.raises(TooSlow):
        reader(client, wait=5).run("pahma", NOW - timedelta(hours=1), NOW)
    assert sorted(client.stopped) == [f"q{n}" for n in range(1, 7)]


@pytest.mark.parametrize("client", [FakeLogs(status="Failed"), FakeLogs(fail_start=True)])
def test_a_failed_query(client: FakeLogs) -> None:
    with pytest.raises(LogUnavailable):
        reader(client).run("pahma", NOW - timedelta(hours=1), NOW)


# --- the admin API

@pytest.fixture
def log_file(tmp_path: Path) -> Path:
    return tmp_path / "serena.log"


@pytest.fixture
def client(store: Store, s3: Any, secretsmanager: Any, log_file: Path) -> TestClient:
    app = make_app(store, s3, secretsmanager)
    app.state.admin.sessions.clock = Clock()
    app.state.requests_log = Requests(FileReader(log_file))
    return TestClient(app, base_url="http://testserver")


def test_the_report(client: TestClient, log_file: Path) -> None:
    # A fixed clock: with the real one, lines written a few minutes before a run just after midnight UTC fell on the
    # previous day, and the days didn't match (CI on October 25, 2026, 00:01 UTC).
    now = NOW
    client.app.state.requests_log.clock = lambda: now  # type: ignore[attr-defined]
    write(log_file, [served(now - timedelta(minutes=2), 1), unserved(now - timedelta(minutes=1), "too_large"),
                     served(now - timedelta(minutes=1), 1, museum="bampfa"),
                     served(now - timedelta(minutes=3), 3, size="Thumbnail"),
                     served(now - timedelta(minutes=4), 4, size="FullHD")])
    assert client.get(URL).status_code == 401
    sign_in(client)
    body = client.get(URL).json()
    assert body["range"] == "24h"  # to start (D106)
    assert (body["max_lines"], body["truncated"]) == (MAX_LINES, False)
    assert body["signed_links"] is False  # only Cinefiles has signed access: its page alone has the column
    assert [(ln["outcome"], ln["reason"]) for ln in body["lines"]][:2] == [("unserved", "too_large"), ("served", "")]
    assert body["days"] == [{"day": now.date().isoformat(), "served": 3, "unserved": {"too_large": 1},
                             "unserved_total": 1}]
    # The museum's sizes, smallest to largest, and the served requests by size in that order (Richard, October 14).
    assert body["sizes"] == ["Thumbnail", "Small", "Medium", "FullHD", "OriginalJpeg", "original"]
    assert body["served_by_size"] == [{"size": "Thumbnail", "requests": 1}, {"size": "FullHD", "requests": 1},
                                      {"size": "original", "requests": 1}]
    assert body["top_paths"][0] == {"path": "/pahma/imageserver/blobs/b1/content", "requests": 1}
    assert body["served_by_cache"] == {"hit": 3, "miss": 0}  # issue #96
    assert (body["read_at"], body["try_again_in"]) == (now.isoformat(), None)  # issue #100
    # Refresh (issue #100): the clock doesn't move here, so the first fresh read goes ahead and the next waits.
    assert client.get(URL, params={"fresh": "1"}).json()["try_again_in"] is None
    assert client.get(URL, params={"fresh": "1"}).json()["try_again_in"] == 10
    assert client.get(URL, params={"range": "7d"}).status_code == 200
    assert client.get(URL, params={"range": "30d"}).status_code == 422
    sign_in(client, "cinefiles")
    assert client.get("/admin/v1/museums/cinefiles/requests").json()["signed_links"] is True
    sign_in(client, "bampfa")
    assert [ln["path"] for ln in client.get("/admin/v1/museums/bampfa/requests").json()["lines"]] == [
        "/pahma/imageserver/blobs/b1/content"]  # bampfa's own line (a synthetic path), never pahma's


def test_the_export_follows_the_filters(client: TestClient, log_file: Path) -> None:
    now = datetime.now(UTC)
    write(log_file, [served(now - timedelta(minutes=3), 1), unserved(now - timedelta(minutes=2), "too_large"),
                     unserved(now - timedelta(minutes=1), "not_listed"),
                     {**unserved(now - timedelta(seconds=30), "not_listed"), "path": "=HYPERLINK(1)"}])
    sign_in(client)
    everything = client.get(f"{URL}/export.csv")
    assert everything.headers["content-type"] == "text/csv; charset=utf-8"
    assert everything.headers["content-disposition"] == (
        f'attachment; filename="serena-requests-pahma-{now.date().isoformat()}.csv"')
    rows = list(csv.reader(io.StringIO(everything.text)))
    assert rows[0] == ["time (UTC)", "outcome", "reason", "path", "kind", "cache", "signed link"]
    assert rows[1][3] == "'=HYPERLINK(1)"  # never run as a formula
    assert len(rows) == 5
    unserved_rows = list(csv.reader(io.StringIO(client.get(f"{URL}/export.csv", params={
        "outcome": "unserved", "reason": "not_listed"}).text)))
    assert [r[2] for r in unserved_rows[1:]] == ["not_listed", "not_listed"]
    assert client.get(f"{URL}/export.csv", params={"reason": "Not Listed"}).status_code == 422


def test_when_the_log_cant_be_read(client: TestClient) -> None:
    sign_in(client)
    client.app.state.requests_log = Requests(reader(FakeLogs(polls=1000), wait=5))  # type: ignore[attr-defined]
    slow = client.get(URL)
    assert slow.status_code == 504
    assert "shorter range" in slow.json()["detail"]
    client.app.state.requests_log = Requests(None)  # type: ignore[attr-defined]
    assert client.get(URL).status_code == 503


# --- from a request to the page, through the local log file

@pytest.fixture
def local_app(store: Store, s3: Any, secretsmanager: Any, log_file: Path) -> Iterator[Any]:
    s3.put_object(Bucket="b-pahma", Key=f"objects/{SHA}", Body=BYTES, ContentType="image/jpeg")
    app = make_app(store, s3, secretsmanager, local_cdn=True, dynamodb_endpoint="http://localhost:8000",
                   log_file=str(log_file))
    app.state.admin.sessions.clock = Clock()
    yield app
    logs.configure("INFO")  # close the file


def test_requests_reach_the_page(local_app: Any, store: Store, log_file: Path) -> None:
    add_blob(store, "pahma", BLOB, MEDIA)
    cache(store, "pahma", "Medium")
    client = TestClient(local_app, base_url="http://testserver", follow_redirects=False)
    assert isinstance(local_app.state.requests_log.reader, requests_log.FileReader)
    client.get(f"/pahma/imageserver/blobs/{BLOB}/derivatives/Medium/content?uid=12345&sig=abc")
    client.get("/pahma/imageserver/blobs/not-a-csid/content")  # unserved
    sign_in(client)
    answer = client.get(URL)
    assert answer.status_code == 200, answer.text
    lines = answer.json()["lines"]
    assert [(ln["outcome"], ln["path"], ln["kind"], ln["cache"], ln["signed"], ln["reason"]) for ln in lines] == [
        ("unserved", "/pahma/imageserver/blobs/not-a-csid/content", "", "", False, "not_listed"),
        ("served", f"/pahma/imageserver/blobs/{BLOB}/derivatives/Medium/content", "image", "hit", False, ""),
    ]
    assert answer.json()["served_by_size"] == [{"size": "Medium", "requests": 1}]  # the "served" line has its size
    assert "uid" not in log_file.read_text() and "12345" not in log_file.read_text()
