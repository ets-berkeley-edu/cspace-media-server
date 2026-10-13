"""Per-museum configuration (design: URLs, Kinds, Servability, Records), one YAML file per museum in museums/.

A museum's settings here are starting values: an admin's value in the Settings table overrides them."""
from __future__ import annotations

import re
from functools import cache
from importlib import resources
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .csid import is_csid

# The derivatives CollectionSpace makes (design: CollectionSpace and ETL facts), in size order.
DERIVATIVES = ("Thumbnail", "Small", "Medium", "FullHD", "OriginalJpeg")
# The kinds Serena serves (design: Kinds). audio and video are in the servable list but not served yet.
SERVED_KINDS = ("image", "card", "3D", "pdf")
Kind = Literal["image", "card", "3D", "pdf"]

_DEADLINE = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
# How long a museum's audit log is kept, in days: 90 days, or 6, 12, 18, 24 or 36 months (decided October 12, 2026,
# D97).
AUDIT_RETENTION_DAYS = (90, 183, 365, 548, 730, 1095)


class StartingSettings(BaseModel):
    """Starting values of the settings admins change in the admin app (design: Records, Settings). The bounds keep a
    typo from breaking the daily refresh (decided October 12, 2026, D88); an admin's value is checked against them
    too."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    watchdog_deadline: str = Field(description="HH:MM, Pacific time")
    etl_poll_interval_seconds: int = Field(ge=5, le=300)
    etl_step_timeout_seconds: int = Field(ge=60, le=7200)
    delta_threshold_percent: float = Field(ge=0.1, le=100)
    size_limit_mb: dict[Kind, int]
    audit_retention_days: int = 90

    @field_validator("watchdog_deadline")
    @classmethod
    def _deadline(cls, value: str) -> str:
        if not _DEADLINE.fullmatch(value):
            raise ValueError("watchdog_deadline must be HH:MM (24-hour, Pacific time)")
        return value

    @field_validator("size_limit_mb")
    @classmethod
    def _limits(cls, limits: dict[str, int]) -> dict[str, int]:
        missing = [kind for kind in SERVED_KINDS if kind not in limits]
        if missing:
            raise ValueError(f"size_limit_mb needs a limit for {', '.join(missing)}")
        if any(not 1 <= limit <= 2048 for limit in limits.values()):
            raise ValueError("size limits must be 1 to 2,048 MB")
        return limits

    @field_validator("audit_retention_days")
    @classmethod
    def _retention(cls, days: int) -> int:
        if days not in AUDIT_RETENTION_DAYS:
            raise ValueError(f"audit_retention_days must be one of {', '.join(map(str, AUDIT_RETENTION_DAYS))}")
        return days


class Museum(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    name: str
    derivatives: tuple[str, ...]
    # Whether the original file (…/blobs/<CSID>/content) is served for images and cards.
    original: bool
    # The Blob the ETL lists in place of a non-public image (design: Placeholder image). Only museums whose ETL
    # uses one have it.
    placeholder_blob_csid: str | None = None
    # The sizes the museum watermarks (design: Watermarks). Until watermarking is built, they get the unavailable
    # image: Serena never serves an unwatermarked copy of a size the museum watermarks.
    watermark_sizes: tuple[str, ...] = ()
    # The kinds whose restricted files are served with a portal's signed link (design: Restricted files). Its keys
    # are a Secrets Manager secret, named in SERENA_SIGNING_KEY_SECRET_IDS.
    signed_access_kinds: tuple[Kind, ...] = ()
    # The CollectionSpace role (its display name) that marks a Serena admin in this museum (design: Admin web app).
    # It carries no permissions in CollectionSpace; the museum's administrators give it to the team.
    admin_role: str = Field(default="Serena_Admin", pattern=r"^[A-Za-z0-9_ ]{1,64}$")
    settings: StartingSettings

    @field_validator("derivatives")
    @classmethod
    def _derivatives(cls, names: tuple[str, ...]) -> tuple[str, ...]:
        if not names:
            raise ValueError("a museum serves at least one derivative")
        unknown = [name for name in names if name not in DERIVATIVES]
        if unknown:
            raise ValueError(f"unknown derivatives: {', '.join(unknown)}")
        if len(set(names)) != len(names):
            raise ValueError("a derivative is listed twice")
        return names

    @field_validator("placeholder_blob_csid")
    @classmethod
    def _csid(cls, value: str | None) -> str | None:
        if value is not None and not is_csid(value):
            raise ValueError("placeholder_blob_csid isn't a CSID")
        return value

    @model_validator(mode="after")
    def _key_is_file_name(self) -> Museum:
        if not re.fullmatch(r"[a-z]+", self.key):
            raise ValueError("a museum's key is lower-case letters")
        unknown = [size for size in self.watermark_sizes if size not in self.derivatives]
        if unknown:
            raise ValueError(f"watermark_sizes not among the museum's derivatives: {', '.join(unknown)}")
        if len(set(self.signed_access_kinds)) != len(self.signed_access_kinds):
            raise ValueError("a kind is listed twice in signed_access_kinds")
        return self


def available() -> list[str]:
    """The museums that have a configuration file."""
    files = resources.files("serena.museums").iterdir()
    return sorted(f.name.removesuffix(".yaml") for f in files if f.name.endswith(".yaml"))


@cache
def load(key: str) -> Museum:
    if key not in available():
        raise ValueError(f"no configuration for museum {key!r}")
    text = resources.files("serena.museums").joinpath(f"{key}.yaml").read_text(encoding="utf-8")
    museum = Museum.model_validate(yaml.safe_load(text))
    if museum.key != key:
        raise ValueError(f"museums/{key}.yaml has key {museum.key!r}")
    return museum


def load_all(tenants: dict[str, str]) -> dict[str, Museum]:
    """The configuration of each museum the deployment serves (Settings.tenants); fails on one with no file."""
    return {key: load(key) for key in sorted(tenants)}
