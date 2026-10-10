"""The audit log of admin actions (design: Records, Admin web app; decided October 10, 2026).

One entry per action: the museum, the time, the admin (their CollectionSpace username), the action, its target (a
Media CSID, run ID or setting name) and, for a setting, the values before and after. Never a password, token or
file's content. Failed sign-ins aren't recorded here: their username may be anyone's. Entries are kept indefinitely."""
from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from . import tables
from .store import Store


class Action(StrEnum):
    SIGN_IN = "sign_in"
    SIGN_OUT = "sign_out"
    SIGN_OUT_ALL = "sign_out_all"
    TAKEDOWN = "takedown"
    UNLOCK = "unlock"
    SETTINGS_CHANGE = "settings_change"
    APPLY_RETRY = "apply_retry"
    THRESHOLD_OVERRIDE = "threshold_override"
    FILE_UPLOAD = "file_upload"
    RESTRICTED_IMAGE_UPLOAD = "restricted_image_upload"


@dataclass(frozen=True)
class Entry:
    tenant: str
    at: str
    admin: str
    action: str
    target: str
    details: dict[str, Any]


class Audit:
    def __init__(self, store: Store, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.store = store
        self.clock = clock

    def record(self, tenant: str, admin: str, action: Action, target: str = "",
               details: dict[str, Any] | None = None) -> Entry:
        at = self.clock().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        entry = Entry(tenant, at, admin, str(action), target, details or {})
        # <time>#<admin>, and a short random suffix so two actions in the same microsecond don't overwrite each other
        self.store.client.put_item(TableName=self.store.table(tables.AUDIT), Item={
            "pk": {"S": tenant}, "sk": {"S": f"{at}#{admin}#{secrets.token_hex(3)}"}, "at": {"S": at},
            "admin": {"S": admin}, "action": {"S": entry.action}, "target": {"S": target},
            "details": {"S": json.dumps(entry.details, sort_keys=True)}})
        return entry

    def recent(self, tenant: str, limit: int = 100, before: str | None = None) -> list[Entry]:
        """Newest first. `before`: an entry's time, for the next page."""
        condition = "pk = :t"
        values: dict[str, Any] = {":t": {"S": tenant}}
        if before:
            condition += " AND sk < :before"
            values[":before"] = {"S": before}
        items = self.store.client.query(TableName=self.store.table(tables.AUDIT), KeyConditionExpression=condition,
                                        ExpressionAttributeValues=values, ScanIndexForward=False,
                                        Limit=limit)["Items"]
        return [Entry(tenant, i["at"]["S"], i["admin"]["S"], i["action"]["S"], i["target"]["S"],
                      json.loads(i["details"]["S"])) for i in items]
