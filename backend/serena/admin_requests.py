"""The admin API for the Past requests page: what Serena served and couldn't serve for the museum, from its log (design:
The Past requests page; decided October 12, 2026, D100 to D113). Any admin of the museum may read it; reading it isn't
audited (D111)."""
from __future__ import annotations

import csv
import io
import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from .admin_api import SignedIn, csv_cell
from .request_counts import RequestCounts
from .requests_log import MAX_LINES, LogUnavailable, Report, Requests, TooSlow, lines_matching

log = logging.getLogger("serena.admin_requests")

# DEFAULT_RANGE in requests_log.py: 24 hours to start (D106)
Range = Annotated[Literal["1h", "24h", "7d"], Query(alias="range")]
Outcome = Annotated[Literal["served", "unserved"] | None, Query()]
ReasonFilter = Annotated[str | None, Query(pattern=r"^[a-z_]+$", max_length=64)]
Period = Annotated[Literal["day", "week", "month", "year"], Query(alias="by")]
# Refresh (issue #100): read the log again now, skipping the minute a report is kept (D108), at most once per museum
# every 10 seconds; inside that, the kept answer comes back with try_again_in.
Fresh = Annotated[bool, Query()]


def _report(request: Request, tenant: str, range_: str, fresh: bool = False) -> tuple[Report, int | None]:
    requests: Requests = request.app.state.requests_log
    try:
        return requests.read(tenant, range_, fresh)
    except TooSlow as slow:
        raise HTTPException(504, str(slow)) from slow
    except LogUnavailable as unavailable:
        raise HTTPException(503, str(unavailable)) from unavailable


def create_router() -> APIRouter:
    router = APIRouter(prefix="/admin/v1/museums/{tenant}")

    @router.get("/requests")
    def requests_report(request: Request, session: SignedIn, range_: Range = "24h",
                        fresh: Fresh = False) -> dict[str, Any]:
        """Counts by day (served; unserved by reason), served counts by size and the most-requested paths cover every
        request in the range; the lines are the newest MAX_LINES, newest first (D105 to D107). The app sorts, filters
        and pages them."""
        report, wait = _report(request, session.tenant, range_, fresh)
        # The museum's sizes, smallest to largest: its derivatives in their configured order, then the original file
        # (Richard, October 14, 2026). The page sorts its Size columns by them; any other name is "(invalid)".
        sizes = [*request.app.state.museums[session.tenant].derivatives, "original"]
        rank = {size: i for i, size in enumerate(sizes)}
        by_size = sorted(report.by_size.items(), key=lambda pair: (rank.get(pair[0], len(sizes)), pair[0]))
        return {
            "range": report.range,
            "start": report.start.isoformat(),
            "end": report.end.isoformat(),
            # When Serena read the log for this report (it's kept a minute, D108), and a refused Refresh's wait
            # (issue #100).
            "read_at": report.end.isoformat(),
            "try_again_in": wait,
            "max_lines": MAX_LINES,
            "truncated": report.truncated,
            # Only a museum with signed access (Cinefiles) can have a signed-link request: the page shows that column
            # for it alone (Richard, October 14, 2026).
            "signed_links": bool(request.app.state.museums[session.tenant].signed_access_kinds),
            "days": [{"day": d.day, "served": d.served, "unserved": d.unserved,
                      "unserved_total": sum(d.unserved.values())} for d in report.days],
            "top_paths": [{"path": path, "requests": n} for path, n in report.top_paths],
            "sizes": sizes,
            # The Served card's "by size" (Richard, October 14, 2026): every served request in the range.
            "served_by_size": [{"size": size, "requests": n} for size, n in by_size],
            # The Served card's split (issue #96): served from Serena's cache (hit) or fetched from CollectionSpace
            # (miss).
            "served_by_cache": {"hit": report.by_cache.get("hit", 0), "miss": report.by_cache.get("miss", 0)},
            "lines": [{"at": line.at, "outcome": line.outcome, "reason": line.reason, "path": line.path,
                       "kind": line.kind, "cache": line.cache, "signed": line.signed} for line in report.lines],
        }

    @router.get("/requests/counts")
    def request_counts(request: Request, session: SignedIn, period: Period = "day",
                       fresh: Fresh = False) -> dict[str, Any]:
        """From the cache or CollectionSpace (issue #96): served requests that were cache hits and misses, and
        unserved requests, by day, ISO week, month or year (UTC), newest first, from the worker's daily counts, with
        today's (and yesterday's, until counted) read from the log. Not the page's range: the counts go back to the
        first day counted. When the log can't be read, the stored counts come back with `live_unavailable`."""
        counts: RequestCounts = request.app.state.request_counts
        summary = counts.summary(session.tenant, period, fresh)
        return {
            "by": summary.period,
            "today": summary.today,
            "since": summary.since,
            "totals": {"hits": summary.hits, "misses": summary.misses, "unserved": summary.unserved},
            "rows": [{"period": row.period, "first_day": row.first_day, "last_day": row.last_day, "hits": row.hits,
                      "misses": row.misses, "unserved": row.unserved, "live": row.live, "partial": row.partial}
                     for row in summary.rows],
            "live_unavailable": summary.live_unavailable,
            "read_at": summary.read_at,  # when the days not counted yet were read from the log (issue #100)
            "try_again_in": summary.try_again_in,
        }

    @router.get("/requests/export.csv")
    def requests_export(request: Request, session: SignedIn, range_: Range = "24h",
                        outcome: Outcome = None, reason: ReasonFilter = None) -> Response:
        """The lines matching the page's range and filters, newest first, as CSV (D112, D113): formula-safe, like
        the audit log's export."""
        report, _ = _report(request, session.tenant, range_)
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\r\n")
        writer.writerow(["time (UTC)", "outcome", "reason", "path", "kind", "cache", "signed link"])
        for line in lines_matching(report, outcome, reason):
            writer.writerow([csv_cell(value) for value in (
                line.at, line.outcome, line.reason, line.path, line.kind, line.cache, "yes" if line.signed else "no")])
        day = report.end.date().isoformat()
        return Response(out.getvalue(), media_type="text/csv; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="serena-requests-{session.tenant}-{day}.csv"'})

    return router
