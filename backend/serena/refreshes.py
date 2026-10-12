"""Refreshes and their states (design: The ETL API; The daily sequence).

A refresh brings Serena up to date for one museum on one refresh date. Serena assigns its ID,
<tenant>-<refresh date>-<n>, where the refresh date is the Pacific date when it starts. Every state change is a
conditional write on the refresh's current state, so two calls can't race; a change from a state that doesn't allow it
raises OutOfOrder (409).

    started -> received -> checking -> check_failed
                                     -> updating -> updated | update_failed

A passed servable list check goes straight on to the servability update (decided October 12, 2026, D80). An open
refresh is closed as abandoned when a later refresh date's refresh starts, or when an admin starts an admin refresh
(D82). A museum has at most one open refresh (any state but updated or abandoned), and it is always its newest."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

from . import tables
from .store import Store

PACIFIC = ZoneInfo("America/Los_Angeles")


class State(StrEnum):
    STARTED = "started"
    RECEIVED = "received"
    CHECKING = "checking"
    CHECK_FAILED = "check_failed"
    UPDATING = "updating"
    UPDATED = "updated"
    UPDATE_FAILED = "update_failed"
    ABANDONED = "abandoned"


CLOSED = frozenset({State.UPDATED, State.ABANDONED})
BUSY = frozenset({State.CHECKING, State.UPDATING})  # the worker is on it: never abandoned
# A servable list may be uploaded, or replaced by a corrected one, except while the worker is on the refresh or once
# it is closed.
UPLOAD_ALLOWED = frozenset({State.STARTED, State.RECEIVED, State.CHECK_FAILED, State.UPDATE_FAILED})


class OutOfOrder(Exception):
    def __init__(self, refresh_id: str, state: State, detail: str):
        super().__init__(detail)
        self.refresh_id = refresh_id
        self.state = state
        self.detail = detail


class Busy(OutOfOrder):
    """A later refresh date's refresh can't start: the open refresh is being checked or updated (decided October 9,
    2026)."""


@dataclass
class Upload:
    sha256: str
    rows: int
    bytes: int
    key: str
    uploaded_at: str


@dataclass
class Refresh:
    tenant: str
    refresh_date: str  # YYYY-MM-DD, Pacific
    n: int
    state: State
    created_at: str
    updated_at: str
    upload: Upload | None = None
    reasons: list[str] = field(default_factory=list)
    check: dict[str, Any] | None = None  # the servable list check's result
    update: dict[str, Any] | None = None  # the servability update's counts
    override: dict[str, Any] | None = None  # an admin's override of the delta threshold for this list (D83)
    admin_refresh: dict[str, Any] | None = None  # an admin refresh: the refresh date its list is for (D75)
    owner: str | None = None  # the worker doing this refresh's step
    heartbeat_at: int | None = None  # when that worker last said it was still on it (Unix seconds)

    @property
    def refresh_id(self) -> str:
        return f"{self.tenant}-{self.refresh_date}-{self.n}"

    @property
    def file_name(self) -> str:
        return f"servable-list.{self.tenant}.{self.refresh_date}.tsv"

    @property
    def open(self) -> bool:
        return self.state not in CLOSED

    @property
    def sort_key(self) -> str:
        return sort_key(self.refresh_date, self.n)


def sort_key(refresh_date: str, n: int) -> str:
    return f"{refresh_date}#{n:03d}"


def parse_refresh_id(tenant: str, refresh_id: str) -> tuple[str, int] | None:
    """(refresh date, n) from <tenant>-<YYYY-MM-DD>-<n>, or None if it isn't one of this museum's refresh IDs."""
    prefix = f"{tenant}-"
    if not refresh_id.startswith(prefix):
        return None
    rest = refresh_id[len(prefix):]
    refresh_date, _, n = rest.rpartition("-")
    try:
        date.fromisoformat(refresh_date)
        number = int(n)
    except ValueError:
        return None
    if not 1 <= number <= 999 or str(number) != n:
        return None
    return refresh_date, number


RESULTS = ("check", "update", "override", "admin_refresh")
_serializer = TypeSerializer()
_deserializer = TypeDeserializer()


def _to_item(refresh: Refresh) -> dict[str, Any]:
    plain: dict[str, Any] = {
        "pk": refresh.tenant, "sk": refresh.sort_key, "refresh_id": refresh.refresh_id,
        "refresh_date": refresh.refresh_date, "n": refresh.n, "state": refresh.state.value,
        "created_at": refresh.created_at, "updated_at": refresh.updated_at, "reasons": refresh.reasons,
    }
    if refresh.upload:
        plain["upload"] = vars(refresh.upload)
    for name in RESULTS:
        if getattr(refresh, name) is not None:
            plain[name] = getattr(refresh, name)
    return {k: _serializer.serialize(_decimals(v)) for k, v in plain.items()}


def _decimals(value: Any) -> Any:
    """DynamoDB stores numbers as Decimal: floats are converted, recursively."""


    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _decimals(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decimals(v) for v in value]
    return value


def _plain(value: Any) -> Any:
    """Decimals back to int or float, recursively."""


    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _from_item(item: dict[str, Any]) -> Refresh:
    plain = {k: _deserializer.deserialize(v) for k, v in item.items()}
    upload = plain.get("upload")
    return Refresh(tenant=plain["pk"], refresh_date=plain["refresh_date"], n=int(plain["n"]),
                   state=State(plain["state"]), created_at=plain["created_at"], updated_at=plain["updated_at"],
                   upload=Upload(upload["sha256"], int(upload["rows"]), int(upload["bytes"]), upload["key"],
                                 upload["uploaded_at"]) if upload else None,
                   reasons=list(plain.get("reasons", [])),
                   check=_plain(plain.get("check")), update=_plain(plain.get("update")),
                   override=_plain(plain.get("override")), admin_refresh=_plain(plain.get("admin_refresh")),
                   owner=plain.get("owner"),
                   heartbeat_at=int(plain["heartbeat_at"]) if "heartbeat_at" in plain else None)


class Refreshes:
    def __init__(self, store: Store, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.client = store.client
        self.table = store.table(tables.REFRESHES)
        self.clock = clock

    def now(self) -> str:
        return self.clock().astimezone(UTC).isoformat(timespec="seconds")

    def today(self) -> str:
        return self.clock().astimezone(PACIFIC).date().isoformat()

    def get(self, tenant: str, refresh_id: str) -> Refresh | None:
        parsed = parse_refresh_id(tenant, refresh_id)
        if parsed is None:
            return None
        item = self.client.get_item(TableName=self.table, ConsistentRead=True,
                                    Key={"pk": {"S": tenant}, "sk": {"S": sort_key(*parsed)}}).get("Item")
        return _from_item(item) if item else None

    def newest(self, tenant: str) -> Refresh | None:
        items = self.client.query(TableName=self.table, KeyConditionExpression="pk = :pk", ConsistentRead=True,
                                  ExpressionAttributeValues={":pk": {"S": tenant}}, ScanIndexForward=False,
                                  Limit=1)["Items"]
        return _from_item(items[0]) if items else None

    def recent(self, tenant: str, limit: int) -> list[Refresh]:
        """The museum's newest refreshes, newest first (the admin app's Refreshes page)."""
        items = self.client.query(TableName=self.table, KeyConditionExpression="pk = :pk", ScanIndexForward=False,
                                  ExpressionAttributeValues={":pk": {"S": tenant}}, Limit=limit)["Items"]
        return [_from_item(item) for item in items]

    def start(self, tenant: str, closing_reason: str | None = None) -> tuple[Refresh, bool]:
        """The museum's open refresh for today's refresh date, or a new one. Returns (refresh, created). Closes an
        earlier refresh date's open refresh as abandoned, unless the worker is on it (Busy). With `closing_reason` (an
        admin refresh, D82), any open refresh is closed that way, today's included, and a new one always starts."""
        for _ in range(3):  # another call may start a refresh at the same moment: re-read and try again
            refresh_date = self.today()
            newest = self.newest(tenant)
            if newest is not None and newest.open:
                if newest.refresh_date == refresh_date and closing_reason is None:
                    return newest, False
                if newest.state in BUSY:
                    step = "checked" if newest.state == State.CHECKING else "updated"
                    raise Busy(newest.refresh_id, newest.state,
                               f"refresh {newest.refresh_id} is still being {step}; try again")
                try:
                    self.transition(newest, State.ABANDONED,
                                    reason=closing_reason or "a later refresh date's refresh started")
                except OutOfOrder:
                    continue
            n = newest.n + 1 if newest is not None and newest.refresh_date == refresh_date else 1
            now = self.now()
            refresh = Refresh(tenant, refresh_date, n, State.STARTED, now, now)
            try:
                self.client.put_item(TableName=self.table, Item=_to_item(refresh),
                                     ConditionExpression="attribute_not_exists(pk)")
            except self.client.exceptions.ConditionalCheckFailedException:
                continue
            return refresh, True
        raise OutOfOrder(f"{tenant}-{self.today()}", State.STARTED,
                         "another refresh was starting at the same time; try again")

    def transition(self, refresh: Refresh, to: State, *, upload: Upload | None = None, reason: str | None = None,
                   results: dict[str, dict[str, Any]] | None = None, release: bool = False) -> Refresh:
        """Move the refresh to `to`, only if it is still in the state it was read in. `results` sets check, update,
        override or admin_refresh; a new upload removes an earlier override, which was for the earlier list.
        `release` ends the worker's claim."""
        now = self.now()
        names = {"#state": "state"}
        values: dict[str, Any] = {":to": {"S": to.value}, ":from": {"S": refresh.state.value}, ":now": {"S": now}}
        update = "SET #state = :to, updated_at = :now"
        if upload is not None:
            update += ", upload = :upload"
            values[":upload"] = _serializer.serialize(vars(upload))
        for name, result in (results or {}).items():
            names[f"#{name}"] = name
            update += f", #{name} = :{name}"
            values[f":{name}"] = _serializer.serialize(_decimals(result))
        if reason is not None:
            update += ", reasons = list_append(if_not_exists(reasons, :empty), :reason)"
            values[":reason"] = {"L": [{"S": reason}]}
            values[":empty"] = {"L": []}
        removing = []
        if upload is not None and "override" not in (results or {}):
            removing.append("#override")
            names["#override"] = "override"
        if release:
            removing += ["#owner", "heartbeat_at"]
            names["#owner"] = "owner"
        if removing:
            update += " REMOVE " + ", ".join(removing)
        try:
            self.client.update_item(TableName=self.table,
                                    Key={"pk": {"S": refresh.tenant}, "sk": {"S": refresh.sort_key}},
                                    UpdateExpression=update, ConditionExpression="#state = :from",
                                    ExpressionAttributeNames=names, ExpressionAttributeValues=values)
        except self.client.exceptions.ConditionalCheckFailedException as error:
            current = self.get(refresh.tenant, refresh.refresh_id)
            state = current.state if current else refresh.state
            raise OutOfOrder(refresh.refresh_id, state, f"refresh {refresh.refresh_id} is {state.value} now") from error
        refresh.state, refresh.updated_at = to, now
        if upload is not None:
            refresh.upload = upload
            if "override" not in (results or {}):
                refresh.override = None
        if reason is not None:
            refresh.reasons.append(reason)
        for name, result in (results or {}).items():
            setattr(refresh, name, result)
        if release:
            refresh.owner, refresh.heartbeat_at = None, None
        return refresh

    # The worker's claim on a refresh's step (decided October 9, 2026, D33): a conditional write sets the owner and a
    # heartbeat; a step whose heartbeat is older than `stale_seconds` was interrupted and may be claimed again.

    def claim(self, refresh: Refresh, owner: str, stale_seconds: float) -> bool:
        now = int(self.clock().timestamp())
        try:
            self.client.update_item(
                TableName=self.table, Key={"pk": {"S": refresh.tenant}, "sk": {"S": refresh.sort_key}},
                UpdateExpression="SET #owner = :owner, heartbeat_at = :now",
                ConditionExpression="#state = :state AND (attribute_not_exists(#owner) OR heartbeat_at < :stale)",
                ExpressionAttributeNames={"#owner": "owner", "#state": "state"},
                ExpressionAttributeValues={":owner": {"S": owner}, ":now": {"N": str(now)},
                                           ":state": {"S": refresh.state.value},
                                           ":stale": {"N": str(int(now - stale_seconds))}})
        except self.client.exceptions.ConditionalCheckFailedException:
            return False
        refresh.owner, refresh.heartbeat_at = owner, now
        return True

    def heartbeat(self, refresh: Refresh, owner: str) -> bool:
        now = int(self.clock().timestamp())
        try:
            self.client.update_item(
                TableName=self.table, Key={"pk": {"S": refresh.tenant}, "sk": {"S": refresh.sort_key}},
                UpdateExpression="SET heartbeat_at = :now", ConditionExpression="#owner = :owner",
                ExpressionAttributeNames={"#owner": "owner"},
                ExpressionAttributeValues={":owner": {"S": owner}, ":now": {"N": str(now)}})
        except self.client.exceptions.ConditionalCheckFailedException:
            return False
        return True

    def latest_updated(self, tenant: str) -> Refresh | None:
        """The museum's most recent updated refresh."""
        start: dict[str, Any] | None = None
        while True:
            options: dict[str, Any] = {"ExclusiveStartKey": start} if start else {}
            page = self.client.query(TableName=self.table, KeyConditionExpression="pk = :pk", ScanIndexForward=False,
                                     FilterExpression="#state = :updated", ConsistentRead=True,
                                     ExpressionAttributeNames={"#state": "state"},
                                     ExpressionAttributeValues={":pk": {"S": tenant}, ":updated": {"S": "updated"}},
                                     **options)
            if page["Items"]:
                return _from_item(page["Items"][0])
            start = page.get("LastEvaluatedKey")
            if not start:
                return None
