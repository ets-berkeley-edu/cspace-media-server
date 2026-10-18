"""The test stack the suite runs against, and plain HTTP calls to it (no browser).

`./serena test` starts its own Docker Compose project, `serena-test`, on ports of its own, so a run never touches the
stack testers use by hand (`./serena up`). It passes the addresses below in the environment."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, TypeVar

SERENA_URL = os.environ.get("SERENADE_SERENA_URL", "http://localhost:8400")
SIM_URL = os.environ.get("SERENADE_SIM_URL", "http://localhost:8480")
# Set only by ./serena test: the tests that use the dataset run only on the test stack, never on a tester's.
ON_TEST_STACK = os.environ.get("SERENADE_STACK") == "test"
# How to stop and start Serena's web service, for the test of what the admin app says while Serena can't be reached
# (T47): the test stack's web container. Override them for a stack run without Docker.
WEB_STOP = os.environ.get("SERENADE_WEB_STOP", "docker compose -p serena-test stop web")
WEB_START = os.environ.get("SERENADE_WEB_START", "docker compose -p serena-test start web")
# Only the local stack, over plain http: never QA or production.
for _url in (SERENA_URL, SIM_URL):
    if not _url.startswith(("http://localhost:", "http://127.0.0.1:")):
        raise SystemExit(f"serenade runs only against the local stack, not {_url}")

T = TypeVar("T")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def redirect_of(path: str) -> str:
    """Requests a file's path from Serena and returns where it redirects (Serena answers every file request with a
    302: to the stored file, or to the unavailable image)."""
    try:
        _opener.open(SERENA_URL + path, timeout=60)
    except urllib.error.HTTPError as answer:
        if answer.code == 302:
            return str(answer.headers["Location"])
        raise
    raise AssertionError(f"{path} wasn't answered with a redirect")


def simulator(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    """Calls the CollectionSpace simulator's test controls (/_fake/…)."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(SIM_URL + path, data=data, method=method,  # noqa: S310 (local http only, above)
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as answer:  # noqa: S310
        return json.load(answer)


def calls_to_simulator() -> list[str]:
    """The paths Serena has called on the simulator, in order."""
    calls: list[str] = simulator("GET", "/_fake/calls")
    return calls


def eventually(check: Callable[[], T], seconds: float = 60, every: float = 1) -> T:
    """Repeats a check until it passes or time runs out, for a change that takes effect within a minute."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            return check()
        except AssertionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(every)


def stop_serena() -> None:
    """Stops Serena's web service (the admin app's dev server then answers its API calls with 502)."""
    subprocess.run(shlex.split(WEB_STOP), check=True, capture_output=True, timeout=120)  # noqa: S603 (our own command)


def start_serena() -> None:
    """Starts Serena's web service again and waits until it answers (its data is in moto, which kept running)."""
    subprocess.run(shlex.split(WEB_START), check=True, capture_output=True, timeout=120)  # noqa: S603 (our own command)

    def healthy() -> None:
        try:
            with urllib.request.urlopen(f"{SERENA_URL}/health", timeout=5) as response:  # noqa: S310 (local http)
                status = response.status
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            raise AssertionError(f"Serena isn't answering yet: {e}") from e
        if status != 200:
            raise AssertionError(f"Serena answered {status}")

    eventually(healthy, seconds=120)
