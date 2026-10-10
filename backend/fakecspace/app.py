"""A small simulated CollectionSpace Media service, for development and tests.

It implements only what Serena calls (design: Image fetch): GET media/<csid> (the light check, with its workflow
state) and the Media record's current file, media/<csid>/blob/content and media/<csid>/blob/derivatives/<name>/content.
State is in memory. It is not CollectionSpace: behaviour against the real server is confirmed on a test tenant
(docs/testing-checklist.md).

Run: uvicorn fakecspace.app:app --port 8180
User: serena, password serena (synthetic; Serena's read-only service account in development).
Development hooks:
  POST /_fake/reset                 empty
  POST /_fake/media                 {"csid", "kind": image|pdf|3D, "state"?}: a Media record with sample files
  POST /_fake/delete/<csid>         soft-delete it (the Media service still returns it, as CollectionSpace does)
  POST /_fake/replace/<csid>        replace its image (CollectionSpace makes a new Blob; the Media service then
                                    returns the new file)
  POST /_fake/remove-file/<csid>    leave the record with no file
  POST /_fake/fail                  {"match", "status", "times"}: answer requests whose path contains match with status
  GET  /_fake/calls                 the paths called, in order
"""
from __future__ import annotations

import base64
import secrets
import threading
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from . import samples

USERS = {"serena": "serena"}
DERIVATIVES = ("Thumbnail", "Small", "Medium", "FullHD", "OriginalJpeg")


@dataclass
class Media:
    csid: str
    state: str = "project"  # CollectionSpace's workflow state; "deleted" when soft-deleted
    files: dict[str, tuple[bytes, str]] = field(default_factory=dict)  # "content" or a derivative -> (bytes, type)


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

    def add(self, csid: str, kind: str = "image", state: str = "project", shade: int = 128) -> Media:
        if kind == "image":
            image = samples.png(shade=shade)
            files = {"content": (image, "image/png"), **{name: (image, "image/png") for name in DERIVATIVES}}
        elif kind == "pdf":
            files = {"content": (samples.pdf(), "application/pdf")}
        elif kind == "3D":
            files = {"content": (samples.x3d(), "model/x3d+xml")}
        else:
            raise ValueError(f"unknown kind {kind}")
        media = Media(csid, state, files)
        with self.lock:
            self.media[csid] = media
        return media

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


def _authorized(request: Request) -> bool:
    scheme, _, encoded = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "basic":
        return False
    try:
        user, _, password = base64.b64decode(encoded).decode().partition(":")
    except ValueError:
        return False
    return secrets.compare_digest(USERS.get(user, "\0"), password)


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
            f'</ns2:media_common><ns2:collectionspace_core xmlns:ns2="http://collectionspace.org/collectionspace_core/">'
            f"<workflowState>{media.state}</workflowState></ns2:collectionspace_core></document>").encode()


@app.get("/cspace-services/media/{csid}")
def get_media(request: Request, csid: str) -> Response:
    refused = _gate(request)
    if refused:
        return refused
    media = store.media.get(csid)
    if media is None:
        return Response(status_code=404)
    return Response(_media_xml(media), media_type="application/xml")


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


# --- development hooks

@app.post("/_fake/reset")
def reset() -> dict[str, str]:
    store.reset()
    return {"ok": "reset"}


@app.post("/_fake/media")
async def add_media(request: Request) -> JSONResponse:
    body: dict[str, Any] = await request.json()
    media = store.add(body["csid"], body.get("kind", "image"), body.get("state", "project"))
    return JSONResponse({"csid": media.csid, "files": sorted(media.files)})


@app.post("/_fake/delete/{csid}")
def soft_delete(csid: str) -> dict[str, str]:
    store.media[csid].state = "deleted"
    return {"csid": csid, "state": "deleted"}


@app.post("/_fake/replace/{csid}")
def replace(csid: str) -> dict[str, str]:
    image = samples.png(shade=32)  # a different image
    store.media[csid].files = {"content": (image, "image/png"), **{n: (image, "image/png") for n in DERIVATIVES}}
    return {"csid": csid, "replaced": "yes"}


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
