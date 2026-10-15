"""Parsing the legacy imageserver paths (design: URLs).

Serena accepts only these shapes under …/<tenant>/imageserver/:

    blobs/<blob CSID>/derivatives/<derivative>/content
    blobs/<blob CSID>/content
    blobs/<blob CSID>/content/linked_pdf:<suffix>     Cinefiles only
    blobs/<blob CSID>/content/inline_pdf:<suffix>     Cinefiles only
    media/<media CSID>/blob/derivatives/<derivative>/content     (pull request 15: answered as its listed Blob's)
    media/<media CSID>/blob/content

The PDF link suffix carries the signed-in visitor's email address: it is accepted, thrown away here, and never logged,
recorded or forwarded. Use log_path() for anything that records a path."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from .csid import is_csid
from .museum import Museum
from .unserved import Reason

# The suffix: at most 512 characters, no slash (design: URLs).
SUFFIX_MAX = 512
PDF_MUSEUMS = frozenset({"cinefiles"})

_DERIVATIVE = re.compile(r"blobs/(?P<csid>[^/]+)/derivatives/(?P<name>[^/]+)/content")
_ORIGINAL = re.compile(r"blobs/(?P<csid>[^/]+)/content")
_MEDIA_DERIVATIVE = re.compile(r"media/(?P<csid>[^/]+)/blob/derivatives/(?P<name>[^/]+)/content")
_MEDIA_ORIGINAL = re.compile(r"media/(?P<csid>[^/]+)/blob/content")
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
class MediaRequest:
    """A request by Media CSID (decided October 14, 2026, D174 to D177): answered as a request for the Media record's
    Blob in the last servability update's servable list (servability.resolve), public files only."""
    tenant: str
    media_csid: str
    derivative: str | None  # None: the original file


@dataclass(frozen=True)
class Refused:
    reason: Reason


def parse(museum: Museum, rest: str) -> BlobRequest | MediaRequest | Refused:
    """`rest` is the path after …/<tenant>/imageserver/. The museum is already known to be one Serena serves."""
    media = _MEDIA_DERIVATIVE.fullmatch(rest) or _MEDIA_ORIGINAL.fullmatch(rest)
    if media:
        derivative = media.groupdict().get("name")
        if not is_csid(media["csid"]):
            return Refused(Reason.BAD_CSID)
        if derivative is not None and derivative not in museum.derivatives:
            return Refused(Reason.DERIVATIVE_NOT_SERVED)
        return MediaRequest(museum.key, media["csid"], derivative)
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


@dataclass(frozen=True)
class Given:
    """A path or URL an admin gave (Media look up, the recall form), read as the signed-in museum's (Richard, October
    14, 2026): `rest` is what follows …/imageserver/ (for paths.parse(); it may hold the PDF link suffix, so it's never
    logged or shown), or `problem` says why it can't be read. `shown` is the path as it may be shown and recorded
    (log_path: no host, query string or PDF link suffix)."""
    shown: str
    rest: str = ""
    problem: str | None = None

    @property
    def csid(self) -> tuple[str, str] | None:
        """("blob" or "media", the CSID) the path names, whatever follows it; None without a valid one."""
        m = _NAMED.match(self.rest)
        if self.problem is not None or m is None or not is_csid(m["csid"]):
            return None
        return ("blob" if m["which"] == "blobs" else "media"), m["csid"]


_NAMED = re.compile(r"^(?P<which>blobs|media)/(?P<csid>[^/]+)(?:/|$)")
_STARTS = ("imageserver", "blobs", "media")


def given(museum: Museum, museums: dict[str, Museum], text: str, verb: str = "looking up") -> Given:
    """Forgives a path's shape: a URL or a path, with or without its leading slash, and with no museum
    (`imageserver/blobs/…`, `blobs/<CSID>/…`) for the signed-in museum's. Another museum's path says which museum it
    is. Any query string is dropped, and `shown` never has the PDF link suffix."""
    text = text.strip()
    path = urlsplit(text).path if "://" in text else text.split("?", 1)[0].split("#", 1)[0]
    parts = path.lstrip("/").split("/")
    if parts[0] in _STARTS:
        parts = [museum.key, *parts] if parts[0] == "imageserver" else [museum.key, "imageserver", *parts]
    shown = log_path("/" + "/".join(parts))
    if len(parts) < 2 or parts[1] != "imageserver":
        return Given(shown, problem=f"Not one of {museum.name}'s file paths: they start with "
                                    f"/{museum.key}/imageserver/")
    if parts[0] != museum.key:
        other = museums.get(parts[0])
        if other is None:
            return Given(shown, problem=f"Not one of {museum.name}'s file paths: they start with "
                                        f"/{museum.key}/imageserver/")
        return Given(shown, problem=f"That's a {other.name} path; you're {verb} {museum.name}'s files.")
    return Given(shown, rest="/".join(parts[2:]))


def log_path(path: str) -> str:
    """The path as it may be logged or recorded: the PDF link suffix removed, the length bounded."""
    cleaned = _SUFFIX_ANYWHERE.sub(r"\1:", path)
    return cleaned if len(cleaned) <= LOG_PATH_MAX else cleaned[:LOG_PATH_MAX] + "…"
