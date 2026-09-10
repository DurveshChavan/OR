"""One error envelope for every service-desk response (spec D).

A client that has to guess the shape of a failure ends up showing "something
went wrong". Every failure here carries a machine-readable code, a sentence a
dispatcher can act on, and the identifiers involved::

    {"error": {"code": "AGENT_NOT_ELIGIBLE", "message": "...", "details": {...}},
     "request_id": "..."}

Nothing in `details` may carry a password hash, a session token, model
internals, or a historical outcome the user is not entitled to see.
"""
from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """A failure with a stable code, raised anywhere below the route layer."""

    def __init__(self, code: str, message: str, status_code: int = 400, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def error_body(code: str, message: str, request_id: str, details=None) -> dict:
    return {
        "error": {"code": code, "message": message, "details": details or {}},
        "request_id": request_id,
    }


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(exc.code, exc.message, request_id, exc.details),
    )


async def validation_error_handler(request: Request, exc) -> JSONResponse:
    """FastAPI's own request validation, re-dressed in the project envelope."""
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=422,
        content=error_body(
            "REQUEST_INVALID",
            "The request body failed validation.",
            request_id,
            {"fields": _summarise_validation(exc)},
        ),
    )


def _summarise_validation(exc) -> list:
    summary = []
    for error in getattr(exc, "errors", lambda: [])():
        location = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
        summary.append({"field": location, "problem": error.get("msg", "invalid")})
    return summary


async def http_error_handler(request: Request, exc) -> JSONResponse:
    """Starlette's HTTPException, so a 404 looks like every other failure."""
    request_id = getattr(request.state, "request_id", "unknown")
    code = {401: "NOT_AUTHENTICATED", 403: "NOT_PERMITTED", 404: "NOT_FOUND"}.get(
        exc.status_code, "REQUEST_FAILED"
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(code, str(exc.detail), request_id),
    )
