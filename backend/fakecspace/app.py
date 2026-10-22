"""A small simulated CollectionSpace Media service, for development and tests.

It implements only what Serena calls (design: Image fetch, Recalls): GET media/<csid> (the light check, with its
workflow state and its blobCsid), the Media record's current file, media/<csid>/blob/content and
media/<csid>/blob/derivatives/<name>/content, and, for the recall form, GET blobs/<csid> and the search for the Media
record with a given blobCsid, GET media?as=media_common:blobCsid="<csid>".
State is in memory. It is not CollectionSpace: behaviour against the real server is confirmed on a test tenant
(docs/testing-checklist.md).

Run: uvicorn fakecspace.app:app --port 8180
Each museum is told apart by the host name it's called by (pahma.fakecspace) or a path prefix (/pahma/...).
User: serena, password serena (synthetic; Serena's read-only service account in development).
Development hooks:
  POST /_fake/reset                 empty
  POST /_fake/media                 {"csid", "kind": image|pdf|3D, "state"?, "blob"?, "identification"?, "band"?}:
                                    a Media record with sample files, its Blob's CSID and identification number
                                    (2026.1.<n> unless given). With a band (an image's only: 100KB, 1MB, 5MB, 20MB or
                                    100MB), its files are JPEGs of about a real file's size instead of 8x8 PNGs, for
                                    ./serena aws replay (D283): the original and OriginalJpeg about the band's size,
                                    the other derivatives about a real one's (see bands.py). A record it already
                                    has is kept as it is (changes made with the hooks below, its number and "last
                                    changed" included), so each ./serena etl, which adds its records first, doesn't
                                    make them look changed.
  POST /_fake/delete/<csid>         soft-delete it (the Media service still returns it, as CollectionSpace does)
  POST /_fake/undelete/<csid>       undo a soft delete, as CollectionSpace's undelete workflow transition does (a record
                                    that isn't deleted is left as it is)
  POST /_fake/replace/<csid>        replace its image (CollectionSpace makes a new Blob, so a record with a Blob
                                    gets a new Blob CSID; the Media service then returns the new file)
  POST /_fake/restore/<csid>        undo replacing: the file and Blob CSID it had before its first replace, as staff
                                    would point the Media record back at its old Blob (a record never replaced is left
                                    as it is)
  POST /_fake/approve/<csid>        {"approved": false}: change its "Approved for web" (PAHMA's media_pahma
                                    approvedforweb), as staff do to take it off the web
  POST /_fake/remove-file/<csid>    leave the record with no file
  POST /_fake/unreachable           {"on": true | false}: an outage; every CollectionSpace call answers 503, the
                                    records are kept (an unknown CSID in these hooks gets a 404 that says why)
  POST /_fake/fail                  {"match", "status", "times"}: answer requests whose path contains match with status
  GET  /_fake/calls                 the paths called, in order
"""
from __future__ import annotations

import base64
import re
import secrets
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from . import bands, samples

USERS = {"serena": "serena"}
# Admins' own accounts, for the admin app's sign-in (design: Admin web app; decided October 10, 2026). Synthetic: each
# password is its username. The museum is the first label of the host name the simulator is called by
# (pahma.fakecspace, or pahma.cspace.test in the tests), as each museum has its own CollectionSpace.
ADMINS = {"admin": "admin", "pahma-admin": "pahma-admin", "viewer": "viewer"}
ADMIN_MUSEUMS = {"admin": {"bampfa", "botgarden", "cinefiles", "pahma", "ucjeps"}, "pahma-admin": {"pahma"},
                 "viewer": set()}
TENANT_IDS = {"bampfa": "11", "botgarden": "12", "cinefiles": "13", "pahma": "14", "ucjeps": "15"}  # synthetic
DERIVATIVES = ("Thumbnail", "Small", "Medium", "FullHD", "OriginalJpeg")


@dataclass
class Media:
    csid: str
    state: str = "project"  # CollectionSpace's workflow state; "deleted" when soft-deleted
    # "content" or a derivative -> (bytes, type); None for bytes: the record's band's file of that name (band below)
    files: dict[str, tuple[bytes | None, str]] = field(default_factory=dict)
    blob: str | None = None  # its Blob's CSID (blobCsid)
    publish_to: str = "All"  # media_common's publishTo, a vocabulary term (core CollectionSpace)
    approved_for_web: bool = True  # media_pahma's approvedforweb: what PAHMA's ETL reads (for Media look up)
    identification_number: str = ""  # media_common's identificationNumber, as staff know the record (D153)
    updated_at: str = field(default_factory=lambda: _now())  # collectionspace_core's updatedAt
    # Its file and Blob CSID before its first replace, for /_fake/restore; None if never replaced.
    before_replace: tuple[dict[str, tuple[bytes | None, str]], str | None] | None = None
    band: str | None = None  # the size band of its files (D283), or None for the 8x8 samples


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


@dataclass
class Failure:
    match: str
    status: int
    times: int


class Store:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self.lock:
            self.media: dict[str, Media] = {}
            self.failures: list[Failure] = []
            self.calls: list[str] = []
            self.unreachable = False  # an outage: every CollectionSpace call answers 503, the records kept

    def add(self, csid: str, kind: str = "image", state: str = "project", shade: int = 128,
            blob: str | None = None, identification_number: str | None = None, band: str | None = None) -> Media:
        files: dict[str, tuple[bytes | None, str]]
        if band is not None and kind not in ("image", "card"):
            raise ValueError(f"a size band is for images only, not {kind}")
        if band is not None:
            bands.prepare(band)  # made in the background, so the first request for the file waits less
            files = {name: (None, "image/jpeg") for name in ("content", *DERIVATIVES)}
        elif kind in ("image", "card"):
            image = samples.png(shade=shade)
            files = {"content": (image, "image/png"), **{name: (image, "image/png") for name in DERIVATIVES}}
        elif kind == "pdf":
            files = {"content": (samples.pdf(), "application/pdf")}
        elif kind == "3D":
            files = {"content": (samples.x3d(), "model/x3d+xml")}
        else:
            raise ValueError(f"unknown kind {kind}")
        with self.lock:
            # A synthetic identification number unless one is given: 2026.1.1, 2026.1.2, ... (D153)
            number = identification_number if identification_number is not None else f"2026.1.{len(self.media) + 1}"
            media = Media(csid, state, files, blob, identification_number=number, band=band)
            self.media[csid] = media
        return media

    def media_of_blob(self, blob: str) -> Media | None:
        with self.lock:
            return next((m for m in self.media.values() if m.blob == blob), None)

    def fail(self, match: str, status: int, times: int = 1) -> None:
        with self.lock:
            self.failures.append(Failure(match, status, times))

    def injected(self, path: str) -> int | None:
        with self.lock:
            self.calls.append(path)
            if self.unreachable:
                return 503
            for failure in self.failures:
                if failure.match in path and failure.times > 0:
                    failure.times -= 1
                    return failure.status
        return None


store = Store()
app = FastAPI(title="Fake CollectionSpace (Media service only)", docs_url=None, redoc_url=None, openapi_url=None)


def _login(request: Request) -> tuple[str, str] | None:
    scheme, _, encoded = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "basic":
        return None
    try:
        user, _, password = base64.b64decode(encoded).decode().partition(":")
    except ValueError:
        return None
    return user, password


def _authorized(request: Request) -> bool:
    login = _login(request)
    return login is not None and secrets.compare_digest(USERS.get(login[0], "\0"), login[1])


def museum_of(request: Request) -> str:
    """The museum a request is for: the path prefix it came with (an AWS environment, see MuseumPrefix), or else the
    first label of the host name (the local stack and the tests); PAHMA when neither names one."""
    prefixed = request.scope.get("fake_museum")
    if prefixed:
        return str(prefixed)
    label = (request.url.hostname or "").split(".")[0]
    return label if label in TENANT_IDS else "pahma"


class MuseumPrefix:
    """Lets each museum's CollectionSpace be the simulator under a path, http://<simulator>/<museum>, as well as under a
    host name of its own. An AWS environment with the simulator (deploy/README.md) has one name for it in its private
    DNS, so Serena's SERENA_TENANTS gives each museum's server as <that name>/<museum>: the prefix is removed here, and
    museum_of reads it. Paths without a museum's prefix (the development hooks, the local stack) pass unchanged."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            first, _, rest = scope["path"].lstrip("/").partition("/")
            if first in TENANT_IDS and rest:
                scope = {**scope, "fake_museum": first, "path": "/" + rest,
                         "raw_path": ("/" + rest).encode()}
        await self.app(scope, receive, send)


app.add_middleware(MuseumPrefix)


def _gate(request: Request) -> Response | None:
    if not _authorized(request):
        return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="CollectionSpace"'})
    status = store.injected(request.url.path)
    if status is not None:
        return Response(status_code=status)
    return None


def _media_xml(media: Media) -> bytes:
    return (f'<?xml version="1.0" encoding="UTF-8"?><document name="media">'
            f'<ns2:media_common xmlns:ns2="http://collectionspace.org/services/media"><csid>{media.csid}</csid>'
            f"<identificationNumber>{media.identification_number}</identificationNumber>"
            f'{f"<blobCsid>{media.blob}</blobCsid>" if media.blob else ""}<publishToList><publishTo>'
            f"urn:cspace:pahma.cspace.berkeley.edu:vocabularies:name(publishto):item:name({media.publish_to.lower()})"
            f"'{media.publish_to}'</publishTo></publishToList></ns2:media_common>"
            f'<ns2:media_pahma xmlns:ns2="http://collectionspace.org/services/media/local/pahma">'
            f"<approvedforweb>{str(media.approved_for_web).lower()}</approvedforweb></ns2:media_pahma>"
            f'<ns2:collectionspace_core xmlns:ns2="http://collectionspace.org/collectionspace_core/">'
            f"<workflowState>{media.state}</workflowState><updatedAt>{media.updated_at}</updatedAt>"
            f"</ns2:collectionspace_core></document>").encode()


@app.get("/cspace-services/media/{csid}")
def get_media(request: Request, csid: str) -> Response:
    refused = _gate(request)
    if refused:
        return refused
    media = store.media.get(csid)
    if media is None:
        return Response(status_code=404)
    return Response(_media_xml(media), media_type="application/xml")


_BLOB_SEARCH = re.compile(r'^media_common:blobCsid\s*=\s*"([A-Za-z0-9-]{1,64})"$')


@app.get("/cspace-services/media")
def search_media(request: Request, as_: str = Query("", alias="as")) -> Response:
    """Only the search Serena makes: the Media record whose blobCsid is a given Blob CSID."""
    refused = _gate(request)
    if refused:
        return refused
    found = _BLOB_SEARCH.match(as_)
    if not found:
        return Response(status_code=400)
    media = store.media_of_blob(found.group(1))
    items = f"<list-item><csid>{media.csid}</csid></list-item>" if media else ""
    body = (f'<?xml version="1.0" encoding="UTF-8"?><ns2:abstract-common-list xmlns:ns2="http://collectionspace.org/'
            f'services/jaxb"><totalItems>{1 if media else 0}</totalItems>{items}</ns2:abstract-common-list>')
    return Response(body, media_type="application/xml")


@app.get("/cspace-services/blobs/{csid}")
def get_blob(request: Request, csid: str) -> Response:
    refused = _gate(request)
    if refused:
        return refused
    if store.media_of_blob(csid) is None:
        return Response(status_code=404)
    body = (f'<?xml version="1.0" encoding="UTF-8"?><document name="blobs"><ns2:blobs_common '
            f'xmlns:ns2="http://collectionspace.org/services/blob"><csid>{csid}</csid></ns2:blobs_common></document>')
    return Response(body, media_type="application/xml")


def _file(request: Request, csid: str, name: str) -> Response:
    refused = _gate(request)
    if refused:
        return refused
    media = store.media.get(csid)
    if media is None or name not in media.files:
        return Response(status_code=404)
    content, content_type = media.files[name]
    if content is None:
        # The band's shared file, made different for each record by a comment naming it, so that no two records'
        # files are the same bytes (Serena stores files by content hash) without copying the file for each request.
        shared = bands.band_file(bands.band_of(name, media.band or ""))
        head = bands.marked_head(media.csid)
        return StreamingResponse(bands.stream(head, shared), media_type=content_type,
                                 headers={"Content-Length": str(len(head) + len(shared) - 2)})
    return Response(content, media_type=content_type)


@app.get("/cspace-services/media/{csid}/blob/content")
def get_original(request: Request, csid: str) -> Response:
    return _file(request, csid, "content")


@app.get("/cspace-services/media/{csid}/blob/derivatives/{name}/content")
def get_derivative(request: Request, csid: str, name: str) -> Response:
    return _file(request, csid, name)


@app.get("/cspace-services/accounts/0/accountroles")
def account_roles(request: Request) -> Response:
    """The signed-in account's roles in this museum's tenant, as CollectionSpace answers it."""
    login = _login(request)
    known = {**USERS, **ADMINS}
    if login is None or not secrets.compare_digest(known.get(login[0], "\0"), login[1]):
        return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="CollectionSpace"'})
    museum = museum_of(request)
    tenant = TENANT_IDS[museum]
    roles = [f"ROLE_{tenant}_TENANT_READER"]
    if museum in ADMIN_MUSEUMS.get(login[0], set()):
        roles.append(f"ROLE_{tenant}_SERENA_ADMIN")
    role_xml = "".join(f"<role><roleName>{name}</roleName></role>" for name in roles)
    body = (f'<?xml version="1.0" encoding="UTF-8"?><ns2:account_role xmlns:ns2="http://collectionspace.org/'
            f'services/authorization"><account><userId>{login[0]}</userId><tenantId>{tenant}</tenantId></account>'
            f"{role_xml}</ns2:account_role>")
    return Response(body, media_type="application/xml")


# --- development hooks

@app.post("/_fake/reset")
def reset() -> dict[str, str]:
    store.reset()
    return {"ok": "reset"}


@app.post("/_fake/media")
async def add_media(request: Request) -> JSONResponse:
    body: dict[str, Any] = await request.json()
    existing = store.media.get(body["csid"])
    if existing is not None:
        return JSONResponse({"csid": existing.csid, "files": sorted(existing.files), "kept": True})
    band = body.get("band")
    if band is not None and band not in bands.ORIGINALS:
        raise HTTPException(400, f"unknown band {band}: one of {', '.join(bands.ORIGINALS)}")
    try:
        media = store.add(body["csid"], body.get("kind", "image"), body.get("state", "project"),
                          blob=body.get("blob"), identification_number=body.get("identification"), band=band)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return JSONResponse({"csid": media.csid, "files": sorted(media.files)})


def _known(csid: str) -> Media:
    """A development hook's Media record, or a 404 that says what to give (a Blob CSID isn't a Media record's)."""
    media = store.media.get(csid)
    if media is None:
        blob_of = store.media_of_blob(csid)
        hint = (f": that's the Blob of Media record {blob_of.csid}; give the Media CSID" if blob_of
                else ": give a Media CSID the simulator has (POST /_fake/media adds one)")
        raise HTTPException(404, f"No Media record {csid}{hint}")
    return media


@app.post("/_fake/delete/{csid}")
def soft_delete(csid: str) -> dict[str, str]:
    media = _known(csid)
    media.state = "deleted"
    media.updated_at = _now()
    return {"csid": csid, "state": "deleted"}


@app.post("/_fake/undelete/{csid}")
def undelete(csid: str) -> dict[str, str]:
    media = _known(csid)
    if media.state == "deleted":
        media.state = "project"
        media.updated_at = _now()  # an undelete is a change, as in CollectionSpace
    return {"csid": csid, "state": media.state}


@app.post("/_fake/replace/{csid}")
def replace(csid: str) -> dict[str, str]:
    media = _known(csid)
    if media.before_replace is None:
        media.before_replace = (media.files, media.blob)
    image = samples.png(shade=32)  # a different image
    media.files = {"content": (image, "image/png"), **{n: (image, "image/png") for n in DERIVATIVES}}
    if media.blob:
        media.blob = str(uuid.uuid4())  # CollectionSpace makes a new Blob for the new file
    media.updated_at = _now()
    return {"csid": csid, "replaced": "yes", "blob": media.blob or ""}


@app.post("/_fake/restore/{csid}")
def restore(csid: str) -> dict[str, str]:
    media = _known(csid)
    if media.before_replace is not None:
        media.files, media.blob = media.before_replace
        media.before_replace = None
        media.updated_at = _now()  # pointing the record back at its old Blob is a change, as in CollectionSpace
    return {"csid": csid, "blob": media.blob or ""}


@app.post("/_fake/approve/{csid}")
async def approve(request: Request, csid: str) -> dict[str, Any]:
    """Set the Media record's "Approved for web", as PAHMA's staff do to take it off the web."""
    media = _known(csid)
    body: dict[str, Any] = await request.json()
    media.approved_for_web = bool(body["approved"])
    media.updated_at = _now()
    return {"csid": csid, "approved": media.approved_for_web}


@app.post("/_fake/remove-file/{csid}")
def remove_file(csid: str) -> dict[str, str]:
    _known(csid).files = {}
    return {"csid": csid, "files": "none"}


@app.post("/_fake/unreachable")
async def unreachable(request: Request) -> dict[str, bool]:
    """{"on": true}: an outage, every CollectionSpace call answers 503 and the records are kept; {"on": false}
    ends it."""
    body: dict[str, Any] = await request.json()
    store.unreachable = bool(body["on"])
    return {"unreachable": store.unreachable}


@app.post("/_fake/fail")
async def fail(request: Request) -> dict[str, str]:
    body: dict[str, Any] = await request.json()
    store.fail(body["match"], int(body["status"]), int(body.get("times", 1)))
    return {"ok": "failure added"}


@app.get("/_fake/calls")
def calls() -> list[str]:
    return list(store.calls)
