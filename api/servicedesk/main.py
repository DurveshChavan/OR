"""The service-desk FastAPI application.

Two processes serve this project, and they are separate on purpose::

    uvicorn api.servicedesk.main:app --port 8001    # the product
    uvicorn api.main:app             --port 8000    # the Operations Research engine

The product is what a dispatcher uses. The engine is what the Methods section
reads, and it answers on its own port so the two never collide on ``/api``; the
dev server reaches it through an ``/or-api`` prefix it strips.

The product imports one thing from ``api.engine``: the deteriorating-item
replacement method, which the Hardware screen shows. That is deliberate, and it
is the only one - reimplementing an average-cost table inside the application
would create a second definition of a figure that gets checked by hand.

Handlers are synchronous, and so are the database sessions. For a single
machine serving one dispatch team that is a smaller thing to explain and a
smaller thing to get wrong than an async stack.
"""
import uuid

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.servicedesk import deps, errors
from api.servicedesk.db.session import get_engine
from api.servicedesk.domain import schemas
from api.servicedesk.routes import agents as agents_routes
from api.servicedesk.routes import auth as auth_routes
from api.servicedesk.routes import decisions as decision_routes
from api.servicedesk.routes import hardware as hardware_routes
from api.servicedesk.routes import radar as radar_routes
from api.servicedesk.routes import rescore as rescore_routes
from api.servicedesk.routes import tickets as tickets_routes
from api.servicedesk.services import scoring

API_PREFIX = "/api"

app = FastAPI(
    title="SLA-aware service desk (the application)",
    version="1.0.0",
    description=(
        "SLA-aware ticket allocation with an auditable decision history. "
        "Authentication, tickets, agents, the audit trail, recommendation, "
        "acceptance, override, manual rescore and Risk Radar."
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
# The rescore router owns POST /tickets/rescore and must be mounted before the
# ticket router, whose GET /tickets/{ticket_id} would otherwise not conflict but
# whose ordering is easier to reason about with the fixed path registered first.
app.include_router(rescore_routes.router, prefix=API_PREFIX)
app.include_router(tickets_routes.router, prefix=API_PREFIX)
app.include_router(agents_routes.router, prefix=API_PREFIX)
app.include_router(decision_routes.router, prefix=API_PREFIX)
app.include_router(radar_routes.router, prefix=API_PREFIX)
app.include_router(hardware_routes.router, prefix=API_PREFIX)


@app.get(API_PREFIX + "/health", response_model=schemas.HealthResponse, tags=["health"])
def health(request_id: str = Depends(deps.request_id)) -> schemas.HealthResponse:
    """Liveness, the dialect, migration state, and which artifacts are loaded.

    The model versions are here because the demo has to be able to answer "which
    model produced that number?" without opening a database, and because a build
    with no usable artifact should say so on its health endpoint rather than at
    the first ticket creation.
    """
    engine = get_engine()
    with engine.connect() as connection:
        head_present = engine.dialect.has_table(connection, "alembic_version")
    try:
        risk_version, duration_version = scoring.available_versions()
        models_available = True
    except errors.ApiError:
        risk_version = duration_version = None
        models_available = False
    return schemas.HealthResponse(
        status="ok",
        dialect=engine.dialect.name,
        migration_head_present=bool(head_present),
        models_available=models_available,
        risk_model_version=risk_version,
        duration_model_version=duration_version,
        request_id=request_id,
    )
