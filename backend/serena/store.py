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
        item = self.client.get_item(TableName=self.table(tables.SETTINGS), Key={"pk": {"S": tenant}}).get("Item")
        if item is None or "values" not in item:
            return {}
        values = json.loads(item["values"]["S"])
        return values if isinstance(values, dict) else {}
