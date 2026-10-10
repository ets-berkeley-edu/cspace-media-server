"""The ETL API, /etl/v1/ (design: The ETL API). The ETL drives each night through it.

Every call needs the museum's bearer token. Errors are application/problem+json with reasons, never internals. Its
OpenAPI description is generated from this module into docs/api/etl-v1.json (python -m serena.etl_api), and a test
fails when that copy no longer matches."""

import asyncio
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from typing import Annotated, Any, cast

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import uploads
from .config import Settings
from .museum import Museum
from .museum_settings import MuseumSettings
from .problems import Problem, ProblemError, openapi_responses, response
from .runs import BUSY, UPLOAD_ALLOWED, OutOfOrder, Run, Runs, State, Upload
from .tokens import Tokens, TokenStoreUnavailable

log = logging.getLogger("serena.etl")
SHA256 = re.compile(r"[0-9a-f]{64}")
PREFIX = "/etl/v1"


@dataclass
class Services:
    settings: Settings
    museums: dict[str, Museum]
    museum_settings: MuseumSettings
    runs: Runs
    tokens: Tokens
    s3: Any


class Links(BaseModel):
    self: str
    blob_media: str
    preflight: str
    solr_load: str
    apply: str


class UploadInfo(BaseModel):
    sha256: str = Field(description="SHA-256 of the uncompressed file, as sent in X-Content-SHA256")
    rows: int = Field(description="Data rows, not counting the header")
    bytes: int = Field(description="Size of the uncompressed file")
    uploaded_at: str


class RunOut(BaseModel):
    run_id: str = Field(examples=["pahma-2026-10-10-1"])
    museum: str = Field(examples=["pahma"])
    night: str = Field(description="The Pacific date when the run started", examples=["2026-10-10"])
    state: State
    file_name: str = Field(description="The name to give the Blob-to-Media file",
                           examples=["blob-media.pahma.2026-10-10.tsv"])
    poll_interval_seconds: int = Field(description="How long to wait between polls; use this value, not a fixed one",
                                       examples=[15])
    step_timeout_seconds: int = Field(description="How long a step may take before the ETL carries on without Serena",
                                      examples=[1800])
    upload: UploadInfo | None = None
    reasons: list[str] = Field(default_factory=list, description="Why the run is in its state, when that needs saying")
    links: Links


class Ping(BaseModel):
    museum: str = Field(description="The museum the token belongs to", examples=["pahma"])


def _out(services: Services, run: Run) -> RunOut:
    current = services.museum_settings.get(services.museums[run.tenant])
    base = f"{PREFIX}/museums/{run.tenant}/runs/{run.run_id}"
    upload = run.upload
    return RunOut(
        run_id=run.run_id, museum=run.tenant, night=run.night, state=run.state, file_name=run.file_name,
        poll_interval_seconds=current.etl_poll_interval_seconds,
        step_timeout_seconds=current.etl_step_timeout_seconds,
        upload=UploadInfo(sha256=upload.sha256, rows=upload.rows, bytes=upload.bytes, uploaded_at=upload.uploaded_at)
        if upload else None,
        reasons=run.reasons,
        links=Links(self=base, blob_media=f"{base}/blob-media", preflight=f"{base}/preflight",
                    solr_load=f"{base}/solr-load", apply=f"{base}/apply"))


def _json(model: BaseModel, status: int = 200) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json"), status_code=status, headers={"Cache-Control": "no-store"})


def create_etl_app(services: Services) -> FastAPI:
    app = FastAPI(title="Serena ETL API", version="1",
                  summary="How the nightly Solr ETL hands each night's Blob-to-Media file to Serena",
                  description="See docs/design.md, The ETL API and The nightly sequence. Every call needs the museum's "
                              "bearer token (Authorization: Bearer <token>). Errors are application/problem+json.",
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(ProblemError)
    async def _problem(request: Request, error: ProblemError) -> JSONResponse:
        return response(error.problem, error.headers)

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, error: RequestValidationError) -> JSONResponse:
        fields = sorted({".".join(str(p) for p in e["loc"][1:]) or str(e["loc"][0]) for e in error.errors()})
        return response(Problem(type="about:blank", title="Bad request", status=400,
                                detail=f"Missing or malformed: {', '.join(fields)}"))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, error: StarletteHTTPException) -> JSONResponse:
        return response(Problem(type="about:blank", title="Not found" if error.status_code == 404 else "Error",
                                status=error.status_code))

    @app.exception_handler(Exception)
    async def _internal(request: Request, error: Exception) -> JSONResponse:
        log.exception("ETL API internal error")
        return response(Problem(type="about:blank", title="Internal error", status=500,
                                detail="Serena couldn't complete the call; try again"))

    def museum_of_token(authorization: Annotated[str | None, Header(include_in_schema=False)] = None) -> str:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise ProblemError(401, "the-etl-api", "No token", "Send Authorization: Bearer <the museum's token>",
                               {"WWW-Authenticate": "Bearer"})
        try:
            museum = services.tokens.museum_of(token.strip())
        except TokenStoreUnavailable:
            raise ProblemError(503, "the-etl-api", "Can't check tokens right now", "Try again") from None
        if museum is None:
            raise ProblemError(401, "the-etl-api", "Unknown token", "Check the token for this museum",
                               {"WWW-Authenticate": "Bearer"})
        return museum

    TokenMuseum = Annotated[str, Depends(museum_of_token)]

    def for_museum(tenant: str, token_museum: TokenMuseum) -> str:
        if tenant not in services.museums:
            raise ProblemError(404, "the-etl-api", "No such museum", f"Serena doesn't serve {tenant}")
        if token_museum != tenant:
            # decided October 9, 2026 (D31)
            raise ProblemError(403, "the-etl-api", "Token for another museum", f"This token isn't for {tenant}")
        return tenant

    Tenant = Annotated[str, Depends(for_museum)]

    def run_of(tenant: str, run_id: str) -> Run:
        run = services.runs.get(tenant, run_id)
        if run is None:
            raise ProblemError(404, "the-etl-api", "No such run", f"{tenant} has no run {run_id}")
        return run

    def out_of_order(error: OutOfOrder) -> ProblemError:
        return ProblemError(409, "the-etl-api", "Out of order", error.detail)

    @app.get("/ping", response_model=Ping, responses=openapi_responses(401, 503),
             summary="Check connectivity and the token")
    def ping(museum: TokenMuseum) -> JSONResponse:
        """Answers with the museum the token belongs to (decided October 9, 2026, D32)."""
        return _json(Ping(museum=museum))

    @app.post("/museums/{tenant}/runs", response_model=RunOut, status_code=201,
              responses={200: {"description": "The museum's open run for tonight, returned instead of a new one",
                               "model": RunOut}, **openapi_responses(401, 403, 404, 409, 503)},
              summary="Start tonight's run")
    def start_run(tenant: Tenant) -> JSONResponse:
        """Serena assigns the run ID and the night (the Pacific date now). If the museum's run for tonight is still
        open, returns it (200). An earlier night's open run is closed as abandoned, unless Serena is preflighting or
        applying it: then 409, and the ETL tries again (decided October 9, 2026, D30)."""
        try:
            run, created = services.runs.start(tenant)
        except OutOfOrder as error:  # Busy included
            raise out_of_order(error) from None
        log.info("run started" if created else "open run returned",
                 extra={"museum": tenant, "run_id": run.run_id, "state": run.state.value})
        return _json(_out(services, run), 201 if created else 200)

    @app.get("/museums/{tenant}/runs/{run_id}", response_model=RunOut,
             responses=openapi_responses(401, 403, 404, 503), summary="The run's status")
    def get_run(tenant: Tenant, run_id: str) -> JSONResponse:
        return _json(_out(services, run_of(tenant, run_id)))

    @app.put("/museums/{tenant}/runs/{run_id}/blob-media", response_model=RunOut,
             responses=openapi_responses(400, 401, 403, 404, 409, 413, 415, 422, 503),
             summary="Upload the night's Blob-to-Media file",
             openapi_extra={"requestBody": {"required": True, "content": {
                 "text/tab-separated-values": {"schema": {"type": "string", "format": "binary"},
                                               "example": "blob_csid\tmedia_csid\tkind\taccess\n"}}}})
    async def put_blob_media(
        request: Request,
        tenant: Tenant,
        run_id: str,
        content_type: Annotated[str, Header(description="text/tab-separated-values")],
        x_row_count: Annotated[int, Header(ge=0, description="Data rows, not counting the header")],
        x_content_sha256: Annotated[str, Header(description="Hex SHA-256 of the uncompressed file")],
        content_encoding: Annotated[str | None, Header(description="gzip, or absent")] = None,
    ) -> JSONResponse:
        """Streams the file to Serena. Uploading the same file again changes nothing; a corrected file replaces the
        previous one until the load's outcome is reported, and must then be preflighted again. The file's format is
        checked by the preflight."""
        if content_type.split(";")[0].strip().lower() != "text/tab-separated-values":
            raise ProblemError(415, "the-etl-api", "Wrong content type", "Send text/tab-separated-values")
        sha = x_content_sha256.strip().lower()
        if not SHA256.fullmatch(sha):
            raise ProblemError(400, "the-etl-api", "Bad request", "X-Content-SHA256 must be 64 hex digits")
        encoding = (content_encoding or "identity").strip().lower()
        if encoding not in ("gzip", "identity"):
            raise ProblemError(415, "the-etl-api", "Unsupported Content-Encoding", "Send gzip or no encoding")
        bucket = services.settings.buckets.get(tenant)
        if bucket is None:
            raise ProblemError(503, "the-etl-api", "Storage not configured", "Serena has no bucket for this museum")
        run = await asyncio.to_thread(run_of, tenant, run_id)
        if run.state not in UPLOAD_ALLOWED:
            busy = " (Serena is preflighting it)" if run.state in BUSY else ""
            raise ProblemError(409, "the-etl-api", "Out of order",
                               f"run {run.run_id} is {run.state.value}{busy}; a file can be uploaded only before the "
                               "load's outcome is reported")
        try:
            received = await uploads.receive(request.stream(), gzipped=encoding == "gzip",
                                             max_bytes=services.settings.upload_max_mb * 1024 * 1024,
                                             directory=services.settings.upload_dir)
        except uploads.TooLarge:
            raise ProblemError(413, "the-etl-api", "File too large",
                               f"At most {services.settings.upload_max_mb} MB uncompressed") from None
        except uploads.BadGzip:
            raise ProblemError(400, "the-etl-api", "Bad gzip", "The body isn't valid gzip") from None
        try:
            if received.sha256 != sha:
                raise ProblemError(422, "the-etl-api", "SHA-256 doesn't match",
                                   "X-Content-SHA256 must be the SHA-256 of the uncompressed file")
            if received.rows != x_row_count:
                raise ProblemError(422, "the-etl-api", "Row count doesn't match",
                                   f"X-Row-Count is {x_row_count}; the file has {received.rows} data rows")
            if run.upload is not None and run.upload.sha256 == sha:
                log.info("same file uploaded again", extra={"museum": tenant, "run_id": run.run_id})
                return _json(_out(services, run))
            key = f"blob-media/{run.run_id}/{run.file_name}.gz"
            await asyncio.to_thread(uploads.store, services.s3, bucket, key, received)
            upload = Upload(sha, received.rows, received.size, key, services.runs.now())
            try:
                run = await asyncio.to_thread(services.runs.transition, run, State.RECEIVED, upload=upload)
            except OutOfOrder as error:
                raise out_of_order(error) from None
        finally:
            os.unlink(received.path)
        log.info("file received", extra={"museum": tenant, "run_id": run.run_id, "rows": received.rows})
        return _json(_out(services, run))

    return app


def openapi_document() -> str:
    """The ETL API's OpenAPI description, as saved in docs/api/etl-v1.json. Building it calls no service."""
    app = create_etl_app(cast(Services, None))
    document = app.openapi()
    # Serena answers a malformed request with 400 problem+json, never FastAPI's default 422 "Validation Error".
    for operation in (op for ops in document["paths"].values() for op in ops.values()):
        if operation["responses"].get("422", {}).get("description") == "Validation Error":
            del operation["responses"]["422"]
    schemas = document["components"]["schemas"]
    for name in ("HTTPValidationError", "ValidationError"):
        schemas.pop(name, None)
    schemas["Problem"] = Problem.model_json_schema()
    document["servers"] = [{"url": PREFIX, "description": "Under Serena's base URL, which Serena's team provides"}]
    document["components"].setdefault("securitySchemes", {})["bearer"] = {"type": "http", "scheme": "bearer"}
    document["security"] = [{"bearer": []}]
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    if "--openapi" in sys.argv:
        sys.stdout.write(openapi_document())
