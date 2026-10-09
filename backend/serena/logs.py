"""Structured JSON logs, scrubbed of secrets and personal data (design: Logs and metrics; No personal data in logs).

The code never hands a password, token, signed URL or visitor's email address to a logger; scrubbing every finished
field is the backstop for the mistake nobody has made yet. Tracebacks are scrubbed too.

Uvicorn's access log is turned off: it would log each request's raw path, and Cinefiles' PDF links carry the visitor's
email address after linked_pdf: or inline_pdf:. Serena logs requests itself, with the suffix removed."""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

REMOVED = "[removed]"
_VALUE = r"[^\s'\",)}\]&]+"
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Cinefiles' PDF link suffix carries the signed-in visitor's email address: keep the marker, drop the rest of
    # the path segment. The colon may arrive percent-encoded.
    (re.compile(r"(?i)\b(linked_pdf|inline_pdf)(:|%3A)[^/\s'\"?#]*"), r"\1\2" + REMOVED),
    # Authorization: Basic dXNlcjpwYXNz   'Authorization': 'Bearer abc'   authorization=Bearer abc
    (re.compile(r"(?i)(authorization['\"]?\s*[:=]\s*['\"]?)(?:(?:basic|bearer)\s+)?" + _VALUE), r"\1" + REMOVED),
    # a bare "Basic <token>" or "Bearer <token>" that looks like a token, so "basic checks" is left alone
    (
        re.compile(r"\b([Bb]asic|[Bb]earer)\s+(?=\S[A-Za-z0-9+/=_.-]*[A-Z0-9+/=])[A-Za-z0-9+/=_.-]{8,}"),
        r"\1 " + REMOVED,
    ),
    # password=..., "password": "...", token: ..., secret=...
    (re.compile(r"(?i)((?:password|passwd|pwd|token|secret)['\"]?\s*[:=]\s*['\"]?)" + _VALUE), r"\1" + REMOVED),
    # https://user:secret@host
    (re.compile(r"(?i)(https?://[^/\s:@]+:)[^@\s/]+@"), r"\1" + REMOVED + "@"),
    # CloudFront signed URLs: the signature, the policy and the key pair
    (re.compile(r"(?i)\b(Signature|Policy|Key-Pair-Id)=[^&\s'\"]+"), r"\1=" + REMOVED),
    # any email address left, plain or percent-encoded
    (re.compile(r"[A-Za-z0-9._%+-]+(?:@|%40)[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"), REMOVED),
]

# LogRecord's own attributes; anything else on a record came from `extra=` and is logged as a field. Uvicorn adds
# color_message, the message again with terminal colours.
_STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime", "taskName",
                                                                          "color_message"}


def scrub(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _scrub_value(value: Any) -> Any:
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        return {str(k): _scrub_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_scrub_value(v) for v in value]
    if value is None or isinstance(value, bool | int | float):
        return value
    return scrub(str(value))


class JsonFormatter(logging.Formatter):
    """One JSON object per line: time, level, logger, message, any `extra=` fields, and the exception if any."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD and key not in entry:
                entry[key] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(_scrub_value(entry), ensure_ascii=False)


def configure(level: str = "INFO") -> None:
    """Send every log, uvicorn's included, through one JSON handler on stderr. Call it when the app or worker starts
    (after uvicorn has set up its own logging, which this replaces)."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    if logging.lastResort is not None:
        logging.lastResort.setFormatter(JsonFormatter())
