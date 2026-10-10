"""Nightly runs and their states (design: The ETL API; The nightly sequence).

A run is one ETL night for one museum. Serena assigns its ID, <tenant>-<night>-<n>, where the night is the Pacific
date when it starts. Every state change is a conditional write on the run's current state, so two calls can't race;
a change from a state that doesn't allow it raises OutOfOrder (409).

    started -> received -> preflighting -> ready | preflight_failed
    ready -- loaded --> solr_loaded -> applying -> applied | apply_failed
    ready -- fell_back --> abandoned

A museum has at most one open run (any state but applied or abandoned), and it is always its newest."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
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
    PREFLIGHTING = "preflighting"
    READY = "ready"
    PREFLIGHT_FAILED = "preflight_failed"
    SOLR_LOADED = "solr_loaded"
    APPLYING = "applying"
    APPLIED = "applied"
    APPLY_FAILED = "apply_failed"
    ABANDONED = "abandoned"


CLOSED = frozenset({State.APPLIED, State.ABANDONED})
BUSY = frozenset({State.PREFLIGHTING, State.APPLYING})  # the worker is on it: never abandoned
# A file may be uploaded, or replaced, until the load's outcome is reported (and not while it's being preflighted).
UPLOAD_ALLOWED = frozenset({State.STARTED, State.RECEIVED, State.READY, State.PREFLIGHT_FAILED})


class OutOfOrder(Exception):
    def __init__(self, run_id: str, state: State, detail: str):
        super().__init__(detail)
        self.run_id = run_id
        self.state = state
        self.detail = detail


class Busy(OutOfOrder):
    """A later night's run can't start: the open run is being preflighted or applied (decided October 9, 2026)."""


@dataclass
class Upload:
    sha256: str
    rows: int
    bytes: int
    key: str
    uploaded_at: str


@dataclass
class Run:
    tenant: str
    night: str  # YYYY-MM-DD, Pacific
    n: int
    state: State
    created_at: str
    updated_at: str
    upload: Upload | None = None
    reasons: list[str] = field(default_factory=list)

    @property
    def run_id(self) -> str:
        return f"{self.tenant}-{self.night}-{self.n}"

    @property
    def file_name(self) -> str:
        return f"blob-media.{self.tenant}.{self.night}.tsv"

    @property
    def open(self) -> bool:
        return self.state not in CLOSED

    @property
    def sort_key(self) -> str:
        return sort_key(self.night, self.n)


def sort_key(night: str, n: int) -> str:
    return f"{night}#{n:03d}"


def parse_run_id(tenant: str, run_id: str) -> tuple[str, int] | None:
    """(night, n) from <tenant>-<YYYY-MM-DD>-<n>, or None if it isn't one of this museum's run IDs."""
    prefix = f"{tenant}-"
    if not run_id.startswith(prefix):
        return None
    rest = run_id[len(prefix):]
    night, _, n = rest.rpartition("-")
    try:
        date.fromisoformat(night)
        number = int(n)
    except ValueError:
        return None
    if not 1 <= number <= 999 or str(number) != n:
        return None
    return night, number


_serializer = TypeSerializer()
_deserializer = TypeDeserializer()


def _to_item(run: Run) -> dict[str, Any]:
    plain: dict[str, Any] = {
        "pk": run.tenant, "sk": run.sort_key, "run_id": run.run_id, "night": run.night, "n": run.n,
        "state": run.state.value, "created_at": run.created_at, "updated_at": run.updated_at, "reasons": run.reasons,
    }
    if run.upload:
        plain["upload"] = vars(run.upload)
    return {k: _serializer.serialize(v) for k, v in plain.items()}


def _from_item(item: dict[str, Any]) -> Run:
    plain = {k: _deserializer.deserialize(v) for k, v in item.items()}
    upload = plain.get("upload")
    return Run(tenant=plain["pk"], night=plain["night"], n=int(plain["n"]), state=State(plain["state"]),
               created_at=plain["created_at"], updated_at=plain["updated_at"],
               upload=Upload(upload["sha256"], int(upload["rows"]), int(upload["bytes"]), upload["key"],
                             upload["uploaded_at"]) if upload else None,
               reasons=list(plain.get("reasons", [])))


class Runs:
    def __init__(self, store: Store, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.client = store.client
        self.table = store.table(tables.RUNS)
        self.clock = clock

    def now(self) -> str:
        return self.clock().astimezone(UTC).isoformat(timespec="seconds")

    def tonight(self) -> str:
        return self.clock().astimezone(PACIFIC).date().isoformat()

    def get(self, tenant: str, run_id: str) -> Run | None:
        parsed = parse_run_id(tenant, run_id)
        if parsed is None:
            return None
        item = self.client.get_item(TableName=self.table, ConsistentRead=True,
                                    Key={"pk": {"S": tenant}, "sk": {"S": sort_key(*parsed)}}).get("Item")
        return _from_item(item) if item else None

    def newest(self, tenant: str) -> Run | None:
        items = self.client.query(TableName=self.table, KeyConditionExpression="pk = :pk", ConsistentRead=True,
                                  ExpressionAttributeValues={":pk": {"S": tenant}}, ScanIndexForward=False,
                                  Limit=1)["Items"]
        return _from_item(items[0]) if items else None

    def start(self, tenant: str) -> tuple[Run, bool]:
        """The museum's open run for tonight, or a new one. Returns (run, created). Closes an earlier night's open run
        as abandoned, unless the worker is on it (Busy)."""
        for _ in range(3):  # another call may start a run at the same moment: re-read and try again
            night = self.tonight()
            newest = self.newest(tenant)
            if newest is not None and newest.open:
                if newest.night == night:
                    return newest, False
                if newest.state in BUSY:
                    step = "preflighted" if newest.state == State.PREFLIGHTING else "applied"
                    raise Busy(newest.run_id, newest.state, f"run {newest.run_id} is still being {step}; try again")
                try:
                    self.transition(newest, State.ABANDONED, reason="a later night's run started")
                except OutOfOrder:
                    continue
            n = newest.n + 1 if newest is not None and newest.night == night else 1
            now = self.now()
            run = Run(tenant, night, n, State.STARTED, now, now)
            try:
                self.client.put_item(TableName=self.table, Item=_to_item(run),
                                     ConditionExpression="attribute_not_exists(pk)")
            except self.client.exceptions.ConditionalCheckFailedException:
                continue
            return run, True
        raise OutOfOrder(f"{tenant}-{self.tonight()}", State.STARTED,
                         "another run was starting at the same time; try again")

    def transition(self, run: Run, to: State, *, upload: Upload | None = None, reason: str | None = None) -> Run:
        """Move the run to `to`, only if it is still in the state it was read in."""
        now = self.now()
        names = {"#state": "state"}
        values: dict[str, Any] = {":to": {"S": to.value}, ":from": {"S": run.state.value}, ":now": {"S": now}}
        update = "SET #state = :to, updated_at = :now"
        if upload is not None:
            update += ", upload = :upload"
            values[":upload"] = _serializer.serialize(vars(upload))
        if reason is not None:
            update += ", reasons = list_append(if_not_exists(reasons, :empty), :reason)"
            values[":reason"] = {"L": [{"S": reason}]}
            values[":empty"] = {"L": []}
        try:
            self.client.update_item(TableName=self.table, Key={"pk": {"S": run.tenant}, "sk": {"S": run.sort_key}},
                                    UpdateExpression=update, ConditionExpression="#state = :from",
                                    ExpressionAttributeNames=names, ExpressionAttributeValues=values)
        except self.client.exceptions.ConditionalCheckFailedException as error:
            current = self.get(run.tenant, run.run_id)
            state = current.state if current else run.state
            raise OutOfOrder(run.run_id, state, f"run {run.run_id} is {state.value} now") from error
        run.state, run.updated_at = to, now
        if upload is not None:
            run.upload = upload
        if reason is not None:
            run.reasons.append(reason)
        return run
