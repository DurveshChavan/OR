"""The migration head is reachable, and it produces the schema the spec names."""
import sqlalchemy as sa

from api.servicedesk.db import models

EXPECTED_TABLES = {
    "users",
    "sessions",
    "agents",
    "agent_skills",
    "sla_policies",
    "tickets",
    "assignment_decisions",
    "ticket_events",
    # Added by revision 0003: the operator-maintained machine register the
    # replacement advisor reads. It holds no mined or predicted value.
    "machines",
}

#: Tables the review explicitly decided not to create. Their absence is a
#: design decision, so it is asserted rather than assumed.
FORBIDDEN_TABLES = {"assignments", "assignment_runs", "model_versions"}


def test_head_creates_exactly_the_declared_tables(engine):
    tables = set(sa.inspect(engine).get_table_names())
    assert EXPECTED_TABLES <= tables
    assert FORBIDDEN_TABLES.isdisjoint(tables)
    # alembic_version is the only extra table a migrated database may carry.
    assert tables - EXPECTED_TABLES <= {"alembic_version"}


def test_tickets_has_the_three_required_indexes(engine):
    indexes = sa.inspect(engine).get_indexes("tickets")
    columns = {tuple(index["column_names"]) for index in indexes}
    assert ("status", "sla_due_at") in columns
    assert ("status", "priority", "risk_probability") in columns
    assert ("current_assignee_id",) in columns


def test_priority_outside_one_to_four_is_rejected(engine):
    from datetime import timedelta

    from api.servicedesk.db.types import utcnow

    opened = utcnow()
    with engine.begin() as connection:
        with_bad_priority = sa.insert(models.Ticket.__table__).values(
            id="ticket-bad-priority",
            source="manual",
            status="open",
            priority=9,
            opened_at=opened,
            sla_due_at=opened + timedelta(minutes=60),
            created_at=opened,
            updated_at=opened,
        )
        try:
            connection.execute(with_bad_priority)
        except sa.exc.IntegrityError:
            return
        raise AssertionError("priority 9 was accepted; the check constraint is missing")


def test_risk_probability_above_one_is_rejected(db, make_ticket):
    ticket = make_ticket()
    ticket.risk_probability = 1.4
    db.add(ticket)
    try:
        db.commit()
    except sa.exc.IntegrityError:
        db.rollback()
        return
    raise AssertionError("risk probability 1.4 was accepted; the range check is missing")


def test_sla_due_must_follow_opened_at(db, make_ticket):
    from datetime import timedelta

    from api.servicedesk.db.types import utcnow

    opened = utcnow()
    try:
        make_ticket(opened_at=opened, sla_due_at=opened - timedelta(minutes=1))
    except sa.exc.IntegrityError:
        db.rollback()
        return
    raise AssertionError("a deadline before the open time was accepted")
