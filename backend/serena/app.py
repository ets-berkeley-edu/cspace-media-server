"""The web app: built by create_app(), served by uvicorn (serena.main:app)."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from . import logs, museum
from .config import Settings, get_settings

log = logging.getLogger("serena.app")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logs.configure(settings.log_level)
    museums = museum.load_all(settings.tenants)

    # No interactive API documentation here: the ETL API's description is generated into docs/api/ (design: The ETL
    # API), and the admin app has its own button for it.
    app = FastAPI(title="Serena", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.museums = museums

    @app.get("/health", include_in_schema=False)
    def health() -> PlainTextResponse:
        """For the load balancer: answers "ok" and nothing else about Serena."""
        return PlainTextResponse("ok", headers={"Cache-Control": "no-store"})

    log.info("Serena started", extra={"museums": sorted(museums), "environment": settings.env_label})
    return app
