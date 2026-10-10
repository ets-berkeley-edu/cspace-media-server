"""The legacy imageserver paths (design: Serving a request).

Every request is answered with a 302: to a signed URL when the file may be served, otherwise to the museum's
unavailable image with Cache-Control: no-store. Never an error page: when Serena can't decide, it doesn't serve."""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from importlib import resources

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse

from . import cache_index, paths, servability, signed_links, signing
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


def _redirect(request: Request, tenant: str, entry: cache_index.Entry, signed_kid: str | None = None) -> Response:
    """302 to a signed URL for the stored object (design: Signed URLs, Responses). The URL is never logged. A restricted
    file served on a portal's signed link gets Cache-Control: no-store, so the browser asks again next time."""
    signer: signing.Signer | None = request.app.state.signer
    if signer is None:
        log.error("no signer configured: set SERENA_CDN_BASE_URL and SERENA_CLOUDFRONT_KEY_SECRET_ID")
        return _unavailable(request, tenant, Reason.INTERNAL_ERROR)
    now = datetime.now(UTC)
    expires = signing.expiry(now)
    url = signer.url(tenant, entry.key, expires)
    if signed_kid is not None:
        log.info("served", extra={"museum": tenant, "cache": "hit", "signed": True, "kid": signed_kid})
        return RedirectResponse(url, status_code=302, headers={"Cache-Control": "no-store"})
    log.info("served", extra={"museum": tenant, "cache": "hit"})
    max_age = max(expires - int(now.timestamp()), 0)
    return RedirectResponse(url, status_code=302, headers={"Cache-Control": f"private, max-age={max_age}"})


def _vouch(request: Request, tenant: str, blob_csid: str) -> Callable[[], signed_links.Verdict]:
    """Checks the request's signed link, when servability asks (design: Signed links). exp, uid and sig are never
    logged."""
    def check() -> signed_links.Verdict:
        query = {name: request.query_params.getlist(name) for name in signed_links.PARAMETERS}
        keys: signed_links.SigningKeys = request.app.state.signing_keys
        return signed_links.verify(keys, tenant, blob_csid, query, int(datetime.now(UTC).timestamp()))
    return check


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
        decision = servability.decide(museum, parsed, request.app.state.store,
                                      _vouch(request, tenant, parsed.blob_csid))
        if decision.reason is not None:
            return _unavailable(request, tenant, decision.reason)
        if parsed.derivative in museum.watermark_sizes:
            # Never an unwatermarked copy of a size the museum watermarks (design: Watermarks).
            return _unavailable(request, tenant, Reason.WATERMARK_NOT_BUILT)
        entry = cache_index.lookup(request.app.state.store, tenant, parsed.blob_csid, parsed.derivative)
        if entry is None and decision.record is not None:
            # A miss: the light check, then fetch, check and store (design: The steps, steps 4 and 5).
            fetched = request.app.state.fetcher.get(museum, decision.record, parsed.derivative)
            if isinstance(fetched, Reason):
                return _unavailable(request, tenant, fetched)
            entry = fetched
        if entry is None:
            return _unavailable(request, tenant, Reason.INTERNAL_ERROR)
        return _redirect(request, tenant, entry, decision.signed_kid)
    except signed_links.SigningKeysUnavailable:
        # Already logged, with the museum; fail closed (design: Signed links).
        return _unavailable(request, tenant, Reason.INTERNAL_ERROR)
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


@router.get(signing.LocalSigner.PREFIX + "/{tenant}/objects/{sha256}", include_in_schema=False)
def local_cdn(request: Request, tenant: str, sha256: str, Expires: int = 0, Signature: str = "") -> Response:
    """Local development only (SERENA_LOCAL_CDN, which needs DynamoDB Local): stands in for CloudFront, checking
    the local signature and serving the object from the museum's bucket. In AWS this route answers 404."""
    signer = request.app.state.signer
    if not isinstance(signer, signing.LocalSigner) or tenant not in request.app.state.museums:
        return Response(status_code=404)
    key = f"objects/{sha256}"
    if not signer.valid(tenant, key, Expires, Signature, datetime.now(UTC)):
        return Response(status_code=403)
    obj = request.app.state.s3.get_object(Bucket=request.app.state.settings.buckets[tenant], Key=key)
    return StreamingResponse(obj["Body"].iter_chunks(), media_type=obj.get("ContentType"),
                             headers={"Cache-Control": "private, max-age=900"})
