"""Shared route dependencies: the session, the request id, and the actor."""
from fastapi import Depends, Request
from sqlalchemy.orm import Session as DbSession

from api.app_v2.db import models
from api.app_v2.db.session import get_db
from api.app_v2.services import auth


def request_id(request: Request) -> str:
    """The id assigned by the middleware, echoed in every response."""
    return getattr(request.state, "request_id", "unknown")


def current_user(
    request: Request, db: DbSession = Depends(get_db)
) -> models.User:
    """The signed-in user, or a 401 in the project's error envelope."""
    token = request.cookies.get(auth.SESSION_COOKIE_NAME)
    return auth.resolve_session(db, token)


def current_manager(user: models.User = Depends(current_user)) -> models.User:
    """A signed-in manager, for policy and rescore actions."""
    return auth.require_role(user, "manager")
