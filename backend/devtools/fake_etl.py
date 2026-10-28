"""A fake ETL: runs one museum's whole ETL job through Serena's ETL API, as the real one will (design: The daily
sequence, The ETL API; Jira CSW-1027). For the local stack, and for an AWS environment that runs the simulated
CollectionSpace (deploy/README.md: ./serena aws etl <museum>), where every museum's server is the simulator.

    python -m devtools.fake_etl --museum pahma           # a whole daily refresh: the Solr refresh's stand-in, the
                                                         # servable list, then start, upload, check and poll
    python -m devtools.fake_etl --museum pahma --failed  # a failed refresh: Serena is never called, as when it can't
                                                         # be reached; the repair is a manual refresh (D85)
    python -m devtools.fake_etl --museum pahma --sizes 100KB:900,5MB:90,100MB:2
                                                         # 992 records whose files are about a real file's size, in
                                                         # that order, for ./serena aws replay (D283), which prints it

It adds synthetic Media records to the CollectionSpace simulator first (the stand-in for the Solr refresh), and lists
them in the servable list (the stand-in for the ETL list script), so each listed file can then be fetched on a
miss. The CSIDs are made from the museum and a number, so the same --rows
gives the same servable list every day (the delta threshold passes). The museum's ETL token is read from the
local Secrets Manager stand-in, as the real ETL reads its own from its secret store; it's never printed."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
import time
import uuid
from collections.abc import Callable
from typing import Any

import boto3
import httpx

from serena.config import get_settings
from serena.museum import load

BANDS = ("100KB", "1MB", "5MB", "20MB", "100MB")  # the simulator's size bands (fakecspace/bands.py)
NAMESPACE = uuid.UUID("3f6b0c55-2c4e-4f6e-9d4b-6a1c0b6e5a10")  # for the synthetic CSIDs; not a secret
DONE = {"check_failed", "updated", "update_failed", "abandoned"}

# What each museum's synthetic servable list holds: (kind, access) by row, repeating.
MIX: dict[str, list[tuple[str, str]]] = {
    "pahma": [("image", "public"), ("image", "public"), ("card", "public")],
    "bampfa": [("image", "public"), ("3D", "public")],
    "botgarden": [("image", "public")],
    "cinefiles": [("image", "public"), ("pdf", "public"), ("pdf", "restricted")],
    "ucjeps": [("image", "public")],
}


def csid(tenant: str, what: str, n: int) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{tenant}/{what}/{n}"))


def rows(tenant: str, count: int, first: int = 0) -> list[tuple[str, str, str, str]]:
    """The servable list's rows, records first to first + count - 1. A museum with a placeholder image gets it too,
    with no Media CSID, as the real ETL lists it (design: Placeholder image)."""
    mix = MIX.get(tenant, [("image", "public")])
    listed = [(csid(tenant, "blob", n), csid(tenant, "media", n), *mix[n % len(mix)])
              for n in range(first, first + count)]
    placeholder = load(tenant).placeholder_blob_csid
    if placeholder:
        listed.append((placeholder, "", "image", "public"))
    return listed


def tsv(listed: list[tuple[str, str, str, str]]) -> bytes:
    return ("blob_csid\tmedia_csid\tkind\taccess\n" + "".join("\t".join(row) + "\n" for row in listed)).encode()


# A synthetic Media record holding the placeholder image's Blob, for an admin to name on the Settings page (D166).
PLACEHOLDER_MEDIA = "9e8d7c6b-5a49-4382-9170-6f5e4d3c2b1a"


def parse_sizes(spec: str) -> list[str]:
    """--sizes "100KB:900,5MB:90": each row's size band, in order (the first 900 rows 100KB, the next 90 5MB)."""
    bands: list[str] = []
    for part in spec.split(","):
        band, _, count = part.strip().partition(":")
        if band not in BANDS or not count.isdigit():
            raise ValueError(f"--sizes takes BAND:COUNT,... with BAND one of {', '.join(BANDS)}, not {part.strip()!r}")
        bands += [band] * int(count)
    if not bands:
        raise ValueError("--sizes lists no rows")
    return bands


def add_to_simulator(cspace: httpx.Client, listed: list[tuple[str, str, str, str]],
                     bands: list[str] | None = None) -> None:
    """Adds the listed records to the simulator; with bands, row n's image gets band n's files (D283)."""
    for n, (blob, media, kind, _) in enumerate(listed):
        # The placeholder image is listed without a Media CSID; its picture comes from the record an admin names.
        record = {"csid": media or PLACEHOLDER_MEDIA, "kind": kind, "blob": blob}
        if not media:
            record["identification"] = "Placeholder"
        elif bands and n < len(bands) and kind in ("image", "card"):
            record["band"] = bands[n]
        cspace.post("/_fake/media", json=record).raise_for_status()


def _call(response: httpx.Response) -> dict[str, Any]:
    if response.status_code >= 400:
        sys.exit(f"{response.request.method} {response.request.url.path}: {response.status_code} {response.text}")
    body: dict[str, Any] = response.json()
    return body


def _wait(serena: httpx.Client, refresh: dict[str, Any], headers: dict[str, str], until: set[str], poll: float,
          wait: Callable[[float], None], timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while refresh["state"] not in until:
        if time.monotonic() > deadline:
            sys.exit(f"refresh {refresh['refresh_id']} still {refresh['state']} after {timeout:.0f} seconds: is the "
                     "worker running?")
        wait(poll)
        refresh = _call(serena.get(refresh["links"]["self"], headers=headers))
    return refresh


def daily_refresh(serena: httpx.Client, cspace: httpx.Client, tenant: str, token: str, count: int = 20,
                  failed: bool = False, poll: float | None = None, wait: Callable[[float], None] = time.sleep,
                  timeout: float = 300.0, bands: list[str] | None = None, first: int = 0) -> dict[str, Any]:
    """Runs the ETL job in the order of the daily sequence (design: The daily sequence; D70, D81) and returns a
    summary: the refresh's final state (None when Serena wasn't called), its counts, and sample paths to request."""
    listed = rows(tenant, count, first)
    add_to_simulator(cspace, listed, bands)  # the Solr refresh's stand-in; `listed` is the ETL list script's
    refresh: dict[str, Any] = {"refresh_id": None, "state": None}
    if not failed:
        headers = {"Authorization": f"Bearer {token}"}
        refresh = _call(serena.post(f"/etl/v1/museums/{tenant}/refreshes", headers=headers))
        every = poll if poll is not None else float(refresh["poll_interval_seconds"])
        body = tsv(listed)
        upload = {**headers, "Content-Type": "text/tab-separated-values", "Content-Encoding": "gzip",
                  "X-Row-Count": str(len(listed)), "X-Content-SHA256": hashlib.sha256(body).hexdigest()}
        _call(serena.put(refresh["links"]["servable_list"], content=gzip.compress(body), headers=upload))
        refresh = _call(serena.post(refresh["links"]["check"], headers=headers))
        refresh = _wait(serena, refresh, headers, DONE, every, wait, timeout)

    samples: dict[str, str] = {}
    for blob, media, kind, access in listed:
        if not media:
            continue
        key = kind if access == "public" else f"{kind} ({access})"
        if key not in samples:
            tail = "derivatives/Medium/content" if kind in ("image", "card") else "content"
            samples[key] = f"/{tenant}/imageserver/blobs/{blob}/{tail}"
    return {"refresh_id": refresh["refresh_id"], "state": refresh["state"], "check": refresh.get("check"),
            "update": refresh.get("update"), "failed": failed, "samples": samples}


def count_lines(summary: dict[str, Any]) -> list[str]:
    """The refresh's counts, as the admin app shows them: the servable list's rows (and, after an earlier servability
    update, what changed), then the servability update's counts."""
    lines = []
    check = summary.get("check") or {}
    if check:
        line = f"  servable list: {check['rows']} rows"
        if check.get("previous_rows") is not None:
            line += (f"; {check['added']} added, {check['removed']} removed, {check['changed']} changed "
                     f"({check['delta_percent']}% of the last servability update's {check['previous_rows']} rows)")
        lines.append(line)
    update = summary.get("update")
    if update:
        lines.append(f"  servability update: {update['written']} written, {update['deleted']} deleted, "
                     f"{update['unchanged']} unchanged")
    return lines


def threshold_failed(summary: dict[str, Any]) -> bool:
    errors = (summary.get("check") or {}).get("errors", [])
    return any("threshold" in problem.get("problem", "") for problem in errors)


def token_for(tenant: str) -> str:
    settings = get_settings()
    secret_id = settings.etl_token_secret_ids.get(tenant)
    if not secret_id:
        sys.exit(f"no ETL token secret for {tenant} (SERENA_ETL_TOKEN_SECRET_IDS)")
    client = boto3.client("secretsmanager", region_name=settings.aws_region,
                          endpoint_url=settings.secretsmanager_endpoint)
    token: str = json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"])["current"]
    return token


def why_not_here(secretsmanager_endpoint: str | None, tenants: dict[str, str], simulator: str,
                 simulated: str) -> str | None:
    """None where the fake ETL may run: the local stack (a local Secrets Manager stand-in), or an AWS environment that
    runs the simulated CollectionSpace (SERENA_SIMULATED_CSPACE=true, set only there) and whose every museum's server
    is that simulator, so the records it adds and the servable lists it sends never touch a real museum's data.
    Otherwise, why not."""
    if secretsmanager_endpoint is not None:
        return None
    if simulated != "true":
        return ("devtools.fake_etl runs only against the local stack, or in an AWS environment with the simulated "
                "CollectionSpace.")
    base = simulator.rstrip("/") + "/"
    real = sorted(t for t, url in tenants.items() if not (url.rstrip("/") + "/").startswith(base))
    if not tenants or real:
        return (f"devtools.fake_etl refused: every museum's CollectionSpace must be the simulator ({simulator}); "
                + ("no museum is set." if not tenants else "not " + ", ".join(real) + "."))
    return None


def repair_hint(museum: str, count: int, in_aws: bool) -> str:
    """What --failed prints. In AWS the servable list for the manual refresh is made on the local stack: its CSIDs
    depend only on the museum and --rows, so the file matches the records just added to the environment's simulator."""
    make = f"./serena etl {museum} --rows {count} --file-only > <file>"
    if in_aws:
        where = (f"With the local stack up (./serena up): {make}, then upload it on "
                 "Manual refresh in this environment's admin app.")
    else:
        where = f"{make}, then upload it on Manual refresh in the admin app."
    return (f"Failed refresh: {museum}'s records were added and its servable list made, but Serena wasn't called.\n"
            f"  Repair it with a manual refresh. {where}")


def threshold_hint(refresh_id: str, in_aws: bool) -> str:
    """What a refresh that failed on the delta threshold prints: how to let it through (design: Override the delta
    threshold), or how to avoid it."""
    afresh = "" if in_aws else ", or start afresh with ./serena down and ./serena up"
    return ("  The servable list changes more rows than the delta threshold allows: the last updated refresh had other "
            "records (--rows, --sizes or --first-row).\n"
            f"  To let this one through, override the delta threshold on {refresh_id} on the admin app's Refreshes "
            "page (no need to run this again: its records are in the simulator).\n"
            f"  Otherwise use the same options as the last updated refresh{afresh}.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one museum's ETL job through Serena's ETL API (the local stack, or AWS with the simulator).")
    parser.add_argument("--museum", required=True)
    parser.add_argument("--rows", type=int, default=None, help="how many records (20 unless --sizes says)")
    parser.add_argument("--sizes", default=None,
                        help="BAND:COUNT,...: the records' files about a real file's size, in that order, with "
                             f"BAND one of {', '.join(BANDS)} (for ./serena aws replay; sets --rows)")
    parser.add_argument("--first-row", type=int, default=0,
                        help="number the records from this one (new records, not yet in Serena's cache, for another "
                             "cold replay; ./serena aws replay prints it)")
    parser.add_argument("--failed", action="store_true",
                        help="a failed refresh: the Solr refresh's stand-in and the servable list, but Serena is "
                             "never called")
    parser.add_argument("--serena", default="http://web:8000")
    parser.add_argument("--cspace", default="http://fakecspace:8180")
    parser.add_argument("--poll", type=float, default=2.0, help="seconds between polls (faster than the API says)")
    parser.add_argument("--public", default="http://localhost:8300", help="Serena's address in your browser")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    parser.add_argument("--file-only", action="store_true",
                        help="add the records to the simulator and print the servable list, for the admin app's upload "
                             "page; Serena isn't called")
    args = parser.parse_args()
    bands = None
    if args.sizes is not None:
        try:
            bands = parse_sizes(args.sizes)
        except ValueError as error:
            parser.error(str(error))
        if args.rows is not None and args.rows != len(bands):
            parser.error(f"--sizes lists {len(bands)} rows but --rows says {args.rows}: give one or the other")
    args.rows = len(bands) if bands is not None else (20 if args.rows is None else args.rows)
    settings = get_settings()
    refusal = None if settings.secretsmanager_endpoint is not None else why_not_here(
        None, settings.tenants, args.cspace, os.environ.get("SERENA_SIMULATED_CSPACE", ""))
    if refusal:
        sys.exit(refusal)
    if args.file_only:
        listed = rows(args.museum, args.rows, args.first_row)
        with httpx.Client(base_url=args.cspace, timeout=60) as cspace:
            add_to_simulator(cspace, listed, bands)
        sys.stdout.buffer.write(tsv(listed))
        return
    with httpx.Client(base_url=args.serena, timeout=60) as serena, \
            httpx.Client(base_url=args.cspace, timeout=60) as cspace:
        summary = daily_refresh(serena, cspace, args.museum, token_for(args.museum), args.rows, args.failed, args.poll,
                                bands=bands, first=args.first_row)
    if args.json:
        print(json.dumps(summary))
        return
    if summary["failed"]:
        print(repair_hint(args.museum, args.rows, in_aws=settings.secretsmanager_endpoint is None))
        return
    print(f"{summary['refresh_id']}: {summary['state']}")
    for line in count_lines(summary):
        print(line)
    for problem in (summary.get("check") or {}).get("errors", []):
        print(f"  servable list check: {problem['problem']}")
    for warning in (summary.get("check") or {}).get("warnings", []):
        print(f"  servable list check warning: {warning}")
    if summary["state"] == "check_failed" and threshold_failed(summary):
        print(threshold_hint(summary["refresh_id"], in_aws=settings.secretsmanager_endpoint is None))
    for kind, path in summary["samples"].items():
        print(f"  {kind:<20} {args.public}{path}")


if __name__ == "__main__":
    main()
