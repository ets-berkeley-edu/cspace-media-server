"""Look up a file (design: Admin web app; decided October 12, 2026, D121 to D123): why Serena serves a file or not.

Given a file's URL or path, a Blob CSID or a Media CSID, it shows each step of the servability check and its outcome,
whether a copy is stored, and the verdict for each size: the same decision a request gets (servability.decide), with
no signed link. It never calls CollectionSpace. The admin's text may hold a PDF link suffix (a visitor's email
address): only paths.log_path()'s version of it is shown, and nothing of it is logged."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from . import cache_index, paths
from .csid import is_csid
from .museum import SERVED_KINDS, Museum
from .refreshes import Refreshes
from .servability import ORIGINAL_ONLY_KINDS, decide
from .store import Store
from .takedowns import rows_of_media
from .unserved import Reason


class LookupProblem(ValueError):
    pass


def _step(check: str, outcome: str, ok: bool | None) -> dict[str, Any]:
    return {"check": check, "outcome": outcome, "ok": ok}  # ok None: neither, it depends on the request


def explain(museum: Museum, text: str, store: Store, refreshes: Refreshes) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise LookupProblem("Give a file's URL or path, a Blob CSID or a Media CSID.")
    sizes: list[str | None] = [None, *museum.derivatives]
    shown = text
    if "/" in text:
        path = urlsplit(text).path if "://" in text else text.split("?", 1)[0].split("#", 1)[0]
        shown = paths.log_path(path)
        prefix = f"/{museum.key}/imageserver/"
        if not path.startswith(prefix):
            raise LookupProblem(f"Not one of {museum.name}'s file paths: they start with {prefix}")
        parsed = paths.parse(museum, path[len(prefix):])
        if isinstance(parsed, paths.Refused):
            return {"input": shown, "refused": parsed.reason.value, "items": [], "refresh": _refresh(museum,
                                                                                                     refreshes)}
        blobs = [parsed.blob_csid]
        sizes = [parsed.derivative]
    else:
        if not is_csid(text):
            raise LookupProblem("That isn't a CSID, a URL or a path.")
        if store.servability(museum.key, text) is not None:
            blobs = [text]
        else:
            blobs = [r.blob_csid for r in rows_of_media(store, museum.key, text)] or [text]
    return {"input": shown, "refused": None, "refresh": _refresh(museum, refreshes),
            "items": [_blob(museum, blob, sizes, store) for blob in blobs]}


def _refresh(museum: Museum, refreshes: Refreshes) -> dict[str, str] | None:
    latest = refreshes.latest_updated(museum.key)
    return {"refresh_id": latest.refresh_id, "refresh_date": latest.refresh_date} if latest else None


def _blob(museum: Museum, blob: str, sizes: list[str | None], store: Store) -> dict[str, Any]:
    record = store.servability(museum.key, blob)
    steps = []
    if record is None:
        steps.append(_step("In the servable list", "Not in the servable list of the last servability update.",
                           False))
    else:
        steps.append(_step("In the servable list", "Listed in the servable list of the last servability update.",
                           True))
        steps.append(_step("Kind", record.kind + ("" if record.kind in SERVED_KINDS else ": not served"),
                           record.kind in SERVED_KINDS))
        if record.access == "public":
            steps.append(_step("Access", "public", True))
        elif record.access == "restricted" and record.kind in museum.signed_access_kinds:
            steps.append(_step("Access", "restricted: served only on a portal's valid signed link", None))
        else:
            steps.append(_step("Access", f"{record.access}: not served", False))
        if record.media_csid is None:
            steps.append(_step("Takedown", "No Media record (the museum's placeholder image).", True))
        else:
            takedown = store.takedown(museum.key, record.media_csid)
            if takedown is None:
                steps.append(_step("Takedown", "No takedown.", True))
            else:
                kept = (f" Refresh {takedown.kept_by} kept it: the file is still public in CollectionSpace."
                        if takedown.kept_by else "")
                steps.append(_step("Takedown", f"Taken down by {takedown.by} at {takedown.at}: {takedown.reason}."
                                   + kept, False))
        if blob == museum.placeholder_blob_csid:
            steps.append(_step("Placeholder image", "The museum's placeholder image: served from files an admin "
                               "uploads (pull request 14b); none yet.", False))
    if record is not None and record.kind in ORIGINAL_ONLY_KINDS:
        sizes = [s for s in sizes if s is None] or sizes  # derivatives of a PDF or 3D file are never served
    return {"blob_csid": blob, "media_csid": record.media_csid if record else None,
            "kind": record.kind if record else None, "access": record.access if record else None,
            "steps": steps, "sizes": [_size(museum, blob, size, store) for size in sizes]}


def _size(museum: Museum, blob: str, size: str | None, store: Store) -> dict[str, Any]:
    decision = decide(museum, paths.BlobRequest(museum.key, blob, size), store)  # no signed link
    reason = decision.reason
    if reason is None and size in museum.watermark_sizes:
        reason = Reason.WATERMARK_NOT_BUILT
    entry = cache_index.lookup(store, museum.key, blob, size)
    stored = {"fetched_at": entry.fetched_at, "size": entry.size, "content_type": entry.content_type} if entry else None
    if reason is not None:
        verdict = "not served"
    elif stored:
        verdict = "served from the stored copy"
    else:
        verdict = "served: would be fetched on the next request"
    return {"size": size or "original", "served": reason is None, "reason": reason.value if reason else None,
            "verdict": verdict, "stored": stored}
