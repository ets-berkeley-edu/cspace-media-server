"""A failed ETL list update, for trying the admin app's failed-update pages by hand on the local stack (testing
checklist section 45). An update that fails partway can't be made to happen there, so this records one: a new refresh
with the museum's last updated ETL list, in `update_failed`, which the worker then retries every 10 minutes (decided
October 28, 2026) and an admin can retry at once. Local only: it refuses without a local DynamoDB.

    ./serena etl pahma            # first, an updated refresh to repeat
    ./serena failed-update pahma
"""
from __future__ import annotations

import argparse
import sys

from serena.config import get_settings
from serena.refreshes import Refresh, Refreshes, State
from serena.store import Store, dynamodb_client
from serena.worker import RETRY_FOR, UPDATE_ATTEMPTS


def record(refreshes: Refreshes, museum: str) -> Refresh | None:
    """The new refresh, failed as the worker leaves one; None if the museum has no updated refresh to repeat."""
    last = refreshes.latest_updated(museum)
    if last is None or last.upload is None:
        return None
    refresh, _ = refreshes.start(museum)
    refresh = refreshes.transition(refresh, State.RECEIVED, upload=last.upload)
    refresh = refreshes.transition(refresh, State.CHECKING)
    refresh = refreshes.transition(refresh, State.UPDATING, results={"check": last.check or {}})
    until = (refreshes.clock() + RETRY_FOR).isoformat(timespec="seconds")
    return refreshes.transition(refresh, State.UPDATE_FAILED, results={"retry_until": until},
                                reason=f"ETL list update failed after {UPDATE_ATTEMPTS} attempts (ClientError); "
                                       "Serena tries it again by itself, and an admin can retry it")


def main() -> None:
    parser = argparse.ArgumentParser(description="Record a failed ETL list update (the local stack only).")
    parser.add_argument("--museum", required=True)
    args = parser.parse_args()
    settings = get_settings()
    if not settings.dynamodb_endpoint:
        sys.exit("Only on the local stack: there's no local DynamoDB here.")
    refresh = record(Refreshes(Store(dynamodb_client(settings), settings.table_prefix)), args.museum)
    if refresh is None:
        sys.exit(f"No updated refresh for {args.museum} yet: run ./serena etl {args.museum} first.")
    print(f"{refresh.refresh_id}: update_failed; the worker retries it from 10 minutes on, "
          f"until {(refresh.retry_until or '')[11:16]} UTC")


if __name__ == "__main__":
    main()
