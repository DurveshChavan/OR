"""Declarative base and shared column conventions."""
import uuid

from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase

#: Identifiers are UUID4 rendered as 36-character text. Text keeps the same
#: representation on PostgreSQL and SQLite and keeps IDs readable in an audit
#: export without a dialect-specific UUID type.
ID_LENGTH = 36
IdColumn = String(ID_LENGTH)


class Base(DeclarativeBase):
    """Base class for every service-desk table."""


def new_id() -> str:
    """A fresh identifier for any row in this schema."""
    return str(uuid.uuid4())
