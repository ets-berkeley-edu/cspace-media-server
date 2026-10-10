"""Errors as application/problem+json (RFC 9457), with reasons and never internals (design: The ETL API)."""
from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel

MEDIA_TYPE = "application/problem+json"


class Problem(BaseModel):
    """An error: `type` names its kind, `title` says what it is, `detail` what to do about it."""

    type: str
    title: str
    status: int
    detail: str = ""


class ProblemError(Exception):
    """Raised by the API's handlers; turned into a problem+json response."""

    def __init__(self, status: int, kind: str, title: str, detail: str = "", headers: dict[str, str] | None = None):
        super().__init__(title)
        self.problem = Problem(type=f"https://github.com/ets-berkeley-edu/cspace-media-server/blob/main/docs/design.md#{kind}",
                               title=title, status=status, detail=detail)
        self.headers = headers or {}


def response(problem: Problem, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(problem.model_dump(), status_code=problem.status, media_type=MEDIA_TYPE,
                        headers={"Cache-Control": "no-store", **(headers or {})})


def openapi_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """The error responses an endpoint documents."""
    meaning = {400: "A header or parameter is missing or malformed", 401: "No token, or a token Serena doesn't know",
               403: "The token is for another museum", 404: "No such museum or run",
               409: "The call is out of order for the run's state", 413: "The file is larger than Serena accepts",
               415: "The file isn't sent as text/tab-separated-values",
               422: "The file doesn't match its row count or SHA-256",
               503: "Serena can't check right now (tokens or storage unavailable); try again"}
    schema = {"$ref": "#/components/schemas/Problem"}
    return {status: {"description": meaning[status], "content": {MEDIA_TYPE: {"schema": schema}}}
            for status in statuses}
