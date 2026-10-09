"""Parsing the legacy imageserver paths (design: URLs).

Serena accepts only these shapes under …/<tenant>/imageserver/:

    blobs/<blob CSID>/derivatives/<derivative>/content
    blobs/<blob CSID>/content
    blobs/<blob CSID>/content/linked_pdf:<suffix>     Cinefiles only
    blobs/<blob CSID>/content/inline_pdf:<suffix>     Cinefiles only

The PDF link suffix carries the signed-in visitor's email address: it is accepted, thrown away here, and never logged,
recorded or forwarded. Use log_path() for anything that records a path."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .csid import is_csid
from .museum import Museum
from .unserved import Reason

# The suffix: at most 512 characters, no slash (design: URLs).
SUFFIX_MAX = 512
PDF_MUSEUMS = frozenset({"cinefiles"})

_DERIVATIVE = re.compile(r"blobs/(?P<csid>[^/]+)/derivatives/(?P<name>[^/]+)/content")
_ORIGINAL = re.compile(r"blobs/(?P<csid>[^/]+)/content")
_PDF = re.compile(rf"blobs/(?P<csid>[^/]+)/content/(?:linked_pdf|inline_pdf):[^/]{{0,{SUFFIX_MAX}}}")
# Anything that looks like the PDF link suffix, anywhere in a path, raw or percent-encoded.
_SUFFIX_ANYWHERE = re.compile(r"(?i)\b(linked_pdf|inline_pdf)(:|%3A)[^/?#]*")
LOG_PATH_MAX = 300


@dataclass(frozen=True)
class BlobRequest:
    tenant: str
    blob_csid: str
    derivative: str | None  # None: the original file


@dataclass(frozen=True)
class Refused:
    reason: Reason


def parse(museum: Museum, rest: str) -> BlobRequest | Refused:
    """`rest` is the path after …/<tenant>/imageserver/. The museum is already known to be one Serena serves."""
    if m := _DERIVATIVE.fullmatch(rest):
        csid, derivative = m["csid"], m["name"]
    elif m := _ORIGINAL.fullmatch(rest):
        csid, derivative = m["csid"], None
    elif (m := _PDF.fullmatch(rest)) and museum.key in PDF_MUSEUMS:
        csid, derivative = m["csid"], None
    else:
        return Refused(Reason.UNKNOWN_PATH)
    if not is_csid(csid):
        return Refused(Reason.BAD_CSID)
    if derivative is not None and derivative not in museum.derivatives:
        return Refused(Reason.DERIVATIVE_NOT_SERVED)
    # Whether the original file may be served depends on the Blob's kind (design: Kinds): decided with the
    # servability record.
    return BlobRequest(museum.key, csid, derivative)


def log_path(path: str) -> str:
    """The path as it may be logged or recorded: the PDF link suffix removed, the length bounded."""
    cleaned = _SUFFIX_ANYWHERE.sub(r"\1:", path)
    return cleaned if len(cleaned) <= LOG_PATH_MAX else cleaned[:LOG_PATH_MAX] + "…"
