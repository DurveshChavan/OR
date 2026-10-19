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


# --- escalation review --------------------------------------------------------


def test_starting_escalation_review_changes_ticket_state_and_records_the_reason(
    client, db, signed_in, make_ticket
):
    """A real in-product escalation must alter visible ticket state.

    The UI must never call a record-only acknowledgement an escalation. Starting
    review changes this application's state to ``escalation_review`` and leaves
    an immutable event with the human's stated reason. It still does not claim
    that an external L2 or vendor system was contacted.
    """
    signed_in("dispatcher")
    ticket = make_ticket(status="open")

    response = client.post(
        "/api/tickets/%s/escalation-review" % ticket.id,
        json={
            "note": "Network on-call needs to review the repeated outage.",
            "target": "senior_resolver",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["ticket_status"] == "escalation_review"
    assert body["escalation_target"] == "senior_resolver"
    assert body["event"]["event_type"] == "TICKET_UPDATED"
    assert body["event"]["payload"]["action"] == "escalation_review_started"
    assert body["event"]["payload"]["escalation_target"] == "senior_resolver"
    assert body["event"]["payload"]["note"] == (
        "Network on-call needs to review the repeated outage."
    )

    db.expire_all()
    stored = db.get(models.Ticket, ticket.id)
    assert stored.status == "escalation_review"
    assert stored.escalation_target == "senior_resolver"
    assert stored.escalation_opened_at is not None


def test_a_review_can_be_closed_and_the_ticket_returns_to_the_working_queue(
    client, db, signed_in, make_ticket, make_agent
):
    """An escalation a ticket cannot leave is the acknowledgement ritual again.

    Closing states an outcome, clears the live target and puts the ticket back
    where a dispatcher will see it: ``assigned`` when it has an owner.
    """
    signed_in("dispatcher")
    agent = make_agent(skills=["network"])
    ticket = make_ticket(status="open", current_assignee_id=agent.id)
    client.post(
        "/api/tickets/%s/escalation-review" % ticket.id,
        json={"note": "Second outage this week.", "target": "duty_manager"},
    )

    response = client.post(
        "/api/tickets/%s/escalation-review/close" % ticket.id,
        json={"note": "Duty manager confirmed the owner.", "outcome": "no_action"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["ticket_status"] == "assigned"
    assert body["escalation_target"] is None
    assert body["event"]["payload"]["action"] == "escalation_review_closed"
    assert body["event"]["payload"]["outcome"] == "no_action"
    assert body["event"]["payload"]["escalation_target"] == "duty_manager"

    db.expire_all()
    stored = db.get(models.Ticket, ticket.id)
    assert stored.status == "assigned"
    assert stored.escalation_target is None
    assert stored.escalation_opened_at is None


def test_closing_as_reassigned_without_a_new_owner_is_refused(
    client, db, signed_in, make_ticket, make_agent
):
    """An outcome is a claim about the ticket, and a false claim is refused.

    "A different resolver now owns it" has to be visible in the row, or the
    audit entry says something the database contradicts - which is the
    record-only acknowledgement defect one level up.
    """
    signed_in("dispatcher")
    agent = make_agent(skills=["network"])
    ticket = make_ticket(status="open", current_assignee_id=agent.id)
    client.post(
        "/api/tickets/%s/escalation-review" % ticket.id,
        json={"note": "Owner may be wrong.", "target": "senior_resolver"},
    )

    response = client.post(
        "/api/tickets/%s/escalation-review/close" % ticket.id,
        json={"note": "Handed over.", "outcome": "reassigned"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "ESCALATION_OUTCOME_NOT_TRUE"

    db.expire_all()
    assert db.get(models.Ticket, ticket.id).status == "escalation_review"


def test_closing_as_reassigned_is_allowed_once_the_owner_really_changed(
    client, db, signed_in, make_ticket, make_agent
):
    """The same guard must not block the case it exists to describe."""
    signed_in("dispatcher")
    first = make_agent(display_name="Resolver A", skills=["network"])
    second = make_agent(display_name="Resolver B", skills=["network"])
    ticket = make_ticket(status="open", current_assignee_id=first.id)
    client.post(
        "/api/tickets/%s/escalation-review" % ticket.id,
        json={"note": "Owner may be wrong.", "target": "senior_resolver"},
    )

    stored = db.get(models.Ticket, ticket.id)
    stored.current_assignee_id = second.id
    db.commit()

    response = client.post(
        "/api/tickets/%s/escalation-review/close" % ticket.id,
        json={"note": "Resolver B took it.", "outcome": "reassigned"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["ticket_status"] == "assigned"


def test_closing_a_ticket_that_is_not_in_review_is_refused(
    client, signed_in, make_ticket
):
    """The close route must not be a way to rewrite an ordinary ticket's status."""
    signed_in("dispatcher")
    ticket = make_ticket(status="open")

    response = client.post(
        "/api/tickets/%s/escalation-review/close" % ticket.id,
        json={"note": "Nothing to close.", "outcome": "no_action"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ESCALATION_REVIEW_NOT_ACTIVE"


def test_a_target_this_desk_cannot_reach_is_refused(client, signed_in, make_ticket):
    """No L2 queue and no vendor exist here, so neither may be named as a target."""
    signed_in("dispatcher")
    ticket = make_ticket(status="open")

    response = client.post(
        "/api/tickets/%s/escalation-review" % ticket.id,
        json={"note": "Send it out.", "target": "vendor"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ESCALATION_TARGET_UNKNOWN"


def test_the_replacement_route_requires_the_ticket_to_asset_link(
    client, signed_in, make_ticket
):
    """The one bridge between dispatch and the asset register is a human's link.

    Without it there is no machine to decide about, so the review is refused
    rather than opened against nothing.
    """
    signed_in("dispatcher")
    ticket = make_ticket(status="open")

    response = client.post(
        "/api/tickets/%s/escalation-review" % ticket.id,
        json={"note": "This laptop keeps failing.", "target": "asset_replacement"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TICKET_HAS_NO_MACHINE"


def test_raising_a_replacement_stores_the_verdict_computed_at_that_moment(
    client, db, signed_in, make_ticket
):
    """The history must say what the arithmetic said on the day.

    A machine's advice moves as it ages, so an event that only pointed at the
    machine would read differently months later. The verdict is copied into the
    event beside the asset tag.
    """
    from datetime import timedelta

    from api.servicedesk.db.types import utcnow

    signed_in("dispatcher")
    machine = models.Machine(
        asset_tag="LAP-0142",
        location="HQ",
        machine_type="laptop",
        age_months=60,
        age_recorded_at=utcnow() - timedelta(days=1),
        purchase_cost=10000.0,
        scrap_value_by_year_json=[2000.0],
        running_cost_by_year_json=[1000.0, 2000.0, 3000.0, 5000.0],
        source_note="asset register export, 2026-09",
    )
    db.add(machine)
    db.commit()
    ticket = make_ticket(status="open", machine_id=machine.id)

    client.post(
        "/api/tickets/%s/escalation-review" % ticket.id,
        json={"note": "Third failure on this laptop.", "target": "asset_replacement"},
    )
    response = client.post(
        "/api/tickets/%s/escalation-review/close" % ticket.id,
        json={
            "note": "Replacement raised with asset planning.",
            "outcome": "replacement_raised",
        },
    )

    assert response.status_code == 201, response.text
    replacement = response.json()["event"]["payload"]["replacement"]
    assert replacement["asset_tag"] == "LAP-0142"
    # Five years old against an optimal replacement year of 3: overdue.
    assert replacement["verdict"] == "replace_now"
    assert replacement["optimal_replacement_year"] == 3
    assert replacement["source_note"] == "asset register export, 2026-09"
