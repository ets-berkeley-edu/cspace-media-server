"""The admin app's Settings page (design: Admin web app, Records; decided October 12, 2026, D86 to D90, D97).

Each museum's settings have default values (the starting values in its YAML file); an admin's value, stored in the
Settings table, overrides one until it's removed ("Use default"). Every change needs a reason and is audited with the
value before and after. A change to the delta threshold or the audit log's retention also raises an alert, which the
worker emails: both weaken a protection. The app and the worker read the settings again within about a minute.

The placeholder image's Media record (decided October 14, 2026, D166 to D172) is a setting too: Serena checks the
record with CollectionSpace before saving it, and fetches every size of its file again, indexing them under the
placeholder's Blob only if all of them pass; "Use default" goes back to the generic picture."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from .admin_api import SignedIn, changes, services
from .alerts import Alert, Alerts, Kind
from .audit import Action, Audit
from .cspace.client import CSpaceError, MediaState
from .fetch import Fetcher
from .museum import AUDIT_RETENTION_DAYS, SERVED_KINDS, Museum, StartingSettings
from .museum_settings import MuseumSettings
from .refreshes import PACIFIC
from .store import ServabilityRecord, Store

log = logging.getLogger("serena.admin")


@dataclass(frozen=True)
class Setting:
    name: str  # as in the API's path: a StartingSettings field, or size_limit_mb.<kind>
    group: str
    label: str
    alerted: bool = False  # weakening it weakens a protection: the team is emailed (D89, D97)


SETTINGS = (
    Setting("watchdog_deadline", "watchdog", "Deadline for today's refresh (HH:MM, Pacific)"),
    Setting("etl_poll_interval_seconds", "etl", "ETL poll interval (seconds)"),
    Setting("etl_step_timeout_seconds", "etl", "ETL step timeout (seconds)"),
    Setting("delta_threshold_percent", "check", "Delta threshold (%)", alerted=True),
    *(Setting(f"size_limit_mb.{kind}", "size_limits", f"Largest {kind} file fetched (MB)") for kind in SERVED_KINDS),
    Setting("audit_retention_days", "audit", "How long the audit log is kept (days)", alerted=True),
    Setting("placeholder_media_csid", "placeholder", "Placeholder image (Media CSID)"),
)
PLACEHOLDER = "placeholder_media_csid"
NUMBER = "placeholder_identification_number"  # kept with it (not a setting of its own)
BY_NAME = {setting.name: setting for setting in SETTINGS}


@dataclass
class SettingsServices:
    museum_settings: MuseumSettings
    store: Store
    alerts: Alerts  # the app's: records alerts; the worker emails them
    audit: Audit
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    fetcher: Fetcher | None = None  # the placeholder image's files, and CollectionSpace through its clients


def settings_services(request: Request) -> SettingsServices:
    found: SettingsServices = request.app.state.admin_settings
    return found


Settings_ = Annotated[SettingsServices, Depends(settings_services)]


class Change(BaseModel):
    value: str | int | float
    reason: str = Field(min_length=1, max_length=500)


class Reason(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


def value_of(settings: StartingSettings, name: str) -> Any:
    if name.startswith("size_limit_mb."):
        return settings.size_limit_mb[name.split(".", 1)[1]]  # type: ignore[index]
    return getattr(settings, name)


def merged(museum: Museum, overrides: dict[str, Any]) -> StartingSettings:
    return StartingSettings.model_validate({**museum.settings.model_dump(), **overrides})


def with_value(museum: Museum, overrides: dict[str, Any], name: str, value: Any) -> dict[str, Any]:
    """The admin's values with `name` set to `value`; a value equal to the starting value removes the admin's."""
    updated = dict(overrides)
    starting = museum.settings
    if name.startswith("size_limit_mb."):
        kind = name.split(".", 1)[1]
        limits = dict(updated.get("size_limit_mb") or starting.size_limit_mb)
        limits[kind] = value
        if limits == dict(starting.size_limit_mb):
            updated.pop("size_limit_mb", None)
        else:
            updated["size_limit_mb"] = limits
    elif value == getattr(starting, name):
        updated.pop(name, None)
    else:
        updated[name] = value
    return updated


def _clean(text: str) -> str:
    return " ".join(text.split())


def create_router() -> APIRouter:
    router = APIRouter(prefix="/admin/v1/museums/{tenant}")

    def describe(st: SettingsServices, museum: Museum) -> dict[str, Any]:
        overrides, _ = st.store.settings_with_version(museum.key)
        try:
            current = merged(museum, overrides)
        except ValidationError:
            current = museum.settings  # as the app and worker do: an invalid admin value isn't used
        now = st.clock()
        removed = st.audit.count_before(museum.key, {days: now - timedelta(days=days) for days in AUDIT_RETENTION_DAYS})
        return {
            "settings": [{"name": s.name, "group": s.group, "label": s.label, "value": value_of(current, s.name),
                          "default": value_of(museum.settings, s.name),
                          "changed": value_of(current, s.name) != value_of(museum.settings, s.name)}
                         for s in SETTINGS],
            # The Blob the museum's ETL lists for its placeholder image (its configuration), if it uses one, and the
            # named record's identification number, for the Settings page (D169).
            "placeholder": {"blob_csid": museum.placeholder_blob_csid,
                            "identification_number": current.placeholder_identification_number},
            "audit_retention_choices": [{"days": days, "entries_removed": removed[days]}
                                        for days in AUDIT_RETENTION_DAYS]}

    def placeholder_check(st: SettingsServices, museum: Museum, media_csid: str) -> dict[str, Any]:
        """D170 to D172: the Media record must exist, not be soft-deleted, and have a file; every size the museum serves
        is fetched again (all or none indexed). Returns what the audit entry and the answer add."""
        if st.fetcher is None:
            raise HTTPException(503, "CollectionSpace isn't configured here, so the record can't be checked.")
        try:
            record = st.fetcher.clients.get(museum.key).media_record(media_csid)
        except CSpaceError as error:
            log.warning("placeholder image: CollectionSpace not asked", extra={"museum": museum.key,
                                                                             "error": type(error).__name__})
            raise HTTPException(503, "CollectionSpace can't be reached right now, so the record can't be checked. "
                                     "Try again in a minute.") from error
        if record.state is MediaState.GONE:
            raise HTTPException(422, "CollectionSpace has no Media record with this CSID.")
        if record.state is MediaState.DELETED:
            raise HTTPException(422, "This Media record is soft-deleted in CollectionSpace.")
        if not record.blob_csid:
            raise HTTPException(422, "This Media record has no file in CollectionSpace.")
        added: dict[str, Any] = {"identification_number": record.identification_number}
        blob = museum.placeholder_blob_csid
        if blob is None:
            return added  # nothing lists a placeholder for this museum yet: nothing to fetch
        if record.blob_csid != blob:
            added["warning"] = (f"This Media record's Blob ({record.blob_csid}) isn't the one the ETL lists for the "
                                f"placeholder image ({blob}). Serena serves this record's picture anyway.")
        sizes: list[str | None] = [None, *museum.derivatives] if museum.original else list(museum.derivatives)
        fetched = st.fetcher.fetch_all(museum, ServabilityRecord(museum.key, blob, media_csid, "image", "public"),
                                       sizes)
        if isinstance(fetched, tuple):
            size, why = fetched
            what = why.value.replace("_", " ")
            raise HTTPException(422, f"Its {size or 'original'} file can't be served ({what}), so the setting wasn't "
                                     "changed.")
        added["fetched"] = [size or "original" for size in fetched]
        return added

    def change(request: Request, session: Any, st: SettingsServices, name: str, value: Any, reason: str,
               to_default: bool) -> dict[str, Any]:
        admin = services(request)
        setting = BY_NAME.get(name)
        if setting is None:
            raise HTTPException(404, "No such setting.")
        museum = admin.museums[session.tenant]
        overrides, version = st.store.settings_with_version(museum.key)
        try:
            before = value_of(merged(museum, overrides), name)
        except ValidationError:
            before = value_of(museum.settings, name)
        if to_default:
            value = value_of(museum.settings, name)
        updated = with_value(museum, overrides, name, value)
        try:
            after = value_of(merged(museum, updated), name)
        except ValidationError as error:
            problems = "; ".join(e["msg"].removeprefix("Value error, ") for e in error.errors())
            raise HTTPException(422, f"{setting.label}: {problems}") from None
        updated = with_value(museum, overrides, name, after)  # stored as the validated value (a number, not text)
        extra: dict[str, Any] = {}
        if name == PLACEHOLDER and after is not None:
            extra = placeholder_check(st, museum, after)  # before saving: a record that won't do changes nothing
        if name == PLACEHOLDER:
            # Kept with the setting, as read when it's saved, so the Settings page doesn't ask CollectionSpace.
            updated.pop(NUMBER, None)
            if extra.get("identification_number"):
                updated[NUMBER] = extra["identification_number"]
        if not st.store.put_settings_overrides(museum.key, updated, version):
            raise HTTPException(409, "Another admin changed this museum's settings just now: reload and try again.")
        st.museum_settings.forget(museum.key)
        details = {"before": before, "after": after, "reason": reason,
                   **{k: v for k, v in extra.items() if k != "warning" and v is not None}}
        if to_default:
            details["default_value"] = True
        st.audit.record(museum.key, session.user, Action.SETTINGS_CHANGE, name, details)
        if setting.alerted and before != after:
            at = st.clock().astimezone(UTC).isoformat(timespec="seconds")
            st.alerts.raise_(Alert(museum.key, st.clock().astimezone(PACIFIC).date().isoformat(),
                                   Kind.SETTING_CHANGED, name,
                                   f"An admin changed a setting for {museum.name}: {setting.label}, from {before} "
                                   f"to {after}. Reason: {reason}", instance=at))
        log.info("setting changed", extra={"museum": museum.key, "setting": name})
        answer = describe(st, museum)
        if "warning" in extra:
            answer["warning"] = extra["warning"]
        return answer

    @router.get("/settings")
    def get_settings(request: Request, session: SignedIn, st: Settings_) -> dict[str, Any]:
        return describe(st, services(request).museums[session.tenant])

    @router.put("/settings/{name}", dependencies=[Depends(changes)])
    def put_setting(name: str, body: Change, request: Request, session: SignedIn, st: Settings_) -> dict[str, Any]:
        value = body.value.strip() if isinstance(body.value, str) else body.value
        return change(request, session, st, name, value, _clean(body.reason), to_default=False)

    @router.post("/settings/{name}/reset", dependencies=[Depends(changes)])
    def reset_setting(name: str, body: Reason, request: Request, session: SignedIn, st: Settings_) -> dict[str, Any]:
        """"Use default" (D90): removes the admin's value for this setting."""
        return change(request, session, st, name, None, _clean(body.reason), to_default=True)

    return router
