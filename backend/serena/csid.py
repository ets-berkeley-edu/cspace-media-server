"""What Serena accepts as a CollectionSpace CSID (design: URLs).

Most CSIDs are UUIDs, but CollectionSpace doesn't require it: a record created by an import keeps the CSID it was
given (PAHMA's restricted-image Blob has a shorter one). So a CSID is 1 to 64 letters, digits and hyphens. The check
only keeps malformed paths out; whether a Blob is served is decided by the nightly Blob-to-Media file."""
import re

CSID_PATTERN = re.compile(r"[A-Za-z0-9-]{1,64}")


def is_csid(value: str) -> bool:
    return CSID_PATTERN.fullmatch(value) is not None
