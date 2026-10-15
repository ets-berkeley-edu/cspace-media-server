"""Media look up (design: Admin web app; decided October 12, 2026, D121 to D123, and October 13, 2026, D139 to D143):
why Serena serves a file or not.

Given a file's URL or path, a Blob CSID or a Media CSID, it shows each step of the servability check and its outcome,
and for each size the verdict a request gets (servability.decide, with no signed link), whether a copy is stored,
when it was first stored and when it was last served (the cache index, to the day). Beside that, what CollectionSpace
says now about the Media record (D139): whether it exists, its Blob, when it last changed and the museum's lookup
fields (D140), with a sentence on what the next refresh will do (D141). Serena's verdict never depends on that call;
when CollectionSpace can't be reached, the page says so. The admin's text may hold a PDF link suffix (a visitor's
email address): only paths.log_path()'s version of it is shown, and nothing of it is logged."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from . import cache_index, paths
from .csid import is_csid
from .cspace.client import CSpaceClient, CSpaceError, MediaRecord, MediaState
from .museum import SERVED_KINDS, Museum
from .recalls import rows_of_media
from .refreshes import Refresh, Refreshes
from .servability import ORIGINAL_ONLY_KINDS, decide
from .servable_list import kind_word
from .store import Store
from .unserved import Reason

log = logging.getLogger("serena.lookup")

# A Blob's own URL with nothing after it, which Serena doesn't serve (it needs /content or /derivatives/<size>/content).
BARE_BLOB = re.compile(r"^blobs/([^/]{1,64})/?$")


class LookupProblem(ValueError):
    pass


def _step(check: str, outcome: str, ok: bool | None) -> dict[str, Any]:
    return {"check": check, "outcome": outcome, "ok": ok}  # ok None: neither, it depends on the request


def explain(museum: Museum, text: str, store: Store, refreshes: Refreshes,
            cspace: CSpaceClient | None = None, museums: dict[str, Museum] | None = None,
            placeholder_media: str | None = None) -> dict[str, Any]:
    """`placeholder_media`: the Media record named for the museum's placeholder image on the Settings page (D166)."""
    text = text.strip()
    if not text:
        raise LookupProblem("Give a file's URL or path, a Blob CSID or a Media CSID.")
    sizes: list[str | None] = [None, *museum.derivatives]
    shown = text
    if "/" in text:
        # The path's shape is forgiven (Richard, October 14, 2026): no leading slash, or no museum.
        found = paths.given(museum, museums or {museum.key: museum}, text)
        shown = found.shown
        if found.problem is not None:
            raise LookupProblem(found.problem)
        parsed = paths.parse(museum, found.rest)
        if isinstance(parsed, paths.Refused):
            # A Blob's URL without /content (D163), or a /media/ URL (served from pull request 15): Serena doesn't
            # serve that URL, but its CSID is good, so the page says why the URL fails and then looks the Blob or
            # the Media record up on its own, every size.
            named = found.csid
            if named is None or (named[0] == "blob" and BARE_BLOB.match(found.rest) is None):
                return {"input": shown, "refused": parsed.reason.value, "items": [],
                        "refresh": _refresh(refreshes.latest_updated(museum.key))}
            refused: str | None = parsed.reason.value
            blobs = _blobs_of(store, museum, named[1])
        else:
            refused = None
            blobs = [parsed.blob_csid]
            sizes = [parsed.derivative]
    else:
        refused = None
        if not is_csid(text):
            raise LookupProblem("That isn't a CSID, a URL or a path.")
        blobs = _blobs_of(store, museum, text)
    latest = refreshes.latest_updated(museum.key)
    items = [_blob(museum, blob, sizes, store, placeholder_media) for blob in blobs]
    asked: dict[str, MediaRecord] = {}
    for item in items:
        item["cspace"] = _cspace(museum, item, store, cspace, latest, asked)
    return {"input": shown, "refused": refused, "refresh": _refresh(latest), "items": items}


def _blobs_of(store: Store, museum: Museum, csid: str) -> list[str]:
    """A Blob CSID's Blob, or a Media CSID's Blobs; a CSID Serena doesn't know is looked up as it is."""
    if store.servability(museum.key, csid) is not None:
        return [csid]
    return [r.blob_csid for r in rows_of_media(store, museum.key, csid)] or [csid]


def _refresh(latest: Refresh | None) -> dict[str, str] | None:
    return ({"refresh_id": latest.refresh_id, "refresh_date": latest.refresh_date, "started_at": latest.created_at}
            if latest else None)


def _ask(cspace: CSpaceClient, museum: Museum, media_csid: str, asked: dict[str, MediaRecord]) -> MediaRecord:
    """One call per Media record per look up (two listed Blobs of one record share it)."""
    if media_csid not in asked:
        asked[media_csid] = cspace.media_record(media_csid, [(f.part, f.field, f.label) for f in museum.lookup_fields])
    return asked[media_csid]


def _cspace(museum: Museum, item: dict[str, Any], store: Store, cspace: CSpaceClient | None, latest: Refresh | None,
            asked: dict[str, MediaRecord]) -> dict[str, Any]:
    """What CollectionSpace says now about the item's Media record (D139), and what the next refresh will do (D141).
    Adjusts the sizes a fetch would refuse because the record is deleted or gone."""
    listed = item["kind"] is not None
    if listed and item["media_csid"] is None:
        return {"state": "no_media"}  # the placeholder image
    if cspace is None:
        return {"state": "unavailable"}
    csid = item["media_csid"] if listed else item["blob_csid"]
    try:
        record = _ask(cspace, museum, csid, asked)
        media = csid
        if not listed and record.state is MediaState.GONE:
            found = cspace.media_of_blob(csid)  # a Blob CSID: its Media record, if any
            if found:
                media, record = found, _ask(cspace, museum, found, asked)
    except CSpaceError as error:
        log.warning("Media look up: CollectionSpace not asked", extra={"museum": museum.key,
                                                                         "error": type(error).__name__})
        return {"state": "unavailable"}
    if record.state is MediaState.GONE:
        if listed:
            _refuse_fetches(item, Reason.MEDIA_GONE)
        return {"state": "gone", "next": "CollectionSpace has no such Media record now. The next refresh drops this "
                "Blob." if listed else "CollectionSpace has no Blob or Media record with this CSID either."}
    changed = _after(record.updated_at, latest.created_at if latest else None)
    if record.state is MediaState.DELETED and listed:
        _refuse_fetches(item, Reason.MEDIA_DELETED)
    recall = store.recall(museum.key, media) if listed else None
    return {"state": str(record.state), "media_csid": media, "blob_csid": record.blob_csid,
            "identification_number": record.identification_number,
            "updated_at": record.updated_at, "changed_since_refresh": changed,
            "fields": [{"label": label, "value": value} for label, value in record.fields],
            "next": _next(listed, item["blob_csid"], kind_word(item["kind"]), record, changed,
                          recall.kept_by if recall else None,
                          recall is not None)}


def _refuse_fetches(item: dict[str, Any], reason: Reason) -> None:
    """A size without a stored copy is fetched on its next request, and the fetch would refuse it (design: Image
    fetch); stored sizes are still served."""
    for size in item["sizes"]:
        if size["served"] and not size["stored"]:
            size.update(served=False, reason=reason.value, verdict="not served: a fetch would find the Media record "
                        + ("soft-deleted" if reason is Reason.MEDIA_DELETED else "gone") + " in CollectionSpace")


def _after(updated_at: str | None, started_at: str | None) -> bool:
    if not updated_at or not started_at:
        return False
    try:
        return datetime.fromisoformat(updated_at.replace("Z", "+00:00")) > datetime.fromisoformat(started_at)
    except ValueError:
        return False


def _next(listed: bool, blob: str, noun: str, record: MediaRecord, changed: bool, kept_by: str | None,
          recalled: bool) -> str:
    """What the next refresh will do (D141): only what Serena can tell for any museum. The ETL's rules decide what's
    public, so a change to the record says only that the next refresh will show the result."""
    if not listed:
        if changed:
            return ("The Media record changed in CollectionSpace after the last refresh: the next refresh shows "
                    "whether it's public now.")
        return ("CollectionSpace has it, but the ETL's rules left it out of the servable list (for example, it isn't "
                "published, or its Object is marked sensitive). Nothing changes at the next refresh unless the "
                "record does.")
    if record.state is MediaState.DELETED:
        return ("The Media record is soft-deleted in CollectionSpace. The next refresh drops this Blob; until then, "
                "only its cached sizes are served.")
    if record.blob_csid and record.blob_csid != blob:
        if changed:
            return ("The Media record has a new Blob in CollectionSpace since the last refresh. The next refresh lists "
                    f"the new Blob and drops this one; until then, a cached size is the old {noun}, and any other size "
                    "is fetched from the Media record, which returns the new one.")
        return ("CollectionSpace's Media record has another Blob. The servable list still has this one, and a request "
                f"for it is answered with the Media record's current {noun}.")
    if changed:
        return ("The Media record changed in CollectionSpace after the last refresh. The next refresh shows whether "
                "it's still public" + (", and ends the recall if it isn't." if recalled else "."))
    if kept_by:
        return ("Nothing has changed in CollectionSpace since the last refresh: the next refresh lists it again and "
                "keeps the recall, with another alert, unless staff change the record or an admin releases the "
                "recall.")
    if recalled:
        return ("Nothing has changed in CollectionSpace since the last refresh: unless staff change the record, the "
                "next refresh lists it, keeps the recall and alerts.")
    return "Nothing has changed in CollectionSpace since the last refresh."


def _blob(museum: Museum, blob: str, sizes: list[str | None], store: Store,
          placeholder_media: str | None = None) -> dict[str, Any]:
    record = store.servability(museum.key, blob)
    steps = []
    if record is None:
        steps.append(_step("In the servable list", "Not in the servable list of the last servability update.",
                           False))
    else:
        steps.append(_step("In the servable list", "Listed in the servable list of the last servability update.",
                           True))
        steps.append(_step("Kind", kind_word(record.kind) + ("" if record.kind in SERVED_KINDS else ": not served"),
                           record.kind in SERVED_KINDS))
        if record.access == "public":
            steps.append(_step("Access", "public", True))
        elif record.access == "restricted" and record.kind in museum.signed_access_kinds:
            steps.append(_step("Access", "restricted: served only on a portal's valid signed link", None))
        else:
            steps.append(_step("Access", f"{record.access}: not served", False))
        if record.media_csid is None:
            steps.append(_step("Recall", "No Media record (the museum's placeholder image).", True))
        else:
            recall = store.recall(museum.key, record.media_csid)
            if recall is None:
                steps.append(_step("Recall", "No recall.", True))
            else:
                kept = (f" Refresh {recall.kept_by} kept it: the {kind_word(record.kind)} is still public in "
                        "CollectionSpace." if recall.kept_by else "")
                steps.append(_step("Recall", f"Recalled by {recall.by} at {recall.at}: {recall.reason}."
                                   + kept, False))
        if blob == museum.placeholder_blob_csid:
            steps.append(_step("Placeholder image", f"The museum's placeholder image: served from Media record "
                               f"{placeholder_media}, named on the Settings page." if placeholder_media else
                               "The museum's placeholder image: no Media record is named for it on the Settings page, "
                               "so a request gets Serena's generic picture.", placeholder_media is not None))
    if record is not None and record.kind in ORIGINAL_ONLY_KINDS:
        sizes = [s for s in sizes if s is None] or sizes  # derivatives of a PDF or 3D file are never served
    return {"blob_csid": blob, "media_csid": record.media_csid if record else None,
            "kind": record.kind if record else None, "access": record.access if record else None,
            "steps": steps, "sizes": [_size(museum, blob, size, store, placeholder_media) for size in sizes]}


def _size(museum: Museum, blob: str, size: str | None, store: Store,
          placeholder_media: str | None = None) -> dict[str, Any]:
    decision = decide(museum, paths.BlobRequest(museum.key, blob, size), store,  # no signed link
                      placeholder_media=placeholder_media)
    reason = decision.reason
    if reason is None and size in museum.watermark_sizes:
        reason = Reason.WATERMARK_NOT_BUILT
    entry = cache_index.lookup(store, museum.key, blob, size)
    stored = ({"fetched_at": entry.fetched_at, "last_served": entry.last_served, "size": entry.size,
               "content_type": entry.content_type} if entry else None)
    if reason is not None:
        verdict = "not served"
    elif stored:
        verdict = "served from the cached copy"
    else:
        verdict = "served: would be fetched on the next request"
    return {"size": size or "original", "served": reason is None, "reason": reason.value if reason else None,
            "verdict": verdict, "stored": stored}
