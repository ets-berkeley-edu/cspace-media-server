"""An admin's override of the change threshold, for a museum's next run (design: Preflight and apply; decided October
10, 2026, D64).

A failed preflight stops the night: the ETL doesn't load the public core. So an override can't rescue the failed run;
an admin arms it for the museum's next run instead, which the ETL team starts by rerunning the night (or the next night
starts it). The next preflight skips the threshold check once, says so in its warnings, and uses the override up.
Every other check still applies. An override nobody uses expires after 48 hours.

It's one item in the Settings table, keyed <tenant>#threshold-override, apart from the museum's settings."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from . import tables
from .store import Store

LIFETIME_SECONDS = 48 * 3600


@dataclass(frozen=True)
class Override:
    tenant: str
    armed_by: str  # the admin's CollectionSpace username
    armed_at: float  # Unix seconds
    expires_at: float
    after_run: str  # the run that failed on the threshold
    reason: str


class Overrides:
    def __init__(self, store: Store, clock: Callable[[], float] = time.time):
        self.store = store
        self.clock = clock

    @property
    def table(self) -> str:
        return self.store.table(tables.SETTINGS)

    @staticmethod
    def key(tenant: str) -> dict[str, dict[str, str]]:
        return {"pk": {"S": f"{tenant}#threshold-override"}}

    def arm(self, tenant: str, admin: str, after_run: str, reason: str) -> Override:
        now = self.clock()
        override = Override(tenant, admin, now, now + LIFETIME_SECONDS, after_run, reason)
        self.store.client.put_item(TableName=self.table, Item={
            **self.key(tenant), "armed_by": {"S": admin}, "armed_at": {"N": str(now)},
            "expires_at": {"N": str(int(override.expires_at))}, "after_run": {"S": after_run},
            "reason": {"S": reason}})
        return override

    def get(self, tenant: str) -> Override | None:
        """The museum's armed override, or None (an expired one is gone)."""
        item = self.store.client.get_item(TableName=self.table, Key=self.key(tenant), ConsistentRead=True).get("Item")
        if item is None:
            return None
        override = Override(tenant, item["armed_by"]["S"], float(item["armed_at"]["N"]),
                            float(item["expires_at"]["N"]), item["after_run"]["S"], item["reason"]["S"])
        if self.clock() >= override.expires_at:
            self.cancel(tenant)
            return None
        return override

    def use(self, tenant: str) -> Override | None:
        """Takes the armed override for a preflight: returns it and removes it, in one conditional delete, so two
        preflights can't both use it."""
        override = self.get(tenant)
        if override is None:
            return None
        try:
            self.store.client.delete_item(TableName=self.table, Key=self.key(tenant),
                                          ConditionExpression="armed_at = :armed",
                                          ExpressionAttributeValues={":armed": {"N": str(override.armed_at)}})
        except self.store.client.exceptions.ConditionalCheckFailedException:
            return None
        return override

    def cancel(self, tenant: str) -> None:
        self.store.client.delete_item(TableName=self.table, Key=self.key(tenant))
