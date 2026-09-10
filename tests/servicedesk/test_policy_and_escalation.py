"""The two administrative actions Phase 4's screens need (spec I.4, B.1).

Both were specified before Phase 3 and neither existed after it: the SLA policy
was readable but not editable, and ``ESCALATION_ACKNOWLEDGED`` was a declared
event type that nothing wrote. The tests here are written against the property
each action must hold, not against the shape of its response.
"""
from datetime import timedelta

import pytest

from api.servicedesk.db import models
from api.servicedesk.db.types import utcnow


# --- SLA policy editing -----------------------------------------------------


def test_a_policy_edit_bumps_the_version_and_leaves_stored_deadlines_alone(
    client, db, signed_in, make_policy, make_ticket
):
    """The whole content of the "future recommendations only" warning.

    A manager halves the priority-2 target while a priority-2 ticket is open.
    The ticket's deadline was written from the old target when it opened and
    must not move; the policy version must, because every live recommendation
    was priced under numbers that no longer apply.
    """
    signed_in("manager")
    policy = make_policy(priority=2, target_minutes=240)
    opened_at = utcnow() - timedelta(minutes=30)
    ticket = make_ticket(priority=2, opened_at=opened_at,
                         sla_due_at=opened_at + timedelta(minutes=240))
    due_before = ticket.sla_due_at

    response = client.patch(
        "/api/sla-policies/%s" % policy.id, json={"target_minutes": 120}
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["policy"]["target_minutes"] == 120
    assert body["policy"]["version"] == 2
    assert body["changes"]["target_minutes"] == {"from": 240, "to": 120}
    assert body["affected_ticket_ids"] == [ticket.id]

    db.expire_all()
    stored = db.get(models.Ticket, ticket.id)
    assert stored.sla_due_at == due_before


def test_an_edit_that_changes_nothing_does_not_invalidate_live_recommendations(
    client, db, signed_in, make_policy, make_ticket
):
    """Re-saving an unchanged form is not an edit.

    If it bumped the version anyway, opening the administration screen and
    pressing save would make every outstanding recommendation unacceptable.
    """
    signed_in("manager")
    policy = make_policy(priority=3, target_minutes=480)
    make_ticket(priority=3)

    response = client.patch(
        "/api/sla-policies/%s" % policy.id, json={"target_minutes": 480}
    )
    assert response.status_code == 200, response.text
    assert response.json()["policy"]["version"] == 1
    assert response.json()["changes"] == {}
    assert response.json()["affected_ticket_ids"] == []
    assert db.query(models.TicketEvent).filter_by(
        event_type="POLICY_CHANGED_REFERENCE"
    ).count() == 0


def test_the_open_tickets_of_that_priority_carry_the_reference_and_others_do_not(
    client, db, signed_in, make_policy, make_ticket
):
    """The audit link between a manager's edit and a dispatcher's stale refusal."""
    signed_in("manager")
    policy = make_policy(priority=2)
    make_policy(priority=4)
    affected = make_ticket(priority=2, status="open")
    other_priority = make_ticket(priority=4, status="open")
    already_closed = make_ticket(priority=2, status="closed")

    client.patch(
        "/api/sla-policies/%s" % policy.id,
        json={"breach_penalty_per_minute": 11.5},
    )

    referenced = {
        row.ticket_id
        for row in db.query(models.TicketEvent).filter_by(
            event_type="POLICY_CHANGED_REFERENCE"
        )
    }
    assert referenced == {affected.id}
    assert other_priority.id not in referenced
    assert already_closed.id not in referenced


def test_a_dispatcher_cannot_edit_the_policy(client, signed_in, make_policy):
    signed_in("dispatcher")
    policy = make_policy(priority=2)
    response = client.patch(
        "/api/sla-policies/%s" % policy.id, json={"target_minutes": 60}
    )
    assert response.status_code == 403, response.text


@pytest.mark.parametrize(
    "field, value",
    [
        ("target_minutes", 0),
        ("escalation_threshold", 1.5),
        ("breach_penalty_per_minute", -1.0),
        ("source_note", ""),
    ],
)
def test_a_policy_input_outside_its_declared_range_is_refused(
    client, signed_in, make_policy, field, value
):
    """The check constraints exist in the table; the API must not reach them."""
    signed_in("manager")
    policy = make_policy(priority=2)
    response = client.patch(
        "/api/sla-policies/%s" % policy.id, json={field: value}
    )
    assert response.status_code == 422, response.text


def test_the_version_is_not_something_a_manager_can_type(
    client, db, signed_in, make_policy
):
    """A typed version could make an old recommendation look current."""
    signed_in("manager")
    policy = make_policy(priority=2)
    client.patch("/api/sla-policies/%s" % policy.id,
                 json={"version": 99, "target_minutes": 300})
    db.expire_all()
    assert db.get(models.SlaPolicy, policy.id).version == 2


# --- escalation acknowledgement --------------------------------------------


def _acknowledge(client, ticket_id, note="Paged the network on-call engineer."):
    return client.post(
        "/api/tickets/%s/escalation-acknowledgement" % ticket_id,
        json={"note": note},
    )


def test_acknowledging_appends_an_event_and_changes_nothing_else(
    client, db, signed_in, make_ticket, make_agent
):
    """Spec B.2: escalation is a recorded human decision, not a system action."""
    signed_in("dispatcher")
    agent = make_agent()
    ticket = make_ticket(priority=1, status="assigned", current_assignee_id=agent.id)

    response = _acknowledge(client, ticket.id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["event"]["event_type"] == "ESCALATION_ACKNOWLEDGED"
    assert body["ticket_status"] == "assigned"

    db.expire_all()
    stored = db.get(models.Ticket, ticket.id)
    assert stored.status == "assigned"
    assert stored.current_assignee_id == agent.id


def test_the_history_says_whether_the_model_flagged_it_first(
    client, db, signed_in, make_ticket, make_event
):
    """An agreement and a first move are different entries in an audit trail.

    "A human agreed with the model" and "a human went first" must not read the
    same afterwards, so the payload records which one happened.
    """
    signed_in("dispatcher")
    flagged = make_ticket(priority=2)
    unflagged = make_ticket(priority=2)
    make_event(flagged, event_type="ESCALATION_RECOMMENDED",
               payload={"risk_probability": 0.91})

    following = _acknowledge(client, flagged.id).json()
    leading = _acknowledge(client, unflagged.id, note="Caller escalated by phone.").json()

    assert following["following_recommendation"] is True
    assert following["event"]["payload"]["acknowledged_event_id"] is not None
    assert leading["following_recommendation"] is False
    assert leading["event"]["payload"]["acknowledged_event_id"] is None


def test_an_acknowledgement_without_a_note_is_refused(client, signed_in, make_ticket):
    """Same rule as an override: an unexplained entry is not an audit trail."""
    signed_in("dispatcher")
    ticket = make_ticket()
    response = client.post(
        "/api/tickets/%s/escalation-acknowledgement" % ticket.id, json={"note": ""}
    )
    assert response.status_code == 422, response.text


def test_a_closed_ticket_has_no_live_escalation(client, signed_in, make_ticket):
    signed_in("dispatcher")
    ticket = make_ticket(status="closed")
    response = _acknowledge(client, ticket.id)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "TICKET_NOT_OPEN"


def test_acknowledging_requires_a_signed_in_actor(client, make_ticket):
    ticket = make_ticket()
    assert _acknowledge(client, ticket.id).status_code == 401


def test_the_acknowledgement_is_readable_in_the_ticket_history(
    client, signed_in, make_ticket
):
    """Risk Radar's action has to be visible on the ticket page afterwards."""
    signed_in("dispatcher")
    ticket = make_ticket()
    _acknowledge(client, ticket.id, note="Vendor contacted, awaiting a callback.")

    events = client.get("/api/tickets/%s/events" % ticket.id).json()["events"]
    acknowledged = [e for e in events if e["event_type"] == "ESCALATION_ACKNOWLEDGED"]
    assert len(acknowledged) == 1
    assert acknowledged[0]["payload"]["note"] == "Vendor contacted, awaiting a callback."
    assert acknowledged[0]["actor_user_id"]
