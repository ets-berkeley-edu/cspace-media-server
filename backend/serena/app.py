"""The web app: built by create_app(), served by uvicorn (serena.main:app)."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Any

import boto3
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from . import etl_api, imageserver, logs, museum, tables
from .config import Settings, get_settings
from .museum_settings import MuseumSettings
from .runs import Runs
from .secret_cache import SecretCache, secretsmanager_client
from .store import Store, dynamodb_client
from .tokens import Tokens
from .unserved import DynamoRecorder, Recorder

log = logging.getLogger("serena.app")


def create_app(settings: Settings | None = None, store: Store | None = None, unserved: Recorder | None = None,
               s3: Any = None, secretsmanager: Any = None, clock: Callable[[], datetime] | None = None) -> FastAPI:
    """The app. Tests pass their own store, recorder and clients (moto); otherwise they use AWS."""
    settings = settings or get_settings()
    logs.configure(settings.log_level)
    museums = museum.load_all(settings.tenants)
    if store is None:
        client = dynamodb_client(settings)
        if settings.create_tables:
            created = tables.create_all(client, settings.table_prefix)
            if created:
                log.info("created tables", extra={"tables": created})
        store = Store(client, settings.table_prefix)
    recorder = unserved or DynamoRecorder(store.client, store.table(tables.UNSERVED))

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        flusher = asyncio.create_task(_flush_unserved(recorder, settings.unserved_flush_seconds))
        try:
            yield
        finally:
            flusher.cancel()
            await asyncio.to_thread(_flush_now, recorder)

    # No interactive API documentation here: the ETL API's description is generated into docs/api/ (design: The ETL
    # API), and the admin app has its own button for it.
    app = FastAPI(title="Serena", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.museums = museums
    app.state.store = store
    app.state.museum_settings = MuseumSettings(store, settings.settings_cache_seconds)
    app.state.unserved = recorder

    if s3 is None:
        s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint)
    if secretsmanager is None:
        secretsmanager = secretsmanager_client(settings)
    tokens = Tokens(SecretCache(secretsmanager, settings.secret_cache_seconds), settings.etl_token_secret_ids)
    app.mount(etl_api.PREFIX, etl_api.create_etl_app(etl_api.Services(
        settings, museums, app.state.museum_settings, Runs(store, clock) if clock else Runs(store), tokens, s3)))

    @app.get("/health", include_in_schema=False)
    def health() -> PlainTextResponse:
        """For the load balancer: answers "ok" and nothing else about Serena."""
        return PlainTextResponse("ok", headers={"Cache-Control": "no-store"})

    app.include_router(imageserver.router)

    log.info("Serena started", extra={"museums": sorted(museums), "environment": settings.env_label})
    return app


def _flush_now(recorder: Recorder) -> None:
    flush = getattr(recorder, "flush", None)
    if flush is not None:
        try:
            flush()
        except Exception:
            log.exception("could not write unserved-request counts")


async def _flush_unserved(recorder: Recorder, every_seconds: float) -> None:
    while True:
        await asyncio.sleep(every_seconds)
        await asyncio.to_thread(_flush_now, recorder)
