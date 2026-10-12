import pytest

from serena.refreshes import parse_refresh_id


@pytest.mark.parametrize(("refresh_id", "parsed"), [
    ("pahma-2026-10-10-1", ("2026-10-10", 1)),
    ("pahma-2026-10-10-12", ("2026-10-10", 12)),
    ("pahma-2026-10-10-0", None),
    ("pahma-2026-10-10-01", None),
    ("pahma-2026-10-10-1000", None),
    ("ucjeps-2026-10-10-1", None),
    ("pahma-2026-02-30-1", None),
    ("pahma--1", None),
])
def test_parse_refresh_id(refresh_id: str, parsed: tuple[str, int] | None) -> None:
    assert parse_refresh_id("pahma", refresh_id) == parsed
