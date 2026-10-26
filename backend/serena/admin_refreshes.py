"""The admin app's refreshes and alerts (design: Admin web app, The daily sequence, Servable list check and
servability update; decided October 10, 2026, D62 to D67, and revised October 12, 2026, D73 to D75, D82, D83).

Every action needs a signed-in admin for the museum and the app's header, acts only on the museum's newest refresh,
and goes in the audit log. Actions that change a refresh need a reason, which is recorded in the refresh's reasons and
the audit log. An override of the delta threshold is also emailed to the team: the app records an alert, and the
worker sends it (D62), so the app needs no permission to publish."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Annotated, Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from . import uploads
from .admin_api import SignedIn, changes, services
from .alerts import Alert, Alerts, Kind
from .audit import Action
from .refreshes import Busy, OutOfOrder, Refresh, Refreshes, State, Upload

log = logging.getLogger("serena.admin")

DAYS_SHOWN = 30  # the Refreshes and Alerts pages show the last 30 days (D67, D93)
FILE_NAME = re.compile(r"[^\w.\- ]")


@dataclass
class RefreshServices:
    refreshes: Refreshes
    alerts: Alerts  # the app's: records alerts; the worker emails them
    s3: Any


def refresh_services(request: Request) -> RefreshServices:
    found: RefreshServices = request.app.state.admin_refreshes
    return found


Refreshes_ = Annotated[RefreshServices, Depends(refresh_services)]


class Reason(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class Acknowledge(BaseModel):
    key: str = Field(min_length=1, max_length=200)


# The most alerts one "Acknowledge all" takes: far more than 30 days hold (a few a day), so a request with more is a
# mistake, not a museum's backlog.
MAX_ACKNOWLEDGE_ALL = 500


class AcknowledgeAll(BaseModel):
    """The alerts the Alerts page shows as waiting (D207): acknowledging all of them never takes one raised since."""
    keys: list[str] = Field(min_length=1, max_length=MAX_ACKNOWLEDGE_ALL)

    @field_validator("keys")
    @classmethod
    def each_key(cls, keys: list[str]) -> list[str]:
        if any(not 1 <= len(k) <= 200 for k in keys):
            raise ValueError("each key is 1 to 200 characters")
        return list(dict.fromkeys(keys))  # once each, in order


def summary(refresh: Refresh) -> dict[str, Any]:
    return {"refresh_id": refresh.refresh_id, "refresh_date": refresh.refresh_date, "state": refresh.state.value,
            "created_at": refresh.created_at, "updated_at": refresh.updated_at,
            "rows": refresh.upload.rows if refresh.upload else None, "reasons": refresh.reasons,
            # An admin refresh: the refresh date its servable list is for, which may be earlier than the refresh's
            # own (D66, D75).
            "admin_refresh_date": (refresh.admin_refresh or {}).get("refresh_date"),
            # An admin's override of the delta threshold (D83): when, by whom and why, so every page can say so
            # (issue #108). An override made before October 26, 2026 has only `at`.
            "override": refresh.override}


def detail(refresh: Refresh, newest: bool) -> dict[str, Any]:
    return {**summary(refresh), "newest": newest, "file_name": refresh.file_name,
            "upload": {"rows": refresh.upload.rows, "bytes": refresh.upload.bytes, "sha256": refresh.upload.sha256,
                       "uploaded_at": refresh.upload.uploaded_at} if refresh.upload else None,
            "check": refresh.check, "update": refresh.update, "actions": actions(refresh, newest)}


def threshold_only(refresh: Refresh) -> bool:
    """Whether the refresh's servable list check failed on the delta threshold and nothing else."""
    result = refresh.check or {}
    errors = result.get("errors") or []
    return (refresh.state == State.CHECK_FAILED and result.get("error_count") == 1 and len(errors) == 1
            and errors[0].get("field") == "file" and "threshold" in str(errors[0].get("problem", "")))


def actions(refresh: Refresh, newest: bool) -> list[str]:
    """What an admin may do to the refresh now (D63, D83): only to the museum's newest refresh."""
    if not newest:
        return []
    if refresh.state == State.UPDATE_FAILED:
        return ["retry_update"]
    if threshold_only(refresh):
        return ["override_threshold"]
    return []


def _clean(reason: str) -> str:
    return " ".join(reason.split())


def create_router() -> APIRouter:
    router = APIRouter(prefix="/admin/v1/museums/{tenant}")

    def newest_or_404(r: RefreshServices, tenant: str, refresh_id: str) -> tuple[Refresh, bool]:
        refresh = r.refreshes.get(tenant, refresh_id)
        if refresh is None:
            raise HTTPException(404, "No such refresh.")
        newest = r.refreshes.newest(tenant)
        return refresh, newest is not None and newest.refresh_id == refresh.refresh_id

    def acting_on(r: RefreshServices, tenant: str, refresh_id: str, action: str) -> Refresh:
        refresh, newest = newest_or_404(r, tenant, refresh_id)
        if action not in actions(refresh, newest):
            raise HTTPException(409, f"Refresh {refresh.refresh_id} is {refresh.state.value}"
                                     f"{'' if newest else ', and a later refresh has started'}: it can't be done now.")
        return refresh

    @router.get("/status")
    def status(session: SignedIn, r: Refreshes_) -> dict[str, Any]:
        newest = r.refreshes.newest(session.tenant)
        return {"newest": detail(newest, True) if newest else None,
                "unacknowledged": sum(1 for a in r.alerts.recent(session.tenant, _since(r))
                                      if not a["acknowledged_at"])}

    @router.get("/refreshes")
    def list_refreshes(session: SignedIn, r: Refreshes_) -> dict[str, Any]:
        """The last 30 days' refreshes, newest first; the app sorts and pages them (D91, D93)."""
        return {"days": DAYS_SHOWN,
                "refreshes": [summary(refresh) for refresh in r.refreshes.since(session.tenant, _since(r))]}

    @router.get("/refreshes/{refresh_id}")
    def get_refresh(refresh_id: str, session: SignedIn, r: Refreshes_) -> dict[str, Any]:
        refresh, newest = newest_or_404(r, session.tenant, refresh_id)
        return detail(refresh, newest)

    @router.post("/refreshes/{refresh_id}/retry-update", dependencies=[Depends(changes)])
    def retry_update(refresh_id: str, body: Reason, session: SignedIn, r: Refreshes_,
                     request: Request) -> dict[str, Any]:
        """D63: an update_failed refresh, still the newest, goes back to the worker."""
        refresh = acting_on(r, session.tenant, refresh_id, "retry_update")
        reason = _clean(body.reason)
        try:
            refresh = r.refreshes.transition(refresh, State.UPDATING,
                                             reason=f"servability update retried by an admin: {reason}")
        except OutOfOrder as error:
            raise HTTPException(409, error.detail) from None
        services(request).audit.record(session.tenant, session.user, Action.UPDATE_RETRY, refresh.refresh_id,
                                       {"reason": reason})
        return detail(refresh, True)

    @router.post("/refreshes/{refresh_id}/override-threshold", dependencies=[Depends(changes)])
    def override_threshold(refresh_id: str, body: Reason, session: SignedIn, r: Refreshes_,
                           request: Request) -> dict[str, Any]:
        """D74, D83: a refresh whose servable list check failed on the delta threshold alone goes back to the worker,
        which checks the same servable list again without the delta threshold and, on a pass, does the servability
        update. Nothing is left armed. Emailed to the team (D62)."""
        refresh = acting_on(r, session.tenant, refresh_id, "override_threshold")
        reason = _clean(body.reason)
        at = r.refreshes.now()
        try:
            override = {"at": at, "by": session.user, "reason": reason}
            refresh = r.refreshes.transition(refresh, State.CHECKING, results={"override": override},
                                             reason=f"delta threshold overridden by an admin: {reason}")
        except OutOfOrder as error:
            raise HTTPException(409, error.detail) from None
        delta = (refresh.check or {}).get("delta_percent")
        museum = services(request).museums[session.tenant]
        r.alerts.raise_(Alert(session.tenant, r.refreshes.today(), Kind.THRESHOLD_OVERRIDDEN, refresh.refresh_id,
                              f"An admin overrode the delta threshold for {museum.name}'s refresh "
                              f"{refresh.refresh_id} ({delta}% of the rows change). Serena checks the same servable "
                              f"list again without it and, on a pass, updates. Reason: {reason}",
                              instance=at))  # each override is emailed (D62)
        services(request).audit.record(session.tenant, session.user, Action.THRESHOLD_OVERRIDE, refresh.refresh_id,
                                       {"reason": reason, "delta_percent": delta})
        return detail(refresh, True)

    @router.post("/refreshes", status_code=201, dependencies=[Depends(changes)])
    async def start_admin_refresh(request: Request, session: SignedIn, r: Refreshes_,
                     x_live_core_confirmed: Annotated[str, Header()] = "",
                     x_file_name: Annotated[str, Header(max_length=600)] = "",
                     x_refresh_date: Annotated[str, Header(max_length=10)] = "",
                     x_reason: Annotated[str, Header(max_length=1600)] = "") -> dict[str, Any]:
        """An admin refresh (D66, D75, D82): the body is a servable list made with the servable list script (plain or
        gzip), and the admin confirms it was made from the live public core. Serena closes the museum's open refresh,
        if there is one, as abandoned, starts a refresh with the list, checks it, and on a pass does the servability
        update. Refused while the worker is checking or updating a refresh."""
        admin = services(request)
        if x_live_core_confirmed != "yes":
            raise HTTPException(422, "Confirm that the servable list was made from the live public core.")
        reason = _clean(unquote(x_reason))  # sent URL-encoded: a header carries only ASCII
        if not reason or len(reason) > 500:
            raise HTTPException(422, "Give a reason, up to 500 characters (D62).")
        refresh_date = x_refresh_date.strip()
        if refresh_date:
            try:
                date.fromisoformat(refresh_date)
            except ValueError:
                raise HTTPException(422, "The refresh date is a date, YYYY-MM-DD.") from None
        bucket = admin.settings.buckets.get(session.tenant)
        if bucket is None:
            raise HTTPException(503, "Serena has no bucket for this museum.")
        newest = await asyncio.to_thread(r.refreshes.newest, session.tenant)
        if newest is not None and newest.state in (State.CHECKING, State.UPDATING):
            raise HTTPException(409, f"Refresh {newest.refresh_id} is {newest.state.value}: wait for it to finish.")
        stream, gzipped = await _sniff(request.stream())
        try:
            received = await uploads.receive(stream, gzipped=gzipped,
                                             max_bytes=admin.settings.upload_max_mb * 1024 * 1024,
                                             directory=admin.settings.upload_dir)
        except uploads.TooLarge:
            raise HTTPException(413, f"At most {admin.settings.upload_max_mb} MB uncompressed.") from None
        except uploads.BadGzip:
            raise HTTPException(400, "The file looks like gzip but isn't valid gzip.") from None
        before = await asyncio.to_thread(r.refreshes.newest, session.tenant)
        try:
            try:
                refresh, _ = await asyncio.to_thread(r.refreshes.start, session.tenant,
                                                     "closed by an admin refresh")
            except Busy as busy:
                raise HTTPException(409, busy.detail) from None
            except OutOfOrder as error:
                raise HTTPException(409, error.detail) from None
            key = f"servable-list/{refresh.refresh_id}/{refresh.file_name}.gz"
            await asyncio.to_thread(uploads.store, r.s3, bucket, key, received)
            name = FILE_NAME.sub("", os.path.basename(unquote(x_file_name)))[:120] or "the servable list"
            note = (f"admin refresh with the servable list {name}"
                    + (f", for the refresh date {refresh_date}" if refresh_date else "") + f": {reason}")
            try:
                refresh = r.refreshes.transition(refresh, State.RECEIVED, reason=note,
                                                 results={"admin_refresh": {"refresh_date": refresh_date or None}},
                                                 upload=Upload(received.sha256, received.rows, received.size, key,
                                                               r.refreshes.now()))
                refresh = r.refreshes.transition(refresh, State.CHECKING)
            except OutOfOrder as error:
                raise HTTPException(409, error.detail) from None
        finally:
            os.unlink(received.path)
        if before is not None and before.open:  # the open refresh it closed, by that refresh (D150)
            admin.audit.record(session.tenant, f"refresh {before.refresh_id}", Action.REFRESH_OUTCOME,
                               before.refresh_id, {"state": State.ABANDONED.value,
                                                   "reasons": ["closed by an admin refresh"]})
        admin.audit.record(session.tenant, session.user, Action.ADMIN_REFRESH, refresh.refresh_id,
                           {"file_name": name, "refresh_date": refresh_date, "rows": received.rows,
                            "sha256": received.sha256, "reason": reason})
        log.info("admin refresh started",
                 extra={"museum": session.tenant, "refresh_id": refresh.refresh_id, "rows": received.rows})
        return detail(refresh, True)

    @router.get("/alerts")
    def list_alerts(session: SignedIn, r: Refreshes_) -> dict[str, Any]:
        return {"alerts": r.alerts.recent(session.tenant, _since(r))}

    @router.post("/alerts/acknowledge", dependencies=[Depends(changes)])
    def acknowledge(body: Acknowledge, session: SignedIn, r: Refreshes_, request: Request) -> dict[str, Any]:
        if not r.alerts.acknowledge(session.tenant, body.key, session.user):
            raise HTTPException(409, "No such alert, or it's already acknowledged.")
        services(request).audit.record(session.tenant, session.user, Action.ALERT_ACKNOWLEDGE, body.key)
        return {"acknowledged": body.key}

    @router.post("/alerts/acknowledge-all", dependencies=[Depends(changes)])
    def acknowledge_all(body: AcknowledgeAll, session: SignedIn, r: Refreshes_, request: Request) -> dict[str, Any]:
        """Acknowledges each alert the admin was shown as waiting (D207 to D210): one audit entry per alert, as for one
        alert. An alert acknowledged meanwhile (by another admin), or not this museum's, is skipped, not an error."""
        done = [key for key in body.keys if r.alerts.acknowledge(session.tenant, key, session.user)]
        for key in done:
            services(request).audit.record(session.tenant, session.user, Action.ALERT_ACKNOWLEDGE, key)
        log.info("alerts acknowledged", extra={"museum": session.tenant, "acknowledged": len(done),
                                               "skipped": len(body.keys) - len(done)})
        return {"acknowledged": done, "skipped": len(body.keys) - len(done)}

    return router


def _since(r: RefreshServices) -> str:
    return (date.fromisoformat(r.refreshes.today()) - timedelta(days=DAYS_SHOWN)).isoformat()


async def _sniff(chunks: AsyncIterator[bytes]) -> tuple[AsyncIterator[bytes], bool]:
    """Reads the first chunk to tell gzip (1f 8b) from a plain file, and gives back the whole stream."""
    first = b""
    async for chunk in chunks:
        if chunk:
            first = chunk
            break

    async def rest() -> AsyncIterator[bytes]:
        if first:
            yield first
        async for chunk in chunks:
            yield chunk

    return rest(), first[:2] == b"\x1f\x8b"
