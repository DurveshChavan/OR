"""The audit trail cannot be rewritten, and the database is what stops it.

These tests go around the ORM and issue raw UPDATE and DELETE statements,
because the claim under test is about the database, not about application
discipline. If a future change drops the triggers, the ORM would happily
comply and only these tests would notice.
"""
import sqlalchemy as sa

from api.servicedesk.db import models


#: Both dialects raise a message containing this phrase, and nothing else in the
#: schema does. Matching on it distinguishes the trigger from the other reasons
#: a statement can fail - a foreign key on ticket_events would reject a decision
#: delete just as loudly, and the test would look green while the trigger was
#: missing.
APPEND_ONLY_MESSAGE = "append-only"


def _raw_update_rejected(engine, table, row_id, column, value):
    statement = sa.text(
        "UPDATE %s SET %s = :value WHERE id = :row_id" % (table, column)
    )
    with engine.begin() as connection:
        try:
            connection.execute(statement, {"value": value, "row_id": row_id})
        except sa.exc.DatabaseError as exc:
            return APPEND_ONLY_MESSAGE in str(exc)
    return False


def _raw_delete_rejected(engine, table, row_id):
    statement = sa.text("DELETE FROM %s WHERE id = :row_id" % table)
    with engine.begin() as connection:
        try:
            connection.execute(statement, {"row_id": row_id})
        except sa.exc.DatabaseError as exc:
            return APPEND_ONLY_MESSAGE in str(exc)
    return False


def test_ticket_event_cannot_be_updated(engine, make_ticket, make_event):
    event = make_event(make_ticket())
    assert _raw_update_rejected(
        engine, "ticket_events", event.id, "event_type", "TICKET_UPDATED"
    )


def test_ticket_event_cannot_be_deleted(engine, make_ticket, make_event):
    event = make_event(make_ticket())
    assert _raw_delete_rejected(engine, "ticket_events", event.id)


def test_assignment_decision_cannot_be_updated(engine, make_ticket, make_agent, make_decision):
    decision = make_decision(make_ticket(), make_agent())
    assert _raw_update_rejected(
        engine, "assignment_decisions", decision.id, "reason_text", "rewritten"
    )


def test_assignment_decision_cannot_be_deleted(engine, make_ticket, make_agent, make_decision):
    decision = make_decision(make_ticket(), make_agent())
    assert _raw_delete_rejected(engine, "assignment_decisions", decision.id)


def test_rejected_update_leaves_the_row_exactly_as_written(
    engine, db, make_ticket, make_event
):
    event = make_event(make_ticket(), payload={"note": "original"})
    original_type = event.event_type
    _raw_update_rejected(engine, "ticket_events", event.id, "event_type", "TICKET_UPDATED")
    stored = db.get(models.TicketEvent, event.id)
    db.refresh(stored)
    assert stored.event_type == original_type
    assert stored.payload_json == {"note": "original"}


def test_a_ticket_row_is_still_updatable(db, make_ticket):
    """Only the two append-only tables are frozen; current state must still move."""
    ticket = make_ticket(status="open")
    ticket.status = "assigned"
    db.commit()
    db.refresh(ticket)
    assert ticket.status == "assigned"


def test_a_decision_delete_is_stopped_by_the_trigger_not_a_foreign_key(
    engine, make_ticket, make_agent, make_decision
):
    """A decision with no events referring to it is still undeletable."""
    decision = make_decision(make_ticket(), make_agent())
    statement = sa.text("DELETE FROM assignment_decisions WHERE id = :row_id")
    with engine.begin() as connection:
        referring_events = connection.execute(
            sa.text("SELECT count(*) FROM ticket_events WHERE decision_id = :row_id"),
            {"row_id": decision.id},
        ).scalar()
        assert referring_events == 0
        try:
            connection.execute(statement, {"row_id": decision.id})
        except sa.exc.DatabaseError as exc:
            assert APPEND_ONLY_MESSAGE in str(exc)
            return
    raise AssertionError("an unreferenced decision row was deleted")
