"""The ETL API, /etl/v1/ (design: The ETL API). The ETL job drives each refresh through it.

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

from boto3.exceptions import Boto3Error
from botocore.exceptions import BotoCoreError, ClientError
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
from .refreshes import BUSY, UPLOAD_ALLOWED, OutOfOrder, Refresh, Refreshes, State, Upload
from .tokens import Tokens, TokenStoreUnavailable

log = logging.getLogger("serena.etl")
SHA256 = re.compile(r"[0-9a-f]{64}")
PREFIX = "/etl/v1"
AWS_ERRORS: tuple[type[Exception], ...] = (BotoCoreError, ClientError, Boto3Error)


@dataclass
class Services:
    settings: Settings
    museums: dict[str, Museum]
    museum_settings: MuseumSettings
    refreshes: Refreshes
    tokens: Tokens
    s3: Any


class Links(BaseModel):
    self: str
    servable_list: str
    check: str


class UploadInfo(BaseModel):
    sha256: str = Field(description="SHA-256 of the uncompressed servable list, as sent in X-Content-SHA256")
    rows: int = Field(description="Data rows, not counting the header")
    bytes: int = Field(description="Size of the uncompressed servable list")
    uploaded_at: str


class RefreshOut(BaseModel):
    refresh_id: str = Field(examples=["pahma-2026-10-10-1"])
    museum: str = Field(examples=["pahma"])
    refresh_date: str = Field(description="The Pacific date when the refresh started", examples=["2026-10-10"])
    state: State
    file_name: str = Field(description="The name to give the servable list",
                           examples=["servable-list.pahma.2026-10-10.tsv"])
    poll_interval_seconds: int = Field(description="How long to wait between polls; use this value, not a fixed one",
                                       examples=[15])
    step_timeout_seconds: int = Field(description="How long a step may take before the ETL job carries on without "
                                                  "Serena",
                                      examples=[1800])
    upload: UploadInfo | None = None
    check: dict[str, Any] | None = Field(
        None, description="The servable list check's result: result (passed or failed), rows, added, removed, changed, "
                          "previous_rows, threshold_percent, delta_percent, error_count, errors (the first 20, each "
                          "with line, field and problem), warnings")
    update: dict[str, Any] | None = Field(None,
                                          description="The servability update's counts: deleted, written, unchanged")
    reasons: list[str] = Field(default_factory=list,
                               description="Why the refresh is in its state, when that needs saying")
    links: Links


class Ping(BaseModel):
    museum: str = Field(description="The museum the token belongs to", examples=["pahma"])


def _out(services: Services, refresh: Refresh) -> RefreshOut:
    current = services.museum_settings.get(services.museums[refresh.tenant])
    base = f"{PREFIX}/museums/{refresh.tenant}/refreshes/{refresh.refresh_id}"
    upload = refresh.upload
    return RefreshOut(
        refresh_id=refresh.refresh_id, museum=refresh.tenant, refresh_date=refresh.refresh_date, state=refresh.state,
        file_name=refresh.file_name,
        poll_interval_seconds=current.etl_poll_interval_seconds,
        step_timeout_seconds=current.etl_step_timeout_seconds,
        upload=UploadInfo(sha256=upload.sha256, rows=upload.rows, bytes=upload.bytes, uploaded_at=upload.uploaded_at)
        if upload else None,
        check=refresh.check, update=refresh.update,
        reasons=refresh.reasons,
        links=Links(self=base, servable_list=f"{base}/servable-list", check=f"{base}/check"))


def _json(model: BaseModel, status: int = 200) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json"), status_code=status, headers={"Cache-Control": "no-store"})


def create_etl_app(services: Services) -> FastAPI:
    app = FastAPI(title="Serena ETL API", version="1",
                  summary="How the daily Solr ETL job hands each servable list to Serena",
                  description="See docs/design.md, The ETL API and The daily sequence. Every call needs the museum's "
                              "bearer token (`Authorization: Bearer <token>`). Errors are application/problem+json.",
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

    async def _aws_unavailable(request: Request, error: Exception) -> JSONResponse:
        # DynamoDB or S3 failed or couldn't be reached: the ETL retries, as for any 5xx (design: The ETL API).
        log.warning("ETL API: AWS unavailable", extra={"error": type(error).__name__})
        return response(Problem(type="about:blank", title="Storage unavailable", status=503,
                                detail="Serena can't reach its records or storage right now; try again"))

    for aws_error in AWS_ERRORS:
        app.add_exception_handler(aws_error, _aws_unavailable)

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

    def refresh_of(tenant: str, refresh_id: str) -> Refresh:
        refresh = services.refreshes.get(tenant, refresh_id)
        if refresh is None:
            raise ProblemError(404, "the-etl-api", "No such refresh", f"{tenant} has no refresh {refresh_id}")
        return refresh

    def out_of_order(error: OutOfOrder) -> ProblemError:
        return ProblemError(409, "the-etl-api", "Out of order", error.detail)

    @app.get("/ping", response_model=Ping, responses=openapi_responses(401, 503),
             summary="Check connectivity and the token")
    def ping(museum: TokenMuseum) -> JSONResponse:
        """Answers with the museum the token belongs to (decided October 9, 2026, D32)."""
        return _json(Ping(museum=museum))

    @app.post("/museums/{tenant}/refreshes", response_model=RefreshOut, status_code=201,
              responses={200: {"description": "The museum's open refresh for today, returned instead of a new one",
                               "model": RefreshOut}, **openapi_responses(401, 403, 404, 409, 503)},
              summary="Start today's refresh")
    def start_refresh(tenant: Tenant) -> JSONResponse:
        """Serena assigns the refresh ID and the refresh date (the Pacific date now). If the museum's refresh for today
        is still open, returns it (200). An earlier refresh date's open refresh is closed as abandoned, unless Serena is
        checking or updating it: then 409, and the ETL job tries again (decided October 9, 2026, D30)."""
        try:
            refresh, created = services.refreshes.start(tenant)
        except OutOfOrder as error:  # Busy included
            raise out_of_order(error) from None
        log.info("refresh started" if created else "open refresh returned",
                 extra={"museum": tenant, "refresh_id": refresh.refresh_id, "state": refresh.state.value})
        return _json(_out(services, refresh), 201 if created else 200)

    @app.get("/museums/{tenant}/refreshes/{refresh_id}", response_model=RefreshOut,
             responses=openapi_responses(401, 403, 404, 503), summary="The refresh's status")
    def get_refresh(tenant: Tenant, refresh_id: str) -> JSONResponse:
        return _json(_out(services, refresh_of(tenant, refresh_id)))

    @app.put("/museums/{tenant}/refreshes/{refresh_id}/servable-list", response_model=RefreshOut,
             responses=openapi_responses(400, 401, 403, 404, 409, 413, 415, 422, 503),
             summary="Upload the servable list",
             openapi_extra={"requestBody": {"required": True, "content": {
                 "text/tab-separated-values": {"schema": {"type": "string", "format": "binary"},
                                               "example": "blob_csid\tmedia_csid\tkind\taccess\n"}}}})
    async def put_servable_list(
        request: Request,
        tenant: Tenant,
        refresh_id: str,
        content_type: Annotated[str, Header(description="text/tab-separated-values")],
        x_row_count: Annotated[int, Header(ge=0, description="Data rows, not counting the header")],
        x_content_sha256: Annotated[str, Header(description="Hex SHA-256 of the uncompressed servable list")],
        content_encoding: Annotated[str | None, Header(description="gzip, or absent")] = None,
    ) -> JSONResponse:
        """Streams the servable list to Serena. Uploading the same list again changes nothing; a corrected list
        replaces the previous one while the refresh is started, received, check_failed or update_failed, and must then
        be checked again. Its format is checked by the servable list check."""
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
        refresh = await asyncio.to_thread(refresh_of, tenant, refresh_id)
        if refresh.state not in UPLOAD_ALLOWED:
            busy = " (Serena is working on it)" if refresh.state in BUSY else ""
            raise ProblemError(409, "the-etl-api", "Out of order",
                               f"refresh {refresh.refresh_id} is {refresh.state.value}{busy}; a servable list can be "
                               "uploaded only while the refresh is started, received, check_failed or update_failed")
        try:
            received = await uploads.receive(request.stream(), gzipped=encoding == "gzip",
                                             max_bytes=services.settings.upload_max_mb * 1024 * 1024,
                                             directory=services.settings.upload_dir)
        except uploads.TooLarge:
            raise ProblemError(413, "the-etl-api", "Servable list too large",
                               f"At most {services.settings.upload_max_mb} MB uncompressed") from None
        except uploads.BadGzip:
            raise ProblemError(400, "the-etl-api", "Bad gzip", "The body isn't valid gzip") from None
        try:
            if received.sha256 != sha:
                raise ProblemError(422, "the-etl-api", "SHA-256 doesn't match",
                                   "X-Content-SHA256 must be the SHA-256 of the uncompressed servable list")
            if received.rows != x_row_count:
                raise ProblemError(422, "the-etl-api", "Row count doesn't match",
                                   f"X-Row-Count is {x_row_count}; the servable list has {received.rows} data rows")
            if refresh.upload is not None and refresh.upload.sha256 == sha:
                log.info("same servable list uploaded again",
                         extra={"museum": tenant, "refresh_id": refresh.refresh_id})
                return _json(_out(services, refresh))
            key = f"servable-list/{refresh.refresh_id}/{refresh.file_name}.gz"
            await asyncio.to_thread(uploads.store, services.s3, bucket, key, received)
            upload = Upload(sha, received.rows, received.size, key, services.refreshes.now())
            try:
                refresh = await asyncio.to_thread(services.refreshes.transition, refresh, State.RECEIVED,
                                                  upload=upload)
            except OutOfOrder as error:
                raise out_of_order(error) from None
        finally:
            os.unlink(received.path)
        log.info("servable list received",
                 extra={"museum": tenant, "refresh_id": refresh.refresh_id, "rows": received.rows})
        return _json(_out(services, refresh))

    def step(tenant: str, refresh_id: str, allowed: State | frozenset[State], to: State, done: frozenset[State],
             what: str) -> JSONResponse:
        """Moves a refresh from `allowed` to `to`; a refresh already in `to` or past it (`done`) is returned as it is,
        so repeating the call is safe. Anything else is out of order."""
        refresh = refresh_of(tenant, refresh_id)
        if refresh.state in done:
            return _json(_out(services, refresh), 202 if refresh.state in BUSY else 200)
        states = allowed if isinstance(allowed, frozenset) else frozenset({allowed})
        if refresh.state not in states:
            needed = " or ".join(sorted(s.value for s in states))
            raise ProblemError(409, "the-etl-api", "Out of order",
                               f"refresh {refresh.refresh_id} is {refresh.state.value}; {what} needs it {needed}")
        try:
            refresh = services.refreshes.transition(refresh, to)
        except OutOfOrder as error:
            raise out_of_order(error) from None
        log.info("step requested",
                 extra={"museum": tenant, "refresh_id": refresh.refresh_id, "state": refresh.state.value})
        return _json(_out(services, refresh), 202 if to in BUSY else 200)

    @app.post("/museums/{tenant}/refreshes/{refresh_id}/check", response_model=RefreshOut, status_code=202,
              responses={200: {"description": "The servable list check is already done; the refresh is returned as "
                                              "it is", "model": RefreshOut},
                         **openapi_responses(401, 403, 404, 409, 503)},
              summary="Check the servable list, then update Serena from it")
    def request_check(tenant: Tenant, refresh_id: str) -> JSONResponse:
        """Queues the servable list check (202). When it passes, the worker goes straight on to the servability update
        (decided October 12, 2026, D80): poll the refresh until it is updated, check_failed or update_failed. Allowed
        once a servable list is uploaded (received). After a failed check, upload a corrected list first."""
        return step(tenant, refresh_id, State.RECEIVED, State.CHECKING,
                    frozenset({State.CHECKING, State.CHECK_FAILED, State.UPDATING, State.UPDATED,
                               State.UPDATE_FAILED}),
                    "the servable list check")

    @app.get("/museums/{tenant}", response_model=RefreshOut, responses=openapi_responses(401, 403, 404, 503),
             summary="The museum's latest updated refresh")
    def latest_updated(tenant: Tenant) -> JSONResponse:
        """For troubleshooting. 404 if the museum has no updated refresh yet."""
        refresh = services.refreshes.latest_updated(tenant)
        if refresh is None:
            raise ProblemError(404, "the-etl-api", "No updated refresh", f"{tenant} has no updated refresh yet")
        return _json(_out(services, refresh))

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
