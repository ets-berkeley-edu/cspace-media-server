"""Seeds the local stack's AWS stand-in (moto) before Serena starts (design: Local development).

Creates each museum's bucket and the secrets Serena reads: an ETL token per museum and a signing key for each museum
with signed access, both random and made here at start-up, so none is written in the repository or on disk; and the
CollectionSpace simulator's synthetic account. moto keeps everything in memory, so each `./serena up` starts afresh.

Refuses to run against AWS: every endpoint must be set (a local stand-in)."""
from __future__ import annotations

import json
import logging
import secrets
import sys
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError

from fakecspace.app import USERS
from serena.config import Settings, get_settings
from serena.museum import load_all

log = logging.getLogger("devtools.seed")


def _create_secret(client: Any, secret_id: str, value: dict[str, Any]) -> bool:
    """Creates the secret; leaves one that exists as it is. True if created."""
    try:
        client.create_secret(Name=secret_id, SecretString=json.dumps(value))
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ResourceExistsException":
            return False
        raise
    return True


def seed(settings: Settings, s3: Any, secretsmanager: Any) -> dict[str, list[str]]:
    museums = load_all(settings.tenants)
    done: dict[str, list[str]] = {"buckets": [], "secrets": []}
    for bucket in sorted(settings.buckets.values()):
        try:
            s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": settings.aws_region})
            done["buckets"].append(bucket)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                raise
    login = next(iter(USERS.items()))  # the simulator's synthetic account
    for tenant in sorted(museums):
        if tenant in settings.etl_token_secret_ids and _create_secret(
                secretsmanager, settings.etl_token_secret_ids[tenant],
                {"current": secrets.token_urlsafe(32), "previous": None}):
            done["secrets"].append(settings.etl_token_secret_ids[tenant])
        if tenant in settings.cspace_secret_ids and _create_secret(
                secretsmanager, settings.cspace_secret_ids[tenant], {"username": login[0], "password": login[1]}):
            done["secrets"].append(settings.cspace_secret_ids[tenant])
        if tenant in settings.signing_key_secret_ids and _create_secret(
                secretsmanager, settings.signing_key_secret_ids[tenant],
                {"current": {"kid": f"local-{tenant}", "key": secrets.token_urlsafe(32)}, "previous": None}):
            done["secrets"].append(settings.signing_key_secret_ids[tenant])
    return done


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()
    if not (settings.s3_endpoint and settings.secretsmanager_endpoint and settings.dynamodb_endpoint):
        sys.exit("devtools.seed runs only against local stand-ins: set the S3, Secrets Manager and DynamoDB endpoints.")
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint)
    sm = boto3.client("secretsmanager", region_name=settings.aws_region, endpoint_url=settings.secretsmanager_endpoint)
    for attempt in range(30):  # moto may still be starting
        try:
            done = seed(settings, s3, sm)
            break
        except EndpointConnectionError:
            if attempt == 29:
                raise
            time.sleep(1)
    log.info("seeded %d buckets and %d secrets (names only; values are never printed)",
             len(done["buckets"]), len(done["secrets"]))


if __name__ == "__main__":
    main()
