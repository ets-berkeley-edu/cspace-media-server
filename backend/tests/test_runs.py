import pytest

from serena.runs import parse_run_id


@pytest.mark.parametrize(("run_id", "parsed"), [
    ("pahma-2026-10-10-1", ("2026-10-10", 1)),
    ("pahma-2026-10-10-12", ("2026-10-10", 12)),
    ("pahma-2026-10-10-0", None),
    ("pahma-2026-10-10-01", None),
    ("pahma-2026-10-10-1000", None),
    ("ucjeps-2026-10-10-1", None),
    ("pahma-2026-02-30-1", None),
    ("pahma--1", None),
])
def test_parse_run_id(run_id: str, parsed: tuple[str, int] | None) -> None:
    assert parse_run_id("pahma", run_id) == parsed
