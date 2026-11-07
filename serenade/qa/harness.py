"""What the synthetic-record tests share: requests to Serena that are remembered, the web service's log lines for
them (read once per phase, not once per request), and the admin API through a signed-in browser.

Requests are plain HTTP, never following the redirect (serenade/aws/target.py: get). Serena logs one line per request
("served" with its cache hit or miss, or "unserved" with its reason) and one per fetch from CollectionSpace ("fetched",
or "refused: …"); the lines come from `aws logs filter-log-events` (read-only, D231), which catches up within seconds
to a minute. A phase makes all its requests first and then waits once for every line (Log.catch_up)."""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from selenium.webdriver.remote.webdriver import WebDriver

from serenade.aws.target import Answer, Target, aws_cli, eventually, get
from serenade.pages.page import Page

API = "/admin/v1/museums"
PLACEHOLDER_BLOB = "59a733dd-d641-4e1a-8552"  # PAHMA's placeholder image (backend/serena/museums/pahma.yaml)
LOGGED = ("served", "unserved", "fetched", "already stored")  # and every "refused: …"


@dataclass(frozen=True)
class Sent:
    url: str
    path: str          # as Serena logs it: the URL's path, without the query string
    answer: Answer
    at: float          # time.time() when it was sent
    seconds: float     # how long the answer took
    nth: int           # this is the nth request of this path in the run (0-based)


@dataclass
class Serena:
    """Requests to the environment's PAHMA image paths, each remembered for the log check."""
    target: Target
    sent: list[Sent] = field(default_factory=list)
    _count: Counter[str] = field(default_factory=Counter)
    _lock: threading.Lock = field(default_factory=threading.Lock)  # step 12 sends from several threads

    def blob(self, blob: str, size: str | None = None) -> str:
        tail = f"derivatives/{size}/content" if size else "content"
        return f"{self.target.url}/{self.target.museum}/imageserver/blobs/{blob}/{tail}"

    def media(self, media: str, size: str | None = None) -> str:
        tail = f"blob/derivatives/{size}/content" if size else "blob/content"
        return f"{self.target.url}/{self.target.museum}/imageserver/media/{media}/{tail}"

    def send(self, url: str) -> Sent:
        path = urllib.parse.urlsplit(url).path
        started = time.monotonic()
        answer = get(url)
        with self._lock:
            sent = Sent(url, path, answer, time.time(), time.monotonic() - started, self._count[path])
            self._count[path] += 1
            self.sent.append(sent)
        return sent

    # ---- what an answer says ----------------------------------------------------------------------------------------

    def served(self, sent: Sent) -> str:
        """The S3 name (the stored file's SHA-256) a served answer's signed address names; fails if it isn't one."""
        a = sent.answer
        assert a.status == 302, f"{sent.path}: {a.status}, not 302"
        location = a.header("Location")
        prefix = f"{self.target.files_url}/{self.target.museum}/objects/"
        assert location.startswith(prefix), f"{sent.path}: not served, but redirected to {location}"
        assert a.header("Cache-Control").startswith("private, max-age="), f"{sent.path}: {a.header('Cache-Control')}"
        return location.removeprefix(prefix).split("?", 1)[0]

    def unavailable(self, sent: Sent, museum: str | None = None) -> None:
        """The museum's unavailable image (or the default one, for a museum Serena doesn't know), never stored."""
        a = sent.answer
        assert a.status == 302, f"{sent.path}: {a.status}, not 302"
        expected = f"{self.target.files_url}/{museum or self.target.museum}/unavailable.svg"
        assert a.header("Location") == expected, f"{sent.path}: redirected to {a.header('Location')}"
        assert a.header("Cache-Control") == "no-store", f"{sent.path}: {a.header('Cache-Control')}"

    def generic_placeholder(self, sent: Sent) -> None:
        """The generic placeholder picture: the placeholder image with no Media record named (D168)."""
        a = sent.answer
        assert a.status == 302, f"{sent.path}: {a.status}, not 302"
        expected = f"{self.target.files_url}/default/placeholder.svg"
        assert a.header("Location") == expected, f"{sent.path}: redirected to {a.header('Location')}"
        assert a.header("Cache-Control") == "no-store", f"{sent.path}: {a.header('Cache-Control')}"


class Log:
    """The web service's log lines since the run began (every web task's stream)."""

    def __init__(self, target: Target, since: float):
        self.target = target
        self.since_ms = int((since - 5) * 1000)
        self._lines: list[dict[str, Any]] = []

    def read(self) -> list[dict[str, Any]]:
        events = aws_cli("logs", "filter-log-events", "--log-group-name", f"{self.target.log_prefix}/web",
                         "--start-time", str(self.since_ms), "--query", "events[].[timestamp, message]") or []
        lines = []
        for _stamp, message in sorted(events, key=lambda e: e[0]):
            try:
                line = json.loads(message)
            except (TypeError, ValueError):
                continue
            if isinstance(line, dict) and (line.get("message") in LOGGED
                                           or str(line.get("message", "")).startswith("refused")):
                lines.append(line)
        self._lines = lines
        return lines

    def requests(self, path: str) -> list[dict[str, Any]]:
        """The served and unserved lines for a path, oldest first."""
        return [line for line in self._lines if line.get("message") in ("served", "unserved")
                and line.get("path") == path]

    def catch_up(self, sent: Iterable[Sent], seconds: float = 300) -> None:
        """Waits until every request has its line (Serena logs each one; the log lags a little)."""
        wanted = Counter(s.path for s in sent)

        def caught_up() -> None:
            self.read()
            missing = [p for p, n in wanted.items() if len(self.requests(p)) < n]
            assert not missing, f"no log line yet for {len(missing)} request(s), such as {missing[0]}"

        eventually(caught_up, seconds=seconds, every=10)

    def line(self, sent: Sent) -> dict[str, Any]:
        """The request's own line (its path's nth line since the run began)."""
        lines = self.requests(sent.path)
        assert len(lines) > sent.nth, f"no log line for {sent.path} (run Log.catch_up first)"
        return lines[sent.nth]

    def reason(self, sent: Sent) -> str:
        line = self.line(sent)
        return str(line.get("reason") or "") if line.get("message") == "unserved" else "served"

    def cache(self, sent: Sent) -> str:
        line = self.line(sent)
        assert line.get("message") == "served", f"{sent.path}: {line.get('message')} ({line.get('reason')})"
        return str(line.get("cache"))

    def fetches(self, blob: str, size: str | None = None) -> list[dict[str, Any]]:
        """The fetches from CollectionSpace for a Blob's size since the run began: fetched, or refused (too large, the
        wrong type, not decodable). A request answered from Serena's memory or without the light check has none."""
        derivative = size or "original"
        return [line for line in self._lines if line.get("blob") == blob and line.get("derivative") == derivative
                and (line.get("message") == "fetched" or str(line.get("message", "")).startswith("refused"))]


class Admin:
    """The admin API with one signed-in browser session, as the admin app calls it (X-Serena-Admin)."""

    def __init__(self, driver: WebDriver, base_url: str, museum: str):
        self.page = Page(driver, base_url)
        self.museum = museum

    def call(self, method: str, path: str, body: dict[str, Any] | None = None, ok: tuple[int, ...] = (200,)) -> Any:
        status, text = self.page.call_api(method, f"{API}/{self.museum}{path}",
                                          json.dumps(body) if body is not None else None,
                                          {"Content-Type": "application/json"} if body is not None else None)
        assert status in ok, f"{method} {path}: the admin API answered {status}: {text[:300]}"
        return json.loads(text) if text else None

    def lookup(self, what: str) -> dict[str, Any]:
        """Media look up's answer for a CSID or a path (it doesn't search by identification number)."""
        answer: dict[str, Any] = self.call("GET", f"/lookup?q={urllib.parse.quote(what, safe='')}")
        return answer

    def item(self, blob: str) -> dict[str, Any]:
        """A Blob's look up: its kind (None when it isn't listed), access, Media CSID and sizes."""
        items = self.lookup(blob)["items"]
        found = [i for i in items if i["blob_csid"] == blob]
        assert found, f"Media look up found nothing for {blob}"
        item: dict[str, Any] = found[0]
        return item

    def stored(self, blob: str) -> dict[str, bool]:
        """Which of a Blob's sizes Serena has a stored copy of ("original" for the original)."""
        return {s["size"]: s["stored"] is not None for s in self.item(blob)["sizes"]}

    def last_refresh(self) -> dict[str, Any] | None:
        """The last refresh whose servability update Serena applied: refresh_id, refresh_date, started_at."""
        found: dict[str, Any] | None = self.lookup(PLACEHOLDER_BLOB).get("refresh")
        return found

    def setting(self, name: str) -> dict[str, Any]:
        settings = self.call("GET", "/settings")["settings"]
        found = [s for s in settings if s["name"] == name]
        assert found, f"no setting {name}"
        one: dict[str, Any] = found[0]
        return one

    def change(self, name: str, value: Any, reason: str) -> dict[str, Any]:
        answer: dict[str, Any] = self.call("PUT", f"/settings/{name}", {"value": value, "reason": reason})
        return answer

    def use_default(self, name: str, reason: str) -> None:
        self.call("POST", f"/settings/{name}/reset", {"reason": reason})

    def put_back(self, name: str, before: dict[str, Any], reason: str) -> None:
        """Puts a setting back as it was read (its default, or the admin's value)."""
        if before["changed"]:
            self.change(name, before["value"], reason)
        else:
            self.use_default(name, reason)

    def audit(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = self.call("GET", "/audit")["entries"]
        return entries

    def alerts(self) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = self.call("GET", "/alerts")["alerts"]
        return alerts

    def recall(self, media: str, reason: str) -> None:
        answer = self.call("POST", "/recalls", {"text": media, "reason": reason})
        assert answer.get("recalled"), f"nothing recalled: {answer}"

    def active_recalls(self) -> list[dict[str, Any]]:
        active: list[dict[str, Any]] = self.call("GET", "/recalls")["active"]
        return active

    def cancel(self, media: str, reason: str) -> None:
        self.call("POST", f"/recalls/{media}/cancel", {"reason": reason})


def web_count() -> int:
    """How many web tasks the environment runs (WEB_COUNT): each remembers refusals and fetches on its own."""
    return int(os.environ.get("SERENADE_WEB_COUNT") or "1")
