"""An ETL list made from the CollectionSpace simulator's records, for the admin app's Manual refresh ("Make one from the
simulator"; serena-fakecspace-questions F12, October 29, 2026). Only where every museum's server is the simulator
(settings.simulated_cspace): the local stack, or an AWS environment with simulated_cspace.

The simulator stands in for CollectionSpace and the Solr refresh's public core: the list holds each of the museum's
Media records the ETL would list, as the real ETL list script writes it (design: The servable list). The admin app then
checks and applies it as an uploaded ETL list, so what is applied is exactly what the dry run checked."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .museum import Museum
from .servable_list import ACCESS, HEADER, KINDS

RECORDS_PATH = "/_fake/media"  # the simulator's list of a museum's Media records (fakecspace 0.2.0)


class SimulatorUnavailable(Exception):
    """The simulator didn't answer, or didn't answer as the simulator does."""


@dataclass(frozen=True)
class SimulatorList:
    tsv: str
    rows: int  # rows below the header
    left_out: dict[str, int]  # why records weren't listed: reason -> how many


def listed(record: dict[str, Any]) -> str | None:
    """None when the ETL would list the record; otherwise why not. As the public core: a record with a file and a
    Blob, not soft-deleted, approved for web (PAHMA's), of a kind and access the servable list takes."""
    if record.get("state") == "deleted":
        return "soft-deleted"
    if not record.get("blobCsid") or "content" not in record.get("files", []):
        return "no file"
    if not record.get("approvedForWeb", True):
        return "not approved for web"
    if record.get("kind") not in KINDS or record.get("access") not in ACCESS:
        return "a kind or access the ETL list doesn't take"
    return None


def make_list(records: list[dict[str, Any]], museum: Museum) -> SimulatorList:
    """The ETL list for these records: one row per listed Blob, the placeholder image's without a Media CSID, as the
    real ETL lists it (design: Placeholder image)."""
    rows: list[str] = []
    seen: set[str] = set()
    left_out: dict[str, int] = {}
    for record in records:
        why = listed(record)
        if why is None and record["blobCsid"] in seen:
            why = "a Blob listed already"
        if why is not None:
            left_out[why] = left_out.get(why, 0) + 1
            continue
        seen.add(record["blobCsid"])
        media = "" if record["blobCsid"] == museum.placeholder_blob_csid else record["csid"]
        rows.append("\t".join((record["blobCsid"], media, record["kind"], record["access"])))
    return SimulatorList(HEADER + "\n" + "".join(row + "\n" for row in rows), len(rows), left_out)


def records(http: httpx.Client, base_url: str) -> list[dict[str, Any]]:
    """The museum's records, from the simulator's development hook (the museum is told by its URL)."""
    try:
        response = http.get(base_url.rstrip("/") + RECORDS_PATH, headers={"User-Agent": "serena-admin"})
    except httpx.TransportError as error:
        raise SimulatorUnavailable(f"GET {RECORDS_PATH}: {type(error).__name__}") from error
    if response.status_code != 200:
        raise SimulatorUnavailable(f"GET {RECORDS_PATH} returned {response.status_code}")
    try:
        found = response.json()
    except ValueError as error:
        raise SimulatorUnavailable(f"GET {RECORDS_PATH}: the answer isn't JSON") from error
    if not isinstance(found, list) or not all(isinstance(r, dict) and "csid" in r for r in found):
        raise SimulatorUnavailable(f"GET {RECORDS_PATH}: not the simulator's answer")
    return found
