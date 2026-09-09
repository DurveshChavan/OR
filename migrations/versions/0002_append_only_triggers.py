"""Make assignment_decisions and ticket_events append-only in the database.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-09

An audit trail that only the application refuses to rewrite is not an audit
trail: anyone with a database session can edit it, and the demo cannot show that
it is impossible. These triggers reject UPDATE and DELETE on both tables inside
the database, so the guarantee holds for the API, for a psql prompt, and for a
sqlite3 shell alike.

Both dialects are covered because SQLite is a supported operating mode, not a
convenience. PostgreSQL needs a trigger function that raises; SQLite has
RAISE(ABORT, ...) available directly in the trigger body and needs one trigger
per operation because it has no combined BEFORE UPDATE OR DELETE form.
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

APPEND_ONLY_TABLES = ("assignment_decisions", "ticket_events")

_PG_FUNCTION = """
CREATE OR REPLACE FUNCTION v2_reject_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'table % is append-only: % rejected', TG_TABLE_NAME, TG_OP;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(_PG_FUNCTION)
        for table in APPEND_ONLY_TABLES:
            op.execute(
                "CREATE TRIGGER trg_%s_append_only "
                "BEFORE UPDATE OR DELETE ON %s "
                "FOR EACH ROW EXECUTE FUNCTION v2_reject_mutation();" % (table, table)
            )
    elif bind.dialect.name == "sqlite":
        for table in APPEND_ONLY_TABLES:
            for operation in ("UPDATE", "DELETE"):
                op.execute(
                    "CREATE TRIGGER trg_%s_no_%s BEFORE %s ON %s BEGIN "
                    "SELECT RAISE(ABORT, '%s is append-only'); END;"
                    % (table, operation.lower(), operation, table, table)
                )
    else:
        raise RuntimeError(
            "append-only triggers are defined for postgresql and sqlite only; "
            "got dialect %r" % bind.dialect.name
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in APPEND_ONLY_TABLES:
            op.execute("DROP TRIGGER IF EXISTS trg_%s_append_only ON %s;" % (table, table))
        op.execute("DROP FUNCTION IF EXISTS v2_reject_mutation();")
    elif bind.dialect.name == "sqlite":
        for table in APPEND_ONLY_TABLES:
            for operation in ("update", "delete"):
                op.execute("DROP TRIGGER IF EXISTS trg_%s_no_%s;" % (table, operation))
