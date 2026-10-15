"""The web app: built by create_app(), served by uvicorn (serena.main:app)."""
from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Any

import boto3
import httpx
from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import PlainTextResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import (
    admin_api,
    admin_recalls,
    admin_refreshes,
    admin_requests,
    admin_settings,
    etl_api,
    imageserver,
    logs,
    museum,
    requests_log,
    signed_links,
    signing,
    tables,
)
from .admin_sessions import Sessions
from .alerts import Alerts
from .audit import Audit
from .config import Settings, get_settings
from .cspace.clients import CSpaceClients, HttpFactory
from .fetch import Fetcher
from .museum_settings import MuseumSettings
from .refreshes import Refreshes
from .secret_cache import SecretCache, secretsmanager_client
from .store import Store, dynamodb_client
from .tokens import Tokens
from .unserved import Recorder

log = logging.getLogger("serena.app")


def create_app(settings: Settings | None = None, store: Store | None = None, unserved: Recorder | None = None,
               s3: Any = None, secretsmanager: Any = None, clock: Callable[[], datetime] | None = None,
               cspace_http: HttpFactory | None = None, log_reader: requests_log.Reader | None = None) -> FastAPI:
    """The app. Tests pass their own store, recorder, log reader and clients (moto, the CollectionSpace simulator);
    otherwise they use AWS and each museum's CollectionSpace."""
    settings = settings or get_settings()
    logs.configure(settings.log_level, settings.log_file)
    museums = museum.load_all(settings.tenants)
    if store is None:
        client = dynamodb_client(settings)
        if settings.create_tables:
            created = tables.create_all(client, settings.table_prefix)
            if created:
                log.info("created tables", extra={"tables": created})
        store = Store(client, settings.table_prefix)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            app.state.fetcher.clients.close()

    # No interactive API documentation here: the ETL API's description is generated into docs/api/ (design: The ETL
    # API), and the admin app has its own button for it.
    app = FastAPI(title="Serena", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.museums = museums
    app.state.store = store
    app.state.museum_settings = MuseumSettings(store, settings.settings_cache_seconds)
    app.state.unserved = unserved

    if s3 is None:
        s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint)
    if secretsmanager is None:
        secretsmanager = secretsmanager_client(settings)
    secret_cache = SecretCache(secretsmanager, settings.secret_cache_seconds)
    tokens = Tokens(secret_cache, settings.etl_token_secret_ids, list(museums))
    app.state.s3 = s3
    app.state.signer = _signer(settings, secret_cache)
    app.state.signing_keys = signed_links.SigningKeys(secret_cache, settings.signing_key_secret_ids)
    app.state.fetcher = Fetcher(
        CSpaceClients(settings, secret_cache, cspace_http), s3, settings.buckets, app.state.museum_settings, store,
        fetch_dir=settings.fetch_dir, free_margin_mb=settings.fetch_free_margin_mb,
        failure_seconds=settings.fetch_failure_memory_seconds)
    for key, configured in museums.items():
        if configured.signed_access_kinds and key not in settings.signing_key_secret_ids:
            log.warning("no signing key secret for a museum with signed access: its restricted files aren't served",
                        extra={"museum": key})
    app.mount(etl_api.PREFIX, etl_api.create_etl_app(etl_api.Services(
        settings, museums, app.state.museum_settings, Refreshes(store, clock) if clock else Refreshes(store), tokens,
        s3, Audit(store))))

    @app.get("/health", include_in_schema=False)
    def health() -> PlainTextResponse:
        """For the load balancer: answers "ok" and nothing else about Serena."""
        return PlainTextResponse("ok", headers={"Cache-Control": "no-store"})

    @app.exception_handler(StarletteHTTPException)
    async def not_found(request: Request, error: StarletteHTTPException) -> Response:
        """An address outside Serena's APIs that matches nothing gets a short plain-text 404 (Richard, October 14,
        2026), never JSON and never a list of Serena's addresses; the admin API keeps its JSON errors (the ETL API,
        mounted on its own, has its own)."""
        if error.status_code == 404 and not request.url.path.startswith(admin_api.PREFIX + "/"):
            return PlainTextResponse("Not found.", status_code=404, headers={"Cache-Control": "no-store"})
        return await http_exception_handler(request, error)

    # The app records alerts (an admin's override or setting change, D62, D89) but doesn't email them: the worker does.
    app_alerts = Alerts(store, None, "")
    audit = Audit(store)  # real time: entries are ordered by it
    app.state.admin_refreshes = admin_refreshes.RefreshServices(
        Refreshes(store, clock) if clock else Refreshes(store), app_alerts, s3)
    app.state.requests_log = requests_log.Requests(log_reader or _log_reader(settings))
    app.state.admin_recalls = admin_recalls.RecallServices(
        store, app.state.fetcher.clients, audit, app_alerts, Refreshes(store, clock) if clock else Refreshes(store),
        app.state.museum_settings, s3, settings.buckets, *((clock,) if clock else ()))
    app.state.admin_settings = admin_settings.SettingsServices(
        app.state.museum_settings, store, app_alerts, audit, **({"clock": clock} if clock else {}),
        fetcher=app.state.fetcher)
    admin_api.add_to(app, admin_api.AdminServices(
        settings, museums,
        Sessions(store, settings.admin_session_idle_minutes, settings.admin_session_hours), audit,
        cspace_http or _admin_http), routers=(admin_refreshes.create_router(), admin_settings.create_router(),
                                            admin_requests.create_router(), admin_recalls.create_router()))
    app.include_router(imageserver.router)

    log.info("Serena started", extra={"museums": sorted(museums), "environment": settings.env_label})
    return app


def _log_reader(settings: Settings) -> requests_log.Reader | None:
    """Where the Past requests page reads the log (D109): CloudWatch Logs Insights in AWS, the local log file
    otherwise."""
    if settings.log_group:
        return requests_log.CloudWatchReader(boto3.client("logs", region_name=settings.aws_region),
                                             settings.log_group)
    if settings.log_file:
        return requests_log.FileReader(settings.log_file)
    return None


def _signer(settings: Settings, secret_cache: SecretCache) -> signing.Signer | None:
    if settings.cdn_base_url and settings.cloudfront_key_secret_id:
        return signing.CloudFrontURLSigner(settings.cdn_base_url, secret_cache, settings.cloudfront_key_secret_id)
    if settings.local_cdn:
        return signing.LocalSigner()
    log.warning("no CloudFront signer configured: servable files get the unavailable image")
    return None


def _admin_http(tenant: str) -> httpx.Client:
    """For an admin's sign-in: one short request to the museum's CollectionSpace, no redirects followed."""
    return httpx.Client(timeout=httpx.Timeout(10.0), follow_redirects=False)
