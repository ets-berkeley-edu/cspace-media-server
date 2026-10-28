"""The admin app's refreshes and alerts (design: Admin web app, The daily sequence, Servable list check and
servability update; decided October 10, 2026, D62 to D67, and revised October 12, 2026, D73 to D75, D82, D83).

Every action needs a signed-in admin for the museum and the app's header, acts only on the museum's newest refresh,
and goes in the audit log. Actions that change a refresh need a reason, which is recorded in the refresh's reasons and
the audit log. An override of the delta threshold is also emailed to the team: the app records an alert, and the
worker sends it (D62), so the app needs no permission to publish.

A manual refresh (the admin app's Manual refresh page, issue #118; reworked October 28, 2026, mockup version 55;
"admin refresh" in the earlier decisions) replaces the current ETL list with one of the ETL's recent ones or an
uploaded one. A dry run checks it first, changing nothing and making no refresh; Apply then starts an ordinary manual
refresh, which checks the list again and, on a pass, updates by itself. A pending refresh in the way (rule D): one
waiting for the ETL job is stopped only if it is the one the admin was shown and confirmed stopping; one the worker is
checking or updating means waiting; a failed one is replaced without asking."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from . import servable_list_check as checking
from . import uploads
from .admin_api import SignedIn, changes, services
from .alerts import Alert, Alerts, Kind
from .audit import Action
from .refreshes import BUSY, PACIFIC, Busy, OutOfOrder, ReasonKind, Refresh, Refreshes, State, Upload, reason_kinds
from .servable_list import read_rows

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


# Why an admin expects the change an override lets through (issue #120, mockup version 47): one of these, then the
# reason in the admin's own words, at least OVERRIDE_REASON_MIN characters. An override made before has no kind.
OVERRIDE_KINDS = {"first_load": "First load", "bulk_change": "Known bulk change in CollectionSpace",
                  "testing": "Testing", "other": "Something else"}
OVERRIDE_REASON_MIN = 20


class Override(BaseModel):
    kind: str = Field(default="", max_length=20)
    reason: str = Field(min_length=1, max_length=500)


def override_reason(kind: str | None, reason: str) -> str:
    """The override's reason as the alert and the refresh's reasons give it: its kind's words first, when it has one."""
    return f"{OVERRIDE_KINDS[kind]}: {reason}" if kind in OVERRIDE_KINDS else reason


class FromList(BaseModel):
    """A manual refresh with one of the ETL's servable lists (issue #118), named by the refresh it came with."""
    refresh_id: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=500)
    # The pending refresh the admin was shown and confirmed stopping, when it waits for the ETL job (rule D).
    open_refresh: str = Field(default="", max_length=100)
    # Apply with override (mockup version 55): why the change is expected; the reason is then the override's.
    kind: str = Field(default="", max_length=20)


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
            # Which list each reason goes in, one per reason (issue #120): problem, admin or override.
            "reason_kinds": reason_kinds(refresh),
            # A manual refresh: the refresh date its servable list is for, which may be earlier than the refresh's
            # own (D66, D75), and, for one of the ETL's lists, the refresh it came with (issue #118).
            "manual": refresh.admin_refresh is not None,
            "admin_refresh_date": (refresh.admin_refresh or {}).get("refresh_date"),
            "admin_refresh_from": (refresh.admin_refresh or {}).get("from"),
            # An admin's override of the delta threshold (D83): when, by whom and why, so every page can say so
            # (issue #108). An override made before October 26, 2026 has only `at`.
            "override": refresh.override}


def detail(refresh: Refresh, newest: bool) -> dict[str, Any]:
    return {**summary(refresh), "newest": newest, "file_name": refresh.file_name,
            "upload": {"rows": refresh.upload.rows, "bytes": refresh.upload.bytes, "sha256": refresh.upload.sha256,
                       "uploaded_at": refresh.upload.uploaded_at} if refresh.upload else None,
            "check": refresh.check, "update": refresh.update, "actions": actions(refresh, newest),
            # A failed update: until when the worker tries it again by itself (decided October 28, 2026).
            "retry_until": refresh.retry_until if refresh.state == State.UPDATE_FAILED else None}


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


def deadline_at(refresh: Refresh, deadline: str) -> str | None:
    """When the watchdog's deadline for an ETL refresh's day passes, in UTC (mockup version 55): the app says so
    beside a refresh still waiting or working after it. A manual refresh has none."""
    if refresh.admin_refresh is not None:
        return None
    hours, minutes = (int(part) for part in deadline.split(":"))
    at = datetime.combine(date.fromisoformat(refresh.refresh_date), time(hours, minutes), tzinfo=PACIFIC)
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


# An admin's retry, in the refresh's reasons, with who retried it (decided October 28, 2026): the 409 of an admin who
# comes second names them.
RETRIED = "ETL list update retried by "


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

    def closing(r: RefreshServices, tenant: str, shown: str) -> Refresh | None:
        """The museum's pending refresh, which a manual refresh replaces (rule D, decided October 28, 2026): refused
        while the worker is checking or applying its ETL list; one waiting for the ETL job only if it's the one the
        admin was shown and confirmed stopping; a failed one without asking, since applying another ETL list is one of
        its fixes."""
        newest = r.refreshes.newest(tenant)
        if newest is None or not newest.open:
            return None
        if newest.state in BUSY:
            step = "checking" if newest.state == State.CHECKING else "applying"
            raise HTTPException(409, f"Refresh {newest.refresh_id} is {step} its ETL list: wait a few minutes, then "
                                     "apply again.")
        if newest.state not in (State.CHECK_FAILED, State.UPDATE_FAILED) and newest.refresh_id != shown:
            raise HTTPException(409, f"Refresh {newest.refresh_id} is still under way: confirm that applying your ETL "
                                     "list stops it, then apply again.")
        return newest

    def previous_rows(request: Request, r: RefreshServices, tenant: str) -> tuple[Refresh | None, Any]:
        """The last updated refresh and its ETL list's rows, which a check compares with (None: the first)."""
        last = r.refreshes.latest_updated(tenant)
        if last is None or last.upload is None:
            return last, None
        with stored(request, tenant, last.upload.key) as handle:
            return last, read_rows(handle)

    def stored(request: Request, tenant: str, key: str) -> Any:
        """A stored (gzip) ETL list, downloaded to a temporary file on the task's disk, as the worker does."""
        admin = services(request)
        handle = tempfile.TemporaryFile(dir=admin.settings.upload_dir)
        r = refresh_services(request)
        r.s3.download_fileobj(admin.settings.buckets[tenant], key, handle)
        handle.seek(0)
        return handle

    def dry_run(request: Request, r: RefreshServices, tenant: str, handle: Any) -> dict[str, Any]:
        """Manual refresh's check (mockup version 55): what applying the ETL list would change, against the last ETL
        list update, as the worker checks it; nothing is stored, and no refresh is made. A check of some 187,000 rows
        takes about a second, so it answers within the request (measured October 28, 2026)."""
        museum = services(request).museums[tenant]
        last, previous = previous_rows(request, r, tenant)
        threshold = request.app.state.museum_settings.get(museum).delta_threshold_percent
        result = checking.check(museum, handle, previous, threshold)
        return {"check": result.summary(), "checked_at": r.refreshes.now(),
                "against": {"refresh_id": last.refresh_id, "updated_at": last.updated_at}
                if last is not None and previous is not None else None}

    def overriding(r: RefreshServices, session: Any, kind: str, reason: str) -> dict[str, Any] | None:
        """Apply with override: the kind and a reason long enough, as for an override on a refresh's page."""
        if not kind:
            return None
        if kind not in OVERRIDE_KINDS:
            raise HTTPException(422, "Choose why the change is expected.")
        if len(reason) < OVERRIDE_REASON_MIN:
            raise HTTPException(422, f"Say a little more: at least {OVERRIDE_REASON_MIN} characters.")
        return {"at": r.refreshes.now(), "by": session.user, "kind": kind, "reason": reason}

    def applied(request: Request, r: RefreshServices, session: Any, refresh: Refresh,
                override: dict[str, Any] | None) -> None:
        """An override applied with the ETL list is emailed then, and audited, as every override is (D62)."""
        if override is None:
            return
        museum = services(request).museums[session.tenant]
        given = override_reason(override["kind"], override["reason"])
        r.alerts.raise_(Alert(session.tenant, r.refreshes.today(), Kind.THRESHOLD_OVERRIDDEN, refresh.refresh_id,
                              f"An admin overrode the delta threshold for {museum.name}'s manual refresh "
                              f"{refresh.refresh_id}. Serena checks the ETL list without it and, on a pass, "
                              f"updates. Reason: {given}", instance=override["at"]))
        services(request).audit.record(session.tenant, session.user, Action.THRESHOLD_OVERRIDE, refresh.refresh_id,
                                       {"kind": override["kind"], "reason": override["reason"],
                                        "delta_percent": None})

    def audit_closed(request: Request, tenant: str, r: RefreshServices, before: Refresh | None) -> None:
        """The open refresh a manual refresh closed, by that refresh (D150), with the reason it was given."""
        if before is None:
            return
        closed = r.refreshes.get(tenant, before.refresh_id)
        services(request).audit.record(tenant, f"refresh {before.refresh_id}", Action.REFRESH_OUTCOME,
                                       before.refresh_id, {"state": State.ABANDONED.value,
                                                           "reasons": (closed.reasons if closed else [])[-1:]})

    def acting_on(r: RefreshServices, tenant: str, refresh_id: str, action: str) -> Refresh:
        refresh, newest = newest_or_404(r, tenant, refresh_id)
        if action not in actions(refresh, newest):
            if action == "retry_update":
                raise HTTPException(409, not_retried(r, refresh))
            raise HTTPException(409, f"Refresh {refresh.refresh_id} is {refresh.state.value}"
                                     f"{'' if newest else ', and a later refresh has started'}: it can't be done now.")
        return refresh

    def not_retried(r: RefreshServices, refresh: Refresh) -> str:
        """Why a retry came second (decided October 28, 2026, mockup version 56): who or what got there first. The
        page shows it and loads the refresh again."""
        newest = r.refreshes.newest(refresh.tenant)
        if newest is not None and newest.refresh_id != refresh.refresh_id:
            which = "manual refresh" if newest.admin_refresh is not None else "refresh"
            return f"Not retried: the {which} {newest.refresh_id} replaced it. This page shows the refresh as it is."
        if refresh.state in (State.UPDATING, State.UPDATED):
            retried = next((x for x in reversed(refresh.reasons) if x.startswith(RETRIED)), None)
            who = retried[len(RETRIED):].split(":", 1)[0] if retried else "Serena"
            now = "Serena is applying the ETL list now" if refresh.state == State.UPDATING else "it is updated now"
            return f"Not retried: {who} retried it first, and {now}. This page shows the refresh as it is."
        return f"Not retried: refresh {refresh.refresh_id} is {refresh.state.value}. This page shows it as it is."

    def watchdog_deadline(request: Request, tenant: str) -> str:
        museum = services(request).museums[tenant]
        deadline: str = request.app.state.museum_settings.get(museum).watchdog_deadline
        return deadline

    @router.get("/status")
    def status(session: SignedIn, r: Refreshes_, request: Request) -> dict[str, Any]:
        """The museum's newest refresh, and (mockup version 55, decided October 28, 2026) its current refresh, the
        newest updated one, which Serena serves from, and its pending refresh, the newest while it is open."""
        newest = r.refreshes.newest(session.tenant)
        current = newest if newest and newest.state == State.UPDATED else r.refreshes.latest_updated(session.tenant)
        deadline = watchdog_deadline(request, session.tenant)
        return {"newest": detail(newest, True) if newest else None,
                "current": detail(current, newest is current) if current else None,
                "pending": {**detail(newest, True), "deadline_at": deadline_at(newest, deadline)}
                if newest and newest.open else None,
                "unacknowledged": sum(1 for a in r.alerts.recent(session.tenant, _since(r))
                                      if not a["acknowledged_at"])}

    @router.get("/refreshes")
    def list_refreshes(session: SignedIn, r: Refreshes_) -> dict[str, Any]:
        """The last 30 days' refreshes, newest first; the app sorts and pages them (D91, D93)."""
        return {"days": DAYS_SHOWN,
                "refreshes": [summary(refresh) for refresh in r.refreshes.since(session.tenant, _since(r))]}

    @router.get("/refreshes/{refresh_id}")
    def get_refresh(refresh_id: str, session: SignedIn, r: Refreshes_, request: Request) -> dict[str, Any]:
        refresh, newest = newest_or_404(r, session.tenant, refresh_id)
        deadline = watchdog_deadline(request, session.tenant)
        return {**detail(refresh, newest), "deadline_at": deadline_at(refresh, deadline)}

    @router.post("/refreshes/{refresh_id}/retry-update", dependencies=[Depends(changes)])
    def retry_update(refresh_id: str, body: Reason, session: SignedIn, r: Refreshes_,
                     request: Request) -> dict[str, Any]:
        """D63: an update_failed refresh, still the newest, goes back to the worker."""
        refresh = acting_on(r, session.tenant, refresh_id, "retry_update")
        reason = _clean(body.reason)
        try:
            refresh = r.refreshes.transition(refresh, State.UPDATING,
                                             reason=f"{RETRIED}{session.user}: {reason}",
                                             reason_kind=ReasonKind.ADMIN)
        except OutOfOrder:
            # Another admin's retry, or the worker's, came first (a conditional write): say who.
            current = r.refreshes.get(session.tenant, refresh_id)
            raise HTTPException(409, not_retried(r, current or refresh)) from None
        services(request).audit.record(session.tenant, session.user, Action.UPDATE_RETRY, refresh.refresh_id,
                                       {"reason": reason})
        return detail(refresh, True)

    @router.post("/refreshes/{refresh_id}/override-threshold", dependencies=[Depends(changes)])
    def override_threshold(refresh_id: str, body: Override, session: SignedIn, r: Refreshes_,
                           request: Request) -> dict[str, Any]:
        """D74, D83: a refresh whose servable list check failed on the delta threshold alone goes back to the worker,
        which checks the same servable list again without the delta threshold and, on a pass, does the servability
        update. Nothing is left armed. Emailed to the team (D62). The admin says why the change is expected: a kind,
        and the reason in their own words (issue #120)."""
        refresh = acting_on(r, session.tenant, refresh_id, "override_threshold")
        if body.kind not in OVERRIDE_KINDS:
            raise HTTPException(422, "Choose why the change is expected.")
        reason = _clean(body.reason)
        if len(reason) < OVERRIDE_REASON_MIN:
            raise HTTPException(422, f"Say a little more: at least {OVERRIDE_REASON_MIN} characters.")
        given = override_reason(body.kind, reason)
        at = r.refreshes.now()
        try:
            override = {"at": at, "by": session.user, "kind": body.kind, "reason": reason}
            refresh = r.refreshes.transition(refresh, State.CHECKING, results={"override": override},
                                             reason=f"delta threshold overridden by an admin: {given}",
                                             reason_kind=ReasonKind.OVERRIDE)
        except OutOfOrder as error:
            raise HTTPException(409, error.detail) from None
        delta = (refresh.check or {}).get("delta_percent")
        museum = services(request).museums[session.tenant]
        then = "on a pass, updates"
        r.alerts.raise_(Alert(session.tenant, r.refreshes.today(), Kind.THRESHOLD_OVERRIDDEN, refresh.refresh_id,
                              f"An admin overrode the delta threshold for {museum.name}'s refresh "
                              f"{refresh.refresh_id} ({delta}% of the rows change). Serena checks the same servable "
                              f"list again without it and, {then}. Reason: {given}",
                              instance=at))  # each override is emailed (D62)
        services(request).audit.record(session.tenant, session.user, Action.THRESHOLD_OVERRIDE, refresh.refresh_id,
                                       {"kind": body.kind, "reason": reason, "delta_percent": delta})
        return detail(refresh, True)

    @router.get("/servable-lists")
    def servable_lists(session: SignedIn, r: Refreshes_) -> dict[str, Any]:
        """Issue #118 (MR3 to MR5): the museum's 10 most recent servable lists from the ETL, newest first, each with
        its refresh and that refresh's outcome."""
        return {"lists": [{"refresh_id": refresh.refresh_id, "refresh_date": refresh.refresh_date,
                           "state": refresh.state.value, "override": refresh.override,
                           "rows": refresh.upload.rows, "sha256": refresh.upload.sha256,
                           "uploaded_at": refresh.upload.uploaded_at}
                          for refresh in r.refreshes.etl_lists(session.tenant) if refresh.upload is not None]}

    @router.post("/servable-lists/{refresh_id}/dry-run", dependencies=[Depends(changes)])
    def dry_run_of_list(refresh_id: str, session: SignedIn, r: Refreshes_, request: Request) -> dict[str, Any]:
        """Manual refresh's dry run of one of the ETL's recent lists (mockup version 55): nothing is stored, nothing
        audited."""
        source = r.refreshes.get(session.tenant, refresh_id)
        if source is None or source.upload is None or source.admin_refresh is not None:
            raise HTTPException(404, "No such ETL list.")
        with stored(request, session.tenant, source.upload.key) as handle:
            return dry_run(request, r, session.tenant, handle)

    @router.post("/servable-lists/dry-run", dependencies=[Depends(changes)])
    async def dry_run_of_upload(request: Request, session: SignedIn, r: Refreshes_) -> dict[str, Any]:
        """Manual refresh's dry run of an uploaded list (plain or gzip): it's read to the task's disk, checked and
        removed; it's sent again with Apply."""
        received = await receive(request)
        try:
            with open(received.path, "rb") as handle:
                return await asyncio.to_thread(dry_run, request, r, session.tenant, handle)
        finally:
            os.unlink(received.path)

    async def receive(request: Request) -> Any:
        admin = services(request)
        stream, gzipped = await _sniff(request.stream())
        try:
            return await uploads.receive(stream, gzipped=gzipped, max_bytes=admin.settings.upload_max_mb * 1024 * 1024,
                                         directory=admin.settings.upload_dir)
        except uploads.TooLarge:
            raise HTTPException(413, f"At most {admin.settings.upload_max_mb} MB uncompressed.") from None
        except uploads.BadGzip:
            raise HTTPException(400, "The file looks like gzip but isn't valid gzip.") from None

    @router.post("/refreshes/from-list", status_code=201, dependencies=[Depends(changes)])
    def start_from_list(body: FromList, session: SignedIn, r: Refreshes_, request: Request) -> dict[str, Any]:
        """Apply refresh with one of the ETL's lists (issue #118, MR3 to MR7; mockup version 55), named by the
        refresh it came with: an ordinary manual refresh, whose stored list is checked again and, on a pass, applied
        by the worker. With `kind`, the delta threshold is overridden for it (Apply with override)."""
        reason = _clean(body.reason)
        source = r.refreshes.get(session.tenant, body.refresh_id)
        if source is None or source.upload is None or source.admin_refresh is not None:
            raise HTTPException(404, "No such ETL list.")
        override = overriding(r, session, body.kind, reason)
        before = closing(r, session.tenant, body.open_refresh)
        try:
            refresh, _ = r.refreshes.start(session.tenant, "replaced by the manual refresh {refresh_id}")
        except OutOfOrder as error:  # Busy included
            raise HTTPException(409, error.detail) from None
        note = (f"manual refresh with the ETL list for {source.refresh_date}, from {source.refresh_id}: "
                f"{reason}")
        # The list stays where the ETL's upload put it: Serena never deletes a servable list.
        upload = Upload(source.upload.sha256, source.upload.rows, source.upload.bytes, source.upload.key,
                        r.refreshes.now())
        try:
            refresh = r.refreshes.transition(refresh, State.RECEIVED, reason=note, reason_kind=ReasonKind.ADMIN,
                                             upload=upload, results={
                "admin_refresh": {"refresh_date": source.refresh_date, "from": source.refresh_id},
                **({"override": override} if override else {})})
            refresh = r.refreshes.transition(refresh, State.CHECKING)
        except OutOfOrder as error:
            raise HTTPException(409, error.detail) from None
        audit_closed(request, session.tenant, r, before)
        applied(request, r, session, refresh, override)
        services(request).audit.record(session.tenant, session.user, Action.ADMIN_REFRESH, refresh.refresh_id,
                                       {"from": source.refresh_id, "refresh_date": source.refresh_date,
                                        "rows": upload.rows, "sha256": upload.sha256, "reason": reason})
        log.info("manual refresh started", extra={"museum": session.tenant, "refresh_id": refresh.refresh_id,
                                                  "from": source.refresh_id, "rows": upload.rows})
        return detail(refresh, True)

    @router.post("/refreshes", status_code=201, dependencies=[Depends(changes)])
    async def start_admin_refresh(request: Request, session: SignedIn, r: Refreshes_,
                     x_live_core_confirmed: Annotated[str, Header()] = "",
                     x_file_name: Annotated[str, Header(max_length=600)] = "",
                     x_refresh_date: Annotated[str, Header(max_length=10)] = "",
                     x_reason: Annotated[str, Header(max_length=1600)] = "",
                     x_open_refresh: Annotated[str, Header(max_length=100)] = "",
                     x_override_kind: Annotated[str, Header(max_length=20)] = "") -> dict[str, Any]:
        """Apply refresh with an uploaded list (D66, D75, D82; issue #118; mockup version 55): the body is an ETL list
        made with the ETL list script (plain or gzip), sent again after its dry run, and the admin confirms it
        was made from the live public core. Serena replaces the pending refresh as rule D allows (X-Open-Refresh: the
        one the admin was shown), starts a manual refresh with the list, and the worker checks and, on a pass,
        applies it. With X-Override-Kind, the delta threshold is overridden for it."""
        admin = services(request)
        if x_live_core_confirmed != "yes":
            raise HTTPException(422, "Confirm that the ETL list was made from the live public core.")
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
        override = overriding(r, session, x_override_kind.strip(), reason)
        await asyncio.to_thread(closing, r, session.tenant, x_open_refresh.strip())
        received = await receive(request)
        before = await asyncio.to_thread(closing, r, session.tenant, x_open_refresh.strip())
        try:
            try:
                refresh, _ = await asyncio.to_thread(r.refreshes.start, session.tenant,
                                                     "replaced by the manual refresh {refresh_id}")
            except Busy as busy:
                raise HTTPException(409, busy.detail) from None
            except OutOfOrder as error:
                raise HTTPException(409, error.detail) from None
            key = f"servable-list/{refresh.refresh_id}/{refresh.file_name}.gz"
            await asyncio.to_thread(uploads.store, r.s3, bucket, key, received)
            name = FILE_NAME.sub("", os.path.basename(unquote(x_file_name)))[:120] or "the ETL list"
            note = (f"manual refresh with the ETL list {name}"
                    + (f", for the refresh date {refresh_date}" if refresh_date else "") + f": {reason}")
            try:
                refresh = r.refreshes.transition(refresh, State.RECEIVED, reason=note, reason_kind=ReasonKind.ADMIN,
                                                 results={"admin_refresh": {"refresh_date": refresh_date or None},
                                                          **({"override": override} if override else {})},
                                                 upload=Upload(received.sha256, received.rows, received.size, key,
                                                               r.refreshes.now()))
                refresh = r.refreshes.transition(refresh, State.CHECKING)
            except OutOfOrder as error:
                raise HTTPException(409, error.detail) from None
        finally:
            os.unlink(received.path)
        await asyncio.to_thread(audit_closed, request, session.tenant, r, before)
        await asyncio.to_thread(applied, request, r, session, refresh, override)
        admin.audit.record(session.tenant, session.user, Action.ADMIN_REFRESH, refresh.refresh_id,
                           {"file_name": name, "refresh_date": refresh_date, "rows": received.rows,
                            "sha256": received.sha256, "reason": reason})
        log.info("manual refresh started",
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
