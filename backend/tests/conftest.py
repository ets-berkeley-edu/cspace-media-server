import os
from collections.abc import Iterator
from datetime import UTC, datetime
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


@pytest.fixture
def s3(dynamodb: Any) -> Any:
    """Inside the same moto context as the tables: one bucket per museum, b-<tenant>."""
    client = boto3.client("s3", region_name="us-west-2")
    for tenant in TENANTS:
        client.create_bucket(Bucket=f"b-{tenant}", CreateBucketConfiguration={"LocationConstraint": "us-west-2"})
    return client


@pytest.fixture
def secretsmanager(dynamodb: Any) -> Any:
    return boto3.client("secretsmanager", region_name="us-west-2")


def add_blob(store: Store, tenant: str, blob: str, media: str | None, kind: str = "image",
             access: str = "public") -> None:
    """A row of the servability table, as an applied Blob-to-Media file leaves it."""
    item: dict[str, Any] = {"pk": {"S": f"{tenant}#{blob}"}, "tenant": {"S": tenant}, "blob_csid": {"S": blob},
                            "kind": {"S": kind}, "access": {"S": access}}
    if media:
        item["media_csid"] = {"S": media}
        item["media_key"] = {"S": f"{tenant}#{media}"}
    store.client.put_item(TableName=store.table(tables.SERVABILITY), Item=item)


def take_down(store: Store, tenant: str, media: str, state: str = "taken_down") -> None:
    store.client.put_item(TableName=store.table(tables.TAKEDOWNS),
                          Item={"pk": {"S": f"{tenant}#{media}"}, "state": {"S": state}})


@pytest.fixture
def clock() -> Any:
    from etl_helpers import Clock

    return Clock(datetime(2026, 10, 10, 10, 30, tzinfo=UTC))  # 03:30 Pacific, October 10


@pytest.fixture
def client(store: Store, s3: Any, secretsmanager: Any, clock: Any) -> Any:
    """The app with the ETL API: every museum has a token secret (tokens made at run time) and a bucket."""
    import json

    from etl_helpers import OLD_PAHMA, TOKENS
    from fastapi.testclient import TestClient

    from serena.app import create_app

    ids = {}
    for tenant, token in TOKENS.items():
        value = {"current": token, "previous": OLD_PAHMA if tenant == "pahma" else ""}
        ids[tenant] = secretsmanager.create_secret(Name=f"etl/{tenant}", SecretString=json.dumps(value))["ARN"]
    settings = Settings(tenants=TENANTS, table_prefix="t", buckets={t: f"b-{t}" for t in TENANTS},
                        etl_token_secret_ids=ids, upload_max_mb=1, _env_file=None)
    return TestClient(create_app(settings, store, s3=s3, secretsmanager=secretsmanager, clock=clock))
