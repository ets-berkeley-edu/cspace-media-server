"""The watchdog (design: Watchdog and alerts): runs in the worker every few minutes, in Pacific time (daylight
saving included), and raises an alert when, for a museum:

- today's refresh hasn't reached updated or abandoned by the museum's deadline (08:00 to start, an admin's setting),
  including when no refresh started at all. This is how Serena notices a failed refresh;
- its newest refresh is check_failed, update_failed or abandoned (the worker also raises the first two at once, when
  the step fails: see Watchdog.raise_failure);
- it hasn't had a servability update in 24 hours. Only for a museum that has had one: before its first servability
  update, a museum has nothing to be late with.

Every alert is raised on every pass while it holds and recorded once (see alerts.py)."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta

from .alerts import Alert, Alerts, Kind
from .museum import Museum
from .museum_settings import MuseumSettings
from .refreshes import PACIFIC, Refresh, Refreshes, State

FAILED = {State.CHECK_FAILED: Kind.CHECK_FAILED, State.UPDATE_FAILED: Kind.UPDATE_FAILED,
          State.ABANDONED: Kind.ABANDONED}
# How an alert says what happened, in words rather than the state's name (Richard, October 14, 2026).
FAILED_WORDS = {State.CHECK_FAILED: "failed its servable list check",
                State.UPDATE_FAILED: "failed its servability update", State.ABANDONED: "was abandoned"}
NOT_UPDATED_AFTER = timedelta(hours=24)


class Watchdog:
    def __init__(self, museums: dict[str, Museum], museum_settings: MuseumSettings, refreshes: Refreshes,
                 alerts: Alerts,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.museums = museums
        self.museum_settings = museum_settings
        self.refreshes = refreshes
        self.alerts = alerts
        self.clock = clock

    def failure(self, refresh: Refresh) -> Alert | None:
        """The alert for a refresh that is check_failed, update_failed or abandoned; None otherwise."""
        if refresh.state not in FAILED:
            return None
        reasons = "; ".join(refresh.reasons)
        what = f"Refresh {refresh.refresh_id} {FAILED_WORDS[refresh.state]}"
        return Alert(refresh.tenant, refresh.refresh_date, FAILED[refresh.state], refresh.refresh_id,
                     f"{what}: {reasons}. Its page says more." if reasons else f"{what}. Its page says more.")

    def raise_failure(self, refresh: Refresh) -> None:
        """Raised by the worker as soon as a step fails, so the team hears at once (design: The daily sequence). The
        watchdog's later passes raise the same alert again, which records and emails nothing more."""
        alert = self.failure(refresh)
        if alert is not None:
            self.alerts.raise_(alert)

    def check(self) -> list[Alert]:
        """One pass over the museums; returns the alerts that hold now (each recorded once)."""
        holding = []
        for tenant in sorted(self.museums):
            holding += self.check_museum(tenant)
            self.alerts.resend_unsent(tenant)
        return holding

    def check_museum(self, tenant: str) -> list[Alert]:
        now = self.clock().astimezone(PACIFIC)
        today = now.date().isoformat()
        newest = self.refreshes.newest(tenant)
        found = []

        failure = self.failure(newest) if newest is not None else None
        if failure is not None:
            found.append(failure)

        deadline_text = self.museum_settings.get(self.museums[tenant]).watchdog_deadline
        hours, minutes = (int(part) for part in deadline_text.split(":"))
        deadline = datetime.combine(now.date(), time(hours, minutes), tzinfo=PACIFIC)
        todays = newest if newest is not None and newest.refresh_date == today else None
        if now >= deadline and (todays is None or todays.state not in (State.UPDATED, State.ABANDONED)):
            state = todays.state.value if todays else "no refresh started"
            found.append(Alert(tenant, today, Kind.MISSED_DEADLINE, today,
                               f"By {deadline_text} Pacific, today's refresh isn't updated or abandoned ({state}). "
                               "If the ETL job refreshed the public core without Serena (a failed refresh), bring "
                               "Serena up to date in the admin app: an admin refresh, a retry or an override."))

        updated = self.refreshes.latest_updated(tenant)
        if updated is not None:
            updated_at = datetime.fromisoformat(updated.updated_at)
            if now - updated_at > NOT_UPDATED_AFTER:
                found.append(Alert(tenant, today, Kind.NOT_UPDATED, updated.refresh_id,
                                   f"The last servability update was on {updated.refresh_date} "
                                   f"({updated.refresh_id}, updated {updated.updated_at})."))
        for alert in found:
            self.alerts.raise_(alert)
        return found
