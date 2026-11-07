"""Both accounts checked before anything runs (serenade/qa/conftest.py, pytest_collection_finish): a run that can't
sign in should stop in seconds, saying which account and why, not after it has started changing things in QA.

- The admin account: Serena's own sign-in (POST /admin/v1/sessions), which asks PAHMA's CollectionSpace and checks the
  Serena admin role. It's a real sign-in (the admin app's audit log records it); the browser signs in again after.
- The CollectionSpace account make-test-media.py uses: one read (a page of one Media record).

Passwords go only in a request's body or Authorization header, never in a URL, a message or an exception."""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any

from serenade.secret import Secret

TIMEOUT = 30


def _request(url: str, **kwargs: Any) -> urllib.request.Request:
    if not url.startswith("https://"):
        raise SystemExit(f"Only https addresses are signed in to, not {url.split('?')[0]}")
    return urllib.request.Request(url, **kwargs)  # noqa: S310 (https only, checked above)


def _send(request: urllib.request.Request) -> tuple[int, str]:
    """The status and body; 0 and the reason when nothing answered."""
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:  # noqa: S310 (https only: _request)
            return answer.status, answer.read(2000).decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read(2000).decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", error)
        return 0, str(reason)


def _detail(body: str) -> str:
    try:
        parsed: Any = json.loads(body)
    except ValueError:
        return ""
    detail = parsed.get("detail") if isinstance(parsed, dict) else None
    return detail if isinstance(detail, str) else ""


def admin_problem(app_url: str, museum: str, username: str, password: Secret) -> str | None:
    """Why the admin account can't sign in to Serena for this museum, or None if it can."""
    body = json.dumps({"museum": museum, "username": username, "password": password}).encode()
    request = _request(f"{app_url.rstrip('/')}/admin/v1/sessions", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "X-Serena-Admin": "1"})
    status, text = _send(request)
    if status == 200:
        return None
    if status == 0:
        return f"Serena's admin app didn't answer ({text})"
    return f"Serena refused the admin sign-in ({status}): {_detail(text) or 'no message'}"


def cspace_problem(base: str, username: str, password: Secret) -> str | None:
    """Why make-test-media.py's account can't read PAHMA QA's CollectionSpace, or None if it can."""
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    request = _request(f"{base.rstrip('/')}/media?pgSz=1&wf_deleted=false",
                                     headers={"Authorization": f"Basic {token}", "Accept": "application/xml"})
    status, text = _send(request)
    if status == 200:
        return None
    if status == 0:
        return f"CollectionSpace didn't answer ({text})"
    if status in (401, 403):
        return f"CollectionSpace refused SERENADE_CSPACE_USER ({status}): check the username and password"
    return f"CollectionSpace answered {status} to a read as SERENADE_CSPACE_USER"
