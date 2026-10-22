"""Replays a slice of the legacy imageserver's cleaned access logs against an AWS environment with the simulator, to
measure how big Serena's tasks need to be (design.md: Compute; decisions D278 to D288, October 22, 2026).

Run it through `./serena aws replay` (deploy/aws.sh), which refuses any environment but one with the simulated
CollectionSpace (D279), sets the address, and reads the services' CPU and memory from CloudWatch afterwards (D287).
On its own it only plans (--dry-run): it never sends a request unless SERENA_REPLAY_SIMULATED=true, which only
`./serena aws replay` sets, after its checks.

The log is one month of the cleaned logs (`<month>.tsv.gz`, made by the access-log scripts on Richard's Mac; never in
this repository). From it the replay takes a slice (the busiest hour or minute, or a time and a length) and sends its
requests in their real order and spacing, `--speed` times faster (D280, D285):

- every request goes to the one museum the environment simulates (D282), keeping its URL form (a derivative, or the
  file itself; Cinefiles' PDF links as the file itself) and its method; requests in a form Serena doesn't answer
  ("unknown") are left out and counted;
- each logged file becomes one of the simulator's records, the same file always the same record, so repeats stay
  repeats and Serena's hits and misses follow the real pattern (D280, D281). The fake ETL makes the records, with
  files about the logged sizes (D283): `--dry-run` prints the exact `./serena aws etl` command to run first;
- Serena's redirects aren't followed (the load measured is the tasks'), except one request in `--follow` (D284).

Python's standard library only, so it runs in serenade's environment with nothing added."""
from __future__ import annotations

import argparse
import csv
import gzip
import http.client
import json
import math
import os
import queue
import sys
import threading
import time
import urllib.parse
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

# The fake ETL's synthetic CSIDs (backend/devtools/fake_etl.py: NAMESPACE and csid). backend/tests/test_replay.py
# checks they stay the same.
NAMESPACE = uuid.UUID("3f6b0c55-2c4e-4f6e-9d4b-6a1c0b6e5a10")
# The simulator's size bands, smallest first (backend/fakecspace/bands.py: ORIGINALS).
BANDS = (("100KB", 100_000), ("1MB", 1_000_000), ("5MB", 5_000_000), ("20MB", 20_000_000), ("100MB", 100_000_000))
MAX_RECORDS = 50_000  # the most records the fake ETL is asked for (D281)
# Requests for the file itself: their size decides a record's band. The other derivatives have fixed sizes.
ORIGINAL_SIZES = {"OriginalJpeg", "Original", "originaljpeg"}
FILE_FORMS = {"original", "linked_pdf", "inline_pdf"}
LATE_SECONDS = 1.0  # a request sent this much after its time counts as late


@dataclass(frozen=True)
class Logged:
    """One request from the cleaned log."""
    at: datetime
    museum: str
    form: str
    csid: str
    size: str
    method: str
    nbytes: int


def read_log(path: str | Path) -> Iterator[Logged]:
    """The requests in a cleaned monthly log (sanitize_logs.py's columns), in the file's order."""
    opener: Callable[..., Iterable[str]] = gzip.open if str(path).endswith(".gz") else open  # type: ignore[assignment]
    with opener(path, "rt", encoding="utf-8", newline="") as lines:
        for row in csv.DictReader(lines, delimiter="\t"):
            yield Logged(datetime.fromisoformat(row["ts"]), row["museum"], row["form"], row["csid"], row["size"],
                         row["method"], int(row["bytes"]) if row["bytes"].isdigit() else 0)


def busiest(requests: list[Logged], unit: str) -> datetime:
    """The start of the hour or minute with the most requests."""
    if not requests:
        raise ValueError("the log has no requests")
    counts = Counter(_floor(r.at, unit) for r in requests)
    return max(counts, key=lambda start: (counts[start], -start.timestamp()))


def _floor(at: datetime, unit: str) -> datetime:
    return at.replace(minute=0 if unit == "hour" else at.minute, second=0, microsecond=0)


def take_slice(requests: list[Logged], start: datetime, minutes: float) -> list[Logged]:
    end = start + timedelta(minutes=minutes)
    return sorted((r for r in requests if start <= r.at < end), key=lambda r: r.at)


def band_for(nbytes: int) -> str:
    """The band nearest a file's size by ratio (on a log scale): 2 MB is 1MB's, 3 MB is 5MB's."""
    best = min(BANDS, key=lambda band: abs(math.log(max(nbytes, 1) / band[1])))
    return best[0]


def path_of(logged: Logged, museum: str, blob: str) -> str | None:
    """The request's path at Serena, for the record that stands for its file; None for a form Serena doesn't answer."""
    if logged.form == "derivative" and logged.size:
        return f"/{museum}/imageserver/blobs/{blob}/derivatives/{logged.size}/content"
    if logged.form in FILE_FORMS:
        return f"/{museum}/imageserver/blobs/{blob}/content"
    return None


def csid(tenant: str, what: str, n: int) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{tenant}/{what}/{n}"))


@dataclass
class Plan:
    """What a slice needs: the records (their bands, in the fake ETL's order) and each request's path and time."""
    museum: str
    start: datetime
    minutes: float
    first_row: int = 0
    # (when, in seconds from the start; method; path; the logged file; the logged museum)
    requests: list[tuple[float, str, str, str, str]] = field(default_factory=list)
    bands: list[str] = field(default_factory=list)  # band of record n
    skipped: Counter[str] = field(default_factory=Counter)  # forms left out

    @property
    def sizes(self) -> str:
        """The fake ETL's --sizes: each band's count, in the order the records were numbered."""
        counts = Counter(self.bands)
        return ",".join(f"{band}:{counts[band]}" for band, _ in BANDS if counts[band])

    def etl_command(self, env: str) -> str:
        first = f" --first-row {self.first_row}" if self.first_row else ""
        return f"./serena aws etl {self.museum} --env {env} --sizes {self.sizes}{first}"


def plan(sliced: list[Logged], museum: str, start: datetime, minutes: float, first_row: int = 0) -> Plan:
    """Maps each logged file to a record (D280, D281): records are numbered band by band (all of the smallest band
    first), from first_row, as the fake ETL's --sizes and --first-row make them, so file n of a band gets that band's
    n-th record. Another first_row gives records Serena hasn't cached yet, for another cold replay."""
    biggest: dict[str, int] = {}  # each file's largest original-sized answer, for its band
    for r in sliced:
        if (r.form == "derivative" and r.size in ORIGINAL_SIZES) or r.form in FILE_FORMS:
            biggest[r.csid] = max(biggest.get(r.csid, 0), r.nbytes)
    files = list(dict.fromkeys(r.csid for r in sliced if path_of(r, museum, "x") is not None))
    band_of_file = {f: band_for(biggest[f]) if biggest.get(f) else BANDS[0][0] for f in files}
    result = Plan(museum, start, minutes, first_row)
    record: dict[str, int] = {}
    for band, _ in BANDS:
        for f in files:
            if band_of_file[f] == band:
                record[f] = len(result.bands)
                result.bands.append(band)
    if len(result.bands) > MAX_RECORDS:
        raise ValueError(f"the slice has {len(result.bands)} distinct files, more than {MAX_RECORDS} records: "
                         "replay a shorter slice")
    t0 = sliced[0].at if sliced else start
    seconds: Counter[datetime] = Counter(r.at for r in sliced)
    seen: Counter[datetime] = Counter()
    for r in sliced:
        # The log has whole seconds: spread each second's requests evenly across it.
        offset = (r.at - t0).total_seconds() + seen[r.at] / seconds[r.at]
        seen[r.at] += 1
        path = path_of(r, museum, csid(museum, "blob", first_row + record[r.csid])) if r.csid in record else None
        if path is None:
            result.skipped[r.form or "blank"] += 1
            continue
        result.requests.append((offset, r.method if r.method in ("GET", "HEAD") else "GET", path, r.csid, r.museum))
    return result


@dataclass
class Outcome:
    offset: float  # when it was due, in seconds from the start (at the replay's speed)
    late: float    # how much later it was sent
    status: int    # 0: no answer (a connection error or a timeout)
    seconds: float
    answer: str    # what Serena's answer was (see answer_of)
    museum: str


def answer_of(status: int, location: str | None) -> str:
    """"served" for a 302 to a stored file (a signed address under /<museum>/objects/), "unavailable" for a 302 to the
    unavailable image or the placeholder picture (Serena wouldn't or couldn't serve it), "no answer" for a connection
    error or a timeout, and "other" for anything else."""
    if status == 0:
        return "no answer"
    path = urllib.parse.urlsplit(location or "").path
    if status == 302 and "/objects/" in path:
        return "served"
    if status == 302 and (path.endswith(("/unavailable.svg", "/placeholder.svg")) or path.startswith("/unavailable/")):
        return "unavailable"
    return "other"


def replay(base_url: str, requests: list[tuple[float, str, str, str, str]], *, speed: float, concurrency: int,
           follow: int, timeout: float = 180.0, clock: Callable[[], float] = time.monotonic,
           sleep: Callable[[float], None] = time.sleep, progress: Callable[[str], None] | None = None,
           ) -> list[Outcome]:
    """Sends the requests at their times divided by `speed`, at most `concurrency` at once, each thread keeping its
    own connection. Follows one 302 in `follow` (0: none)."""
    target = urllib.parse.urlsplit(base_url)
    jobs: queue.Queue[tuple[float, str, str, str] | None] = queue.Queue(maxsize=concurrency)
    outcomes: list[Outcome] = []
    lock = threading.Lock()
    redirects = [0]
    start = clock()

    def connect() -> http.client.HTTPConnection:
        kind = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
        return kind(target.hostname or "", target.port, timeout=timeout)

    def work() -> None:
        connection = connect()
        while (job := jobs.get()) is not None:
            due, method, path, museum = job
            sent = clock()
            status = 0
            try:
                connection.request(method, path, headers={"User-Agent": "serena-replay"})
                answer = connection.getresponse()
                answer.read()
                status = answer.status
                location = answer.getheader("Location")
            except (OSError, http.client.HTTPException):
                connection.close()
                connection = connect()
                location = None
            took = clock() - sent
            answer_is = answer_of(status, location)
            if status == 302 and location and follow:
                with lock:
                    redirects[0] += 1
                    check = redirects[0] % follow == 0
                if check:
                    status = _follow(location, timeout)
            with lock:
                outcomes.append(Outcome(due, max(0.0, sent - start - due), status, took, answer_is, museum))
        connection.close()

    threads = [threading.Thread(target=work, daemon=True) for _ in range(concurrency)]
    for thread in threads:
        thread.start()
    total = len(requests)
    for n, (offset, method, path, _file, museum) in enumerate(requests, start=1):
        due = offset / speed
        wait = due - (clock() - start)
        if wait > 0:
            sleep(wait)
        jobs.put((due, method, path, museum))  # waits while every thread is busy: then requests go late
        if progress and n % 1000 == 0:
            progress(f"  {n} of {total} sent")
    for _ in threads:
        jobs.put(None)
    for thread in threads:
        thread.join()
    return sorted(outcomes, key=lambda o: o.offset)


def _follow(location: str, timeout: float) -> int:
    """GETs a signed address and reads its answer; a 302 that leads to a 200 counts as 200 (only the code is kept)."""
    parts = urllib.parse.urlsplit(location)
    kind = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    connection = kind(parts.hostname or "", parts.port, timeout=timeout)
    try:
        connection.request("GET", parts.path + (f"?{parts.query}" if parts.query else ""))
        answer = connection.getresponse()
        answer.read()
        return answer.status
    except (OSError, http.client.HTTPException):
        return 0
    finally:
        connection.close()


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(p / 100 * len(ordered)) - 1))]


def report(outcomes: list[Outcome], wall_seconds: float) -> dict[str, object]:
    """The replay's own figures (D287): what was sent, how late, the answers (by status, and whether Serena served
    the file or the unavailable image), and how long they took."""
    def latency(chosen: list[Outcome]) -> dict[str, float]:
        took = [o.seconds for o in chosen]
        return {"count": len(took), "p50": round(_percentile(took, 50), 3), "p95": round(_percentile(took, 95), 3),
                "p99": round(_percentile(took, 99), 3), "max": round(max(took, default=0.0), 3)}
    late = [o for o in outcomes if o.late > LATE_SECONDS]
    return {
        "sent": len(outcomes),
        "seconds": round(wall_seconds, 1),
        "late": len(late),
        "latest": round(max((o.late for o in outcomes), default=0.0), 1),
        "statuses": dict(sorted(Counter(str(o.status) for o in outcomes).items())),
        "answers": dict(sorted(Counter(o.answer for o in outcomes).items())),
        # Seconds to Serena's answer: on a cold run most are misses (fetched first), on a warm one hits.
        "latency": latency(outcomes),
        "latency_served": latency([o for o in outcomes if o.answer == "served"]),
        "by_logged_museum": dict(sorted(Counter(o.museum for o in outcomes).items())),
    }


def describe(p: Plan, speed: float) -> list[str]:
    duration = (p.requests[-1][0] if p.requests else 0.0) / speed
    lines = [f"Slice: {p.start.isoformat()} for {p.minutes:g} minutes: {len(p.requests)} requests for "
             f"{len(p.bands)} files ({p.sizes or 'none'})",
             f"  at speed {speed:g}: about {duration / 60:.1f} minutes"]
    if p.skipped:
        lines.append("  left out: " + ", ".join(f"{n} {form}" for form, n in sorted(p.skipped.items())))
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay a slice of the cleaned access logs (./serena aws replay).")
    parser.add_argument("--log", required=True, help="a cleaned monthly log, <month>.tsv.gz")
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--busiest", choices=("hour", "minute"), help="the month's busiest hour or minute")
    which.add_argument("--from", dest="start", help="the slice's start, as in the log (2026-09-30T19:00)")
    parser.add_argument("--minutes", type=float, default=60.0, help="the slice's length with --from (default 60)")
    parser.add_argument("--speed", type=float, default=1.0, help="1 is the real rate; 5 five times faster")
    parser.add_argument("--concurrency", type=int, default=256, help="at most this many requests in flight")
    parser.add_argument("--follow", type=int, default=0, help="follow one redirect in N (default none)")
    parser.add_argument("--museum", default="pahma", help="the simulated museum every request goes to")
    parser.add_argument("--first-row", type=int, default=0,
                        help="map onto records numbered from this one: a cold replay with records Serena hasn't "
                             "cached (the fake ETL needs the same; the dry run prints it)")
    parser.add_argument("--env", default="<env>", help="the environment's name, for the printed fake ETL command")
    parser.add_argument("--url", help="Serena's address (./serena aws replay sets it)")
    parser.add_argument("--summary", help="write the run's figures here as JSON")
    parser.add_argument("--dry-run", action="store_true", help="only plan: print the slice and the fake ETL command")
    args = parser.parse_args(argv)
    if args.speed <= 0 or args.concurrency < 1 or args.follow < 0 or args.minutes <= 0 or args.first_row < 0:
        parser.error("--speed and --minutes must be above 0, --concurrency at least 1, --follow and --first-row 0 or "
                     "more")

    everything = list(read_log(args.log))
    if args.busiest:
        start, minutes = busiest(everything, args.busiest), 60.0 if args.busiest == "hour" else 1.0
    else:
        first = everything[0].at if everything else None
        start = datetime.fromisoformat(args.start)
        if start.tzinfo is None and first is not None and first.tzinfo is not None:
            start = start.replace(tzinfo=first.tzinfo)  # as the log's own times
        minutes = args.minutes
    try:
        p = plan(take_slice(everything, start, minutes), args.museum, start, minutes, args.first_row)
    except ValueError as error:
        parser.error(str(error))
    del everything
    for line in describe(p, args.speed):
        print(line)
    print(f"  records it needs, first: {p.etl_command(args.env)}")
    if args.dry_run:
        return 0
    if os.environ.get("SERENA_REPLAY_SIMULATED") != "true" or not args.url:
        print("The replay sends requests only through ./serena aws replay, to an environment with the simulator.",
              file=sys.stderr)
        return 2
    print(f"Replaying against {args.url} ...", flush=True)
    began = datetime.now().astimezone()
    t = time.monotonic()
    outcomes = replay(args.url, p.requests, speed=args.speed, concurrency=args.concurrency, follow=args.follow,
                      progress=lambda line: print(line, flush=True))
    figures = report(outcomes, time.monotonic() - t)
    figures["window"] = {"start": began.isoformat(), "end": datetime.now().astimezone().isoformat()}
    figures["slice"] = {"start": p.start.isoformat(), "minutes": p.minutes, "speed": args.speed,
                        "files": len(p.bands), "sizes": p.sizes, "first_row": p.first_row}
    print(json.dumps(figures, indent=2))
    if args.summary:
        Path(args.summary).write_text(json.dumps(figures), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
