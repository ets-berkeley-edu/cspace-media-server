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
    aws_region: str = "us-west-2"

    @field_validator("tenants")
    @classmethod
    def _cspace_urls(cls, tenants: dict[str, str]) -> dict[str, str]:
        for tenant, url in tenants.items():
            if not url.startswith(("https://", "http://")):
                raise ValueError(f"the CollectionSpace server for {tenant} must be an http(s) URL")
        return {tenant: url.rstrip("/") for tenant, url in tenants.items()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
