"""Column types that behave the same on PostgreSQL and SQLite.

PostgreSQL is the normal deployment mode and SQLite is the supported
offline demo and test mode (spec C.1). Two differences between them would
otherwise leak into application code, so both are handled here instead:

* SQLite has no timezone-aware timestamp. `UtcDateTime` stores every value
  as naive UTC and hands every value back tz-aware, so application code
  only ever sees aware UTC datetimes on either dialect.
* PostgreSQL has `JSONB` and SQLite does not. The spec forbids `JSONB`
  precisely so the fallback stays real, so `CanonicalJson` stores sorted-key
  JSON in a `TEXT` column. Sorted keys also make a stored decision payload
  byte-comparable across runs, which the audit trail relies on.
"""
import json
from datetime import datetime, timezone

from sqlalchemy import DateTime, Text
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator):
    """Timestamp that is UTC-aware in Python and naive UTC in the database."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"expected datetime, got {type(value).__name__}")
        if value.tzinfo is None:
            raise ValueError("naive datetime rejected; pass an aware UTC datetime")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class CanonicalJson(TypeDecorator):
    """A JSON object stored as canonical text: sorted keys, compact separators."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return dumps_canonical(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return json.loads(value)


def dumps_canonical(payload) -> str:
    """Serialise `payload` the one way this application ever serialises it."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def utcnow() -> datetime:
    """Current time as an aware UTC datetime."""
    return datetime.now(timezone.utc)
