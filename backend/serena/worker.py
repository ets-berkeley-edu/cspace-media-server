"""The worker: does the steps the ETL API queues, the servable list check and the servability update (design:
Servable list check and servability update).

Run: python -m serena.worker

Every few seconds it reads each museum's newest refresh (a museum has at most one open refresh, always its newest).
A refresh in `checking` or `updating` is claimed with a conditional write that sets an owner and a heartbeat, renewed
while the step runs; a step whose heartbeat has gone stale was interrupted and is started again, so a restart never
loses a step (decided October 9, 2026, D33). Both steps are safe to repeat. A passed check goes straight on to the
servability update, under the same claim (decided October 12, 2026, D80), and a successful servability update
ends the recalls CollectionSpace has caught up with (D119). Once a day it also removes audit entries older than each
museum's audit retention (D98), and counts each museum's requests of the day before (issue #96)."""
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
from datetime import UTC, datetime, timedelta
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from . import recalls
from . import servability_update as updating
from . import servable_list_check as checking
from .audit import Action, Audit
from .config import Settings
from .museum import Museum
from .museum_settings import MuseumSettings
from .refreshes import PACIFIC, OutOfOrder, Refresh, Refreshes, State
from .request_counts import RequestCounts, latest_countable
from .servable_list import read_rows
from .store import Store
from .watchdog import Watchdog

log = logging.getLogger("serena.worker")
# Transient errors: the whole servability update is tried again (it's safe to repeat) before update_failed.
UPDATE_ATTEMPTS = 3
# A daily request count that failed for a museum is tried again after this long.
COUNT_RETRY_SECONDS = 3600.0
# Counting a month of one museum's log is two queries; they can take longer than the Past requests page waits.
COUNT_WAIT_SECONDS = 300.0


@dataclass
class WorkerServices:
    settings: Settings
    museums: dict[str, Museum]
    museum_settings: MuseumSettings
    refreshes: Refreshes
    store: Store
    s3: Any
    watchdog: Watchdog | None = None
    counts: RequestCounts | None = None  # None: no log to count from here


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
        self.purged_on: str | None = None  # the Pacific date of the last removal of old audit entries
        self.counted_through: str | None = None  # the latest UTC day every museum's requests are counted for
        self.count_tried_at: float | None = None
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

    def purge_audit(self, now: datetime | None = None) -> int:
        """Once a Pacific day, removes each museum's audit entries older than its audit retention (D98), by the
        setting in force now. Returns how many were removed."""
        now = now or datetime.now(UTC)
        today = now.astimezone(PACIFIC).date().isoformat()
        if self.purged_on == today:
            return 0
        self.purged_on = today
        audit = Audit(self.s.store)
        removed = 0
        for key, museum in sorted(self.s.museums.items()):
            try:
                days = self.s.museum_settings.get(museum).audit_retention_days
                count = audit.purge(key, now - timedelta(days=days))
            except Exception:
                log.exception("old audit entries not removed", extra={"museum": key})
                continue
            if count:
                log.info("old audit entries removed", extra={"museum": key, "removed": count, "days": days})
            removed += count
        return removed

    def count_requests(self, now: datetime | None = None) -> int:
        """Each museum's daily request counts (issue #96): once the day before is over and settled, counts every day
        still in the log that isn't counted yet; a museum that fails is tried again after COUNT_RETRY_SECONDS.
        Returns how many days were stored."""
        if self.s.counts is None:
            return 0
        latest = latest_countable(now or datetime.now(UTC)).isoformat()
        if self.counted_through == latest:
            return 0
        if self.count_tried_at is not None and self.monotonic() - self.count_tried_at < COUNT_RETRY_SECONDS:
            return 0
        self.count_tried_at = self.monotonic()
        stored, failed = 0, False
        for key in sorted(self.s.museums):
            try:
                stored += len(self.s.counts.count_missing(key))
            except Exception:
                log.exception("requests not counted", extra={"museum": key})
                failed = True
        if not failed:
            self.counted_through = latest
        return stored

    def run_forever(self) -> None:
        log.info("worker started", extra={"owner": self.owner})
        while not self.stopping.is_set():
            self.watch()
            self.purge_audit()
            self.count_requests()
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
            self._audit_outcome(refresh)
        except OutOfOrder as error:
            log.warning("refresh changed under the worker",
                        extra={"refresh_id": refresh.refresh_id, "detail": error.detail})
        finally:
            heartbeat.halt.set()

    def _audit_outcome(self, refresh: Refresh) -> None:
        """A refresh's outcome in the audit log, by the refresh, next to the ETL's calls (D150): updated,
        check_failed or update_failed. A passed check goes straight on to the update, so it isn't an outcome."""
        try:
            now = self.s.refreshes.get(refresh.tenant, refresh.refresh_id)
            if now is not None and now.state in (State.UPDATED, State.CHECK_FAILED, State.UPDATE_FAILED):
                Audit(self.s.store).record(refresh.tenant, f"refresh {now.refresh_id}", Action.REFRESH_OUTCOME,
                                           now.refresh_id, {"state": now.state.value, "reasons": now.reasons[-1:]})
        except Exception:
            log.exception("refresh outcome not audited", extra={"refresh_id": refresh.refresh_id})

    def _alert(self, refresh: Refresh) -> None:
        """A failed step's alert, raised at once (design: The daily sequence); the watchdog raises it again later if
        this fails."""
        if self.s.watchdog is None:
            return
        try:
            self.s.watchdog.raise_failure(refresh)
        except Exception:
            log.exception("alert for a failed step not raised", extra={"refresh_id": refresh.refresh_id})

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
        # An admin's override of the delta threshold for this refresh's servable list (D83).
        overridden = refresh.override is not None
        with self._file(refresh.tenant, refresh.upload.key) as handle:
            result = checking.check(museum, handle, previous, threshold, override=overridden)
        log.info("servable list check done",
                 extra={"museum": refresh.tenant, "refresh_id": refresh.refresh_id,
                        "result": "passed" if result.passed else "failed", "rows": result.rows,
                        "added": result.added, "removed": result.removed, "changed": result.changed,
                        "threshold_overridden": overridden})
        if not result.passed:
            self.s.refreshes.transition(refresh, State.CHECK_FAILED, results={"check": result.summary()},
                                        reason=f"{result.error_count} problem{'' if result.error_count == 1 else 's'}"
                                               " in the servable list",
                                        release=True)
            self._alert(refresh)
            return
        # Passed: the servability update follows at once, under the same claim (D80).
        self.s.refreshes.transition(refresh, State.UPDATING, results={"check": result.summary()})
        self._update(refresh)

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
                    self._alert(refresh)
                    return
                self.sleep(2 ** attempt)
        results = {**vars(counts), **self._end_recalls(refresh)}
        self.s.refreshes.transition(refresh, State.UPDATED, results={"update": results}, release=True)
        log.info("updated", extra={"museum": refresh.tenant, "refresh_id": refresh.refresh_id, **results})

    def _end_recalls(self, refresh: Refresh) -> dict[str, int]:
        """After a successful servability update, the ends the recalls CollectionSpace has caught up with end (D119). A
        failure here leaves every recall in place, which is safe; the next refresh looks again."""
        try:
            alerts = self.s.watchdog.alerts if self.s.watchdog is not None else None
            ended = recalls.after_update(self.s.museums[refresh.tenant], refresh.refresh_id, refresh.refresh_date,
                                           self.s.store, Audit(self.s.store), alerts)
        except Exception:
            log.exception("recalls not looked at after the servability update",
                          extra={"refresh_id": refresh.refresh_id})
            return {}
        return {"recalls_ended": ended.ended, "recalls_kept": ended.kept}


def build_services(settings: Settings | None = None) -> WorkerServices:
    import boto3

    from . import logs, museum, requests_log
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
    watchdog = Watchdog(museums, museum_settings, refreshes, Alerts(store, sns, settings.alert_topic_arn),
                        store=store)
    # The daily request counts read the app's log group (issue #96); locally, the web container's log file isn't
    # the worker's, so there's nothing to count.
    reader: requests_log.Reader | None = None
    if settings.log_group:
        reader = requests_log.CloudWatchReader(boto3.client("logs", region_name=settings.aws_region),
                                               settings.log_group, wait_seconds=COUNT_WAIT_SECONDS)
    elif settings.log_file:
        reader = requests_log.FileReader(settings.log_file)
    if reader is None:
        log.warning("no request log: requests aren't counted")
    counts = RequestCounts(store, reader, settings.log_retention_days) if reader is not None else None
    return WorkerServices(settings, museums, museum_settings, refreshes, store, s3, watchdog, counts)


def main() -> None:
    worker = Worker(build_services())
    signal.signal(signal.SIGTERM, lambda *_: worker.stopping.set())
    signal.signal(signal.SIGINT, lambda *_: worker.stopping.set())
    worker.run_forever()


if __name__ == "__main__":
    main()
