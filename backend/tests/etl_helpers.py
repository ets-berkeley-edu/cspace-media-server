"""Helpers for the ETL API's tests; the fixtures that use them are in conftest.py."""
import hashlib
import secrets as random
from datetime import datetime
from typing import Any

from conftest import TENANTS
from fastapi.testclient import TestClient

# Tokens are made at run time: none is written in the repository.
TOKENS = {tenant: random.token_urlsafe(32) for tenant in TENANTS}
OLD_PAHMA = random.token_urlsafe(32)
HEADER = "blob_csid\tmedia_csid\tkind\taccess\n"
ROWS = "".join(f"b{n}\tm{n}\timage\tpublic\n" for n in range(3))  # synthetic CSIDs; the format is preflight's job
FILE = (HEADER + ROWS).encode()


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def auth(tenant: str = "pahma") -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKENS[tenant]}"}


def upload_headers(body: bytes, tenant: str = "pahma", **extra: str) -> dict[str, str]:
    rows = max(body.count(b"\n") + (0 if body.endswith(b"\n") else 1) - 1, 0)
    return {**auth(tenant), "Content-Type": "text/tab-separated-values", "X-Row-Count": str(rows),
            "X-Content-SHA256": hashlib.sha256(body).hexdigest(), **extra}


def start(client: TestClient, tenant: str = "pahma") -> dict[str, Any]:
    response = client.post(f"/etl/v1/museums/{tenant}/runs", headers=auth(tenant))
    assert response.status_code in (200, 201), response.text
    body: dict[str, Any] = response.json()
    return body


def put(client: TestClient, run: dict[str, Any], body: bytes, **headers: str) -> Any:
    return client.put(run["links"]["blob_media"], content=body, headers=upload_headers(body, **headers))


def is_problem(response: Any, status: int) -> None:
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["status"] == status


