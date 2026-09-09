"""Sign in and sign out (spec D.1)."""
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session as DbSession

from api.app_v2 import deps
from api.app_v2.db.session import get_db
from api.app_v2.domain import schemas
from api.app_v2.services import auth

router = APIRouter(tags=["auth"])

#: Eight hours, matching SESSION_LIFETIME, expressed for the cookie.
_COOKIE_MAX_AGE = int(auth.SESSION_LIFETIME.total_seconds())


def _set_session_cookie(response: Response, token: str, request: Request) -> None:
    """Server-side session cookie. The token never reaches JavaScript."""
    response.set_cookie(
        auth.SESSION_COOKIE_NAME,
        token,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        # Secure is set only over HTTPS: forcing it on the http://localhost demo
        # would make the browser drop the cookie and the demo would not sign in.
        secure=request.url.scheme == "https",
        path="/",
    )


@router.post("/login", response_model=schemas.LoginResponse)
def login(
    payload: schemas.LoginRequest,
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
    request_id: str = Depends(deps.request_id),
):
    user = auth.authenticate(db, payload.username, payload.password)
    token = auth.start_session(db, user)
    _set_session_cookie(response, token, request)
    return schemas.LoginResponse(
        actor=schemas.ActorOut(id=user.id, username=user.username, role=user.role),
        request_id=request_id,
    )


@router.post("/logout", response_model=schemas.LogoutResponse)
def logout(
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
    request_id: str = Depends(deps.request_id),
):
    auth.revoke_session(db, request.cookies.get(auth.SESSION_COOKIE_NAME))
    response.delete_cookie(auth.SESSION_COOKIE_NAME, path="/")
    return schemas.LogoutResponse(signed_out=True, request_id=request_id)


@router.get("/me", response_model=schemas.LoginResponse)
def whoami(
    user=Depends(deps.current_user),
    request_id: str = Depends(deps.request_id),
):
    """Who the cookie belongs to. The client uses this to restore its session."""
    return schemas.LoginResponse(
        actor=schemas.ActorOut(id=user.id, username=user.username, role=user.role),
        request_id=request_id,
    )
