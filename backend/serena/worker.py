"""The worker: does the steps the ETL API queues, the preflight and the apply (design: Preflight and apply).

Run: python -m serena.worker

Every few seconds it reads each museum's newest run (a museum has at most one open run, always its newest). A run in
`preflighting` or `applying` is claimed with a conditional write that sets an owner and a heartbeat, renewed while
the step runs; a step whose heartbeat has gone stale was interrupted and is started again, so a restart never loses
a step (decided October 9, 2026, D33). Both steps are safe to repeat."""
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

from . import apply as applying
from . import preflight
from .blob_media import read_rows
from .config import Settings
from .museum import Museum
from .museum_settings import MuseumSettings
from .runs import OutOfOrder, Run, Runs, State
from .store import Store
from .watchdog import Watchdog

log = logging.getLogger("serena.worker")
APPLY_ATTEMPTS = 3  # transient errors: the whole apply is tried again (it's safe to repeat) before apply_failed


@dataclass
class WorkerServices:
    settings: Settings
    museums: dict[str, Museum]
    museum_settings: MuseumSettings
    runs: Runs
    store: Store
    s3: Any
    watchdog: Watchdog | None = None


class _Heartbeat(threading.Thread):
    """Renews the claim while a step runs, even a long one."""

    def __init__(self, runs: Runs, run: Run, owner: str, every: float):
        super().__init__(daemon=True, name=f"heartbeat-{run.run_id}")
        self.runs, self.run_, self.owner, self.every = runs, run, owner, every
        self.halt = threading.Event()

    def run(self) -> None:
        while not self.halt.wait(self.every):
            try:
                self.runs.heartbeat(self.run_, self.owner)
            except Exception:
                log.warning("heartbeat failed", extra={"run_id": self.run_.run_id}, exc_info=True)


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
                run = self.s.runs.newest(tenant)
                if run is None or run.state not in (State.PREFLIGHTING, State.APPLYING):
                    continue
                if not self.s.runs.claim(run, self.owner, self.s.settings.worker_heartbeat_stale_seconds):
                    continue
                self._do(run)
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

    def _do(self, run: Run) -> None:
        heartbeat = _Heartbeat(self.s.runs, run, self.owner, self.s.settings.worker_heartbeat_seconds)
        heartbeat.start()
        try:
            if run.state == State.PREFLIGHTING:
                self._preflight(run)
            else:
                self._apply(run)
        except OutOfOrder as error:
            log.warning("run changed under the worker", extra={"run_id": run.run_id, "detail": error.detail})
        finally:
            heartbeat.halt.set()

    def _file(self, tenant: str, key: str) -> Any:
        """The stored (gzip) file, downloaded to a temporary file on the task's disk."""
        handle = tempfile.TemporaryFile(dir=self.s.settings.upload_dir)
        self.s.s3.download_fileobj(self.s.settings.buckets[tenant], key, handle)
        handle.seek(0)
        return handle

    def _preflight(self, run: Run) -> None:
        museum = self.s.museums[run.tenant]
        if run.upload is None:  # can't happen: a run is preflighting only after an upload
            self.s.runs.transition(run, State.PREFLIGHT_FAILED, reason="no file uploaded", release=True)
            return
        previous_run = self.s.runs.latest_applied(run.tenant)
        previous = None
        if previous_run is not None and previous_run.upload is not None:
            with self._file(run.tenant, previous_run.upload.key) as handle:
                previous = read_rows(handle)
        threshold = self.s.museum_settings.get(museum).change_threshold_percent
        with self._file(run.tenant, run.upload.key) as handle:
            result = preflight.check(museum, handle, previous, threshold)
        to = State.READY if result.passed else State.PREFLIGHT_FAILED
        reason = None if result.passed else f"preflight failed: {result.error_count} problem(s)"
        self.s.runs.transition(run, to, results={"preflight": result.summary()}, reason=reason, release=True)
        log.info("preflight done", extra={"museum": run.tenant, "run_id": run.run_id, "result": to.value,
                                          "rows": result.rows, "added": result.added, "removed": result.removed,
                                          "changed": result.changed})

    def _apply(self, run: Run) -> None:
        if run.upload is None:  # can't happen: a run is applying only after a passed preflight
            self.s.runs.transition(run, State.APPLY_FAILED, reason="no file uploaded", release=True)
            return
        with self._file(run.tenant, run.upload.key) as handle:
            rows = read_rows(handle)
        for attempt in range(1, APPLY_ATTEMPTS + 1):
            try:
                counts = applying.apply(self.s.store, run.tenant, rows, self.sleep)
                break
            except (BotoCoreError, ClientError, RuntimeError) as error:
                log.warning("apply attempt failed", extra={"run_id": run.run_id, "attempt": attempt,
                                                           "error": type(error).__name__})
                if attempt == APPLY_ATTEMPTS:
                    self.s.runs.transition(run, State.APPLY_FAILED, release=True,
                                           reason=f"apply failed after {APPLY_ATTEMPTS} attempts "
                                                  f"({type(error).__name__}); an admin can retry it")
                    return
                self.sleep(2 ** attempt)
        self.s.runs.transition(run, State.APPLIED, results={"apply": vars(counts)}, release=True)
        log.info("applied", extra={"museum": run.tenant, "run_id": run.run_id, **vars(counts)})


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
    runs = Runs(store)
    if not settings.alert_topic_arn:
        log.warning("no alert topic: alerts are recorded and logged, not emailed")
    watchdog = Watchdog(museums, museum_settings, runs, Alerts(store, sns, settings.alert_topic_arn))
    return WorkerServices(settings, museums, museum_settings, runs, store, s3, watchdog)


def main() -> None:
    worker = Worker(build_services())
    signal.signal(signal.SIGTERM, lambda *_: worker.stopping.set())
    signal.signal(signal.SIGINT, lambda *_: worker.stopping.set())
    worker.run_forever()


if __name__ == "__main__":
    main()
