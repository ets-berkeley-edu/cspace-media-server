"""The servable list check: checks a refresh's servable list without changing anything (design: Servable list check
and servability update).

Fails on any malformed line, a value outside the rules, a Blob listed twice, or more change than the museum's
threshold allows; warns on a missing placeholder image and on a Media CSID listed for several Blobs. The result
names line numbers and fields only, never the values (decided October 9, 2026, D38)."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import IO, Any

from .csid import is_csid
from .museum import Museum
from .servable_list import ACCESS, HEADER, KINDS, Row, lines

MAX_PROBLEMS = 20  # problems listed in the refresh; all are counted


@dataclass
class Problem:
    line: int
    field: str
    problem: str


@dataclass
class Result:
    passed: bool
    rows: int = 0
    added: int = 0
    removed: int = 0
    changed: int = 0
    previous_rows: int | None = None  # None: the museum's first servability update
    threshold_percent: float = 0.0
    delta_percent: float | None = None
    error_count: int = 0
    errors: list[Problem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        value = asdict(self)
        value["result"] = "passed" if self.passed else "failed"
        del value["passed"]
        return value


class _Problems:
    def __init__(self) -> None:
        self.count = 0
        self.listed: list[Problem] = []

    def add(self, line: int, field_name: str, problem: str) -> None:
        self.count += 1
        if len(self.listed) < MAX_PROBLEMS:
            self.listed.append(Problem(line, field_name, problem))


def check(museum: Museum, new: IO[bytes], previous: dict[str, Row] | None, threshold_percent: float,
          override: bool = False) -> Result:
    """`new` is the uploaded servable list (gzip); `previous` the rows of the servable list of the last servability
    update, None for a first servability update.
    `override`: an admin overrode the delta threshold for this refresh's servable list (decided October 12, 2026,
    D83); the change is still counted and shown, but doesn't fail the servable list check."""
    problems = _Problems()
    rows: dict[str, Row] = {}
    seen_header = False
    for number, raw in lines(new):
        if raw.endswith(b"\r"):
            problems.add(number, "line", "ends in CR; lines must end in LF")
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            problems.add(number, "line", "isn't UTF-8")
            continue
        if number == 1:
            seen_header = True
            if text != HEADER:
                problems.add(1, "header", "must be blob_csid, media_csid, kind, access, tab-separated")
            continue
        fields = text.split("\t")
        if len(fields) != 4:
            problems.add(number, "line", f"has {len(fields)} fields, not 4")
            continue
        blob, media, kind, access = fields
        if not is_csid(blob):
            problems.add(number, "blob_csid", "isn't a CSID")
        if media and not is_csid(media):
            problems.add(number, "media_csid", "isn't a CSID")
        if not media and blob != museum.placeholder_blob_csid:
            problems.add(number, "media_csid", "is empty (allowed only for the museum's placeholder image)")
        if kind not in KINDS:
            problems.add(number, "kind", "isn't image, card, audio, video, 3D or pdf")
        if access not in ACCESS:
            problems.add(number, "access", "isn't public or restricted")
        if blob in rows:
            problems.add(number, "blob_csid", "is listed twice")
            continue
        rows[blob] = Row(media, kind, access)
    if not seen_header:
        problems.add(1, "header", "missing: the file is empty")

    result = Result(passed=False, rows=len(rows), threshold_percent=threshold_percent,
                    error_count=problems.count, errors=problems.listed)
    if museum.placeholder_blob_csid and museum.placeholder_blob_csid not in rows:
        result.warnings.append("the museum's placeholder image isn't listed")
    shared = sum(1 for media, n in Counter(r.media_csid for r in rows.values() if r.media_csid).items() if n > 1)
    if shared:
        result.warnings.append(f"{shared} Media CSID{'s are' if shared > 1 else ' is'} listed for several Blobs")

    # No updated servable list yet, or an empty one: nothing to compare with (decided October 9, 2026, D36).
    if not previous:
        result.warnings.append("first servability update: the delta threshold doesn't apply")
    else:
        result.previous_rows = len(previous)
        result.added = sum(1 for blob in rows if blob not in previous)
        result.removed = sum(1 for blob in previous if blob not in rows)
        result.changed = sum(1 for blob, row in rows.items() if blob in previous and previous[blob] != row)
        changes = result.added + result.removed + result.changed
        # A percentage of what Serena serves now: the last updated servable list's rows (decided October 9, 2026, D37).
        result.delta_percent = round(100 * changes / len(previous), 2)
        if override:
            result.warnings.append(f"the delta threshold was overridden by an admin for this refresh ("
                                   f"{result.delta_percent}% of the rows change; the threshold is "
                                   f"{threshold_percent}%)")
        elif result.delta_percent > threshold_percent:
            problems.count += 1
            result.error_count = problems.count
            result.errors.append(Problem(0, "file", f"{result.delta_percent}% of the rows would change; the "
                                                    f"threshold is {threshold_percent}%"))
    result.passed = result.error_count == 0
    return result
