"""The admin app's runs and alerts (design: Admin web app, The nightly sequence, Preflight and apply; decided October
10, 2026, D62 to D67).

Every action needs a signed-in admin for the museum and the app's header, acts only on the museum's newest run, and
goes in the audit log. Actions that change a run need a reason, which is recorded in the run's reasons and the audit
log. An override of the change threshold is also emailed to the team: the app records an alert, and the worker sends
it (D62), so the app needs no permission to publish."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from . import uploads
from .admin_api import SignedIn, changes, services
from .alerts import Alert, Alerts, Kind
from .audit import Action
from .overrides import Overrides
from .runs import CLOSED, OutOfOrder, Run, Runs, State, Upload

log = logging.getLogger("serena.admin")

NIGHTS_OF_ALERTS = 30  # D67
FILE_NAME = re.compile(r"[^\w.\- ]")


@dataclass
class RunServices:
    runs: Runs
    overrides: Overrides
    alerts: Alerts  # the app's: records alerts; the worker emails them
    s3: Any


def run_services(request: Request) -> RunServices:
    found: RunServices = request.app.state.admin_runs
    return found


Runs_ = Annotated[RunServices, Depends(run_services)]


class Reason(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class RecordLoad(BaseModel):
    confirmed: bool  # the admin confirms the public core loaded that night (D65)
    rows: int | None = Field(default=None, ge=0)
    reason: str = Field(default="", max_length=500)


class Acknowledge(BaseModel):
    key: str = Field(min_length=1, max_length=200)


def summary(run: Run) -> dict[str, Any]:
    return {"run_id": run.run_id, "night": run.night, "state": run.state.value, "created_at": run.created_at,
            "updated_at": run.updated_at, "rows": run.upload.rows if run.upload else None,
            "reasons": run.reasons}


def detail(run: Run, newest: bool, armed: bool = False) -> dict[str, Any]:
    return {**summary(run), "newest": newest, "file_name": run.file_name,
            "upload": {"rows": run.upload.rows, "bytes": run.upload.bytes, "sha256": run.upload.sha256,
                       "uploaded_at": run.upload.uploaded_at} if run.upload else None,
            "preflight": run.preflight, "solr_load": run.solr_load, "apply": run.apply,
            "actions": actions(run, newest, armed)}


def threshold_only(run: Run) -> bool:
    """Whether the run's preflight failed on the change threshold and nothing else."""
    result = run.preflight or {}
    errors = result.get("errors") or []
    return (run.state == State.PREFLIGHT_FAILED and result.get("error_count") == 1 and len(errors) == 1
            and errors[0].get("field") == "file" and "threshold" in str(errors[0].get("problem", "")))


def actions(run: Run, newest: bool, armed: bool = False) -> list[str]:
    """What an admin may do to the run now (D63 to D65): only to the museum's newest run. While an override is
    armed (D64), it isn't offered again."""
    if not newest:
        return []
    if run.state == State.APPLY_FAILED:
        return ["retry_apply"]
    if run.state == State.READY:
        return ["record_load"]
    if threshold_only(run) and not armed:
        return ["override_threshold"]
    return []


def _clean(reason: str) -> str:
    return " ".join(reason.split())


def create_router() -> APIRouter:
    router = APIRouter(prefix="/admin/v1/museums/{tenant}")

    def newest_or_404(r: RunServices, tenant: str, run_id: str) -> tuple[Run, bool]:
        run = r.runs.get(tenant, run_id)
        if run is None:
            raise HTTPException(404, "No such run.")
        newest = r.runs.newest(tenant)
        return run, newest is not None and newest.run_id == run.run_id

    def acting_on(r: RunServices, tenant: str, run_id: str, action: str) -> Run:
        run, newest = newest_or_404(r, tenant, run_id)
        if action not in actions(run, newest, r.overrides.get(tenant) is not None):
            raise HTTPException(409, f"Run {run.run_id} is {run.state.value}"
                                     f"{'' if newest else ', and a later run has started'}: it can't be done now.")
        return run

    @router.get("/status")
    def status(session: SignedIn, r: Runs_) -> dict[str, Any]:
        newest = r.runs.newest(session.tenant)
        override = r.overrides.get(session.tenant)
        return {"newest": detail(newest, True, override is not None) if newest else None,
                "override": asdict(override) if override else None,
                "unacknowledged": sum(1 for a in r.alerts.recent(session.tenant, _since(r))
                                      if not a["acknowledged_at"])}

    @router.get("/runs")
    def list_runs(session: SignedIn, r: Runs_, limit: Annotated[int, Query(ge=1, le=100)] = 30) -> dict[str, Any]:
        return {"runs": [summary(run) for run in r.runs.recent(session.tenant, limit)]}

    @router.get("/runs/{run_id}")
    def get_run(run_id: str, session: SignedIn, r: Runs_) -> dict[str, Any]:
        run, newest = newest_or_404(r, session.tenant, run_id)
        return detail(run, newest, r.overrides.get(session.tenant) is not None)

    @router.post("/runs/{run_id}/retry-apply", dependencies=[Depends(changes)])
    def retry_apply(run_id: str, body: Reason, session: SignedIn, r: Runs_, request: Request) -> dict[str, Any]:
        """D63: an apply_failed run, still the newest, goes back to the worker."""
        run = acting_on(r, session.tenant, run_id, "retry_apply")
        reason = _clean(body.reason)
        try:
            run = r.runs.transition(run, State.APPLYING, reason=f"apply retried by an admin: {reason}")
        except OutOfOrder as error:
            raise HTTPException(409, error.detail) from None
        services(request).audit.record(session.tenant, session.user, Action.APPLY_RETRY, run.run_id,
                                       {"reason": reason})
        return detail(run, True)

    @router.post("/runs/{run_id}/record-load", dependencies=[Depends(changes)])
    def record_load(run_id: str, body: RecordLoad, session: SignedIn, r: Runs_, request: Request) -> dict[str, Any]:
        """D65: after a partial night, a ready run's load is recorded on the admin's word, and the apply queued."""
        if not body.confirmed:
            raise HTTPException(422, "Confirm that the public core loaded that night.")
        run = acting_on(r, session.tenant, run_id, "record_load")
        reason = _clean(body.reason)
        load = {"outcome": "loaded", "rows": body.rows, "recorded_by_admin": True}
        try:
            run = r.runs.transition(run, State.SOLR_LOADED, results={"solr_load": load},
                                    reason="load recorded by an admin" + (f": {reason}" if reason else ""))
            run = r.runs.transition(run, State.APPLYING)
        except OutOfOrder as error:
            raise HTTPException(409, error.detail) from None
        services(request).audit.record(session.tenant, session.user, Action.RECORD_LOAD, run.run_id,
                                       {"rows": body.rows, "reason": reason})
        return detail(run, True)

    @router.post("/runs/{run_id}/override-threshold", dependencies=[Depends(changes)])
    def override_threshold(run_id: str, body: Reason, session: SignedIn, r: Runs_,
                           request: Request) -> dict[str, Any]:
        """D64: armed for the museum's next run, after this one failed on the threshold alone; emailed (D62)."""
        run = acting_on(r, session.tenant, run_id, "override_threshold")
        reason = _clean(body.reason)
        override = r.overrides.arm(session.tenant, session.user, run.run_id, reason)
        change = (run.preflight or {}).get("change_percent")
        museum = services(request).museums[session.tenant]
        r.alerts.raise_(Alert(session.tenant, r.runs.tonight(), Kind.THRESHOLD_OVERRIDDEN, run.run_id,
                              f"An admin overrode the change threshold for {museum.name}'s next run, after "
                              f"{run.run_id} failed on it ({change}% of the rows would change). The ETL team can "
                              f"rerun the night, or the next night uses it. Reason: {reason}"))
        services(request).audit.record(session.tenant, session.user, Action.THRESHOLD_OVERRIDE, run.run_id,
                                       {"reason": reason, "expires_at": int(override.expires_at)})
        return {"override": asdict(override)}

    @router.delete("/threshold-override", dependencies=[Depends(changes)])
    def cancel_override(session: SignedIn, r: Runs_, request: Request) -> dict[str, Any]:
        override = r.overrides.get(session.tenant)
        if override is None:
            raise HTTPException(404, "No override is armed.")
        r.overrides.cancel(session.tenant)
        services(request).audit.record(session.tenant, session.user, Action.THRESHOLD_OVERRIDE_CANCEL,
                                       override.after_run)
        return {"override": None}

    @router.put("/uploads", dependencies=[Depends(changes)])
    async def upload(request: Request, session: SignedIn, r: Runs_,
                     x_loaded_confirmed: Annotated[str, Header()] = "",
                     x_file_name: Annotated[str, Header(max_length=200)] = "",
                     x_night: Annotated[str, Header(max_length=10)] = "") -> dict[str, Any]:
        """D66: after a partial night where the file never reached Serena, an admin uploads that night's file (plain
        or gzip) and confirms the public core loaded it. Serena starts a run, preflights the file, and on a pass
        applies it. Refused while the museum has a run in progress."""
        admin = services(request)
        if x_loaded_confirmed != "yes":
            raise HTTPException(422, "Confirm that the public core loaded that night with this file.")
        night = x_night.strip()
        if night:
            try:
                date.fromisoformat(night)
            except ValueError:
                raise HTTPException(422, "The night is a date, YYYY-MM-DD.") from None
        bucket = admin.settings.buckets.get(session.tenant)
        if bucket is None:
            raise HTTPException(503, "Serena has no bucket for this museum.")
        newest = await asyncio.to_thread(r.runs.newest, session.tenant)
        if newest is not None and newest.state not in CLOSED:
            raise HTTPException(409, f"Run {newest.run_id} is {newest.state.value}: wait for it to finish, or "
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
            run, created = await asyncio.to_thread(r.runs.start, session.tenant)
            if not created:
                raise HTTPException(409, f"Run {run.run_id} has just started: try again once it finishes.")
            key = f"blob-media/{run.run_id}/{run.file_name}.gz"
            await asyncio.to_thread(uploads.store, r.s3, bucket, key, received)
            name = FILE_NAME.sub("", os.path.basename(x_file_name))[:120] or "the file"
            note = f"file uploaded by an admin: {name}" + (f", the night of {night}" if night else "")
            load = {"outcome": "loaded", "rows": None, "recorded_by_admin": True}
            try:
                run = r.runs.transition(run, State.RECEIVED, reason=note, results={"solr_load": load},
                                        upload=Upload(received.sha256, received.rows, received.size, key,
                                                      r.runs.now()))
                run = r.runs.transition(run, State.PREFLIGHTING)
            except OutOfOrder as error:
                raise HTTPException(409, error.detail) from None
        finally:
            os.unlink(received.path)
        admin.audit.record(session.tenant, session.user, Action.FILE_UPLOAD, run.run_id,
                           {"file_name": name, "night": night, "rows": received.rows, "sha256": received.sha256})
        log.info("file uploaded by an admin", extra={"museum": session.tenant, "run_id": run.run_id,
                                                     "rows": received.rows})
        return detail(run, True)

    @router.get("/alerts")
    def list_alerts(session: SignedIn, r: Runs_) -> dict[str, Any]:
        return {"alerts": r.alerts.recent(session.tenant, _since(r))}

    @router.post("/alerts/acknowledge", dependencies=[Depends(changes)])
    def acknowledge(body: Acknowledge, session: SignedIn, r: Runs_, request: Request) -> dict[str, Any]:
        if not r.alerts.acknowledge(session.tenant, body.key, session.user):
            raise HTTPException(409, "No such alert, or it's already acknowledged.")
        services(request).audit.record(session.tenant, session.user, Action.ALERT_ACKNOWLEDGE, body.key)
        return {"acknowledged": body.key}

    return router


def _since(r: RunServices) -> str:
    return (date.fromisoformat(r.runs.tonight()) - timedelta(days=NIGHTS_OF_ALERTS)).isoformat()


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
