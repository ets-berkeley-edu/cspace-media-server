"""A fake ETL: runs one museum's whole night through Serena's ETL API, as the real one will (design: The nightly
sequence, The ETL API; Jira CSW-1027). Local development only.

    python -m devtools.fake_etl --museum pahma             # a whole night: start, upload, preflight, load, apply
    python -m devtools.fake_etl --museum pahma --partial   # stops after the preflight, as a night whose Solr load
                                                           # never finishes: the watchdog notices at the deadline

It adds synthetic Media records to the CollectionSpace simulator first, and lists them in the Blob-to-Media file, so
each listed file can then be fetched on a miss. The CSIDs are made from the museum and a number, so the same
--rows gives the same file every night (preflight's change threshold passes). The museum's ETL token is read from the
local Secrets Manager stand-in, as the real ETL reads its own from its secret store; it's never printed."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import time
import uuid
from collections.abc import Callable
from typing import Any

import boto3
import httpx

from serena.config import get_settings

NAMESPACE = uuid.UUID("3f6b0c55-2c4e-4f6e-9d4b-6a1c0b6e5a10")  # for the synthetic CSIDs; not a secret
DONE = {"ready", "preflight_failed", "applied", "apply_failed", "abandoned"}

# What each museum's synthetic night lists: (kind, access) by row, repeating.
MIX: dict[str, list[tuple[str, str]]] = {
    "pahma": [("image", "public"), ("image", "public"), ("card", "public")],
    "bampfa": [("image", "public"), ("3D", "public")],
    "botgarden": [("image", "public")],
    "cinefiles": [("image", "public"), ("pdf", "public"), ("pdf", "restricted")],
    "ucjeps": [("image", "public")],
}


def csid(tenant: str, what: str, n: int) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{tenant}/{what}/{n}"))


def rows(tenant: str, count: int) -> list[tuple[str, str, str, str]]:
    mix = MIX.get(tenant, [("image", "public")])
    return [(csid(tenant, "blob", n), csid(tenant, "media", n), *mix[n % len(mix)]) for n in range(count)]


def tsv(listed: list[tuple[str, str, str, str]]) -> bytes:
    return ("blob_csid\tmedia_csid\tkind\taccess\n" + "".join("\t".join(row) + "\n" for row in listed)).encode()


def add_to_simulator(cspace: httpx.Client, listed: list[tuple[str, str, str, str]]) -> None:
    for _, media, kind, _ in listed:
        cspace.post("/_fake/media", json={"csid": media, "kind": kind}).raise_for_status()


def _call(response: httpx.Response) -> dict[str, Any]:
    if response.status_code >= 400:
        sys.exit(f"{response.request.method} {response.request.url.path}: {response.status_code} {response.text}")
    body: dict[str, Any] = response.json()
    return body


def _wait(serena: httpx.Client, run: dict[str, Any], headers: dict[str, str], until: set[str], poll: float,
          wait: Callable[[float], None], timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while run["state"] not in until:
        if time.monotonic() > deadline:
            sys.exit(f"run {run['run_id']} still {run['state']} after {timeout:.0f} seconds: is the worker running?")
        wait(poll)
        run = _call(serena.get(run["links"]["self"], headers=headers))
    return run


def night(serena: httpx.Client, cspace: httpx.Client, tenant: str, token: str, count: int = 20,
          partial: bool = False, poll: float | None = None, wait: Callable[[float], None] = time.sleep,
          timeout: float = 300.0) -> dict[str, Any]:
    """Runs the night and returns a summary: the run's final state, its counts, and sample paths to request."""
    listed = rows(tenant, count)
    add_to_simulator(cspace, listed)
    headers = {"Authorization": f"Bearer {token}"}
    run = _call(serena.post(f"/etl/v1/museums/{tenant}/runs", headers=headers))
    every = poll if poll is not None else float(run["poll_interval_seconds"])

    body = tsv(listed)
    upload = {**headers, "Content-Type": "text/tab-separated-values", "Content-Encoding": "gzip",
              "X-Row-Count": str(len(listed)), "X-Content-SHA256": hashlib.sha256(body).hexdigest()}
    _call(serena.put(run["links"]["blob_media"], content=gzip.compress(body), headers=upload))
    run = _call(serena.post(run["links"]["preflight"], headers=headers))
    run = _wait(serena, run, headers, DONE, every, wait, timeout)
    if run["state"] == "ready" and not partial:
        _call(serena.post(run["links"]["solr_load"], headers=headers, json={"outcome": "loaded", "rows": count}))
        run = _call(serena.post(run["links"]["apply"], headers=headers))
        run = _wait(serena, run, headers, DONE - {"ready"}, every, wait, timeout)

    samples: dict[str, str] = {}
    for blob, _, kind, access in listed:
        key = kind if access == "public" else f"{kind} ({access})"
        if key not in samples:
            tail = "derivatives/Medium/content" if kind in ("image", "card") else "content"
            samples[key] = f"/{tenant}/imageserver/blobs/{blob}/{tail}"
    return {"run_id": run["run_id"], "state": run["state"], "preflight": run.get("preflight"),
            "apply": run.get("apply"), "partial": partial, "samples": samples}


def token_for(tenant: str) -> str:
    settings = get_settings()
    secret_id = settings.etl_token_secret_ids.get(tenant)
    if not secret_id:
        sys.exit(f"no ETL token secret for {tenant} (SERENA_ETL_TOKEN_SECRET_IDS)")
    client = boto3.client("secretsmanager", region_name=settings.aws_region,
                          endpoint_url=settings.secretsmanager_endpoint)
    token: str = json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"])["current"]
    return token


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one museum's night through Serena's ETL API (local only).")
    parser.add_argument("--museum", required=True)
    parser.add_argument("--rows", type=int, default=20)
    parser.add_argument("--partial", action="store_true", help="stop after the preflight (no Solr load, no apply)")
    parser.add_argument("--serena", default="http://web:8000")
    parser.add_argument("--cspace", default="http://fakecspace:8180")
    parser.add_argument("--poll", type=float, default=2.0, help="seconds between polls (faster than the API says)")
    parser.add_argument("--public", default="http://localhost:8300", help="Serena's address in your browser")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = parser.parse_args()
    if get_settings().secretsmanager_endpoint is None:
        sys.exit("devtools.fake_etl runs only against the local stack.")
    with httpx.Client(base_url=args.serena, timeout=60) as serena, \
            httpx.Client(base_url=args.cspace, timeout=60) as cspace:
        summary = night(serena, cspace, args.museum, token_for(args.museum), args.rows, args.partial, args.poll)
    if args.json:
        print(json.dumps(summary))
        return
    print(f"{summary['run_id']}: {summary['state']}")
    if summary["partial"]:
        print("Partial night: the Solr load and the apply weren't reported. The watchdog raises a missed deadline "
              "at the museum's deadline.")
    for kind, path in summary["samples"].items():
        print(f"  {kind:<20} {args.public}{path}")


if __name__ == "__main__":
    main()
