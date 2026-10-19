"""Give an escalation review a target and an opening time.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-10

Before this revision a ticket could enter ``escalation_review`` and nothing
recorded who the review was with or when it started. The status was therefore a
state a ticket entered and never left, which is the same defect as the
record-only acknowledgement it replaced, one level up.

Two nullable columns fix it. They are NULL for every ticket that is not in
review, which is why no backfill runs here: a closed or never-opened review has
no target by definition, and inventing one would put a fact in the database that
nobody stated.

Guarded by the inspector for the reason revision 0003 explains: migration 0001
builds tables from the ORM metadata, so a database created after these columns
were added to ``models.py`` already has them.
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("tickets")}
    if "escalation_target" not in columns:
        op.add_column(
            "tickets", sa.Column("escalation_target", sa.String(32), nullable=True)
        )
    if "escalation_opened_at" not in columns:
        op.add_column(
            "tickets",
            sa.Column("escalation_opened_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("tickets", "escalation_opened_at")
    op.drop_column("tickets", "escalation_target")
