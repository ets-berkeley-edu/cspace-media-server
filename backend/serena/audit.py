"""The audit log of admin actions (design: Records, Admin web app; decided October 10, 2026).

One entry per action: the museum, the time, the admin (their CollectionSpace username), the action, its target (a
Media CSID, refresh ID or setting name) and, for a setting, the values before and after. Never a password, token or
file's content. Failed sign-ins aren't recorded here: their username may be anyone's. Entries are kept for the
museum's audit retention (90 days to start; an admin's setting, 6 to 36 months), and the worker removes older ones once
a day (decided October 12, 2026, D97, D98)."""
from __future__ import annotations

import json
import secrets
from collections.abc import Callable, Iterator
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
    RECALL = "recall"
    RECALL_RELEASE = "recall_release"  # an admin's release of a recall a refresh kept (D119)
    RECALL_CANCEL = "recall_cancel"  # an admin cancelled a recall no refresh has decided yet (D148)
    RECALL_ENDED = "recall_ended"  # a servability update ended a recall; the refresh is the actor (D119)
    SETTINGS_CHANGE = "settings_change"
    AUDIT_EXPORT = "audit_export"
    UPDATE_RETRY = "update_retry"
    THRESHOLD_OVERRIDE = "threshold_override"
    ADMIN_REFRESH = "admin_refresh"  # a manual refresh started (the admin app calls it that since issue #118)
    UPDATE_RUN = "update_run"  # an admin ran a manual refresh's servability update (issue #118)
    PLACEHOLDER_UPLOAD = "placeholder_upload"
    ALERT_ACKNOWLEDGE = "alert_acknowledge"
    # The ETL's calls that change something, by "ETL (<museum>)", and each refresh's outcome, by the refresh (D150).
    # Never its GETs or ping, which it makes every few seconds while Serena checks.
    ETL_REFRESH_START = "etl_refresh_start"
    ETL_SERVABLE_LIST_UPLOAD = "etl_servable_list_upload"
    ETL_CHECK_REQUEST = "etl_check_request"
    REFRESH_OUTCOME = "refresh_outcome"


@dataclass(frozen=True)
class Entry:
    tenant: str
    at: str
    admin: str
    action: str
    target: str
    details: dict[str, Any]


REFRESH_ACTOR = "refresh "  # how a refresh's own entries name it (D150): "refresh <refresh ID>"


def shown_by(admin: str) -> str:
    """Who did it, as the admin app and the CSV export show it: a refresh's own entries are by Serena (D155); its
    refresh ID goes in the details, or is the target."""
    return "Serena" if admin.startswith(REFRESH_ACTOR) else admin


def shown_details(entry: Entry) -> dict[str, Any]:
    """The entry's details, with the refresh that acted when it isn't already the target (a recall a refresh ended)."""
    if entry.admin.startswith(REFRESH_ACTOR):
        refresh_id = entry.admin[len(REFRESH_ACTOR):]
        if refresh_id != entry.target:
            return {**entry.details, "refresh": refresh_id}
    return entry.details


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

    def since(self, tenant: str, cutoff: datetime) -> list[Entry]:
        """The museum's entries from `cutoff` on, newest first (the admin app's Audit log page, D93)."""
        return list(self._query(tenant, newest_first=True, condition="pk = :t AND sk >= :cut",
                                values={":cut": {"S": stamp(cutoff)}}))

    def everything(self, tenant: str) -> Iterator[Entry]:
        """All the museum's entries, oldest first (the CSV export, D96)."""
        return self._query(tenant, newest_first=False)

    def count_before(self, tenant: str, cutoffs: dict[int, datetime]) -> dict[int, int]:
        """For each key, how many entries are older than its cutoff (what a shorter retention would remove)."""
        counts = dict.fromkeys(cutoffs, 0)
        marks = {key: stamp(cutoff) for key, cutoff in cutoffs.items()}
        for sort_key in self._sort_keys(tenant):
            for key, mark in marks.items():
                if sort_key < mark:
                    counts[key] += 1
        return counts

    def purge(self, tenant: str, cutoff: datetime) -> int:
        """Deletes the museum's entries older than `cutoff` (the worker, once a day, D98); returns how many."""
        mark = stamp(cutoff)
        doomed = list(self._sort_keys(tenant, before=mark))
        table = self.store.table(tables.AUDIT)
        for start in range(0, len(doomed), 25):
            requests: list[dict[str, Any]] = [{"DeleteRequest": {"Key": {"pk": {"S": tenant}, "sk": {"S": key}}}}
                                              for key in doomed[start:start + 25]]
            for _ in range(5):
                unprocessed = self.store.client.batch_write_item(RequestItems={table: requests}).get(
                    "UnprocessedItems", {}).get(table, [])
                if not unprocessed:
                    break
                requests = unprocessed
        return len(doomed)

    def _sort_keys(self, tenant: str, before: str | None = None) -> Iterator[str]:
        condition = "pk = :t" + (" AND sk < :before" if before else "")
        values: dict[str, Any] = {":t": {"S": tenant}, **({":before": {"S": before}} if before else {})}
        start: dict[str, Any] | None = None
        while True:
            options: dict[str, Any] = {"ExclusiveStartKey": start} if start else {}
            page = self.store.client.query(TableName=self.store.table(tables.AUDIT), KeyConditionExpression=condition,
                                           ExpressionAttributeValues=values, ProjectionExpression="sk", **options)
            for item in page["Items"]:
                yield item["sk"]["S"]
            start = page.get("LastEvaluatedKey")
            if not start:
                return

    def _query(self, tenant: str, newest_first: bool, condition: str = "pk = :t",
               values: dict[str, Any] | None = None) -> Iterator[Entry]:
        start: dict[str, Any] | None = None
        while True:
            options: dict[str, Any] = {"ExclusiveStartKey": start} if start else {}
            page = self.store.client.query(TableName=self.store.table(tables.AUDIT), KeyConditionExpression=condition,
                                           ExpressionAttributeValues={":t": {"S": tenant}, **(values or {})},
                                           ScanIndexForward=not newest_first, **options)
            for i in page["Items"]:
                yield Entry(tenant, i["at"]["S"], i["admin"]["S"], i["action"]["S"], i["target"]["S"],
                            json.loads(i["details"]["S"]))
            start = page.get("LastEvaluatedKey")
            if not start:
                return


def stamp(moment: datetime) -> str:
    """A time as entries store it (and as their sort keys begin)."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
