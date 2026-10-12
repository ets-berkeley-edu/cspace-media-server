"""The admin app's refreshes and alerts (design: Admin web app, The daily sequence, Servable list check and
servability update; decided October 10, 2026, D62 to D67).

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
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Annotated, Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from . import uploads
from .admin_api import SignedIn, changes, services
from .alerts import Alert, Alerts, Kind
from .audit import Action
from .overrides import Overrides
from .refreshes import BUSY, CLOSED, Busy, OutOfOrder, Refresh, Refreshes, State, Upload

log = logging.getLogger("serena.admin")

DAYS_OF_ALERTS = 30  # D67
FILE_NAME = re.compile(r"[^\w.\- ]")


@dataclass
class RefreshServices:
    refreshes: Refreshes
    overrides: Overrides
    alerts: Alerts  # the app's: records alerts; the worker emails them
    s3: Any


def refresh_services(request: Request) -> RefreshServices:
    found: RefreshServices = request.app.state.admin_refreshes
    return found


Refreshes_ = Annotated[RefreshServices, Depends(refresh_services)]


class Reason(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class RecordLoad(BaseModel):
    confirmed: bool  # the admin confirms the public core loaded on that refresh date (D65)
    rows: int | None = Field(default=None, ge=0)
    reason: str = Field(min_length=1, max_length=500)  # every action needs a reason (D62)


class Acknowledge(BaseModel):
    key: str = Field(min_length=1, max_length=200)


def summary(refresh: Refresh) -> dict[str, Any]:
    return {"refresh_id": refresh.refresh_id, "refresh_date": refresh.refresh_date, "state": refresh.state.value,
            "created_at": refresh.created_at, "updated_at": refresh.updated_at,
            "rows": refresh.upload.rows if refresh.upload else None, "reasons": refresh.reasons,
            # An admin upload: the refresh date the servable list is for, which may be earlier than the refresh's
            # own (D66).
            "uploaded_refresh_date": (refresh.solr_load or {}).get("uploaded_refresh_date")}


def detail(refresh: Refresh, newest: bool, armed: bool = False) -> dict[str, Any]:
    return {**summary(refresh), "newest": newest, "file_name": refresh.file_name,
            "upload": {"rows": refresh.upload.rows, "bytes": refresh.upload.bytes, "sha256": refresh.upload.sha256,
                       "uploaded_at": refresh.upload.uploaded_at} if refresh.upload else None,
            "check": refresh.check, "solr_load": refresh.solr_load, "update": refresh.update,
            "actions": actions(refresh, newest, armed)}


def threshold_only(refresh: Refresh) -> bool:
    """Whether the refresh's servable list check failed on the delta threshold and nothing else."""
    result = refresh.check or {}
    errors = result.get("errors") or []
    return (refresh.state == State.CHECK_FAILED and result.get("error_count") == 1 and len(errors) == 1
            and errors[0].get("field") == "file" and "threshold" in str(errors[0].get("problem", "")))


def actions(refresh: Refresh, newest: bool, armed: bool = False) -> list[str]:
    """What an admin may do to the refresh now (D63 to D65): only to the museum's newest refresh. While an override is
    armed (D64), it isn't offered again."""
    if not newest:
        return []
    if refresh.state == State.UPDATE_FAILED:
        return ["retry_update"]
    if refresh.state == State.READY:
        return ["record_load"]
    if threshold_only(refresh) and not armed:
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
        if action not in actions(refresh, newest, r.overrides.get(tenant) is not None):
            raise HTTPException(409, f"Refresh {refresh.refresh_id} is {refresh.state.value}"
                                     f"{'' if newest else ', and a later refresh has started'}: it can't be done now.")
        return refresh

    @router.get("/status")
    def status(session: SignedIn, r: Refreshes_) -> dict[str, Any]:
        newest = r.refreshes.newest(session.tenant)
        override = r.overrides.get(session.tenant)
        return {"newest": detail(newest, True, override is not None) if newest else None,
                "override": asdict(override) if override else None,
                "unacknowledged": sum(1 for a in r.alerts.recent(session.tenant, _since(r))
                                      if not a["acknowledged_at"])}

    @router.get("/refreshes")
    def list_refreshes(session: SignedIn, r: Refreshes_,
                       limit: Annotated[int, Query(ge=1, le=100)] = 30) -> dict[str, Any]:
        return {"refreshes": [summary(refresh) for refresh in r.refreshes.recent(session.tenant, limit)]}

    @router.get("/refreshes/{refresh_id}")
    def get_refresh(refresh_id: str, session: SignedIn, r: Refreshes_) -> dict[str, Any]:
        refresh, newest = newest_or_404(r, session.tenant, refresh_id)
        return detail(refresh, newest, r.overrides.get(session.tenant) is not None)

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

    @router.post("/refreshes/{refresh_id}/record-load", dependencies=[Depends(changes)])
    def record_load(refresh_id: str, body: RecordLoad, session: SignedIn, r: Refreshes_,
                    request: Request) -> dict[str, Any]:
        """D65: after a failed refresh, a ready refresh's load is recorded on the admin's word, and the servability
        update queued."""
        if not body.confirmed:
            raise HTTPException(422, "Confirm that the public core loaded on that refresh date.")
        refresh = acting_on(r, session.tenant, refresh_id, "record_load")
        reason = _clean(body.reason)
        load = {"outcome": "loaded", "rows": body.rows, "recorded_by_admin": True}
        try:
            refresh = r.refreshes.transition(refresh, State.SOLR_LOADED, results={"solr_load": load},
                                             reason=f"load recorded by an admin: {reason}")
            refresh = r.refreshes.transition(refresh, State.UPDATING)
        except OutOfOrder as error:
            raise HTTPException(409, error.detail) from None
        services(request).audit.record(session.tenant, session.user, Action.RECORD_LOAD, refresh.refresh_id,
                                       {"rows": body.rows, "reason": reason})
        return detail(refresh, True)

    @router.post("/refreshes/{refresh_id}/override-threshold", dependencies=[Depends(changes)])
    def override_threshold(refresh_id: str, body: Reason, session: SignedIn, r: Refreshes_,
                           request: Request) -> dict[str, Any]:
        """D64: armed for the museum's next refresh, after this one failed on the threshold alone; emailed (D62)."""
        refresh = acting_on(r, session.tenant, refresh_id, "override_threshold")
        reason = _clean(body.reason)
        override = r.overrides.arm(session.tenant, session.user, refresh.refresh_id, reason)
        change = (refresh.check or {}).get("delta_percent")
        museum = services(request).museums[session.tenant]
        r.alerts.raise_(Alert(session.tenant, r.refreshes.today(), Kind.THRESHOLD_OVERRIDDEN, refresh.refresh_id,
                              f"An admin overrode the delta threshold for {museum.name}'s next refresh, after "
                              f"{refresh.refresh_id} failed on it ({change}% of the rows would change). The ETL "
                              f"team can rerun the ETL job, or the next refresh uses it. Reason: {reason}",
                              instance=str(int(override.armed_at))))  # each override is emailed (D62)
        services(request).audit.record(session.tenant, session.user, Action.THRESHOLD_OVERRIDE, refresh.refresh_id,
                                       {"reason": reason, "expires_at": int(override.expires_at)})
        return {"override": asdict(override)}

    @router.delete("/threshold-override", dependencies=[Depends(changes)])
    def cancel_override(session: SignedIn, r: Refreshes_, request: Request) -> dict[str, Any]:
        override = r.overrides.get(session.tenant)
        if override is None:
            raise HTTPException(404, "No override is armed.")
        r.overrides.cancel(session.tenant)
        services(request).audit.record(session.tenant, session.user, Action.THRESHOLD_OVERRIDE_CANCEL,
                                       override.after_refresh)
        return {"override": None}

    @router.put("/uploads", dependencies=[Depends(changes)])
    async def upload(request: Request, session: SignedIn, r: Refreshes_,
                     x_loaded_confirmed: Annotated[str, Header()] = "",
                     x_file_name: Annotated[str, Header(max_length=600)] = "",
                     x_refresh_date: Annotated[str, Header(max_length=10)] = "",
                     x_reason: Annotated[str, Header(max_length=1600)] = "") -> dict[str, Any]:
        """D66: after a failed refresh where the servable list never reached Serena, an admin uploads it (plain or
        gzip) and confirms the public core loaded it. Serena starts a refresh, checks the servable list, and on a pass
        does the servability update. Refused while today's refresh is open or the worker is on a refresh; an earlier
        refresh date's open refresh is abandoned, as when the ETL job starts a later one."""
        admin = services(request)
        if x_loaded_confirmed != "yes":
            raise HTTPException(422, "Confirm that the public core loaded on that refresh date with this servable "
                                     "list.")
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
        if newest is not None and newest.state not in CLOSED and (newest.refresh_date == r.refreshes.today()
                                                                    or newest.state in BUSY):
            raise HTTPException(409, f"Refresh {newest.refresh_id} is {newest.state.value}: wait for it to finish, or "
                                     "use its own actions.")
        stream, gzipped = await _sniff(request.stream())
        try:
            received = await uploads.receive(stream, gzipped=gzipped,
                                             max_bytes=admin.settings.upload_max_mb * 1024 * 1024,
                                             directory=admin.settings.upload_dir)
        except uploads.TooLarge:
            raise HTTPException(413, f"At most {admin.settings.upload_max_mb} MB uncompressed.") from None
        except uploads.BadGzip:
            raise HTTPException(400, "The file looks like gzip but isn't valid gzip.") from None
        try:
            try:
                refresh, created = await asyncio.to_thread(r.refreshes.start, session.tenant)
            except Busy as busy:
                raise HTTPException(409, busy.detail) from None
            if not created:
                raise HTTPException(409, f"Refresh {refresh.refresh_id} has just started: try again once it finishes.")
            key = f"servable-list/{refresh.refresh_id}/{refresh.file_name}.gz"
            await asyncio.to_thread(uploads.store, r.s3, bucket, key, received)
            name = FILE_NAME.sub("", os.path.basename(unquote(x_file_name)))[:120] or "the servable list"
            note = (f"servable list uploaded by an admin: {name}"
                    + (f", for the refresh date {refresh_date}" if refresh_date else "") + f": {reason}")
            load = {"outcome": "loaded", "rows": None, "recorded_by_admin": True,
                    "uploaded_refresh_date": refresh_date or None}
            try:
                refresh = r.refreshes.transition(refresh, State.RECEIVED, reason=note, results={"solr_load": load},
                                                 upload=Upload(received.sha256, received.rows, received.size, key,
                                                               r.refreshes.now()))
                refresh = r.refreshes.transition(refresh, State.CHECKING)
            except OutOfOrder as error:
                raise HTTPException(409, error.detail) from None
        finally:
            os.unlink(received.path)
        admin.audit.record(session.tenant, session.user, Action.FILE_UPLOAD, refresh.refresh_id,
                           {"file_name": name, "refresh_date": refresh_date, "rows": received.rows,
                            "sha256": received.sha256, "reason": reason})
        log.info("servable list uploaded by an admin",
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

    return router


def _since(r: RefreshServices) -> str:
    return (date.fromisoformat(r.refreshes.today()) - timedelta(days=DAYS_OF_ALERTS)).isoformat()


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
