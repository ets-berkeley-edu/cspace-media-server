"""The admin app's API, under /admin/v1, and the built app itself, under /admin (design: Admin web app).

Sign-in (decided October 10, 2026): the admin picks a museum and signs in with their own CollectionSpace account for
it. Serena reads the account's roles from that museum's CollectionSpace, with the admin's credentials, once; the
account must hold the museum's admin role (Serena_Admin). The password goes only to that museum and is never kept or
logged. Each museum the admin signs in to has its own session and cookie. Every request that changes something
must carry X-Serena-Admin: 1, which a cross-site form can't send; the cookies are also SameSite=Strict."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import etl_api
from .admin_sessions import Session, Sessions
from .audit import Action, Audit
from .config import Settings
from .cspace.accounts import account_roles, has_role
from .cspace.client import CSpaceError, CSpaceUnavailable
from .museum import Museum

log = logging.getLogger("serena.admin")

PREFIX = "/admin/v1"
CSRF_HEADER = "X-Serena-Admin"
# The built app's own pages: scripts and styles only from Serena; Vuetify and Swagger UI set inline styles.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")

HttpFactory = Callable[[str], httpx.Client]


@dataclass
class AdminServices:
    settings: Settings
    museums: dict[str, Museum]
    sessions: Sessions
    audit: Audit
    http: HttpFactory  # a client for the museum's CollectionSpace, to read an admin's roles at sign-in


def cookie_name(settings: Settings, tenant: str) -> str:
    return f"{settings.admin_cookie_name}_{tenant}"


def services(request: Request) -> AdminServices:
    found: AdminServices = request.app.state.admin
    return found


Services = Annotated[AdminServices, Depends(services)]


def changes(x_serena_admin: Annotated[str | None, Header()] = None) -> None:
    """A request that changes something must say it comes from the app (design: decided October 10, 2026)."""
    if x_serena_admin != "1":
        raise HTTPException(403, f"Send {CSRF_HEADER}: 1 with every request that changes something.")


def _museum(s: AdminServices, tenant: str) -> Museum:
    museum = s.museums.get(tenant)
    if museum is None:
        raise HTTPException(404, "Serena doesn't serve that museum.")
    return museum


def signed_in(request: Request, s: Services,
              tenant: Annotated[str, PathParam(pattern=r"^[a-z]+$", max_length=32)]) -> Session:
    _museum(s, tenant)
    token = request.cookies.get(cookie_name(s.settings, tenant))
    session = s.sessions.get(tenant, token) if token else None
    if session is None:
        raise HTTPException(401, "Sign in to this museum.")
    return session


SignedIn = Annotated[Session, Depends(signed_in)]


class SignIn(BaseModel):
    museum: str = Field(pattern=r"^[a-z]+$", max_length=32)
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=512)


def _set_cookie(response: Response, s: AdminServices, tenant: str, token: str) -> None:
    response.set_cookie(cookie_name(s.settings, tenant), token, max_age=int(s.sessions.max_age), path="/admin",
                        secure=s.settings.admin_cookie_secure, httponly=True, samesite="strict")


def create_router() -> APIRouter:
    router = APIRouter(prefix=PREFIX)

    @router.get("/museums")
    def museums(s: Services) -> list[dict[str, str]]:
        """The museums Serena serves, for the sign-in page's menu."""
        return [{"key": m.key, "name": m.name} for m in s.museums.values()]

    @router.get("/me")
    def me(request: Request, s: Services) -> dict[str, Any]:
        """The museums this browser is signed in to, and as whom."""
        signed: list[dict[str, str]] = []
        for tenant, museum in s.museums.items():
            token = request.cookies.get(cookie_name(s.settings, tenant))
            session = s.sessions.get(tenant, token) if token else None
            if session is not None:
                signed.append({"museum": tenant, "name": museum.name, "user": session.user})
        return {"environment": s.settings.env_label, "sessions": signed}

    @router.post("/sessions", dependencies=[Depends(changes)])
    def sign_in(body: SignIn, s: Services, response: Response) -> dict[str, str]:
        museum = _museum(s, body.museum)
        http = s.http(museum.key)
        try:
            roles = account_roles(http, s.settings.tenants[museum.key], body.username, body.password)
        except CSpaceUnavailable:
            log.warning("sign-in: CollectionSpace unavailable", extra={"museum": museum.key})
            raise HTTPException(503, f"{museum.name}'s CollectionSpace didn't answer. Try again in a minute.") from None
        except CSpaceError as error:
            # The username isn't logged: a failed sign-in's may be anyone's, or a mistyped password.
            log.info("sign-in refused", extra={"museum": museum.key, "status": error.status})
            if error.status in (401, 403):
                raise HTTPException(401, f"That username and password don't work in {museum.name}'s "
                                         "CollectionSpace.") from None
            raise HTTPException(502, f"{museum.name}'s CollectionSpace gave an unexpected answer.") from None
        finally:
            http.close()
        if not has_role(roles, museum.admin_role):
            log.info("sign-in refused: no admin role", extra={"museum": museum.key})
            raise HTTPException(403, f"Your {museum.name} account doesn't have the {museum.admin_role} role. "
                                     f"Ask {museum.name}'s CollectionSpace administrators for it.")
        token = s.sessions.start(museum.key, body.username)
        _set_cookie(response, s, museum.key, token)
        s.audit.record(museum.key, body.username, Action.SIGN_IN)
        log.info("signed in", extra={"museum": museum.key})
        return {"museum": museum.key, "name": museum.name, "user": body.username}

    @router.delete("/sessions/{tenant}", dependencies=[Depends(changes)])
    def sign_out(request: Request, session: SignedIn, s: Services, response: Response) -> dict[str, str]:
        s.sessions.end(request.cookies[cookie_name(s.settings, session.tenant)])
        response.delete_cookie(cookie_name(s.settings, session.tenant), path="/admin",
                               secure=s.settings.admin_cookie_secure, httponly=True, samesite="strict")
        s.audit.record(session.tenant, session.user, Action.SIGN_OUT)
        return {"museum": session.tenant}

    @router.post("/museums/{tenant}/sign-out-all", dependencies=[Depends(changes)])
    def sign_out_all(session: SignedIn, s: Services, response: Response) -> dict[str, Any]:
        """Ends every admin's session for this museum, the caller's included: after a role is removed, say."""
        ended = s.sessions.end_all(session.tenant)
        response.delete_cookie(cookie_name(s.settings, session.tenant), path="/admin",
                               secure=s.settings.admin_cookie_secure, httponly=True, samesite="strict")
        s.audit.record(session.tenant, session.user, Action.SIGN_OUT_ALL, details={"sessions": ended})
        return {"museum": session.tenant, "sessions_ended": ended}

    @router.get("/museums/{tenant}/audit")
    def audit(session: SignedIn, s: Services, before: str | None = None, limit: int = 100) -> dict[str, Any]:
        entries = s.audit.recent(session.tenant, max(1, min(limit, 500)), before)
        return {"museum": session.tenant, "entries": [asdict(e) for e in entries]}

    @router.get("/museums/{tenant}/etl-api.json")
    def etl_api_document(session: SignedIn) -> Response:
        """The ETL API's OpenAPI description, for the "API documentation" button (F6): generated from the code, so
        it's always current."""
        return Response(etl_api.openapi_document(), media_type="application/json")

    return router


def add_to(app: FastAPI, admin: AdminServices) -> None:
    """The API, and the built app if there is one (settings.admin_dist_dir: the production image has it; locally,
    Vite's dev server serves the app and forwards /admin/v1 here)."""
    app.state.admin = admin
    app.include_router(create_router())

    @app.middleware("http")
    async def admin_headers(request: Request, call_next: Callable[[Request], Any]) -> Response:
        response: Response = await call_next(request)
        if request.url.path.startswith(PREFIX):
            response.headers["Cache-Control"] = "no-store"
        elif request.url.path == "/admin" or request.url.path.startswith("/admin/"):
            response.headers["Content-Security-Policy"] = CSP
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "same-origin"
        return response

    dist = Path(admin.settings.admin_dist_dir) if admin.settings.admin_dist_dir else None
    if dist is None or not (dist / "index.html").is_file():
        return
    root = dist.resolve()

    @app.get("/admin", include_in_schema=False)
    @app.get("/admin/{path:path}", include_in_schema=False)
    def admin_app(path: str = "") -> Response:
        if path.startswith("v1/") or path == "v1":
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        wanted = (root / path).resolve()
        if path and wanted.is_file() and wanted.is_relative_to(root):
            return FileResponse(wanted)
        # Any other path is a page of the app: the app's router shows it.
        return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})
