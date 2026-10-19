"""Titles, derived priority, resolve / close / reopen, and search."""
from datetime import timedelta

from api.servicedesk.db import models
from api.servicedesk.db.types import utcnow


def _create(client, **overrides):
    body = {"title": "Payroll portal times out", "priority": 2, "required_skill": "network"}
    body.update(overrides)
    return client.post("/api/tickets", json=body)


def _actions(client, ticket_id):
    events = client.get("/api/tickets/%s/events" % ticket_id).json()["events"]
    return [e["payload"] for e in events if e["payload"].get("action")]


def test_a_ticket_needs_a_title_that_says_something(client, signed_in, make_policy):
    signed_in("dispatcher")
    make_policy(priority=2)
    assert client.post("/api/tickets", json={"priority": 2}).status_code == 422
    assert _create(client, title="   ").status_code == 422
    created = _create(client, description="Since 09:00, every user in finance.")
    assert created.status_code == 201, created.text
    assert created.json()["ticket"]["title"] == "Payroll portal times out"
    assert created.json()["ticket"]["description"] == "Since 09:00, every user in finance."


def test_impact_and_urgency_set_the_priority_and_the_deadline(client, signed_in, make_policy):
    """Impact 2, urgency 1 is priority 2 by the matrix, so the P2 target applies."""
    signed_in("dispatcher")
    make_policy(priority=2, target_minutes=240)
    created = _create(client, priority=None, impact=2, urgency=1).json()["ticket"]
    assert created["priority"] == 2
    assert (created["impact"], created["urgency"]) == (2, 1)

    events = client.get("/api/tickets/%s/events" % created["id"]).json()["events"]
    opening = next(e for e in events if e["event_type"] == "TICKET_CREATED")
    scored = next(e for e in events if e["event_type"] == "RISK_SCORED")
    assert opening["payload"]["priority_source"] == "impact_urgency_matrix"
    assert scored["payload"]["unavailable_features"] == ["u_symptom"]


def test_a_priority_that_contradicts_impact_and_urgency_is_refused(client, signed_in, make_policy):
    signed_in("dispatcher")
    make_policy(priority=2)
    response = _create(client, priority=4, impact=2, urgency=1)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PRIORITY_MATRIX_MISMATCH"


def test_status_cannot_be_patched_directly(client, signed_in, make_ticket):
    signed_in("dispatcher")
    ticket = make_ticket(status="open")
    response = client.patch("/api/tickets/%s" % ticket.id, json={"status": "resolved"})
    assert response.status_code == 422
    assert client.get("/api/tickets/%s" % ticket.id).json()["ticket"]["status"] == "open"


def test_resolving_records_the_sla_outcome_and_frees_the_resolver(
    client, db, signed_in, make_ticket, make_agent
):
    signed_in("dispatcher")
    agent = make_agent(wip_limit=1)
    agent.next_available_at = utcnow() + timedelta(hours=3)
    db.commit()
    ticket = make_ticket(status="assigned", current_assignee_id=agent.id)

    response = client.post("/api/tickets/%s/resolve" % ticket.id, json={"note": "Reset the VPN profile."})
    assert response.status_code == 201, response.text
    body = response.json()["ticket"]
    assert body["status"] == "resolved"
    assert body["sla_met"] is True
    assert body["resolved_at"] is not None

    resolved = _actions(client, ticket.id)[-1]
    assert resolved["action"] == "ticket_resolved"
    assert resolved["minutes_past_deadline"] == 0.0
    assert resolved["resolver_available_from"] is not None
    db.expire_all()
    assert db.get(models.Agent, agent.id).next_available_at <= utcnow()


def test_resolving_after_the_deadline_is_a_breach(client, signed_in, make_ticket):
    signed_in("dispatcher")
    opened = utcnow() - timedelta(hours=6)
    ticket = make_ticket(opened_at=opened, sla_due_at=opened + timedelta(hours=4))
    body = client.post("/api/tickets/%s/resolve" % ticket.id, json={"note": "Done."}).json()
    assert body["ticket"]["sla_met"] is False
    assert _actions(client, ticket.id)[-1]["minutes_past_deadline"] >= 119


def test_a_ticket_in_review_cannot_be_resolved_until_the_review_closes(client, signed_in, make_ticket):
    signed_in("dispatcher")
    ticket = make_ticket(status="escalation_review", escalation_target="duty_manager",
                         escalation_opened_at=utcnow())
    response = client.post("/api/tickets/%s/resolve" % ticket.id, json={"note": "Done."})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ESCALATION_REVIEW_ACTIVE"


def test_close_needs_a_resolved_ticket_and_every_transition_needs_a_note(client, signed_in, make_ticket):
    signed_in("dispatcher")
    ticket = make_ticket(status="open")
    refused = client.post("/api/tickets/%s/close" % ticket.id, json={"note": "Confirmed."})
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "TICKET_TRANSITION_INVALID"
    assert client.post("/api/tickets/%s/resolve" % ticket.id, json={"note": ""}).status_code == 422

    client.post("/api/tickets/%s/resolve" % ticket.id, json={"note": "Fixed."})
    closed = client.post("/api/tickets/%s/close" % ticket.id, json={"note": "Caller confirmed."})
    assert closed.json()["ticket"]["status"] == "closed"


def test_reopening_returns_the_ticket_to_dispatch_and_keeps_the_history(
    client, signed_in, make_ticket, make_agent
):
    signed_in("dispatcher")
    agent = make_agent()
    ticket = make_ticket(status="assigned", current_assignee_id=agent.id)
    client.post("/api/tickets/%s/resolve" % ticket.id, json={"note": "Fixed."})
    client.post("/api/tickets/%s/close" % ticket.id, json={"note": "Confirmed."})

    reopened = client.post("/api/tickets/%s/reopen" % ticket.id, json={"note": "Fault is back."})
    body = reopened.json()["ticket"]
    assert (body["status"], body["current_assignee_id"], body["resolved_at"]) == ("open", None, None)
    assert body["sla_due_at"] == client.get("/api/tickets/%s" % ticket.id).json()["ticket"]["sla_due_at"]

    last = _actions(client, ticket.id)[-1]
    assert last["action"] == "ticket_reopened"
    assert last["previous_assignee_id"] == agent.id
    assert last["previous_resolved_at"] is not None


def test_search_matches_reference_or_title_in_any_case(client, signed_in, make_policy):
    signed_in("dispatcher")
    make_policy(priority=2)
    _create(client, external_reference="INC0000101", title="Printer offline on floor 3")
    _create(client, external_reference="INC0000202", title="VPN drops every hour")

    by_title = client.get("/api/tickets", params={"q": "vpn"}).json()
    by_reference = client.get("/api/tickets", params={"q": "inc0000101"}).json()
    assert [t["external_reference"] for t in by_title["tickets"]] == ["INC0000202"]
    assert by_title["total"] == 1
    assert [t["external_reference"] for t in by_reference["tickets"]] == ["INC0000101"]
