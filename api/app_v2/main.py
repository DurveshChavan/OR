"""The version-2 FastAPI application.

Runs beside the legacy Operations Research API, never on top of it::

    uvicorn api.main:app        --port 8000    # legacy demo, still the default
    uvicorn api.app_v2.main:app --port 8001    # this application

Everything is mounted under ``/api/v2`` so the two can be served together
during the transition and the legacy route stays the default until the phase 5
cutover. This package imports nothing from ``api.engine``: the OR modules stay
exactly as the viva will read them.

Handlers are synchronous, and so are the database sessions. For a single
machine serving one dispatch team that is a smaller thing to explain and a
smaller thing to get wrong than an async stack.
"""
import uuid

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.app_v2 import deps, errors
from api.app_v2.db.session import get_engine
from api.app_v2.domain import schemas
from api.app_v2.routes import agents as agents_routes
from api.app_v2.routes import auth as auth_routes
from api.app_v2.routes import tickets as tickets_routes

API_PREFIX = "/api/v2"

app = FastAPI(
    title="SLA-aware service desk (v2)",
    version="2.0.0-phase1",
    description=(
        "SLA-aware ticket allocation with an auditable decision history. "
        "Phase 1 covers authentication, tickets, agents and the audit trail; "
        "recommendation and rescore endpoints arrive in later phases."
    ),
)

# The client runs on the Vite dev server during development and is served from
# the same origin in the demo, so credentials must be allowed for the session
# cookie to survive the cross-origin case.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    """Give every request an id, echo it in the body and in a header."""
    request.state.request_id = uuid.uuid4().hex
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


app.add_exception_handler(errors.ApiError, errors.api_error_handler)
app.add_exception_handler(RequestValidationError, errors.validation_error_handler)
app.add_exception_handler(StarletteHTTPException, errors.http_error_handler)

app.include_router(auth_routes.router, prefix=API_PREFIX)
app.include_router(tickets_routes.router, prefix=API_PREFIX)
app.include_router(agents_routes.router, prefix=API_PREFIX)


@app.get(API_PREFIX + "/health", response_model=schemas.HealthResponse, tags=["health"])
def health(request_id: str = Depends(deps.request_id)) -> schemas.HealthResponse:
    """Liveness, the dialect in use, and whether migrations have been run."""
    engine = get_engine()
    with engine.connect() as connection:
        head_present = engine.dialect.has_table(connection, "alembic_version")
    return schemas.HealthResponse(
        status="ok",
        dialect=engine.dialect.name,
        migration_head_present=bool(head_present),
        request_id=request_id,
    )
