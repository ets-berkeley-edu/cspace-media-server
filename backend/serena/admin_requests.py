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
from .requests_log import MAX_LINES, LogUnavailable, Report, Requests, TooSlow, lines_matching

log = logging.getLogger("serena.admin_requests")

# DEFAULT_RANGE in requests_log.py: 24 hours to start (D106)
Range = Annotated[Literal["1h", "24h", "7d"], Query(alias="range")]
Outcome = Annotated[Literal["served", "unserved"] | None, Query()]
ReasonFilter = Annotated[str | None, Query(pattern=r"^[a-z_]+$", max_length=64)]


def _report(request: Request, tenant: str, range_: str) -> Report:
    requests: Requests = request.app.state.requests_log
    try:
        return requests.report(tenant, range_)
    except TooSlow as slow:
        raise HTTPException(504, str(slow)) from slow
    except LogUnavailable as unavailable:
        raise HTTPException(503, str(unavailable)) from unavailable


def create_router() -> APIRouter:
    router = APIRouter(prefix="/admin/v1/museums/{tenant}")

    @router.get("/requests")
    def requests_report(request: Request, session: SignedIn, range_: Range = "24h") -> dict[str, Any]:
        """Counts by day (served; unserved by reason), served counts by size and the most-requested paths cover every
        request in the range; the lines are the newest MAX_LINES, newest first (D105 to D107). The app sorts, filters
        and pages them."""
        report = _report(request, session.tenant, range_)
        # The museum's sizes, smallest to largest: its derivatives in their configured order, then the original file
        # (Richard, October 14, 2026). The page sorts its Size columns by them; any other name is "(invalid)".
        sizes = [*request.app.state.museums[session.tenant].derivatives, "original"]
        rank = {size: i for i, size in enumerate(sizes)}
        by_size = sorted(report.by_size.items(), key=lambda pair: (rank.get(pair[0], len(sizes)), pair[0]))
        return {
            "range": report.range,
            "start": report.start.isoformat(),
            "end": report.end.isoformat(),
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
            "lines": [{"at": line.at, "outcome": line.outcome, "reason": line.reason, "path": line.path,
                       "kind": line.kind, "cache": line.cache, "signed": line.signed} for line in report.lines],
        }

    @router.get("/requests/export.csv")
    def requests_export(request: Request, session: SignedIn, range_: Range = "24h",
                        outcome: Outcome = None, reason: ReasonFilter = None) -> Response:
        """The lines matching the page's range and filters, newest first, as CSV (D112, D113): formula-safe, like
        the audit log's export."""
        report = _report(request, session.tenant, range_)
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
