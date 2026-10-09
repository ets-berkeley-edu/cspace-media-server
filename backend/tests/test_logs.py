import json
import logging

import pytest

from serena import logs

# The tests' email address is built from parts, so no address appears in the repository as written.
EMAIL = "visitor" + "@" + "example.org"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"GET /cinefiles/imageserver/blobs/abc/content/linked_pdf:{EMAIL}",
         "GET /cinefiles/imageserver/blobs/abc/content/linked_pdf:[removed]"),
        (f"/blobs/abc/content/inline_pdf:{EMAIL}?x=1", "/blobs/abc/content/inline_pdf:[removed]?x=1"),
        ("/blobs/abc/content/linked_pdf%3Avisitor" + "%40" + "example.org",
         "/blobs/abc/content/linked_pdf%3A[removed]"),
        ("Authorization: Basic dXNlcjpwYXNzd29yZA==", "Authorization: [removed]"),
        ("{'authorization': 'Bearer abc.def.ghi'}", "{'authorization': '[removed]'}"),
        ("sent Bearer AbCdEf123456789", "sent Bearer [removed]"),
        ("password=hunter2 next", "password=[removed] next"),
        ('{"token": "xyz123"}', '{"token": "[removed]"}'),
        ("https://reader:s3cret@cspace.test/cspace-services", "https://reader:[removed]@cspace.test/cspace-services"),
        ("https://cdn.test/objects/ab?Expires=1&Signature=Zm9v~&Key-Pair-Id=K123",
         "https://cdn.test/objects/ab?Expires=1&Signature=[removed]&Key-Pair-Id=[removed]"),
        (f"from {EMAIL} today", "from [removed] today"),
        ("/cinefiles/imageserver/blobs/abc/content/linked_pdf:?exp=1791590400&uid=12345&kid=k1&sig=pZqh6CO0MnUTOb6m",
         "/cinefiles/imageserver/blobs/abc/content/linked_pdf:[removed]?exp=1791590400&uid=[removed]&kid=k1"
         "&sig=[removed]"),
    ],
)
def test_scrub(text: str, expected: str) -> None:
    assert logs.scrub(text) == expected


@pytest.mark.parametrize("text", ["basic checks passed", "Basic Authentication", "fetched 3 tokens of work", "guid=abc",
                                  "blobs/0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b/derivatives/Medium/content"])
def test_ordinary_text_is_left_alone(text: str) -> None:
    assert logs.scrub(text) == text


def _format(record: logging.LogRecord) -> dict[str, object]:
    entry: dict[str, object] = json.loads(logs.JsonFormatter().format(record))
    return entry


def test_json_line_with_fields_and_no_personal_data() -> None:
    record = logging.LogRecord("serena.test", logging.INFO, __file__, 1, "served %s", (f"linked_pdf:{EMAIL}",), None)
    record.path = f"/cinefiles/imageserver/blobs/abc/content/inline_pdf:{EMAIL}"
    record.counts = {"hits": 3}
    entry = _format(record)
    assert entry["level"] == "INFO"
    assert entry["logger"] == "serena.test"
    assert entry["message"] == "served linked_pdf:[removed]"
    assert entry["path"] == "/cinefiles/imageserver/blobs/abc/content/inline_pdf:[removed]"
    assert entry["counts"] == {"hits": 3}
    assert str(entry["time"]).endswith("+00:00")


def test_tracebacks_are_scrubbed() -> None:
    try:
        raise RuntimeError("Authorization: Basic dXNlcjpwYXNzd29yZA==")
    except RuntimeError:
        import sys

        record = logging.LogRecord("serena.test", logging.ERROR, __file__, 1, "failed", None, sys.exc_info())
    entry = _format(record)
    assert "dXNlcjpwYXNzd29yZA" not in str(entry["exception"])
    assert "Authorization: [removed]" in str(entry["exception"])


def test_configure_turns_off_the_access_log_and_sends_uvicorn_through_json() -> None:
    logs.configure("INFO")
    assert logging.getLogger("uvicorn.access").disabled
    for name in ("uvicorn", "uvicorn.error"):
        assert logging.getLogger(name).handlers == []
        assert logging.getLogger(name).propagate
    assert logging.getLogger("httpx").level == logging.WARNING
    (handler,) = logging.getLogger().handlers
    assert isinstance(handler.formatter, logs.JsonFormatter)
