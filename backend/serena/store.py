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
    media_csid: str | None  # None only for the museum's restricted-image Blob
    kind: str
    access: str


@dataclass(frozen=True)
class Takedown:
    tenant: str
    media_csid: str
    state: str  # "taken_down" or "unlocked"

    @property
    def active(self) -> bool:
        return self.state == "taken_down"


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
        return Takedown(tenant, media_csid, item["state"]["S"])

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
