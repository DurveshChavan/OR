"""Sign-in, server-side sessions, and actor resolution.

Every mutating endpoint resolves a signed-in user before it writes anything,
because an event whose actor is unknown is not an audit record.
"""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from api.servicedesk.db import models
from api.servicedesk.db.types import utcnow
from api.servicedesk.errors import ApiError
from api.servicedesk.services import security

#: Short enough that a forgotten browser on a shared demo machine expires,
#: long enough to get through a viva without signing in again.
SESSION_LIFETIME = timedelta(hours=8)

SESSION_COOKIE_NAME = "sla_desk_session"


def normalise_username(username: str) -> str:
    """Usernames compare case-insensitively; storage is the lower-cased form."""
    return (username or "").strip().lower()


def authenticate(db: DbSession, username: str, password: str) -> models.User:
    """Return the user for these credentials, or raise the one generic failure.

    A wrong password, an unknown username and a deactivated account all produce
    the same code and message. Distinguishing them would tell an attacker which
    usernames are real.
    """
    user = db.scalar(
        select(models.User).where(models.User.username == normalise_username(username))
    )
    if user is None:
        security.spend_dummy_verification()
        raise _invalid_credentials()
    if not security.verify_password(user.password_hash, password):
        raise _invalid_credentials()
    if not user.is_active:
        raise _invalid_credentials()
    return user


def _invalid_credentials() -> ApiError:
    return ApiError(
        "INVALID_CREDENTIALS",
        "That username and password combination was not accepted.",
        status_code=401,
    )


def start_session(db: DbSession, user: models.User) -> str:
    """Create a session row and return the cookie token, which is not stored."""
    token = security.new_session_token()
    db.add(
        models.Session(
            id=security.session_id_for(token),
            user_id=user.id,
            expires_at=utcnow() + SESSION_LIFETIME,
        )
    )
    db.flush()
    return token


def resolve_session(db: DbSession, token: str) -> models.User:
    """The signed-in user for a cookie token, or a 401."""
    if not token:
        raise _not_authenticated()
    session = db.get(models.Session, security.session_id_for(token))
    if session is None or session.revoked_at is not None or session.expires_at <= utcnow():
        raise _not_authenticated()
    user = db.get(models.User, session.user_id)
    if user is None or not user.is_active:
        raise _not_authenticated()
    return user


def revoke_session(db: DbSession, token: str) -> None:
    """Log out. Revoking an already-revoked or unknown session is not an error."""
    if not token:
        return
    session = db.get(models.Session, security.session_id_for(token))
    if session is not None and session.revoked_at is None:
        session.revoked_at = utcnow()
        db.flush()


def _not_authenticated() -> ApiError:
    return ApiError("NOT_AUTHENTICATED", "Sign in to continue.", status_code=401)


def require_role(user: models.User, *roles: str) -> models.User:
    """Guard a manager-only action."""
    if user.role not in roles:
        raise ApiError(
            "NOT_PERMITTED",
            "This action is limited to the %s role." % " or ".join(roles),
            status_code=403,
            details={"required_roles": list(roles), "actor_role": user.role},
        )
    return user
