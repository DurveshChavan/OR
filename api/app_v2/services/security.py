"""Password hashing and session tokens.

Passwords are hashed with Argon2id through argon2-cffi. A plain password is
never stored, never logged, and never returned.

The session cookie carries a random 256-bit token. Only the SHA-256 of that
token is stored, as the ``sessions`` primary key, so a database dump does not
hand out working sessions. Hashing here is a plain digest rather than a slow
KDF on purpose: the token already has full entropy, so there is nothing to
brute-force in the way a human-chosen password can be.
"""
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

#: Verified against on a failed login so that a missing username and a wrong
#: password cost the same time. Without it, response timing tells an attacker
#: which usernames exist, which spec D.1 forbids revealing.
_DUMMY_HASH = _hasher.hash("timing-equalisation-placeholder")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError):
        return False


def spend_dummy_verification() -> None:
    """Do the work of a real check against a throwaway hash."""
    verify_password(_DUMMY_HASH, "wrong-password")


def new_session_token() -> str:
    """A fresh opaque cookie value."""
    return secrets.token_urlsafe(32)


def session_id_for(token: str) -> str:
    """The stored identifier for a cookie token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
