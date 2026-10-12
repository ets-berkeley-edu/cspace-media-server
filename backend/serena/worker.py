"""The worker: does the steps the ETL API queues, the servable list check and the servability update (design:
Servable list check and servability update).

Run: python -m serena.worker

Every few seconds it reads each museum's newest refresh (a museum has at most one open refresh, always its newest).
A refresh in `checking` or `updating` is claimed with a conditional write that sets an owner and a heartbeat, renewed
while the step runs; a step whose heartbeat has gone stale was interrupted and is started again, so a restart never
loses a step (decided October 9, 2026, D33). Both steps are safe to repeat."""
from __future__ import annotations

import logging
import signal
import socket
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from . import servability_update as updating
from . import servable_list_check as checking
from .config import Settings
from .museum import Museum
from .museum_settings import MuseumSettings
from .overrides import Overrides
from .refreshes import OutOfOrder, Refresh, Refreshes, State
from .servable_list import read_rows
from .store import Store
from .watchdog import Watchdog

log = logging.getLogger("serena.worker")
# Transient errors: the whole servability update is tried again (it's safe to repeat) before update_failed.
UPDATE_ATTEMPTS = 3


@dataclass
class WorkerServices:
    settings: Settings
    museums: dict[str, Museum]
    museum_settings: MuseumSettings
    refreshes: Refreshes
    store: Store
    s3: Any
    watchdog: Watchdog | None = None
    overrides: Overrides | None = None  # an admin's threshold override for the next refresh (D64)


class _Heartbeat(threading.Thread):
    """Renews the claim while a step runs, even a long one."""

    def __init__(self, refreshes: Refreshes, refresh: Refresh, owner: str, every: float):
        super().__init__(daemon=True, name=f"heartbeat-{refresh.refresh_id}")
        self.refreshes, self.refresh_, self.owner, self.every = refreshes, refresh, owner, every
        self.halt = threading.Event()

    def run(self) -> None:
        while not self.halt.wait(self.every):
            try:
                self.refreshes.heartbeat(self.refresh_, self.owner)
            except Exception:
                log.warning("heartbeat failed", extra={"refresh_id": self.refresh_.refresh_id}, exc_info=True)


class Worker:
    def __init__(self, services: WorkerServices, sleep: Callable[[float], None] = time.sleep,
                 monotonic: Callable[[], float] = time.monotonic):
        self.s = services
        self.sleep = sleep
        self.monotonic = monotonic
        self.watched_at: float | None = None
        self.owner = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self.stopping = threading.Event()

    def tick(self) -> int:
        """One pass over the museums; returns how many steps were done."""
        done = 0
        for tenant in sorted(self.s.museums):
            try:
                refresh = self.s.refreshes.newest(tenant)
                if refresh is None or refresh.state not in (State.CHECKING, State.UPDATING):
                    continue
                if not self.s.refreshes.claim(refresh, self.owner, self.s.settings.worker_heartbeat_stale_seconds):
                    continue
                self._do(refresh)
                done += 1
            except Exception:
                log.exception("worker step failed", extra={"museum": tenant})
        return done

    def watch(self) -> bool:
        """Run the watchdog if its interval has passed; returns whether it ran."""
        if self.s.watchdog is None:
            return False
        now = self.monotonic()
        if self.watched_at is not None and now - self.watched_at < self.s.settings.watchdog_seconds:
            return False
        self.watched_at = now
        try:
            self.s.watchdog.check()
        except Exception:
            log.exception("watchdog pass failed")
        return True

    def run_forever(self) -> None:
        log.info("worker started", extra={"owner": self.owner})
        while not self.stopping.is_set():
            self.watch()
            if not self.tick():
                self.stopping.wait(self.s.settings.worker_poll_seconds)
        log.info("worker stopped", extra={"owner": self.owner})

    def _do(self, refresh: Refresh) -> None:
        heartbeat = _Heartbeat(self.s.refreshes, refresh, self.owner, self.s.settings.worker_heartbeat_seconds)
        heartbeat.start()
        try:
            if refresh.state == State.CHECKING:
                self._check(refresh)
            else:
                self._update(refresh)
        except OutOfOrder as error:
            log.warning("refresh changed under the worker",
                        extra={"refresh_id": refresh.refresh_id, "detail": error.detail})
        finally:
            heartbeat.halt.set()

    def _file(self, tenant: str, key: str) -> Any:
        """The stored (gzip) servable list, downloaded to a temporary file on the task's disk."""
        handle = tempfile.TemporaryFile(dir=self.s.settings.upload_dir)
        self.s.s3.download_fileobj(self.s.settings.buckets[tenant], key, handle)
        handle.seek(0)
        return handle

    def _check(self, refresh: Refresh) -> None:
        museum = self.s.museums[refresh.tenant]
        if refresh.upload is None:  # can't happen: a refresh is checking only after an upload
            self.s.refreshes.transition(refresh, State.CHECK_FAILED, reason="no servable list uploaded", release=True)
            return
        previous_refresh = self.s.refreshes.latest_updated(refresh.tenant)
        previous = None
        if previous_refresh is not None and previous_refresh.upload is not None:
            with self._file(refresh.tenant, previous_refresh.upload.key) as handle:
                previous = read_rows(handle)
        threshold = self.s.museum_settings.get(museum).delta_threshold_percent
        # An armed override is used up by this servable list check, whatever its result (D64).
        override = self.s.overrides.use(refresh.tenant) if self.s.overrides is not None and previous else None
        with self._file(refresh.tenant, refresh.upload.key) as handle:
            result = checking.check(museum, handle, previous, threshold, override=override is not None)
        to = State.READY if result.passed else State.CHECK_FAILED
        reason = None if result.passed else f"servable list check failed: {result.error_count} problem(s)"
        if override is not None:
            reason = (f"threshold overridden by an admin after {override.after_refresh}"
                      + (f"; {reason}" if reason else ""))
        self.s.refreshes.transition(refresh, to, results={"check": result.summary()}, reason=reason, release=True)
        if to == State.READY and refresh.solr_load and refresh.solr_load.get("recorded_by_admin"):
            # A servable list an admin uploaded after a failed refresh, with the load already confirmed (D66):
            # update now.
            self.s.refreshes.transition(refresh, State.SOLR_LOADED)
            self.s.refreshes.transition(refresh, State.UPDATING)
        log.info("servable list check done",
                 extra={"museum": refresh.tenant, "refresh_id": refresh.refresh_id, "result": to.value,
                        "rows": result.rows, "added": result.added, "removed": result.removed,
                        "changed": result.changed, "threshold_overridden": override is not None})

    def _update(self, refresh: Refresh) -> None:
        if refresh.upload is None:  # can't happen: a refresh is updating only after a passed check
            self.s.refreshes.transition(refresh, State.UPDATE_FAILED, reason="no servable list uploaded", release=True)
            return
        with self._file(refresh.tenant, refresh.upload.key) as handle:
            rows = read_rows(handle)
        for attempt in range(1, UPDATE_ATTEMPTS + 1):
            try:
                counts = updating.update(self.s.store, refresh.tenant, rows, self.sleep)
                break
            except (BotoCoreError, ClientError, RuntimeError) as error:
                log.warning("servability update attempt failed",
                            extra={"refresh_id": refresh.refresh_id, "attempt": attempt, "error": type(error).__name__})
                if attempt == UPDATE_ATTEMPTS:
                    self.s.refreshes.transition(refresh, State.UPDATE_FAILED, release=True,
                                                reason=f"servability update failed after {UPDATE_ATTEMPTS} attempts "
                                                       f"({type(error).__name__}); an admin can retry it")
                    return
                self.sleep(2 ** attempt)
        self.s.refreshes.transition(refresh, State.UPDATED, results={"update": vars(counts)}, release=True)
        log.info("updated", extra={"museum": refresh.tenant, "refresh_id": refresh.refresh_id, **vars(counts)})


def build_services(settings: Settings | None = None) -> WorkerServices:
    import boto3

    from . import logs, museum
    from .alerts import Alerts
    from .config import get_settings
    from .store import dynamodb_client

    settings = settings or get_settings()
    logs.configure(settings.log_level)
    store = Store(dynamodb_client(settings), settings.table_prefix)
    s3 = boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint)
    sns = boto3.client("sns", region_name=settings.aws_region, endpoint_url=settings.sns_endpoint)
    museums = museum.load_all(settings.tenants)
    museum_settings = MuseumSettings(store, settings.settings_cache_seconds)
    refreshes = Refreshes(store)
    if not settings.alert_topic_arn:
        log.warning("no alert topic: alerts are recorded and logged, not emailed")
    watchdog = Watchdog(museums, museum_settings, refreshes, Alerts(store, sns, settings.alert_topic_arn))
    return WorkerServices(settings, museums, museum_settings, refreshes, store, s3, watchdog, Overrides(store))


def main() -> None:
    worker = Worker(build_services())
    signal.signal(signal.SIGTERM, lambda *_: worker.stopping.set())
    signal.signal(signal.SIGINT, lambda *_: worker.stopping.set())
    worker.run_forever()


if __name__ == "__main__":
    main()
