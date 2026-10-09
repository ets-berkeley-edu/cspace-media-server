import pytest

from serena.csid import is_csid


@pytest.mark.parametrize(
    "value",
    [
        "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b",  # the usual UUID form (synthetic)
        "59a733dd-d641-4e1a-8552",  # PAHMA's restricted-image Blob: a real CSID that isn't a UUID
        "a",
        "A" * 64,
    ],
)
def test_accepted(value: str) -> None:
    assert is_csid(value)


@pytest.mark.parametrize(
    "value",
    ["", "A" * 65, "../etc", "abc/def", "abc.def", "abc def", "abc%2Fdef", "abc\n", "café"],
)
def test_refused(value: str) -> None:
    assert not is_csid(value)
