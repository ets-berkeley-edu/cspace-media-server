"""Settings, read from environment variables prefixed with SERENA_ (see .env.example).

No password, token or key is a setting: secrets are read from AWS Secrets Manager, never from the environment."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SERENA_", env_file=".env", extra="ignore")

    # The museums this deployment serves, each with its CollectionSpace server (without /cspace-services), from
    # SERENA_TENANTS as JSON: {"pahma": "https://..."}. Each must have a file in serena/museums/.
    tenants: dict[str, str] = {}
    # Which environment this is (for example "QA"), shown in the admin app; empty: none.
    env_label: str = ""
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # Where the unavailable images are: <base>/<tenant>/unavailable.svg, served by CloudFront without a signature.
    # Empty (local development, tests): Serena serves them itself at /unavailable/<tenant>.svg.
    unavailable_base_url: str = ""
    aws_region: str = "us-west-2"
    # DynamoDB: every table is <table_prefix>-<name> (serena/tables.py); Terraform sets the prefix per environment.
    table_prefix: str = "serena-local"
    dynamodb_endpoint: str | None = None  # local development only (DynamoDB Local)
    create_tables: bool = False  # local development only: create missing tables at start-up
    # How long each task keeps a museum's settings before reading the Settings table again
    settings_cache_seconds: float = 60.0
    # How often each task writes its counts of unserved requests to their table
    unserved_flush_seconds: float = 60.0

    @field_validator("tenants")
    @classmethod
    def _cspace_urls(cls, tenants: dict[str, str]) -> dict[str, str]:
        for tenant, url in tenants.items():
            if not url.startswith(("https://", "http://")):
                raise ValueError(f"the CollectionSpace server for {tenant} must be an http(s) URL")
        return {tenant: url.rstrip("/") for tenant, url in tenants.items()}

    @field_validator("unavailable_base_url")
    @classmethod
    def _base_url(cls, url: str) -> str:
        if url and not url.startswith("https://"):
            raise ValueError("unavailable_base_url must be an https URL")
        return url.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
