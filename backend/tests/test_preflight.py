import gzip
import io

import pytest

from serena import museum, preflight
from serena.blob_media import HEADER, Row

PAHMA = museum.load("pahma")  # its restricted-image Blob: 59a733dd-d641-4e1a-8552
UCJEPS = museum.load("ucjeps")  # no restricted-image Blob


def gz(text: str | bytes) -> io.BytesIO:
    return io.BytesIO(gzip.compress(text.encode() if isinstance(text, str) else text))


def rows(n: int, kind: str = "image") -> str:
    return "".join(f"blob-{i}\tmedia-{i}\t{kind}\tpublic\n" for i in range(n))


def previous(n: int) -> dict[str, Row]:
    return {f"blob-{i}": Row(f"media-{i}", "image", "public") for i in range(n)}


def test_a_good_file_passes() -> None:
    result = preflight.check(UCJEPS, gz(HEADER + "\n" + rows(100)), previous(100), 5)
    assert result.passed
    assert (result.rows, result.added, result.removed, result.changed, result.change_percent) == (100, 0, 0, 0, 0)
    assert result.summary()["result"] == "passed"


def test_no_final_newline() -> None:
    assert preflight.check(UCJEPS, gz(HEADER + "\n" + rows(3).rstrip("\n")), previous(3), 5).passed


@pytest.mark.parametrize(("body", "field", "problem"), [
    ("blob\tmedia\tkind\taccess\n" + rows(1), "header", "must be"),
    (HEADER + "\nb1\tm1\timage\n", "line", "3 fields"),
    (HEADER + "\nb1\tm1\timage\tpublic\textra\n", "line", "5 fields"),
    (HEADER + "\nnot/a/csid\tm1\timage\tpublic\n", "blob_csid", "isn't a CSID"),
    (HEADER + "\nb1\tm.1\timage\tpublic\n", "media_csid", "isn't a CSID"),
    (HEADER + "\nb1\t\timage\tpublic\n", "media_csid", "is empty"),
    (HEADER + "\nb1\tm1\tmovie\tpublic\n", "kind", "isn't image"),
    (HEADER + "\nb1\tm1\timage\tsecret\n", "access", "isn't public"),
    (HEADER + "\nb1\tm1\timage\tpublic\nb1\tm2\timage\tpublic\n", "blob_csid", "listed twice"),
    (HEADER + "\r\nb1\tm1\timage\tpublic\r\n", "line", "ends in CR"),
    ("", "header", "missing"),
])
def test_problems_fail_the_preflight(body: str, field: str, problem: str) -> None:
    result = preflight.check(UCJEPS, gz(body), None, 5)
    assert not result.passed
    assert any(p.field == field and problem in p.problem for p in result.errors), result.errors


def test_not_utf8() -> None:
    result = preflight.check(UCJEPS, gz(HEADER.encode() + b"\nb1\tm\xff\timage\tpublic\n"), None, 5)
    assert [(p.line, p.field) for p in result.errors] == [(2, "line")]


def test_problems_name_lines_and_fields_never_values() -> None:
    result = preflight.check(UCJEPS, gz(HEADER + "\nsecret-value\t\tmovie\tpublic\n"), None, 5)
    assert all("secret-value" not in p.problem for p in result.errors)
    assert {p.line for p in result.errors} == {2}


def test_only_the_first_20_problems_are_listed_but_all_are_counted() -> None:
    body = HEADER + "\n" + "".join(f"b{i}\tm{i}\tmovie\tpublic\n" for i in range(50))
    result = preflight.check(UCJEPS, gz(body), None, 5)
    assert (result.error_count, len(result.errors)) == (50, 20)


def test_restricted_and_audio_rows_are_allowed() -> None:
    body = HEADER + "\nb1\tm1\tpdf\trestricted\nb2\tm2\taudio\tpublic\nb3\tm3\t3D\tpublic\nb4\tm4\tcard\tpublic\n"
    assert preflight.check(UCJEPS, gz(body), None, 5).passed


def test_the_restricted_image_blob_may_have_no_media_csid() -> None:
    body = HEADER + "\n59a733dd-d641-4e1a-8552\t\timage\tpublic\n" + rows(1)
    result = preflight.check(PAHMA, gz(body), None, 5)
    assert result.passed
    assert not any("restricted-image" in w for w in result.warnings)


def test_warnings() -> None:
    body = HEADER + "\nb1\tshared\timage\tpublic\nb2\tshared\timage\tpublic\n"
    result = preflight.check(PAHMA, gz(body), None, 5)
    assert result.passed  # warnings don't fail it
    assert "the museum's restricted-image Blob isn't listed" in result.warnings
    assert "1 Media CSID is listed for several Blobs" in result.warnings


def test_first_load_has_no_threshold() -> None:
    result = preflight.check(UCJEPS, gz(HEADER + "\n" + rows(1000)), None, 5)
    assert result.passed
    assert result.previous_rows is None and result.change_percent is None
    assert "first load: the change threshold doesn't apply" in result.warnings
    assert preflight.check(UCJEPS, gz(HEADER + "\n" + rows(10)), {}, 5).passed  # an empty last file: the same


def test_the_threshold_is_a_share_of_the_last_applied_rows() -> None:
    last = previous(100)
    five = HEADER + "\n" + rows(95) + "".join(f"new-{i}\tm\timage\tpublic\n" for i in range(0))
    result = preflight.check(UCJEPS, gz(five), last, 5)  # 5 removed of 100: 5%, not more than 5%
    assert result.passed and (result.removed, result.change_percent) == (5, 5.0)
    six = HEADER + "\n" + rows(94)
    result = preflight.check(UCJEPS, gz(six), last, 5)
    assert not result.passed
    assert result.change_percent == 6.0
    assert result.errors[-1].field == "file" and "threshold is 5" in result.errors[-1].problem


def test_changed_rows_count() -> None:
    body = HEADER + "\n" + rows(98) + "blob-98\tother\timage\tpublic\nblob-99\tmedia-99\tcard\tpublic\n"
    result = preflight.check(UCJEPS, gz(body), previous(100), 5)
    assert (result.added, result.removed, result.changed) == (0, 0, 2)
