"""The admin API for recalls and Media look up (design: Recalls, Admin web app; decided October 12, 2026, D116
to D123, D128 to D131)."""
from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from . import cache_index, recalls
from .admin_api import SignedIn, changes, services
from .alerts import Alerts
from .audit import Action, Audit
from .csid import is_csid
from .cspace.clients import CSpaceClients
from .lookup import LookupProblem, explain
from .museum import Museum
from .museum_settings import MuseumSettings
from .refreshes import Refreshes
from .store import Recall, Store

log = logging.getLogger("serena.admin_recalls")

DAYS_SHOWN = 30  # the Recalls page lists the last 30 days' ended recalls (D120)
PREVIEW_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf"})
# A thumbnail or full-size view comes only through the admin API, to signed-in admins, never cached (D129).
PREVIEW_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline"}


@dataclass
class RecallServices:
    store: Store
    cspace: CSpaceClients | None
    audit: Audit
    alerts: Alerts  # the app's: records alerts; the worker emails them
    refreshes: Refreshes
    museum_settings: MuseumSettings
    s3: Any
    buckets: dict[str, str]
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))


def recall_services(request: Request) -> RecallServices:
    found: RecallServices = request.app.state.admin_recalls
    return found


Recalls_ = Annotated[RecallServices, Depends(recall_services)]
MediaCsid = Annotated[str, Path(pattern=r"^[A-Za-z0-9-]{1,64}$")]


class Csids(BaseModel):
    text: str = Field(max_length=80_000)  # up to 1,000 CSIDs of up to 64 characters, with separators


class RecallBody(Csids):
    reason: str = Field(min_length=1, max_length=500)


class Reason(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


def _clean(reason: str) -> str:
    return " ".join(reason.split())


def _parse(text: str) -> list[str]:
    try:
        csids = recalls.parse(text)
    except ValueError as error:
        raise HTTPException(422, f"{str(error)[0].upper()}{str(error)[1:]}: send the rest separately.") from error
    if not csids:
        raise HTTPException(422, "Give at least one Media or Blob CSID.")
    return csids


def _recall_json(t: Recall) -> dict[str, Any]:
    return {"media_csid": t.media_csid, "blob_csids": list(t.blob_csids), "by": t.by, "at": t.at, "reason": t.reason,
            "kept_by": t.kept_by, "kept_on": t.kept_on}


def create_router() -> APIRouter:
    router = APIRouter(prefix="/admin/v1/museums/{tenant}")

    def museum_of(request: Request, tenant: str) -> Museum:
        museum: Museum = services(request).museums[tenant]
        return museum

    @router.get("/recalls")
    def list_recalls(request: Request, session: SignedIn, t: Recalls_) -> dict[str, Any]:
        """Every active recall, and the last 30 days' ended ones, from the audit log (D120)."""
        ended = [{"media_csid": e.target, "at": e.at, "by": e.admin, "action": e.action, "details": e.details}
                 for e in t.audit.since(session.tenant, t.clock() - timedelta(days=DAYS_SHOWN))
                 if e.action in (Action.RECALL_ENDED, Action.RECALL_RELEASE)]
        return {"days": DAYS_SHOWN, "active": [_recall_json(x) for x in t.store.recalls(session.tenant)],
                "ended": ended, "max_in_box": recalls.MAX_IN_BOX, "max_in_file": recalls.MAX_IN_FILE}

    @router.post("/recalls/summary", dependencies=[Depends(changes)])
    def summary(request: Request, session: SignedIn, t: Recalls_, body: Csids) -> dict[str, Any]:
        """What a recall of these CSIDs would recall; nothing changes (D116, D117)."""
        museum = museum_of(request, session.tenant)
        return recalls.identify(museum, _parse(body.text), t.store, t.cspace).json()

    @router.post("/recalls", dependencies=[Depends(changes)])
    def recall(request: Request, session: SignedIn, t: Recalls_, body: RecallBody) -> dict[str, Any]:
        """Takes down the Media records the CSIDs name, finding them again rather than trusting the page (D118)."""
        museum = museum_of(request, session.tenant)
        found = recalls.identify(museum, _parse(body.text), t.store, t.cspace)
        done = recalls.recall(museum, found, _clean(body.reason), session.user, t.store, t.audit, t.alerts,
                                   t.clock)
        return {**found.json(), "recalled": done}

    @router.post("/recalls/{media_csid}/release", dependencies=[Depends(changes)])
    def release(request: Request, session: SignedIn, t: Recalls_, media_csid: MediaCsid,
                body: Reason) -> dict[str, Any]:
        """The one admin action that ends a recall, and only one a refresh kept (D119)."""
        museum = museum_of(request, session.tenant)
        try:
            recalls.release(museum, media_csid, _clean(body.reason), session.user, t.store, t.audit, t.alerts,
                              t.clock)
        except recalls.NotKept as error:
            raise HTTPException(409, "Only a recall a refresh kept, because CollectionSpace still has the file as "
                                     "public, can be released.") from error
        return {"released": media_csid}

    @router.get("/media/{media_csid}/preview")
    def preview(request: Request, session: SignedIn, t: Recalls_, media_csid: MediaCsid,
                size: Annotated[str, Query(pattern="^(thumbnail|full)$")] = "thumbnail",
                source: Annotated[str, Query(pattern="^(any|cspace)$")] = "any") -> Response:
        """A Media record's thumbnail or full-size view, for the recall form (D129): Serena's stored copy if it has
        one, otherwise CollectionSpace's, not stored. source=cspace skips Serena's copy: Media look up's view of
        CollectionSpace's file now (D144). Never cached."""
        museum = museum_of(request, session.tenant)
        if not is_csid(media_csid):
            raise HTTPException(404, "No such Media record.")
        rows = recalls.rows_of_media(t.store, museum.key, media_csid)
        kind = rows[0].kind if rows else None
        if kind == "3D":
            raise HTTPException(404, "A 3D file has no preview.")
        derivative: str | None = "Thumbnail" if "Thumbnail" in museum.derivatives else museum.derivatives[0]
        if size == "full":
            derivative = None if kind == "pdf" else museum.derivatives[-1]
        limit = t.museum_settings.get(museum).size_limit_mb.get(kind or "image", 0) * 1024 * 1024  # type: ignore[call-overload]
        for row in rows if source == "any" else []:
            entry = cache_index.lookup(t.store, museum.key, row.blob_csid, derivative)
            if entry is not None and entry.content_type in PREVIEW_TYPES:
                obj = t.s3.get_object(Bucket=t.buckets[museum.key], Key=entry.key)
                return StreamingResponse(obj["Body"].iter_chunks(), media_type=entry.content_type,
                                         headers=PREVIEW_HEADERS)
        return _from_collectionspace(t, museum.key, media_csid, derivative, limit)

    @router.get("/blobs/{blob_csid}/preview")
    def blob_preview(request: Request, session: SignedIn, t: Recalls_, blob_csid: MediaCsid,
                     size: Annotated[str, Query(pattern="^[A-Za-z]{1,20}$")] = "full") -> Response:
        """A Blob's file at one size, for the file dialogs of Past requests, Recalls and Media look up (D144, D145):
        Serena's stored copy if it has one, otherwise the file from CollectionSpace by the Blob's Media record, not
        stored. "full" is the largest size the museum serves. Admins see recalled and restricted files too. Never
        cached."""
        museum = museum_of(request, session.tenant)
        if not is_csid(blob_csid):
            raise HTTPException(404, "No such Blob.")
        record = t.store.servability(museum.key, blob_csid)
        kind = record.kind if record else None
        if kind == "3D":
            raise HTTPException(404, "A 3D file has no preview.")
        if size == "full":
            derivative: str | None = museum.derivatives[-1]
        elif size == "original":
            derivative = None
        elif size in museum.derivatives:
            derivative = size
        else:
            raise HTTPException(422, f"Not one of {museum.name}'s sizes.")
        if kind == "pdf":
            derivative = None  # a PDF has only its original file
        entry = cache_index.lookup(t.store, museum.key, blob_csid, derivative)
        if entry is not None and entry.content_type in PREVIEW_TYPES:
            obj = t.s3.get_object(Bucket=t.buckets[museum.key], Key=entry.key)
            return StreamingResponse(obj["Body"].iter_chunks(), media_type=entry.content_type,
                                     headers=PREVIEW_HEADERS)
        media = record.media_csid if record else None
        if record is None and t.cspace is not None:
            try:
                media = t.cspace.get(museum.key).media_of_blob(blob_csid)
            except Exception as error:
                log.warning("no preview from CollectionSpace", extra={"museum": museum.key,
                                                                       "error": type(error).__name__})
                raise HTTPException(404, "Not cached, and CollectionSpace can't be reached.") from error
        if media is None:
            raise HTTPException(404, "Not cached, and no Media record has this Blob.")
        limit = t.museum_settings.get(museum).size_limit_mb.get(kind or "image", 0) * 1024 * 1024  # type: ignore[call-overload]
        return _from_collectionspace(t, museum.key, media, derivative, limit)

    @router.get("/lookup")
    def lookup(request: Request, session: SignedIn, t: Recalls_,
               q: Annotated[str, Query(min_length=1, max_length=2000)]) -> dict[str, Any]:
        """Why a file is or isn't served (D121), beside what CollectionSpace says now (D139); not audited (D123)."""
        museum = museum_of(request, session.tenant)
        try:
            return explain(museum, q, t.store, t.refreshes, t.cspace.get(museum.key) if t.cspace else None)
        except LookupProblem as problem:
            raise HTTPException(422, str(problem)) from problem

    return router


def _from_collectionspace(t: RecallServices, tenant: str, media_csid: str, derivative: str | None,
                          limit: int) -> Response:
    if t.cspace is None:
        raise HTTPException(404, "No cached copy, and CollectionSpace isn't configured here.")
    stack = contextlib.ExitStack()
    try:
        fetched = stack.enter_context(t.cspace.get(tenant).fetch(media_csid, derivative))
    except Exception as error:
        stack.close()
        log.warning("no preview from CollectionSpace", extra={"museum": tenant, "error": type(error).__name__})
        raise HTTPException(404, "No cached copy, and CollectionSpace can't be reached.") from error
    too_large = fetched.content_length is not None and limit and fetched.content_length > limit
    if fetched.status != 200 or fetched.content_type not in PREVIEW_TYPES or too_large:
        stack.close()
        raise HTTPException(404, "CollectionSpace has no file this page can show.")

    def chunks() -> Iterator[bytes]:
        sent = 0
        try:
            for chunk in fetched.chunks():
                sent += len(chunk)
                if limit and sent > limit:
                    return
                yield chunk
        finally:
            stack.close()

    return StreamingResponse(chunks(), media_type=fetched.content_type, headers=PREVIEW_HEADERS)
