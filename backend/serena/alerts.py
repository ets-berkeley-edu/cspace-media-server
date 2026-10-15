"""Alerts (design: Watchdog and alerts): recorded for the admin app's banner, logged, and emailed through the
environment's SNS topic to the team's mailing list.

Each alert has a key made from what it is about (`<refresh date>#<kind>#<subject>`), so the watchdog can raise it on
every pass and it is recorded, logged and emailed once. An alert whose email failed is sent again on the next pass.
Alerts hold museum names, refresh IDs and reasons, never personal data."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from . import tables
from .store import Store

log = logging.getLogger("serena.alerts")


class Kind(StrEnum):
    MISSED_DEADLINE = "missed_deadline"  # today's refresh isn't updated or abandoned by the museum's deadline
    CHECK_FAILED = "check_failed"
    UPDATE_FAILED = "update_failed"
    ABANDONED = "abandoned"
    NOT_UPDATED = "not_updated"  # no servability update in 24 hours
    THRESHOLD_OVERRIDDEN = "threshold_overridden"  # an admin overrode the delta threshold for a refresh (D62, D83)
    SETTING_CHANGED = "setting_changed"  # an admin changed the delta threshold or the audit retention (D89, D97)
    RECALL = "recall"  # an admin recalled Media records (D118)
    STILL_PUBLIC = "recall_still_public"  # a refresh kept a recall: the same Blob is still public (D119)
    RECALL_RELEASED = "recall_released"  # an admin released a recall a refresh kept (D119)
    RECALL_CANCELLED = "recall_cancelled"  # an admin cancelled a recall still waiting for a later refresh (D148)
    RECALLS_ENDED = "recalls_ended"  # a refresh ended recalls: CollectionSpace caught up (D119)


TITLES = {
    Kind.MISSED_DEADLINE: "Today's refresh isn't finished by the deadline",
    Kind.CHECK_FAILED: "A servable list check failed",
    Kind.UPDATE_FAILED: "A servability update failed",
    Kind.ABANDONED: "A refresh was abandoned",
    Kind.NOT_UPDATED: "Serena hasn't had a servability update in 24 hours",
    Kind.THRESHOLD_OVERRIDDEN: "An admin overrode the delta threshold",
    Kind.SETTING_CHANGED: "An admin changed a setting",
    Kind.RECALL: "An admin recalled Media records",
    Kind.STILL_PUBLIC: "Recalled in Serena, but still public in CollectionSpace",
    Kind.RECALL_RELEASED: "An admin released a recall",
    Kind.RECALL_CANCELLED: "An admin cancelled a recall",
    Kind.RECALLS_ENDED: "A refresh ended recalls",
}


@dataclass
class Alert:
    tenant: str
    refresh_date: str
    kind: Kind
    subject: str  # the refresh ID, the refresh date, a Media CSID or "<n> Media records" (a recall)
    message: str
    instance: str = ""  # for an alert raised for each event, not once per subject: an admin's override each time

    @property
    def sort_key(self) -> str:
        key = f"{self.refresh_date}#{self.kind.value}#{self.subject}"
        return f"{key}#{self.instance}" if self.instance else key


class Alerts:
    def __init__(self, store: Store, sns: Any, topic_arn: str,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.client = store.client
        self.table = store.table(tables.ALERTS)
        self.sns = sns
        self.topic_arn = topic_arn
        self.clock = clock

    def raise_(self, alert: Alert) -> bool:
        """Record, log and email the alert, once. Returns True the first time."""
        now = self.clock().astimezone(UTC).isoformat(timespec="seconds")
        try:
            self.client.put_item(TableName=self.table, ConditionExpression="attribute_not_exists(pk)", Item={
                "pk": {"S": alert.tenant}, "sk": {"S": alert.sort_key}, "refresh_date": {"S": alert.refresh_date},
                "kind": {"S": alert.kind.value}, "subject": {"S": alert.subject}, "message": {"S": alert.message},
                "created_at": {"S": now}, **({"instance": {"S": alert.instance}} if alert.instance else {})})
        except self.client.exceptions.ConditionalCheckFailedException:
            return False
        log.warning("alert", extra={"museum": alert.tenant, "kind": alert.kind.value, "subject": alert.subject,
                                    "alert": alert.message})
        self._email(alert)
        return True

    def resend_unsent(self, tenant: str) -> int:
        """Email the museum's recorded alerts whose email hasn't gone out (SNS was unavailable)."""
        sent = 0
        items = self.client.query(TableName=self.table, KeyConditionExpression="pk = :t",
                                  FilterExpression="attribute_not_exists(emailed_at)",
                                  ExpressionAttributeValues={":t": {"S": tenant}})["Items"]
        for item in items:
            alert = Alert(tenant, item["refresh_date"]["S"], Kind(item["kind"]["S"]), item["subject"]["S"],
                          item["message"]["S"], item.get("instance", {}).get("S", ""))
            if self._email(alert):
                sent += 1
        return sent

    def recent(self, tenant: str, since_date: str) -> list[dict[str, Any]]:
        """The museum's alerts from `since_date` on, newest first, for the admin app (design: decided October 10,
        2026, D67)."""
        items: list[dict[str, Any]] = []
        start: dict[str, Any] | None = None
        while True:
            options: dict[str, Any] = {"ExclusiveStartKey": start} if start else {}
            page = self.client.query(TableName=self.table, KeyConditionExpression="pk = :t AND sk >= :since",
                                     ExpressionAttributeValues={":t": {"S": tenant}, ":since": {"S": since_date}},
                                     ScanIndexForward=False, **options)
            for item in page["Items"]:
                items.append({"key": item["sk"]["S"], "refresh_date": item["refresh_date"]["S"],
                              "kind": item["kind"]["S"],
                              "title": TITLES.get(Kind(item["kind"]["S"]), item["kind"]["S"]),
                              "subject": item["subject"]["S"], "message": item["message"]["S"],
                              "created_at": item["created_at"]["S"],
                              "acknowledged_by": item.get("acknowledged_by", {}).get("S"),
                              "acknowledged_at": item.get("acknowledged_at", {}).get("S")})
            start = page.get("LastEvaluatedKey")
            if not start:
                return items

    def acknowledge(self, tenant: str, key: str, admin: str) -> bool:
        """Marks the alert acknowledged by the admin. False if there's no such alert or it was already acknowledged."""
        try:
            self.client.update_item(
                TableName=self.table, Key={"pk": {"S": tenant}, "sk": {"S": key}},
                UpdateExpression="SET acknowledged_by = :admin, acknowledged_at = :now",
                ConditionExpression="attribute_exists(pk) AND attribute_not_exists(acknowledged_at)",
                ExpressionAttributeValues={":admin": {"S": admin}, ":now": {
                    "S": self.clock().astimezone(UTC).isoformat(timespec="seconds")}})
        except self.client.exceptions.ConditionalCheckFailedException:
            return False
        return True

    def _email(self, alert: Alert) -> bool:
        if not self.topic_arn:
            return False
        subject = f"Serena: {alert.tenant}: {TITLES[alert.kind]}"
        body = (f"Museum: {alert.tenant}\nRefresh date: {alert.refresh_date}\nAbout: {alert.subject}\n\n"
                f"{alert.message}\n\nAcknowledge it in Serena's admin app.")
        try:
            self.sns.publish(TopicArn=self.topic_arn, Subject=subject[:100], Message=body)
        except Exception as error:
            log.warning("could not email an alert; it will be sent again",
                        extra={"museum": alert.tenant, "kind": alert.kind.value, "error": type(error).__name__})
            return False
        self.client.update_item(TableName=self.table, Key={"pk": {"S": alert.tenant}, "sk": {"S": alert.sort_key}},
                                UpdateExpression="SET emailed_at = :now", ExpressionAttributeValues={
                                    ":now": {"S": self.clock().astimezone(UTC).isoformat(timespec="seconds")}})
        return True
