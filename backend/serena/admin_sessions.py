"""The admin app's sessions (design: Admin web app, Sign-in; decided October 10, 2026).

One session per admin and museum. The browser holds a random token in an HttpOnly, Secure, SameSite=Strict cookie;
the session record is keyed by the token's SHA-256, so the table never holds a token that would work. A session ends
after 30 minutes without activity or 8 hours at most, at sign-out, or when an admin signs everyone out of a museum.
Records expire from the table by TTL. No password is ever stored: the role is checked at sign-in."""
from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import tables
from .store import Store

TOUCH_EVERY_SECONDS = 60  # activity is written at most once a minute, so a page's requests don't each write


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Session:
    tenant: str
    user: str  # the admin's CollectionSpace username
    started_at: float
    last_seen: float


class Sessions:
    def __init__(self, store: Store, idle_minutes: float = 30, max_hours: float = 8,
                 clock: Callable[[], float] = time.time):
        self.store = store
        self.idle = idle_minutes * 60
        self.max_age = max_hours * 3600
        self.clock = clock

    @property
    def table(self) -> str:
        return self.store.table(tables.ADMIN_SESSIONS)

    def start(self, tenant: str, user: str) -> str:
        """A new session's token, for the cookie. The token itself isn't stored."""
        token = secrets.token_urlsafe(32)
        now = self.clock()
        self.store.client.put_item(TableName=self.table, Item={
            "pk": {"S": token_hash(token)}, "tenant": {"S": tenant}, "user": {"S": user},
            "started_at": {"N": str(now)}, "last_seen": {"N": str(now)},
            "expires_at": {"N": str(int(now + self.max_age))}})
        return token

    def get(self, tenant: str, token: str) -> Session | None:
        """The live session for this museum and token, or None (and an ended one is deleted)."""
        key = {"pk": {"S": token_hash(token)}}
        item = self.store.client.get_item(TableName=self.table, Key=key, ConsistentRead=True).get("Item")
        if item is None or item["tenant"]["S"] != tenant:
            return None
        now = self.clock()
        started, last = float(item["started_at"]["N"]), float(item["last_seen"]["N"])
        if now - started > self.max_age or now - last > self.idle:
            self.store.client.delete_item(TableName=self.table, Key=key)
            return None
        if now - last >= TOUCH_EVERY_SECONDS:
            self.store.client.update_item(TableName=self.table, Key=key, UpdateExpression="SET last_seen = :now",
                                          ExpressionAttributeValues={":now": {"N": str(now)}})
            last = now
        return Session(tenant, item["user"]["S"], started, last)

    def end(self, token: str) -> None:
        self.store.client.delete_item(TableName=self.table, Key={"pk": {"S": token_hash(token)}})

    def end_all(self, tenant: str) -> int:
        """Ends every session for the museum; returns how many. The table is small, so a scan is enough."""
        ended = 0
        paginator = self.store.client.get_paginator("scan")
        pages: Any = paginator.paginate(TableName=self.table, FilterExpression="tenant = :t",
                                        ExpressionAttributeValues={":t": {"S": tenant}}, ProjectionExpression="pk")
        for page in pages:
            for item in page.get("Items", []):
                self.store.client.delete_item(TableName=self.table, Key={"pk": item["pk"]})
                ended += 1
        return ended
