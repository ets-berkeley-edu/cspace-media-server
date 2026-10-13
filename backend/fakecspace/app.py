"""A small simulated CollectionSpace Media service, for development and tests.

It implements only what Serena calls (design: Image fetch, Recalls): GET media/<csid> (the light check, with its
workflow state and its blobCsid), the Media record's current file, media/<csid>/blob/content and
media/<csid>/blob/derivatives/<name>/content, and, for the recall form, GET blobs/<csid> and the search for the Media
record with a given blobCsid, GET media?as=media_common:blobCsid="<csid>".
State is in memory. It is not CollectionSpace: behaviour against the real server is confirmed on a test tenant
(docs/testing-checklist.md).

Run: uvicorn fakecspace.app:app --port 8180
User: serena, password serena (synthetic; Serena's read-only service account in development).
Development hooks:
  POST /_fake/reset                 empty
  POST /_fake/media                 {"csid", "kind": image|pdf|3D, "state"?, "blob"?}: a Media record with sample
                                    files, and its Blob's CSID
  POST /_fake/delete/<csid>         soft-delete it (the Media service still returns it, as CollectionSpace does)
  POST /_fake/replace/<csid>        replace its image (CollectionSpace makes a new Blob, so a record with a Blob
                                    gets a new Blob CSID; the Media service then returns the new file)
  POST /_fake/approve/<csid>        {"approved": false}: change its "Approved for web" (PAHMA's media_pahma
                                    approvedforweb), as staff do to take it off the web
  POST /_fake/remove-file/<csid>    leave the record with no file
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

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response

from . import samples

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
    files: dict[str, tuple[bytes, str]] = field(default_factory=dict)  # "content" or a derivative -> (bytes, type)
    blob: str | None = None  # its Blob's CSID (blobCsid)
    publish_to: str = "All"  # media_common's publishTo, a vocabulary term (core CollectionSpace)
    approved_for_web: bool = True  # media_pahma's approvedforweb: what PAHMA's ETL reads (for Media look up)
    updated_at: str = field(default_factory=lambda: _now())  # collectionspace_core's updatedAt


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

    def add(self, csid: str, kind: str = "image", state: str = "project", shade: int = 128,
            blob: str | None = None) -> Media:
        if kind in ("image", "card"):
            image = samples.png(shade=shade)
            files = {"content": (image, "image/png"), **{name: (image, "image/png") for name in DERIVATIVES}}
        elif kind == "pdf":
            files = {"content": (samples.pdf(), "application/pdf")}
        elif kind == "3D":
            files = {"content": (samples.x3d(), "model/x3d+xml")}
        else:
            raise ValueError(f"unknown kind {kind}")
        media = Media(csid, state, files, blob)
        with self.lock:
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
    label = (request.url.hostname or "").split(".")[0]
    return label if label in TENANT_IDS else "pahma"


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
    media = store.add(body["csid"], body.get("kind", "image"), body.get("state", "project"), blob=body.get("blob"))
    return JSONResponse({"csid": media.csid, "files": sorted(media.files)})


@app.post("/_fake/delete/{csid}")
def soft_delete(csid: str) -> dict[str, str]:
    store.media[csid].state = "deleted"
    store.media[csid].updated_at = _now()
    return {"csid": csid, "state": "deleted"}


@app.post("/_fake/replace/{csid}")
def replace(csid: str) -> dict[str, str]:
    image = samples.png(shade=32)  # a different image
    media = store.media[csid]
    media.files = {"content": (image, "image/png"), **{n: (image, "image/png") for n in DERIVATIVES}}
    if media.blob:
        media.blob = str(uuid.uuid4())  # CollectionSpace makes a new Blob for the new file
    media.updated_at = _now()
    return {"csid": csid, "replaced": "yes", "blob": media.blob or ""}


@app.post("/_fake/approve/{csid}")
async def approve(request: Request, csid: str) -> dict[str, Any]:
    """Set the Media record's "Approved for web", as PAHMA's staff do to take it off the web."""
    body: dict[str, Any] = await request.json()
    media = store.media[csid]
    media.approved_for_web = bool(body["approved"])
    media.updated_at = _now()
    return {"csid": csid, "approved": media.approved_for_web}


@app.post("/_fake/remove-file/{csid}")
def remove_file(csid: str) -> dict[str, str]:
    store.media[csid].files = {}
    return {"csid": csid, "files": "none"}


@app.post("/_fake/fail")
async def fail(request: Request) -> dict[str, str]:
    body: dict[str, Any] = await request.json()
    store.fail(body["match"], int(body["status"]), int(body.get("times", 1)))
    return {"ok": "failure added"}


@app.get("/_fake/calls")
def calls() -> list[str]:
    return list(store.calls)
