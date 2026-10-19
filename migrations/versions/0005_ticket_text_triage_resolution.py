"""Give a ticket words, ITIL impact and urgency, and a resolution time.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-15

Five nullable columns on ``tickets``: ``title`` and ``description`` (what the
caller reported), ``impact`` and ``urgency`` (the ITIL pair priority is derived
from), and ``resolved_at`` (when the ticket was resolved, so a breach can be
read against the fixed deadline). No backfill: an older ticket has no title
because nobody wrote one, and inventing one would be a fact nobody stated.

No CHECK constraints are added. SQLite can only add one by rebuilding the
table, and rebuilding ``tickets`` here is not worth the risk for a range the API
already validates. Guarded by the inspector for the reason revision 0003 gives.
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

NEW_COLUMNS = (
    ("title", lambda: sa.String(200)),
    ("description", sa.Text),
    ("impact", sa.Integer),
    ("urgency", sa.Integer),
    ("resolved_at", lambda: sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("tickets")}
    for name, column_type in NEW_COLUMNS:
        if name not in existing:
            op.add_column("tickets", sa.Column(name, column_type(), nullable=True))


def downgrade() -> None:
    for name, _column_type in reversed(NEW_COLUMNS):
        op.drop_column("tickets", name)
