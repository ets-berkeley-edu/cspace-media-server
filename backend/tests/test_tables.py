from typing import Any

from serena import tables


def test_create_all_makes_every_table_once(dynamodb: Any) -> None:
    names = set(dynamodb.list_tables()["TableNames"])
    assert names == {f"t-{table.name}" for table in tables.ALL}
    assert tables.create_all(dynamodb, "t") == []  # nothing left to create


def test_servability_is_indexed_by_media_csid_and_by_museum(dynamodb: Any) -> None:
    table = dynamodb.describe_table(TableName="t-servability")["Table"]
    keys = {index["IndexName"]: index["KeySchema"] for index in table["GlobalSecondaryIndexes"]}
    assert keys == {"by_media": [{"AttributeName": "media_key", "KeyType": "HASH"}],
                    "by_tenant": [{"AttributeName": "tenant", "KeyType": "HASH"}]}


def test_unserved_counts_expire(dynamodb: Any) -> None:
    ttl = dynamodb.describe_time_to_live(TableName="t-unserved")["TimeToLiveDescription"]
    assert ttl["TimeToLiveStatus"] == "ENABLED"
    assert ttl["AttributeName"] == "expires_at"
