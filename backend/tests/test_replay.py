"""The access-log replay (serenade/load/replay.py, ./serena aws replay; D278-D288) and the simulator's files of about a
real file's size (fakecspace/bands.py, D283). The replay lives in serenade, which has no CI job of its own, so it's
tested here. Every log below is made up in the test: no line of a real access log is in the repository."""
from __future__ import annotations

import gzip
import http.server
import importlib.util
import io
import json
import sys
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import pyvips
from fastapi.testclient import TestClient

from devtools import fake_etl
from fakecspace import bands
from fakecspace.app import app as fake_app
from fakecspace.app import store as fake

SERENADE = Path(__file__).resolve().parents[2] / "serenade" / "load"
COLUMNS = ["ts", "museum", "form", "csid", "size", "method", "status", "bytes", "protocol", "query_names",
           "email_suffix", "client", "ua_class", "ua_family", "referrer_host", "path_shape"]
AUTH = ("serena", "serena")


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"serenade_load_{name}", SERENADE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while it's being made
    spec.loader.exec_module(module)
    return module


replay = load("replay")
metrics = load("metrics")
T0 = datetime.fromisoformat("2026-09-30T19:00:00-07:00")


def line(at: datetime, csid: str, form: str = "derivative", size: str = "Medium", nbytes: int = 90_000,
         museum: str = "bampfa", method: str = "GET") -> dict[str, str]:
    return {"ts": at.isoformat(), "museum": museum, "form": form, "csid": csid, "size": size, "method": method,
            "status": "200", "bytes": str(nbytes), "protocol": "HTTP/1.1", "query_names": "", "email_suffix": "0",
            "client": "0123456789abcdef", "ua_class": "browser", "ua_family": "Chrome", "referrer_host": "",
            "path_shape": ""}


def write_log(path: Path, rows: list[dict[str, str]]) -> Path:
    text = "\t".join(COLUMNS) + "\n" + "".join("\t".join(r[c] for c in COLUMNS) + "\n" for r in rows)
    path.write_bytes(gzip.compress(text.encode()))
    return path


@pytest.fixture(autouse=True)
def fresh() -> Iterator[None]:
    fake.reset()
    bands.reset()
    yield
    fake.reset()
    bands.reset()


@pytest.fixture
def small_bands(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every band's file a few KB, so the tests make them in milliseconds."""
    for name in bands.SIZES:
        monkeypatch.setitem(bands.SIZES, name, 3_000)


# --- the replay and the fake ETL agree


def test_the_replay_makes_the_fake_etls_csids_and_knows_its_bands() -> None:
    assert replay.NAMESPACE == fake_etl.NAMESPACE
    assert [replay.csid("pahma", "blob", n) for n in range(4)] == [b for b, *_ in fake_etl.rows("pahma", 4)[:4]]
    assert [name for name, _ in replay.BANDS] == list(fake_etl.BANDS) == list(bands.ORIGINALS)
    assert dict(replay.BANDS) == bands.ORIGINALS


# --- reading the log and choosing the slice


def test_it_reads_a_cleaned_log_and_finds_the_busiest_hour_and_minute(tmp_path: Path) -> None:
    rows = [line(T0 + timedelta(minutes=5), "a")]  # a quiet hour
    rows += [line(T0 + timedelta(hours=2, minutes=7, seconds=s), f"f{s}") for s in range(3)]
    rows += [line(T0 + timedelta(hours=2, minutes=30), "g")]
    logged = list(replay.read_log(write_log(tmp_path / "2026-09.tsv.gz", rows)))
    assert len(logged) == 5 and logged[0].nbytes == 90_000 and logged[0].museum == "bampfa"
    assert replay.busiest(logged, "hour") == T0 + timedelta(hours=2)
    assert replay.busiest(logged, "minute") == T0 + timedelta(hours=2, minutes=7)
    assert [r.csid for r in replay.take_slice(logged, T0 + timedelta(hours=2), 10)] == ["f0", "f1", "f2"]


def test_a_files_band_is_the_nearest_by_ratio() -> None:
    assert [replay.band_for(n) for n in (0, 4_586, 300_000, 2_000_000, 3_000_000, 71_370_651, 161_000_000)] == [
        "100KB", "100KB", "100KB", "1MB", "5MB", "100MB", "100MB"]


# --- the plan: records, paths and times


def test_the_same_file_is_always_the_same_record_and_records_go_band_by_band() -> None:
    sliced = [
        line(T0, "big", "derivative", "OriginalJpeg", 60_000_000),
        line(T0, "small", "derivative", "Thumbnail", 4_000),
        line(T0 + timedelta(seconds=1), "big", "derivative", "Medium", 200_000),
        line(T0 + timedelta(seconds=1), "pdf", "linked_pdf", "", 1_500_000, museum="cinefiles"),
        line(T0 + timedelta(seconds=2), "odd", "unknown", "", 5_000),
        line(T0 + timedelta(seconds=2), "small", "derivative", "Thumbnail", 4_000, method="HEAD"),
    ]
    logged = [replay.Logged(datetime.fromisoformat(r["ts"]), r["museum"], r["form"], r["csid"], r["size"],
                            r["method"], int(r["bytes"])) for r in sliced]
    plan = replay.plan(logged, "pahma", T0, 60)
    # small (no original asked for: the smallest band), then pdf (1.5 MB: 1MB), then big (60 MB: 100MB)
    assert plan.bands == ["100KB", "1MB", "100MB"] and plan.sizes == "100KB:1,1MB:1,100MB:1"
    assert fake_etl.parse_sizes(plan.sizes) == plan.bands
    blob = {n: replay.csid("pahma", "blob", n) for n in range(3)}
    assert [(round(o, 2), m, p) for o, m, p, _, _ in plan.requests] == [
        (0.0, "GET", f"/pahma/imageserver/blobs/{blob[2]}/derivatives/OriginalJpeg/content"),
        (0.5, "GET", f"/pahma/imageserver/blobs/{blob[0]}/derivatives/Thumbnail/content"),  # a second's spread
        (1.0, "GET", f"/pahma/imageserver/blobs/{blob[2]}/derivatives/Medium/content"),
        (1.5, "GET", f"/pahma/imageserver/blobs/{blob[1]}/content"),  # Cinefiles' PDF link: the file itself
        (2.5, "HEAD", f"/pahma/imageserver/blobs/{blob[0]}/derivatives/Thumbnail/content"),
    ]
    assert plan.skipped == {"unknown": 1}
    assert [m for *_, m in plan.requests][3] == "cinefiles"  # the report keeps the logged museum
    assert plan.etl_command("ucb-stage1") == "./serena aws etl pahma --env ucb-stage1 --sizes 100KB:1,1MB:1,100MB:1"
    # Records from another first row: the same layout, further along, as the fake ETL's --first-row makes them.
    later = replay.plan(logged, "pahma", T0, 60, first_row=1000)
    assert later.requests[0][2] == f"/pahma/imageserver/blobs/{replay.csid('pahma', 'blob', 1002)}/derivatives/" \
        "OriginalJpeg/content"
    assert later.etl_command("e").endswith("--sizes 100KB:1,1MB:1,100MB:1 --first-row 1000")
    assert [b for b, *_ in fake_etl.rows("pahma", 3, 1000)][:3] == [replay.csid("pahma", "blob", n)
                                                                   for n in (1000, 1001, 1002)]


def test_a_slice_with_too_many_files_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(replay, "MAX_RECORDS", 2)
    logged = [replay.Logged(T0, "pahma", "derivative", f"f{n}", "Medium", "GET", 1) for n in range(3)]
    with pytest.raises(ValueError, match="3 distinct files"):
        replay.plan(logged, "pahma", T0, 60)


# --- sending


class Recorder(http.server.BaseHTTPRequestHandler):
    seen: list[tuple[str, str]] = []  # noqa: RUF012 (one list for the test's server)

    def do_GET(self) -> None:
        self.answer()

    def do_HEAD(self) -> None:
        self.answer()

    def answer(self) -> None:
        Recorder.seen.append((self.command, self.path))
        if self.path.startswith("/signed/"):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            if self.command == "GET":
                self.wfile.write(b"ok")
            return
        self.send_response(302)
        port = self.headers.get("Host", "").rpartition(":")[2]  # this server's own port
        self.send_header("Location", f"http://127.0.0.1:{port!s}/signed{self.path}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def server() -> Iterator[str]:
    Recorder.seen = []
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_it_sends_every_request_in_order_and_follows_one_redirect_in_n(server: str) -> None:
    requests = [(n * 0.5, "HEAD" if n == 3 else "GET", f"/pahma/objects/{n % 4}", f"f{n % 4}", "bampfa")
                for n in range(8)]
    outcomes = replay.replay(server, requests, speed=50, concurrency=4, follow=4)
    assert len(outcomes) == 8 and [o.offset for o in outcomes] == pytest.approx([n * 0.01 for n in range(8)])
    assert {o.answer for o in outcomes} == {"served"}  # the test server's 302s go to /signed/pahma/objects/...
    sent = [p for _, p in Recorder.seen if not p.startswith("/signed/")]
    assert sorted(sent) == sorted(p for _, _, p, _, _ in requests)
    assert ("HEAD", "/pahma/objects/3") in Recorder.seen
    assert len([p for _, p in Recorder.seen if p.startswith("/signed/")]) == 2  # 8 redirects, one in 4 followed
    assert sorted(o.status for o in outcomes) == [200, 200] + [302] * 6


def test_an_unreachable_server_counts_as_no_answer() -> None:
    outcomes = replay.replay("http://127.0.0.1:9", [(0.0, "GET", "/x", "f", "pahma")], speed=1, concurrency=1,
                             follow=0, timeout=2)
    assert [o.status for o in outcomes] == [0]


def test_the_report_counts_late_requests_statuses_and_latency() -> None:
    make = replay.Outcome
    outcomes = [make(0, 0, 302, 0.1, "served", "pahma"), make(1, 3.0, 302, 0.3, "unavailable", "pahma"),
                make(2, 0, 200, 0.2, "served", "bampfa"), make(3, 0.5, 0, 9.0, "no answer", "pahma")]
    figures = replay.report(outcomes, 12.0)
    assert figures["sent"] == 4 and figures["late"] == 1 and figures["latest"] == 3.0
    assert figures["statuses"] == {"0": 1, "200": 1, "302": 2}
    assert figures["answers"] == {"no answer": 1, "served": 2, "unavailable": 1}
    assert figures["latency"] == {"count": 4, "p50": 0.2, "p95": 9.0, "p99": 9.0, "max": 9.0}
    assert figures["latency_served"]["count"] == 2 and figures["latency_served"]["p50"] == 0.1
    assert figures["by_logged_museum"] == {"bampfa": 1, "pahma": 3}


def test_a_302_is_served_or_unavailable_by_where_it_points() -> None:
    signed = "https://d.cloudfront.net/pahma/objects/ab12?Expires=1&Signature=x&Key-Pair-Id=K"
    assert replay.answer_of(302, signed) == "served"
    assert replay.answer_of(302, "https://d.cloudfront.net/pahma/unavailable.svg") == "unavailable"
    assert replay.answer_of(302, "https://d.cloudfront.net/default/placeholder.svg") == "unavailable"
    assert replay.answer_of(302, "/unavailable/pahma.svg") == "unavailable"  # the local stack's
    assert replay.answer_of(302, None) == "other" and replay.answer_of(404, None) == "other"
    assert replay.answer_of(0, None) == "no answer"


def test_a_dry_run_plans_and_nothing_is_sent_without_serena_aws_replay(tmp_path: Path, server: str,
                                                                       capsys: pytest.CaptureFixture[str],
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    log = write_log(tmp_path / "m.tsv.gz", [line(T0 + timedelta(seconds=s), f"f{s % 2}") for s in range(4)])
    assert replay.main(["--log", str(log), "--busiest", "hour", "--env", "ucb-stage1", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "4 requests for 2 files (100KB:2)" in out
    assert "./serena aws etl pahma --env ucb-stage1 --sizes 100KB:2" in out
    monkeypatch.delenv("SERENA_REPLAY_SIMULATED", raising=False)
    assert replay.main(["--log", str(log), "--busiest", "hour", "--url", server]) == 2
    assert Recorder.seen == []
    monkeypatch.setenv("SERENA_REPLAY_SIMULATED", "true")
    summary = tmp_path / "summary.json"
    assert replay.main(["--log", str(log), "--from", "2026-09-30T19:00", "--minutes", "1", "--speed", "100",
                        "--url", server, "--summary", str(summary)]) == 0
    figures = json.loads(summary.read_text())
    assert figures["sent"] == 4 and figures["slice"]["sizes"] == "100KB:2" and "start" in figures["window"]


def test_the_metrics_line() -> None:
    assert "no figures yet" in metrics.line("web CPU", {"Datapoints": []})
    points = {"Datapoints": [{"Average": 10.0, "Maximum": 30.0}, {"Average": 20.0, "Maximum": 25.0}]}
    assert metrics.line("web CPU", points).split() == [
        "web", "CPU", "average", "15.0", "busiest", "minute", "20.0", "highest", "30.0", "(2", "minutes)"]


# --- the fake ETL's --sizes and the simulator's files of about a real size (D283)


def test_the_fake_etls_sizes_give_each_row_its_band() -> None:
    assert fake_etl.parse_sizes("100KB:2, 5MB:1") == ["100KB", "100KB", "5MB"]
    for bad in ("2MB:1", "100KB", "100KB:x", ""):
        with pytest.raises(ValueError):
            fake_etl.parse_sizes(bad)


def test_banded_records_get_jpegs_of_about_their_size_each_different(small_bands: None) -> None:
    with TestClient(fake_app) as client:
        fake_etl.add_to_simulator(client, fake_etl.rows("pahma", 3), ["100KB", "100KB", "1MB"])
        media = [fake_etl.csid("pahma", "media", n) for n in range(2)]
        assert [fake.media[m].band for m in media] == ["100KB", "100KB"]
        first, second = (client.get(f"/cspace-services/media/{m}/blob/derivatives/OriginalJpeg/content", auth=AUTH)
                         for m in media)
        assert first.status_code == second.status_code == 200 and first.headers["content-type"] == "image/jpeg"
        assert int(first.headers["content-length"]) == len(first.content)
        assert first.content != second.content and first.content[2:].startswith(b"\xff\xfe")
        assert abs(len(first.content) - 3_000) < 1_500  # about the band's size
        assert pyvips.Image.new_from_buffer(first.content, "", access="sequential").avg() > 0  # it decodes
        thumb = client.get(f"/cspace-services/media/{media[0]}/blob/derivatives/Thumbnail/content", auth=AUTH)
        assert thumb.status_code == 200 and thumb.content != first.content
        # Replacing the image still works as before: the 8x8 sample replaces the band's file.
        client.post(f"/_fake/replace/{media[0]}").raise_for_status()
        again = client.get(f"/cspace-services/media/{media[0]}/blob/content", auth=AUTH)
        assert again.headers["content-type"] == "image/png"


def test_a_band_is_for_images_only_and_must_be_known() -> None:
    with TestClient(fake_app) as client:
        assert client.post("/_fake/media", json={"csid": "m1", "kind": "pdf", "band": "1MB"}).status_code == 400
        assert client.post("/_fake/media", json={"csid": "m2", "band": "2MB"}).status_code == 400
        assert "m1" not in fake.media and "m2" not in fake.media


def test_the_fake_etl_bands_only_its_images(small_bands: None) -> None:
    with TestClient(fake_app) as client:
        listed = fake_etl.rows("cinefiles", 4)  # image, pdf, pdf (restricted), image
        fake_etl.add_to_simulator(client, listed, ["1MB"] * 4)
        assert [fake.media[m].band for _, m, _, _ in listed if m] == ["1MB", None, None, "1MB"]


def test_a_band_file_is_noise_of_about_the_size() -> None:
    made = bands.noise_jpeg(50_000)
    assert abs(len(made) - 50_000) < 10_000
    head = bands.marked_head("abc")
    whole = b"".join(bands.stream(head, made))
    assert whole.startswith(b"\xff\xd8\xff\xfe") and b"fakecspace abc" in whole
    assert len(whole) == len(head) + len(made) - 2
    assert pyvips.Image.new_from_buffer(whole, "", access="sequential").avg() > 0
    assert io.BytesIO(whole).read(2) == b"\xff\xd8"
