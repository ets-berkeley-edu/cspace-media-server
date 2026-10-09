"""The legacy imageserver paths (design: Serving a request).

Every request is answered with a 302: to a signed URL when the file may be served, otherwise to the museum's
unavailable image with Cache-Control: no-store. Never an error page: when Serena can't decide, it doesn't serve."""
from __future__ import annotations

import logging
from importlib import resources

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from . import paths
from .museum import Museum
from .unserved import Reason, Recorder, report

log = logging.getLogger("serena.imageserver")
router = APIRouter()

DEFAULT = "default"  # the unavailable image for a museum Serena doesn't serve
_SVG = resources.files("serena.static").joinpath("unavailable.svg").read_bytes()


def unavailable_url(base_url: str, tenant: str | None) -> str:
    """Where the museum's unavailable image is: <base>/<tenant>/unavailable.svg, served by CloudFront without a
    signature. With no base URL (local development, tests), Serena serves it itself at /unavailable/<tenant>.svg."""
    name = tenant or DEFAULT
    return f"{base_url}/{name}/unavailable.svg" if base_url else f"/unavailable/{name}.svg"


def _unavailable(request: Request, tenant: str | None, reason: Reason) -> RedirectResponse:
    report(_recorder(request), tenant, reason, paths.log_path(request.url.path))
    url = unavailable_url(request.app.state.settings.unavailable_base_url, tenant)
    return RedirectResponse(url, status_code=302, headers={"Cache-Control": "no-store"})


def _recorder(request: Request) -> Recorder:
    recorder: Recorder = request.app.state.unserved
    return recorder


@router.api_route("/{tenant}/imageserver/{rest:path}", methods=["GET", "HEAD"], include_in_schema=False)
def imageserver(request: Request, tenant: str, rest: str) -> Response:
    museums: dict[str, Museum] = request.app.state.museums
    museum = museums.get(tenant)
    if museum is None:
        return _unavailable(request, None, Reason.UNKNOWN_MUSEUM)
    try:
        parsed = paths.parse(museum, rest)
        if isinstance(parsed, paths.Refused):
            return _unavailable(request, tenant, parsed.reason)
        # Servability (design: The steps, step 2) comes with the nightly records: until then nothing is servable.
        return _unavailable(request, tenant, Reason.NOT_SERVABLE)
    except Exception:
        log.exception("internal error", extra={"museum": tenant, "path": paths.log_path(request.url.path)})
        return _unavailable(request, tenant, Reason.INTERNAL_ERROR)


@router.get("/unavailable/{name}.svg", include_in_schema=False)
def unavailable_image(request: Request, name: str) -> Response:
    """The unavailable image, for local development and tests only: in AWS, CloudFront serves it."""
    if name != DEFAULT and name not in request.app.state.museums:
        return Response(status_code=404)
    return Response(_SVG, media_type="image/svg+xml", headers={
        "Cache-Control": "public, max-age=300",
        "X-Content-Type-Options": "nosniff",
        # An SVG opened on its own is a document: let it run nothing and load nothing.
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
    })
