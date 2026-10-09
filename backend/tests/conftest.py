import os
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws

from serena import tables
from serena.config import Settings
from serena.store import Store

# Synthetic: no real server is called in the tests, and moto stands in for AWS.
TENANTS = {key: f"https://{key}.cspace.test" for key in ("bampfa", "botgarden", "cinefiles", "pahma", "ucjeps")}
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")


@pytest.fixture
def settings() -> Settings:
    return Settings(tenants=TENANTS, env_label="Test", table_prefix="t", _env_file=None)


@pytest.fixture
def dynamodb() -> Iterator[Any]:
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-west-2")
        tables.create_all(client, "t")
        yield client


@pytest.fixture
def store(dynamodb: Any) -> Store:
    return Store(dynamodb, "t")


def add_blob(store: Store, tenant: str, blob: str, media: str | None, kind: str = "image",
             access: str = "public") -> None:
    """A row of the servability table, as an applied Blob-to-Media file leaves it."""
    item: dict[str, Any] = {"pk": {"S": f"{tenant}#{blob}"}, "kind": {"S": kind}, "access": {"S": access}}
    if media:
        item["media_csid"] = {"S": media}
        item["media_key"] = {"S": f"{tenant}#{media}"}
    store.client.put_item(TableName=store.table(tables.SERVABILITY), Item=item)


def take_down(store: Store, tenant: str, media: str, state: str = "taken_down") -> None:
    store.client.put_item(TableName=store.table(tables.TAKEDOWNS),
                          Item={"pk": {"S": f"{tenant}#{media}"}, "state": {"S": state}})
