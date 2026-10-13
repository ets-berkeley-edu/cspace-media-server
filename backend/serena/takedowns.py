"""Takedowns (design: Takedowns; decided October 12, 2026, D116 to D120, D128 to D131).

An admin takes down Media records at once, given as Media or Blob CSIDs, until CollectionSpace and a later refresh
catch up. Serena finds each CSID in its servability table first and asks CollectionSpace only about the CSIDs the
table doesn't know. A takedown is stored by Media CSID, with the Blob (or Blobs) it had.

Only a successful servability update ends a takedown (D119): one whose refresh date is after the day the takedown was
made (Pacific), when its servable list no longer has any of the takedown's Blobs as public. If it still has one as
public, the takedown stays, the refresh is noted on it, and Serena raises an alert. The one admin action that ends a
takedown is Release, and only on a takedown a refresh kept."""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from . import tables
from .alerts import Alert, Alerts, Kind
from .audit import Action, Audit
from .csid import is_csid
from .cspace.client import CSpaceError, MediaState
from .cspace.clients import CSpaceClients
from .museum import SERVED_KINDS, Museum
from .refreshes import PACIFIC
from .store import ServabilityRecord, Store, Takedown

log = logging.getLogger("serena.takedowns")

MAX_IN_BOX = 12  # the form's box (D116); more come as a file
MAX_IN_FILE = 1000  # D128
_SEPARATORS = re.compile(r"[\s,]+")


def parse(text: str) -> list[str]:
    """The CSIDs in a box or a file: separated by new lines, commas or spaces; blank lines ignored; each once, in
    order."""
    seen: dict[str, None] = {}
    for token in _SEPARATORS.split(text.strip()):
        if token:
            seen.setdefault(token, None)
    if len(seen) > MAX_IN_FILE:
        raise ValueError(f"at most {MAX_IN_FILE:,} CSIDs at a time")
    return list(seen)


@dataclass
class Found:
    """A Media record to take down, and how it was found."""
    media_csid: str
    blob_csids: list[str] = field(default_factory=list)
    kind: str | None = None
    served_today: bool = False
    taken_down: bool = False
    source: str = "serena"  # "serena": its servability table; "collectionspace": a file Serena doesn't serve today
    entered: list[str] = field(default_factory=list)  # the CSIDs the admin gave for it


@dataclass
class NotFound:
    csid: str
    why: str  # not_a_csid, not_found, collectionspace_unreachable, placeholder


WHY = {
    "not_a_csid": "Not a CSID.",
    "not_found": "Not found: neither Serena nor CollectionSpace knows it as a Media record or a Blob.",
    "collectionspace_unreachable": "Not known to Serena, and CollectionSpace can't be reached: not served today. "
                                   "Try again later.",
    "placeholder": "The museum's placeholder image: it has no Media record to take down.",
}


@dataclass
class Summary:
    records: list[Found]
    not_found: list[NotFound]

    def json(self) -> dict[str, Any]:
        return {"records": [vars(r) for r in self.records],
                "not_found": [{"csid": n.csid, "why": n.why, "message": WHY[n.why]} for n in self.not_found]}


def _servable(museum: Museum, record: ServabilityRecord) -> bool:
    if record.kind not in SERVED_KINDS:
        return False
    return record.access == "public" or (record.access == "restricted" and record.kind in museum.signed_access_kinds)


def rows_of_media(store: Store, tenant: str, media_csid: str) -> list[ServabilityRecord]:
    """The servability rows of a Media record, through the by_media index."""
    page = store.client.query(TableName=store.table(tables.SERVABILITY), IndexName="by_media",
                              KeyConditionExpression="media_key = :m",
                              ExpressionAttributeValues={":m": {"S": f"{tenant}#{media_csid}"}})
    found = []
    for item in page["Items"]:
        blob = item["pk"]["S"].partition("#")[2]
        found.append(ServabilityRecord(tenant, blob, media_csid, item["kind"]["S"], item["access"]["S"]))
    return found


def identify(museum: Museum, csids: list[str], store: Store, cspace: CSpaceClients | None) -> Summary:
    """Each CSID as a Media record to take down (D116, D117): Serena's table first, CollectionSpace for the rest."""
    tenant = museum.key
    records: dict[str, Found] = {}
    not_found: list[NotFound] = []
    unknown: list[str] = []

    def add(media: str, blobs: list[str], entered: str, source: str = "serena") -> Found:
        found = records.setdefault(media, Found(media, source=source))
        for blob in blobs:
            if blob not in found.blob_csids:
                found.blob_csids.append(blob)
        if entered not in found.entered:
            found.entered.append(entered)
        return found

    for csid in csids:
        if not is_csid(csid):
            not_found.append(NotFound(csid, "not_a_csid"))
            continue
        record = store.servability(tenant, csid)
        if csid == museum.placeholder_blob_csid or (record is not None and record.media_csid is None):
            not_found.append(NotFound(csid, "placeholder"))
            continue
        if record is not None and record.media_csid is not None:
            add(record.media_csid, [csid], csid)
            continue
        rows = rows_of_media(store, tenant, csid)
        if rows:
            add(csid, [r.blob_csid for r in rows], csid)
        else:
            unknown.append(csid)

    if unknown:
        for csid, answer in zip(unknown, _ask_collectionspace(tenant, unknown, cspace), strict=True):
            if isinstance(answer, NotFound):
                not_found.append(answer)
            else:
                media, blob = answer
                add(media, [blob] if blob else [], csid, "collectionspace")

    for found in records.values():
        rows = [r for r in (store.servability(tenant, b) for b in found.blob_csids) if r is not None]
        if not rows and found.source == "serena":
            rows = rows_of_media(store, tenant, found.media_csid)
        found.kind = rows[0].kind if rows else None
        found.taken_down = store.takedown(tenant, found.media_csid) is not None
        found.served_today = not found.taken_down and any(_servable(museum, r) for r in rows)
    return Summary(list(records.values()), not_found)


def _ask_collectionspace(tenant: str, csids: list[str], cspace: CSpaceClients | None
                         ) -> list[tuple[str, str | None] | NotFound]:
    """For CSIDs Serena's table doesn't know: a Media record (with its Blob), or a Blob (with its Media record)."""
    if cspace is None:
        return [NotFound(c, "collectionspace_unreachable") for c in csids]
    try:
        client = cspace.get(tenant)
    except CSpaceError:
        return [NotFound(c, "collectionspace_unreachable") for c in csids]

    def one(csid: str) -> tuple[str, str | None] | NotFound:
        try:
            state, blob = client.media_blob(csid)
            if state is not MediaState.GONE:
                return csid, blob
            if client.blob_exists(csid):
                media = client.media_of_blob(csid)
                if media:
                    return media, csid
            return NotFound(csid, "not_found")
        except CSpaceError as error:
            log.warning("CollectionSpace couldn't identify a CSID",
                        extra={"museum": tenant, "error": type(error).__name__, "status": error.status})
            return NotFound(csid, "collectionspace_unreachable")

    with ThreadPoolExecutor(max_workers=4) as pool:  # the client's own cap is 4 calls at a time per museum
        return list(pool.map(one, csids))


def _today(clock: Callable[[], datetime]) -> str:
    return clock().astimezone(PACIFIC).date().isoformat()


def take_down(museum: Museum, summary: Summary, reason: str, admin: str, store: Store, audit: Audit,
              alerts: Alerts, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> list[str]:
    """Takes down the summary's Media records not already taken down (D118). Returns their Media CSIDs."""
    at = clock().astimezone(UTC).isoformat(timespec="seconds")
    done: list[str] = []
    for found in summary.records:
        if found.taken_down:
            continue
        if store.put_takedown(Takedown(museum.key, found.media_csid, tuple(found.blob_csids), admin, at, reason)):
            audit.record(museum.key, admin, Action.TAKEDOWN, found.media_csid,
                         {"blob_csids": found.blob_csids, "reason": reason, "found_in": found.source})
            done.append(found.media_csid)
    if done:
        what = "1 Media record" if len(done) == 1 else f"{len(done)} Media records"
        alerts.raise_(Alert(museum.key, _today(clock), Kind.TAKEDOWN, "takedown",
                            f"An admin took down {what} for {museum.name}. Reason: {reason}", instance=at))
        log.info("takedown", extra={"museum": museum.key, "media_records": len(done)})
    return done


class NotKept(Exception):
    """Only a takedown a refresh kept can be released (D119)."""


def release(museum: Museum, media_csid: str, reason: str, admin: str, store: Store, audit: Audit, alerts: Alerts,
            clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
    takedown = store.takedown(museum.key, media_csid)
    if takedown is None or not takedown.kept_by or not store.delete_takedown(museum.key, media_csid, kept_only=True):
        raise NotKept(media_csid)
    audit.record(museum.key, admin, Action.TAKEDOWN_RELEASE, media_csid,
                 {"blob_csids": list(takedown.blob_csids), "kept_by": takedown.kept_by, "reason": reason})
    at = clock().astimezone(UTC).isoformat(timespec="seconds")
    alerts.raise_(Alert(museum.key, _today(clock), Kind.TAKEDOWN_RELEASED, media_csid,
                        f"An admin released the takedown of Media record {media_csid} for {museum.name}, which "
                        f"refresh {takedown.kept_by} kept. Reason: {reason}", instance=at))


@dataclass
class AfterUpdate:
    removed: int = 0
    kept: int = 0


def after_update(museum: Museum, refresh_id: str, refresh_date: str, store: Store, audit: Audit,
                 alerts: Alerts | None) -> AfterUpdate:
    """After a successful servability update: end the takedowns CollectionSpace has caught up with (D119)."""
    counts = AfterUpdate()
    for takedown in store.takedowns(museum.key):
        made_on = datetime.fromisoformat(takedown.at).astimezone(PACIFIC).date().isoformat() if takedown.at else ""
        if refresh_date <= made_on:
            continue  # too early: this refresh's list may predate the change in CollectionSpace
        public = [blob for blob in takedown.blob_csids
                  if (row := store.servability(museum.key, blob)) is not None and row.access == "public"]
        if public:
            store.keep_takedown(takedown, refresh_id, refresh_date)
            counts.kept += 1
            if alerts is not None:
                alerts.raise_(Alert(
                    museum.key, refresh_date, Kind.STILL_PUBLIC, takedown.media_csid,
                    f"Refresh {refresh_id} still lists Media record {takedown.media_csid} of {museum.name} as public "
                    f"(Blob {public[0]}), so its takedown in Serena stays. Change the record in CollectionSpace, or, "
                    "if the takedown was a mistake, release it in the admin app."))
            continue
        if store.delete_takedown(museum.key, takedown.media_csid):
            counts.removed += 1
            audit.record(museum.key, f"refresh {refresh_id}", Action.TAKEDOWN_REMOVED, takedown.media_csid,
                         {"blob_csids": list(takedown.blob_csids), "refresh_id": refresh_id,
                          "why": "no longer listed as public", "taken_down_by": takedown.by,
                          "taken_down_at": takedown.at})
    if counts.removed and alerts is not None:
        what = "1 takedown" if counts.removed == 1 else f"{counts.removed} takedowns"
        alerts.raise_(Alert(museum.key, refresh_date, Kind.TAKEDOWNS_REMOVED, refresh_id,
                            f"Refresh {refresh_id} removed {what} for {museum.name}: its servable list no longer has "
                            "their files as public."))
    return counts
