"""The deployed environment the AWS tests run against, and plain HTTP calls to it (no browser).

`./serena aws test` sets everything below from the environment's settings (deploy/aws.sh: run_tests), after checking
you're signed in and the environment is running. It never runs on its own: the tests refuse any address but the one
the environment's last deploy saved in deploy/environments/<env>.url (D225)."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from email.message import Message
from pathlib import Path
from typing import Any, TypeVar

REPO = Path(__file__).resolve().parents[2]
T = TypeVar("T")


@dataclass(frozen=True)
class Target:
    env: str            # personal-dev
    url: str            # the app: https://<distribution>.cloudfront.net, or the campus name on the shared root (D293)
    files_url: str      # the files and the unavailable images: the same distribution, or the shared root's own (D299)
    root: str           # personal or shared (D302)
    my_address: str     # the address this computer's requests come from, for the address-rule tests
    etl_cidrs: tuple[str, ...]       # who may reach /etl/ (ETL_CIDRS)
    admin_cidrs: tuple[str, ...]     # who may reach /admin (ADMIN_CIDRS)
    admitted_cidrs: tuple[str, ...]  # whom the shared root's load balancer admits at all (Apache, ETL, admin; D291)
    museum: str         # the museum the tests use: the environment's first
    label: str          # the admin app's header: "AWS · personal dev · simulator"
    image_tag: str      # the running image's tag: <commit>[-dirty]-<time>
    simulated: bool     # the simulated CollectionSpace and the fake ETL; False: look-only (D224, D227)
    log_prefix: str     # /serena/dev: the log groups, /serena/dev/web …
    bucket: str         # the museum's bucket: serena-dev-pahma-<account>-us-west-2

    @property
    def admin_url(self) -> str:
        return f"{self.url}/admin/"


def from_environment() -> Target:
    """The target ./serena aws test describes, or SystemExit with what's wrong: never a guess."""
    try:
        env = os.environ["SERENADE_AWS_ENV"]
        url = os.environ["SERENADE_AWS_URL"].rstrip("/")
        files_url = os.environ["SERENADE_AWS_FILES_URL"].rstrip("/")
        target = Target(env=env, url=url, files_url=files_url, root=os.environ["SERENADE_AWS_ROOT"],
                        my_address=os.environ["SERENADE_AWS_MY_ADDRESS"],
                        etl_cidrs=_cidrs(os.environ["SERENADE_AWS_ETL_CIDRS"]),
                        admin_cidrs=_cidrs(os.environ["SERENADE_AWS_ADMIN_CIDRS"]),
                        admitted_cidrs=_cidrs(os.environ["SERENADE_AWS_ADMITTED_CIDRS"]),
                        museum=os.environ["SERENADE_AWS_MUSEUM"],
                        label=os.environ["SERENADE_AWS_LABEL"], image_tag=os.environ["SERENADE_AWS_IMAGE_TAG"],
                        simulated=os.environ["SERENADE_AWS_SIMULATED"] == "true",
                        log_prefix=os.environ["SERENADE_AWS_LOG_PREFIX"], bucket=os.environ["SERENADE_AWS_BUCKET"])
    except KeyError as missing:
        raise SystemExit(f"The AWS tests run only through ./serena aws test ({missing.args[0]} isn't set).") from None
    saved = REPO / "deploy" / "environments" / f"{env}.url"
    if not saved.is_file() or saved.read_text().strip().rstrip("/") != url:
        raise SystemExit(f"{url} isn't the address of '{env}' ({saved}): the AWS tests run nowhere else.")
    if not re.fullmatch(r"https://[a-z0-9]+\.cloudfront\.net", files_url):
        raise SystemExit(f"{files_url} isn't a CloudFront address.")
    if target.root == "personal" and url != files_url:
        raise SystemExit(f"On the personal root the app and the files share one address, not {url} and {files_url}.")
    if target.root == "shared" and not re.fullmatch(r"https://[a-z0-9.-]+", url):
        raise SystemExit(f"{url} isn't a host name.")
    return target


def _cidrs(value: str) -> tuple[str, ...]:
    return tuple(c.strip() for c in value.split(",") if c.strip())


def connects(url: str, port: int, seconds: float = 10) -> bool:
    """Whether a TCP connection to the address's host and port opens within the time (a security group that doesn't
    admit this computer drops it: no answer at all)."""
    host = url.split("://", 1)[1].split("/", 1)[0]
    try:
        with socket.create_connection((host, port), timeout=seconds):
            return True
    except OSError:
        return False


def listed(address: str, cidrs: tuple[str, ...]) -> bool:
    """Whether an address is in one of the ranges."""
    ip = ipaddress.ip_address(address)
    return any(ip in ipaddress.ip_network(c, strict=False) for c in cidrs)


# ---- HTTP -----------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Answer:
    status: int
    headers: Message
    body: bytes

    def header(self, name: str) -> str:
        return str(self.headers.get(name) or "")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def get(url: str) -> Answer:
    """GETs an https address without following a redirect; every status is an answer, not an error."""
    if not url.startswith("https://"):
        raise AssertionError(f"not an https address: {url}")
    try:
        with _opener.open(url, timeout=60) as answer:
            return Answer(answer.status, answer.headers, answer.read())
    except urllib.error.HTTPError as answer:
        return Answer(answer.code, answer.headers, answer.read())


def eventually(check: Callable[[], T], seconds: float = 60, every: float = 2) -> T:
    """Repeats a check until it passes or time runs out (a recall's effect, Logs Insights catching up)."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            return check()
        except AssertionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(every)


# ---- ./serena aws and the AWS CLI (read-only, D231) -----------------------------------------------------------------

def serena_aws(*args: str, timeout: float = 900) -> str:
    """Runs ./serena aws <args> for the target's environment and returns its standard output; fails the test on a
    non-zero exit, with its error output. The profile, region and sign-in are the ones ./serena aws test checked."""
    env = os.environ["SERENADE_AWS_ENV"]
    done = subprocess.run([str(REPO / "serena"), "aws", "--env", env, *args], capture_output=True, text=True,  # noqa: S603
                          timeout=timeout, check=False)
    if done.returncode != 0:
        raise AssertionError(f"./serena aws {' '.join(args)} ended with {done.returncode}:\n{done.stderr[-2000:]}")
    return done.stdout


def fake_etl(museum: str, *options: str) -> dict[str, Any]:
    """A daily refresh by the fake ETL inside the environment (./serena aws etl … --json); its summary."""
    out = serena_aws("etl", museum, *options, "--json")
    lines = [line for line in out.splitlines() if line.startswith("{")]
    if len(lines) != 1:
        raise AssertionError(f"./serena aws etl {museum} --json printed no single summary:\n{out[-2000:]}")
    summary: dict[str, Any] = json.loads(lines[0])
    return summary


def aws_cli(*args: str) -> Any:
    """A read-only AWS CLI call with the environment's profile and region (in the environment ./serena aws test
    exported), answered as JSON."""
    done = subprocess.run(["aws", *args, "--output", "json"], capture_output=True, text=True,  # noqa: S603, S607
                          timeout=120, check=False)
    if done.returncode != 0:
        raise AssertionError(f"aws {' '.join(args)} ended with {done.returncode}:\n{done.stderr[-2000:]}")
    return json.loads(done.stdout or "null")
