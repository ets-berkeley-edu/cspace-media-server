"""Settings, read from environment variables prefixed with SERENA_ (see .env.example).

No password, token or key is a setting: secrets are read from AWS Secrets Manager, never from the environment."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
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
    # Local development only: create missing tables at start-up. Allowed only with dynamodb_endpoint, so it can never
    # create tables in AWS (Terraform does that there).
    create_tables: bool = False
    # How long each task keeps a museum's settings before reading the Settings table again
    settings_cache_seconds: float = 60.0
    # How often each task writes its counts of unserved requests to their table
    unserved_flush_seconds: float = 60.0

    # Each museum's S3 bucket (design: Storage), from SERENA_BUCKETS as JSON: {"pahma": "..."}.
    buckets: dict[str, str] = {}
    s3_endpoint: str | None = None  # local development only
    # The ETL API (design: The ETL API). Each museum's bearer tokens are one Secrets Manager secret holding
    # {"current": ..., "previous": ...}; these are the secrets' IDs, from SERENA_ETL_TOKEN_SECRET_IDS as JSON.
    etl_token_secret_ids: dict[str, str] = {}
    secretsmanager_endpoint: str | None = None  # local development only
    secret_cache_seconds: float = 300.0  # how long each task keeps a secret before reading it again
    upload_max_mb: int = 500  # the largest Blob-to-Media file accepted, uncompressed
    upload_dir: str | None = None  # where uploads are written while they're checked; None: the system's temp directory
    # The worker (design: Preflight and apply): how often it looks for work, how often it renews its claim on a step,
    # and how old a claim may get before the step counts as interrupted and is started again.
    worker_poll_seconds: float = 5.0
    worker_heartbeat_seconds: float = 30.0
    worker_heartbeat_stale_seconds: float = 300.0
    # The watchdog (design: Watchdog and alerts), in the worker: how often it checks, and the SNS topic its alerts
    # are emailed through (one per environment; the team's mailing list subscribes to it). Empty: alerts are
    # recorded and logged, not emailed (local development).
    watchdog_seconds: float = 300.0
    alert_topic_arn: str = ""
    sns_endpoint: str | None = None  # local development only

    # Delivery (design: Signed URLs): the CloudFront distribution's base URL; a file is
    # <base>/<tenant>/objects/<sha256>. The signing key is a Secrets Manager secret
    # {"key_pair_id": ..., "private_key": "<PEM>"}.
    cdn_base_url: str = ""
    cloudfront_key_secret_id: str = ""
    # Local development only, without CloudFront: Serena signs with a key of its own and serves the files itself at
    # /local-cdn/<tenant>/objects/<sha256>. Allowed only with dynamodb_endpoint (DynamoDB Local), so never in AWS.
    local_cdn: bool = False

    @field_validator("tenants")
    @classmethod
    def _cspace_urls(cls, tenants: dict[str, str]) -> dict[str, str]:
        for tenant, url in tenants.items():
            if not url.startswith(("https://", "http://")):
                raise ValueError(f"the CollectionSpace server for {tenant} must be an http(s) URL")
        return {tenant: url.rstrip("/") for tenant, url in tenants.items()}

    @field_validator("cdn_base_url")
    @classmethod
    def _cdn(cls, url: str) -> str:
        return url.rstrip("/")

    @field_validator("unavailable_base_url")
    @classmethod
    def _base_url(cls, url: str) -> str:
        if url and not url.startswith("https://"):
            raise ValueError("unavailable_base_url must be an https URL")
        return url.rstrip("/")

    @model_validator(mode="after")
    def _tables_only_locally(self) -> Settings:
        if self.create_tables and not self.dynamodb_endpoint:
            raise ValueError("create_tables is for local development: set dynamodb_endpoint (DynamoDB Local) too")
        if self.local_cdn and not self.dynamodb_endpoint:
            raise ValueError("local_cdn is for local development: set dynamodb_endpoint (DynamoDB Local) too")
        if self.cdn_base_url and not self.cdn_base_url.startswith("https://"):
            raise ValueError("cdn_base_url must be an https URL")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
