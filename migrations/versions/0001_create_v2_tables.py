"""Create the eight version-2 tables.

Revision ID: 0001
Revises:
Create Date: 2026-09-09

The schema is built from the ORM metadata rather than from a second, hand-copied
list of ``op.create_table`` calls. There is one reason: the check constraints and
indexes in ``api/servicedesk/db/models.py`` are part of the specification, and a
duplicate definition here would eventually disagree with them without anything
failing. This project has no deployed v2 database to migrate, so the first
revision only has to be correct once, on an empty database, in both dialects.

Later revisions that change a table will use explicit operations, because from
that point the difference between the old and new shape is the thing being
expressed.
"""
from alembic import op

from api.servicedesk.db.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

#: The tables this revision owns, in dependency order.
V2_TABLES = (
    "users",
    "sessions",
    "agents",
    "agent_skills",
    "sla_policies",
    "tickets",
    "assignment_decisions",
    "ticket_events",
)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[n] for n in V2_TABLES])


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(
        bind=bind, tables=[Base.metadata.tables[n] for n in reversed(V2_TABLES)]
    )
