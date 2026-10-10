"""Secrets from AWS Secrets Manager, kept for secret_cache_seconds so a rotation reaches every task without a restart.
A secret's value is never logged."""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import Any

import boto3

from .config import Settings


def secretsmanager_client(settings: Settings) -> Any:
    return boto3.client("secretsmanager", region_name=settings.aws_region,
                        endpoint_url=settings.secretsmanager_endpoint)


class SecretCache:
    def __init__(self, client: Any, ttl_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.client = client
        self.ttl = ttl_seconds
        self.clock = clock
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def get_json(self, secret_id: str) -> dict[str, Any]:
        """The secret's value, a JSON object. Raises if it can't be read or isn't a JSON object."""
        now = self.clock()
        with self._lock:
            cached = self._cache.get(secret_id)
            if cached and now - cached[0] < self.ttl:
                return cached[1]
        value = json.loads(self.client.get_secret_value(SecretId=secret_id)["SecretString"])
        if not isinstance(value, dict):
            raise ValueError("the secret isn't a JSON object")
        with self._lock:
            self._cache[secret_id] = (now, value)
        return value
