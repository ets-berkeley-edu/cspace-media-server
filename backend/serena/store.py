"""Reading Serena's records in DynamoDB (design: Records)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import boto3

from . import tables
from .config import Settings


@dataclass(frozen=True)
class ServabilityRecord:
    tenant: str
    blob_csid: str
    media_csid: str | None  # None only for the museum's placeholder image
    kind: str
    access: str


@dataclass(frozen=True)
class Takedown:
    """An admin's takedown of a Media record (design: Takedowns). It exists until a servability update ends it, or an
    admin releases it (D119): there is no inactive state."""
    tenant: str
    media_csid: str
    blob_csids: tuple[str, ...] = ()  # the Blob (or Blobs, while a replaced image's old one is listed) it had
    by: str = ""
    at: str = ""  # ISO time, UTC
    reason: str = ""
    kept_by: str | None = None  # the refresh that kept it because the same Blob is still public (D119)
    kept_on: str | None = None  # that refresh's refresh date

    def item(self) -> dict[str, Any]:
        found: dict[str, Any] = {
            "pk": {"S": f"{self.tenant}#{self.media_csid}"}, "tenant": {"S": self.tenant},
            "media_csid": {"S": self.media_csid}, "blob_csids": {"L": [{"S": b} for b in self.blob_csids]},
            "by": {"S": self.by}, "at": {"S": self.at}, "reason": {"S": self.reason}}
        if self.kept_by:
            found["kept_by"] = {"S": self.kept_by}
            found["kept_on"] = {"S": self.kept_on or ""}
        return found

    @classmethod
    def of(cls, item: dict[str, Any]) -> Takedown:
        tenant, _, media = item["pk"]["S"].partition("#")
        return cls(tenant, media, tuple(b["S"] for b in item.get("blob_csids", {}).get("L", [])),
                   item.get("by", {}).get("S", ""), item.get("at", {}).get("S", ""),
                   item.get("reason", {}).get("S", ""), item.get("kept_by", {}).get("S") or None,
                   item.get("kept_on", {}).get("S") or None)


def dynamodb_client(settings: Settings) -> Any:
    return boto3.client("dynamodb", region_name=settings.aws_region, endpoint_url=settings.dynamodb_endpoint)


class Store:
    def __init__(self, client: Any, prefix: str):
        self.client = client
        self.prefix = prefix

    def table(self, table: tables.Table) -> str:
        return tables.full_name(self.prefix, table)

    def servability(self, tenant: str, blob_csid: str) -> ServabilityRecord | None:
        item = self.client.get_item(TableName=self.table(tables.SERVABILITY),
                                    Key={"pk": {"S": f"{tenant}#{blob_csid}"}}).get("Item")
        if item is None:
            return None
        media = item.get("media_csid", {}).get("S") or None
        return ServabilityRecord(tenant, blob_csid, media, item["kind"]["S"], item["access"]["S"])

    def takedown(self, tenant: str, media_csid: str) -> Takedown | None:
        # Strongly consistent: a takedown takes effect on the next request (design: Takedowns).
        item = self.client.get_item(TableName=self.table(tables.TAKEDOWNS), ConsistentRead=True,
                                    Key={"pk": {"S": f"{tenant}#{media_csid}"}}).get("Item")
        if item is None:
            return None
        return Takedown.of(item)

    def put_takedown(self, takedown: Takedown) -> bool:
        """Records a takedown, unless the Media record is already taken down. Returns False if it was."""
        try:
            self.client.put_item(TableName=self.table(tables.TAKEDOWNS), Item=takedown.item(),
                                 ConditionExpression="attribute_not_exists(pk)")
        except self.client.exceptions.ConditionalCheckFailedException:
            return False
        return True

    def takedowns(self, tenant: str) -> list[Takedown]:
        """The museum's takedowns, oldest first."""
        found: list[Takedown] = []
        start: dict[str, Any] | None = None
        while True:
            options: dict[str, Any] = {"ExclusiveStartKey": start} if start else {}
            page = self.client.query(TableName=self.table(tables.TAKEDOWNS), IndexName="by_tenant",
                                     KeyConditionExpression="tenant = :t",
                                     ExpressionAttributeValues={":t": {"S": tenant}}, **options)
            found.extend(Takedown.of(item) for item in page["Items"])
            start = page.get("LastEvaluatedKey")
            if not start:
                return sorted(found, key=lambda t: t.at)

    def keep_takedown(self, takedown: Takedown, refresh_id: str, refresh_date: str) -> None:
        """Notes the refresh that kept the takedown because the same Blob is still public (D119)."""
        try:
            self.client.update_item(
                TableName=self.table(tables.TAKEDOWNS), Key={"pk": {"S": f"{takedown.tenant}#{takedown.media_csid}"}},
                UpdateExpression="SET kept_by = :r, kept_on = :d", ConditionExpression="attribute_exists(pk)",
                ExpressionAttributeValues={":r": {"S": refresh_id}, ":d": {"S": refresh_date}})
        except self.client.exceptions.ConditionalCheckFailedException:
            pass  # released meanwhile

    def delete_takedown(self, tenant: str, media_csid: str, kept_only: bool = False) -> bool:
        """Ends a takedown. With kept_only (an admin's release), only one a refresh kept. False if there was none."""
        condition = "attribute_exists(kept_by)" if kept_only else "attribute_exists(pk)"
        try:
            self.client.delete_item(TableName=self.table(tables.TAKEDOWNS),
                                    Key={"pk": {"S": f"{tenant}#{media_csid}"}}, ConditionExpression=condition)
        except self.client.exceptions.ConditionalCheckFailedException:
            return False
        return True

    def settings_overrides(self, tenant: str) -> dict[str, Any]:
        """An admin's values for a museum's settings (stored as JSON in the item's "values" attribute)."""
        return self.settings_with_version(tenant)[0]

    def settings_with_version(self, tenant: str) -> tuple[dict[str, Any], int]:
        """An admin's values for a museum's settings, and the item's version (0 when there is none yet), for
        put_settings_overrides."""
        item = self.client.get_item(TableName=self.table(tables.SETTINGS), Key={"pk": {"S": tenant}},
                                    ConsistentRead=True).get("Item")
        if item is None or "values" not in item:
            return {}, int(item["version"]["N"]) if item and "version" in item else 0
        values = json.loads(item["values"]["S"])
        version = int(item["version"]["N"]) if "version" in item else 0
        return (values if isinstance(values, dict) else {}), version

    def put_settings_overrides(self, tenant: str, values: dict[str, Any], version: int) -> bool:
        """Replaces an admin's values for a museum's settings, only if the item is still at `version` (so two admins
        changing settings at once can't undo each other's change). Returns False if it changed meanwhile."""
        condition = "attribute_not_exists(version) OR version = :v" if version == 0 else "version = :v"
        try:
            self.client.put_item(
                TableName=self.table(tables.SETTINGS), ConditionExpression=condition,
                ExpressionAttributeValues={":v": {"N": str(version)}},
                Item={"pk": {"S": tenant}, "values": {"S": json.dumps(values, sort_keys=True)},
                      "version": {"N": str(version + 1)}})
        except self.client.exceptions.ConditionalCheckFailedException:
            return False
        return True
