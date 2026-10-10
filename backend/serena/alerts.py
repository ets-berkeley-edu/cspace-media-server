"""Alerts (design: Watchdog and alerts): recorded for the admin app's banner, logged, and emailed through the
environment's SNS topic to the team's mailing list.

Each alert has a key made from what it is about (`<night>#<kind>#<subject>`), so the watchdog can raise it on every
pass and it is recorded, logged and emailed once. An alert whose email failed is sent again on the next pass. Alerts
hold museum names, run IDs and reasons, never personal data."""
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
    MISSED_DEADLINE = "missed_deadline"  # tonight's run isn't applied or abandoned by the museum's deadline
    PREFLIGHT_FAILED = "preflight_failed"
    APPLY_FAILED = "apply_failed"
    ABANDONED = "abandoned"
    NOT_UPDATED = "not_updated"  # no night applied in 24 hours


TITLES = {
    Kind.MISSED_DEADLINE: "Tonight's run isn't finished by the deadline",
    Kind.PREFLIGHT_FAILED: "A night's preflight failed",
    Kind.APPLY_FAILED: "A night's apply failed",
    Kind.ABANDONED: "A night's run was abandoned",
    Kind.NOT_UPDATED: "Serena hasn't applied a night in 24 hours",
}


@dataclass
class Alert:
    tenant: str
    night: str
    kind: Kind
    subject: str  # the run ID, or the night
    message: str

    @property
    def sort_key(self) -> str:
        return f"{self.night}#{self.kind.value}#{self.subject}"


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
                "pk": {"S": alert.tenant}, "sk": {"S": alert.sort_key}, "night": {"S": alert.night},
                "kind": {"S": alert.kind.value}, "subject": {"S": alert.subject}, "message": {"S": alert.message},
                "created_at": {"S": now}})
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
            alert = Alert(tenant, item["night"]["S"], Kind(item["kind"]["S"]), item["subject"]["S"],
                          item["message"]["S"])
            if self._email(alert):
                sent += 1
        return sent

    def _email(self, alert: Alert) -> bool:
        if not self.topic_arn:
            return False
        subject = f"Serena: {alert.tenant}: {TITLES[alert.kind]}"
        body = (f"Museum: {alert.tenant}\nNight: {alert.night}\nAbout: {alert.subject}\n\n{alert.message}\n\n"
                "Acknowledge it in Serena's admin app.")
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
