"""Machine register, and the operator-set link from a ticket to a machine.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-10

The replacement advisor needs an asset register, and no dataset in this project
supplies one: UCI-498 records incidents and carries no hardware telemetry and no
ticket-to-asset key. So the register is a table an operator fills in from their
own purchasing and maintenance records, and `tickets.machine_id` is a link a
human states rather than one anything infers.

Written as explicit operations rather than from ORM metadata, because migration
0001 already built the earlier tables and a metadata-driven revision here would
try to create them again.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

MACHINE_TYPES = ("desktop", "laptop", "server", "kiosk")


def _in_set(column, allowed):
    values = ", ".join("'%s'" % value for value in allowed)
    return "%s IN (%s)" % (column, values)


def upgrade() -> None:
    """Create what is missing, and nothing else.

    Migration 0001 builds the original tables **from the ORM metadata**, so the
    moment `Machine` and `Ticket.machine_id` were added to `models.py`, a fresh
    database started arriving at revision 0001 already carrying both. An
    unconditional CREATE here fails on a new database and an unconditional skip
    fails on a database migrated before today. Asking the inspector is the only
    version that is correct for both, and it is why this revision reads the
    schema instead of assuming it.
    """
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "machines" not in tables:
        _create_machines()
    ticket_columns = {column["name"] for column in inspector.get_columns("tickets")}
    if "machine_id" not in ticket_columns:
        _add_ticket_machine_id()
    _ensure_index(inspector, "machines", "ix_machines_location", ["location"])
    _ensure_index(inspector, "tickets", "ix_tickets_machine_id", ["machine_id"])


def _ensure_index(inspector, table, name, columns) -> None:
    existing = {index["name"] for index in inspector.get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns)


def _create_machines() -> None:
    op.create_table(
        "machines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("asset_tag", sa.String(64), nullable=False, unique=True),
        sa.Column("location", sa.String(64), nullable=True),
        sa.Column("machine_type", sa.String(16), nullable=False, server_default="desktop"),
        sa.Column("age_months", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("age_recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purchase_cost", sa.Float(), nullable=False),
        sa.Column("scrap_value_by_year_json", sa.Text(), nullable=False),
        sa.Column("running_cost_by_year_json", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_in_set("machine_type", MACHINE_TYPES), name="ck_machines_type"),
        sa.CheckConstraint("age_months >= 0", name="ck_machines_age_non_negative"),
        sa.CheckConstraint("purchase_cost > 0", name="ck_machines_purchase_positive"),
    )


def _add_ticket_machine_id() -> None:
    # Two dialects, two ways to reach the same column, and neither is
    # batch_alter_table: rebuilding `tickets` through the batch context raises a
    # CircularDependencyError on this table's column set. SQLite accepts an
    # inline REFERENCES clause on ADD COLUMN, which is the whole reason a table
    # rebuild is not needed here; PostgreSQL takes the constraint as a separate
    # ALTER. Both end with a real foreign key, so the dialects do not drift.
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            "ALTER TABLE tickets ADD COLUMN machine_id VARCHAR(36) "
            "REFERENCES machines(id)"
        )
    else:
        op.add_column("tickets", sa.Column("machine_id", sa.String(36), nullable=True))
        op.create_foreign_key(
            "fk_tickets_machine_id", "tickets", "machines", ["machine_id"], ["id"]
        )


def downgrade() -> None:
    op.drop_index("ix_tickets_machine_id", table_name="tickets")
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("fk_tickets_machine_id", "tickets", type_="foreignkey")
    op.drop_column("tickets", "machine_id")
    op.drop_index("ix_machines_location", table_name="machines")
    op.drop_table("machines")
