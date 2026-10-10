"""The watchdog (design: Watchdog and alerts): runs in the worker every few minutes, in Pacific time (daylight
saving included), and raises an alert when, for a museum:

- tonight's run hasn't reached applied or abandoned by the museum's deadline (08:00 to start, an admin's setting),
  including when no run started at all. This is how Serena notices a partial night;
- its newest run is preflight_failed, apply_failed or abandoned;
- it hasn't applied a night in 24 hours. Only for a museum that has applied one: before its first night, a museum
  has nothing to be late with.

Every alert is raised on every pass while it holds and recorded once (see alerts.py)."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta

from .alerts import Alert, Alerts, Kind
from .museum import Museum
from .museum_settings import MuseumSettings
from .runs import PACIFIC, Runs, State

FAILED = {State.PREFLIGHT_FAILED: Kind.PREFLIGHT_FAILED, State.APPLY_FAILED: Kind.APPLY_FAILED,
          State.ABANDONED: Kind.ABANDONED}
NOT_UPDATED_AFTER = timedelta(hours=24)


class Watchdog:
    def __init__(self, museums: dict[str, Museum], museum_settings: MuseumSettings, runs: Runs, alerts: Alerts,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.museums = museums
        self.museum_settings = museum_settings
        self.runs = runs
        self.alerts = alerts
        self.clock = clock

    def check(self) -> list[Alert]:
        """One pass over the museums; returns the alerts that hold now (each recorded once)."""
        holding = []
        for tenant in sorted(self.museums):
            holding += self.check_museum(tenant)
            self.alerts.resend_unsent(tenant)
        return holding

    def check_museum(self, tenant: str) -> list[Alert]:
        now = self.clock().astimezone(PACIFIC)
        tonight = now.date().isoformat()
        newest = self.runs.newest(tenant)
        found = []

        if newest is not None and newest.state in FAILED:
            reasons = "; ".join(newest.reasons) or newest.state.value
            found.append(Alert(tenant, newest.night, FAILED[newest.state], newest.run_id,
                               f"Run {newest.run_id} is {newest.state.value}: {reasons}"))

        deadline_text = self.museum_settings.get(self.museums[tenant]).watchdog_deadline
        hours, minutes = (int(part) for part in deadline_text.split(":"))
        deadline = datetime.combine(now.date(), time(hours, minutes), tzinfo=PACIFIC)
        tonights = newest if newest is not None and newest.night == tonight else None
        if now >= deadline and (tonights is None or tonights.state not in (State.APPLIED, State.ABANDONED)):
            state = tonights.state.value if tonights else "no run started"
            found.append(Alert(tenant, tonight, Kind.MISSED_DEADLINE, tonight,
                               f"By {deadline_text} Pacific, tonight's run isn't applied or abandoned ({state}). "
                               "If the ETL loaded the public core without Serena (a partial night), bring Serena up "
                               "to date in the admin app."))

        applied = self.runs.latest_applied(tenant)
        if applied is not None:
            applied_at = datetime.fromisoformat(applied.updated_at)
            if now - applied_at > NOT_UPDATED_AFTER:
                found.append(Alert(tenant, tonight, Kind.NOT_UPDATED, applied.run_id,
                                   f"The last applied night is {applied.night} ({applied.run_id}, applied "
                                   f"{applied.updated_at})."))
        for alert in found:
            self.alerts.raise_(alert)
        return found
