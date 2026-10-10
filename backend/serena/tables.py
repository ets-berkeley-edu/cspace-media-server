"""Serena's DynamoDB tables (design: Records). Each is <table_prefix>-<name>, on-demand.

In AWS, Terraform creates them (with encryption by the customer-managed KMS key and point-in-time recovery);
create_all() is for local development and tests."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Table:
    name: str
    sort_key: str | None = None
    # Global secondary indexes: index name -> partition key attribute (string)
    indexes: dict[str, str] = field(default_factory=dict)
    ttl_attribute: str | None = None


# Every partition key is the string attribute "pk"; a sort key, where there is one, is "sk".
# pk <tenant>#<blob CSID>; indexed by <tenant>#<media CSID> (requests by Media CSID) and by museum (the apply)
SERVABILITY = Table("servability", indexes={"by_media": "media_key", "by_tenant": "tenant"})
TAKEDOWNS = Table("takedowns")  # pk <tenant>#<media CSID>
RUNS = Table("runs", sort_key="sk")  # pk <tenant>, sk <run ID>
SETTINGS = Table("settings")  # pk <tenant>
ALERTS = Table("alerts", sort_key="sk")  # pk <tenant>, sk <time>
UNSERVED = Table("unserved", sort_key="sk", ttl_attribute="expires_at")  # pk <tenant>#<bucket>, sk <reason>
CACHE_INDEX = Table("cache-index")  # pk <tenant>#<blob CSID>#<derivative>
AUDIT = Table("audit", sort_key="sk")  # pk <tenant>, sk <time>#<admin>#<random>
ADMIN_SESSIONS = Table("admin-sessions", ttl_attribute="expires_at")  # pk SHA-256 of the session's token

ALL = (SERVABILITY, TAKEDOWNS, RUNS, SETTINGS, ALERTS, UNSERVED, CACHE_INDEX, AUDIT, ADMIN_SESSIONS)


def full_name(prefix: str, table: Table) -> str:
    return f"{prefix}-{table.name}"


def create_all(dynamodb: Any, prefix: str) -> list[str]:
    """Create the tables that don't exist yet (a boto3 DynamoDB client). Returns the names created."""
    existing = set(dynamodb.list_tables()["TableNames"])
    created = []
    for table in ALL:
        name = full_name(prefix, table)
        if name in existing:
            continue
        keys = [{"AttributeName": "pk", "KeyType": "HASH"}]
        attributes = [{"AttributeName": "pk", "AttributeType": "S"}]
        if table.sort_key:
            keys.append({"AttributeName": table.sort_key, "KeyType": "RANGE"})
            attributes.append({"AttributeName": table.sort_key, "AttributeType": "S"})
        indexes = [
            {"IndexName": index, "KeySchema": [{"AttributeName": key, "KeyType": "HASH"}],
             "Projection": {"ProjectionType": "ALL"}}
            for index, key in table.indexes.items()
        ]
        attributes += [{"AttributeName": key, "AttributeType": "S"} for key in table.indexes.values()]
        options: dict[str, Any] = {"GlobalSecondaryIndexes": indexes} if indexes else {}
        dynamodb.create_table(TableName=name, KeySchema=keys, AttributeDefinitions=attributes,
                              BillingMode="PAY_PER_REQUEST", **options)
        dynamodb.get_waiter("table_exists").wait(TableName=name)
        if table.ttl_attribute:
            dynamodb.update_time_to_live(TableName=name, TimeToLiveSpecification={
                "Enabled": True, "AttributeName": table.ttl_attribute})
        created.append(name)
    return created
