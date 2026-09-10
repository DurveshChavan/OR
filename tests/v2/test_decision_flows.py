"""Recommendation, acceptance, override and rescore through the API (spec H.2).

These tests drive the real endpoints against a migrated database and the real
committed model artifacts. What they are watching for is the set of failures the
plan names by hand: a ticket that disappears out of a batch, an acceptance that
assigns someone who can no longer take the work, an override that quietly edits
the recommendation it disagreed with, and a rescore that reassigns.
"""
from datetime import timedelta

import pytest
from sqlalchemy import select

from api.app_v2.db import models
from api.app_v2.db.types import utcnow


@pytest.fixture
def skilled_agent(db):
    """An agent with a named skill and a chosen speed on it."""
    def _make(display_name, skill="network", multiplier=1.0, wip_limit=2,
              is_active=True, next_available_at=None):
        agent = models.Agent(
            display_name=display_name, wip_limit=wip_limit, is_active=is_active,
            next_available_at=next_available_at,
        )
        db.add(agent)
        db.flush()
        db.add(models.AgentSkill(
            agent_id=agent.id, skill=skill,
            efficiency_multiplier=multiplier, is_primary=True,
        ))
        db.commit()
        return agent
    return _make


@pytest.fixture
def open_ticket(db):
    def _make(priority=2, skill="network", due_in_minutes=240, reference=None,
              window_minutes=240):
        # The deadline is placed relative to now and the opening time is worked
        # backwards from it, so an already-overdue ticket is expressible without
        # violating the table's own "due after opened" constraint.
        due_at = utcnow() + timedelta(minutes=due_in_minutes)
        ticket = models.Ticket(
            external_reference=reference,
            source="manual", status="open", priority=priority,
            category="Network", required_skill=skill,
            opened_at=due_at - timedelta(minutes=window_minutes),
            sla_due_at=due_at,
        )
        db.add(ticket)
        db.commit()
        return ticket
    return _make


def recommend(client, ticket_ids, mode="batch"):
    return client.post(
        "/api/v2/assignment-decisions",
        json={"ticket_ids": list(ticket_ids), "mode": mode},
    )


# --- recommendation ---------------------------------------------------------


def test_a_batch_returns_one_decision_for_every_requested_ticket(
    client, db, signed_in, make_policy, skilled_agent, open_ticket
):
    signed_in("dispatcher")
    make_policy(priority=2)
    skilled_agent("Resolver A")
    tickets = [open_ticket(), open_ticket(), open_ticket()]

    response = recommend(client, [t.id for t in tickets])
    assert response.status_code == 201, response.text
    decisions = response.json()["decisions"]

    assert len(decisions) == 3
    assert {d["ticket_id"] for d in decisions} == {t.id for t in tickets}
    assert all(d["reason"] for d in decisions)
    assert all(d["policy_version"] == 1 for d in decisions)
    assert len({d["batch_id"] for d in decisions}) == 1


def test_recommending_assigns_nobody(
    client, db, signed_in, make_policy, skilled_agent, open_ticket
):
    """Spec D.3: this endpoint produces a recommendation and nothing else."""
    signed_in("dispatcher")
    make_policy(priority=2)
    skilled_agent("Resolver A")
    ticket = open_ticket()

    recommend(client, [ticket.id])

    db.expire_all()
    stored = db.get(models.Ticket, ticket.id)
    assert stored.current_assignee_id is None
    assert stored.status == "open"


def test_a_ticket_no_agent_can_work_gets_a_visible_decision(
    client, db, signed_in, make_policy, skilled_agent, open_ticket
):
    signed_in("dispatcher")
    make_policy(priority=2)
    skilled_agent("Resolver A", skill="network")
    ticket = open_ticket(skill="mainframe")

    decision = recommend(client, [ticket.id]).json()["decisions"][0]
    assert decision["state"] == "no_eligible_agent"
    assert decision["recommended_agent"] is None
    assert "no active agent holds" in decision["reason"]

    events = client.get("/api/v2/tickets/%s/events" % ticket.id).json()["events"]
    assert "NO_ELIGIBLE_AGENT" in [event["event_type"] for event in events]


def test_a_ticket_with_no_free_slot_is_queued_not_dropped(
    client, db, signed_in, make_policy, skilled_agent, open_ticket
):
    signed_in("dispatcher")
    make_policy(priority=2)
    skilled_agent("Resolver A", wip_limit=1)
    tickets = [open_ticket(), open_ticket()]

    decisions = recommend(client, [t.id for t in tickets]).json()["decisions"]
    states = sorted(decision["state"] for decision in decisions)
    assert states == ["queued", "recommended"]

    queued = [d for d in decisions if d["state"] == "queued"][0]
    assert queued["recommended_agent"] is None
    assert "Queued for capacity" in queued["reason"]


def test_a_p1_ticket_takes_the_last_slot_before_a_p4_ticket(
    client, db, signed_in, make_policy, skilled_agent, open_ticket
):
    """Spec F.3: the P1 tier resolves first, P4 sees the queue."""
    signed_in("dispatcher")
    make_policy(priority=1, target_minutes=60)
    make_policy(priority=4, target_minutes=1440)
    skilled_agent("Resolver A", wip_limit=1)
    urgent = open_ticket(priority=1, due_in_minutes=60)
    relaxed = open_ticket(priority=4, due_in_minutes=1440)

    decisions = {
        d["ticket_id"]: d
        for d in recommend(client, [urgent.id, relaxed.id]).json()["decisions"]
    }
    assert decisions[urgent.id]["state"] == "recommended"
    assert decisions[relaxed.id]["state"] == "queued"


def test_the_stored_reason_repeats_the_payload_it_was_generated_from(
    client, db, signed_in, make_policy, skilled_agent, open_ticket
):
    """Spec H.1: the reason cites the decision's own numbers, not fresh ones."""
    signed_in("dispatcher")
    make_policy(priority=2)
    agent = skilled_agent("Resolver Verbatim", multiplier=0.8)
    ticket = open_ticket()

    decision_id = recommend(client, [ticket.id]).json()["decisions"][0]["decision_id"]
    detail = client.get("/api/v2/assignment-decisions/%s" % decision_id).json()
    chosen = detail["candidate_payload"]["chosen"]
    reason = detail["decision"]["reason"]

    assert "Resolver Verbatim" in reason
    assert "%.2f" % chosen["speed_multiplier"] in reason
    assert "%.2f" % chosen["total_cost"] in reason
    assert "%.0f" % round(chosen["projected_service_minutes"]) in reason
    assert "%.2f" % detail["decision"]["risk_probability"] in reason


def test_the_candidate_payload_carries_no_outcome_field(
    client, db, signed_in, make_policy, skilled_agent, open_ticket
):
    signed_in("dispatcher")
    make_policy(priority=2)
    skilled_agent("Resolver A")
    ticket = open_ticket()
    decision_id = recommend(client, [ticket.id]).json()["decisions"][0]["decision_id"]

    payload = client.get(
        "/api/v2/assignment-decisions/%s" % decision_id
    ).json()["candidate_payload"]
    text = str(payload).lower()
    for forbidden in ("made_sla", "resolved_at", "closed_at", "resolved_by", "actual"):
        assert forbidden not in text


def test_a_batch_above_the_documented_cap_is_refused(
    client, db, signed_in, make_policy, skilled_agent
):
    signed_in("dispatcher")
    make_policy(priority=2)
    skilled_agent("Resolver A")
    response = recommend(client, ["ticket-%03d" % index for index in range(101)])
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "BATCH_TOO_LARGE"


def test_a_missing_ticket_id_names_itself_rather_than_being_skipped(
    client, db, signed_in, make_policy, skilled_agent, open_ticket
):
    signed_in("dispatcher")
    make_policy(priority=2)
    skilled_agent("Resolver A")
    ticket = open_ticket()

    response = recommend(client, [ticket.id, "no-such-ticket"])
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "TICKETS_NOT_DISPATCHABLE"
    assert body["details"]["missing"] == ["no-such-ticket"]


# --- acceptance -------------------------------------------------------------


def test_accepting_changes_only_the_assignment_and_writes_one_event(
    client, db, signed_in, make_policy, skilled_agent, open_ticket
):
    actor = signed_in("dispatcher")
    make_policy(priority=2)
    agent = skilled_agent("Resolver A")
    ticket = open_ticket()
    decision = recommend(client, [ticket.id]).json()["decisions"][0]

    response = client.post(
        "/api/v2/assignment-decisions/%s/accept" % decision["decision_id"]
    )
    assert response.status_code == 200, response.text
    assert response.json()["assigned_agent"]["id"] == agent.id
    assert response.json()["overridden"] is False

    db.expire_all()
    stored = db.get(models.Ticket, ticket.id)
    assert stored.current_assignee_id == agent.id
    assert stored.status == "assigned"

    accepted = [
        event for event in
        client.get("/api/v2/tickets/%s/events" % ticket.id).json()["events"]
        if event["event_type"] == "ASSIGNMENT_ACCEPTED"
    ]
    assert len(accepted) == 1
    assert accepted[0]["decision_id"] == decision["decision_id"]
    assert accepted[0]["actor_user_id"] == actor.id


def test_accepting_advances_the_resolvers_projected_availability(
    client, db, signed_in, make_policy, skilled_agent, open_ticket
):
    signed_in("dispatcher")
    make_policy(priority=2)
    agent = skilled_agent("Resolver A")
    ticket = open_ticket()
    decision = recommend(client, [ticket.id]).json()["decisions"][0]
    client.post("/api/v2/assignment-decisions/%s/accept" % decision["decision_id"])

    db.expire_all()
    stored = db.get(models.Agent, agent.id)
    assert stored.next_available_at > utcnow()


def test_accepting_is_refused_once_the_resolver_has_no_slot_left(
    client, db, signed_in, make_policy, skilled_agent, open_ticket
):
    """The second accept in a batch must re-verify, not trust the solve."""
    signed_in("dispatcher")
    make_policy(priority=2)
    skilled_agent("Resolver A", wip_limit=1)
    first, second = open_ticket(), open_ticket()

    # Two separate single-ticket solves, so both name the same free slot.
    one = recommend(client, [first.id], mode="single").json()["decisions"][0]
    two = recommend(client, [second.id], mode="single").json()["decisions"][0]
    assert one["state"] == two["state"] == "recommended"

    assert client.post(
        "/api/v2/assignment-decisions/%s/accept" % one["decision_id"]
    ).status_code == 200
    refused = client.post(
        "/api/v2/assignment-decisions/%s/accept" % two["decision_id"]
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "AGENT_AT_WIP_LIMIT"


def test_accepting_a_decision_made_under_an_older_policy_is_refused(
    client, db, signed_in, make_policy, skilled_agent, open_ticket
):
    signed_in("manager")
    policy = make_policy(priority=2)
    skilled_agent("Resolver A")
    ticket = open_ticket()
    decision = recommend(client, [ticket.id]).json()["decisions"][0]

    policy.version = 2
    db.commit()

    refused = client.post(
        "/api/v2/assignment-decisions/%s/accept" % decision["decision_id"]
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "DECISION_STALE"


def test_a_queued_decision_has_nothing_to_accept(
    client, db, signed_in, make_policy, skilled_agent, open_ticket
):
    signed_in("dispatcher")
    make_policy(priority=2)
    skilled_agent("Resolver A", skill="network")
    ticket = open_ticket(skill="mainframe")
    decision = recommend(client, [ticket.id]).json()["decisions"][0]

    refused = client.post(
        "/api/v2/assignment-decisions/%s/accept" % decision["decision_id"]
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "DECISION_NOT_ACCEPTABLE"


# --- override ---------------------------------------------------------------


def test_override_keeps_the_original_recommendation_intact(
    client, db, signed_in, make_policy, skilled_agent, open_ticket
):
    signed_in("dispatcher")
    make_policy(priority=2)
    recommended = skilled_agent("Resolver Fast", multiplier=0.5)
    other = skilled_agent("Resolver Other", multiplier=1.0)
    ticket = open_ticket()

    decision = recommend(client, [ticket.id]).json()["decisions"][0]
    assert decision["recommended_agent"]["id"] == recommended.id
    before = db.get(models.AssignmentDecision, decision["decision_id"])
    snapshot = (before.recommended_agent_id, before.reason_text,
                before.recommendation_state, before.candidate_payload_json)

    response = client.post(
        "/api/v2/assignment-decisions/%s/override" % decision["decision_id"],
        json={"agent_id": other.id, "reason": "Resolver Fast is on a major incident."},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assigned_agent"]["id"] == other.id
    assert body["decision"]["recommended_agent"]["id"] == recommended.id
    assert body["overridden"] is True

    db.expire_all()
    after = db.get(models.AssignmentDecision, decision["decision_id"])
    assert (after.recommended_agent_id, after.reason_text,
            after.recommendation_state, after.candidate_payload_json) == snapshot
    assert db.get(models.Ticket, ticket.id).current_assignee_id == other.id


def test_override_without_a_reason_is_refused_and_assigns_nobody(
    client, db, signed_in, make_policy, skilled_agent, open_ticket
):
    signed_in("dispatcher")
    make_policy(priority=2)
    agent = skilled_agent("Resolver A")
    other = skilled_agent("Resolver B")
    ticket = open_ticket()
    decision = recommend(client, [ticket.id]).json()["decisions"][0]

    refused = client.post(
        "/api/v2/assignment-decisions/%s/override" % decision["decision_id"],
        json={"agent_id": other.id, "reason": "   "},
    )
    assert refused.status_code in (422,)

    db.expire_all()
    assert db.get(models.Ticket, ticket.id).current_assignee_id is None
    events = client.get("/api/v2/tickets/%s/events" % ticket.id).json()["events"]
    assert "ASSIGNMENT_OVERRIDDEN" not in [e["event_type"] for e in events]


@pytest.mark.parametrize(
    "kind,expected", [
        ("unqualified", "AGENT_NOT_ELIGIBLE"),
        ("inactive", "AGENT_NOT_ELIGIBLE"),
        ("full", "AGENT_AT_WIP_LIMIT"),
    ],
)
def test_override_to_an_agent_who_cannot_take_it_is_refused(
    client, db, signed_in, make_policy, skilled_agent, open_ticket, kind, expected
):
    signed_in("dispatcher")
    make_policy(priority=2)
    recommended = skilled_agent("Resolver A")
    ticket = open_ticket()
    decision = recommend(client, [ticket.id]).json()["decisions"][0]

    if kind == "unqualified":
        target = skilled_agent("Resolver Mainframe", skill="mainframe")
    elif kind == "inactive":
        target = skilled_agent("Resolver Away", is_active=False)
    else:
        target = skilled_agent("Resolver Full", wip_limit=1)
        occupied = open_ticket()
        occupied.current_assignee_id = target.id
        occupied.status = "assigned"
        db.commit()

    refused = client.post(
        "/api/v2/assignment-decisions/%s/override" % decision["decision_id"],
        json={"agent_id": target.id, "reason": "Trying it anyway."},
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == expected

    db.expire_all()
    assert db.get(models.Ticket, ticket.id).current_assignee_id is None


# --- rescore ----------------------------------------------------------------


def test_rescore_is_manager_only(client, db, signed_in, make_policy):
    signed_in("dispatcher")
    make_policy(priority=2)
    response = client.post("/api/v2/tickets/rescore", json={"only_stale": False})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NOT_PERMITTED"


def test_rescore_does_not_reassign_an_accepted_ticket(
    client, db, signed_in, make_policy, skilled_agent, open_ticket
):
    signed_in("manager")
    make_policy(priority=2)
    agent = skilled_agent("Resolver A")
    ticket = open_ticket()
    decision = recommend(client, [ticket.id]).json()["decisions"][0]
    client.post("/api/v2/assignment-decisions/%s/accept" % decision["decision_id"])

    response = client.post("/api/v2/tickets/rescore", json={"only_stale": False})
    assert response.status_code == 200, response.text

    db.expire_all()
    stored = db.get(models.Ticket, ticket.id)
    assert stored.current_assignee_id == agent.id
    assert stored.status == "assigned"


def test_rescoring_twice_writes_one_score_event(
    client, db, signed_in, make_policy, skilled_agent, open_ticket
):
    """Idempotent for the same ticket, model and policy (spec D.5)."""
    signed_in("manager")
    make_policy(priority=2)
    skilled_agent("Resolver A")
    ticket = open_ticket()

    first = client.post("/api/v2/tickets/rescore", json={"only_stale": False}).json()
    second = client.post("/api/v2/tickets/rescore", json={"only_stale": False}).json()
    assert first["rescored"] == 1
    assert second["rescored"] == 0
    assert second["unchanged"] == 1

    events = client.get("/api/v2/tickets/%s/events" % ticket.id).json()["events"]
    scored = [e for e in events if e["event_type"] == "RISK_SCORED"]
    assert len(scored) == 1
    assert scored[0]["payload"]["trigger"] == "manual_rescore"


def test_a_patched_priority_is_what_actually_moves_a_score(
    client, db, signed_in, make_policy, skilled_agent, open_ticket
):
    """The one ordinary way a rescore has work to do.

    Every feature the artifact reads is fixed at creation, so an unchanged ticket
    scores the same forever. Patching the priority changes the most predictive
    field, and the rescore then has a genuinely different number to write. This
    test exists because without it the whole rescore path is only ever exercised
    on first-time scoring, and a no-op would look identical to a working one.
    """
    signed_in("manager")
    make_policy(priority=2)
    make_policy(priority=4, target_minutes=1440)
    skilled_agent("Resolver A")
    ticket = open_ticket(priority=2)

    client.post("/api/v2/tickets/rescore", json={"only_stale": False})
    db.expire_all()
    before = db.get(models.Ticket, ticket.id).risk_probability

    patched = client.patch("/api/v2/tickets/%s" % ticket.id, json={"priority": 4})
    assert patched.status_code == 200, patched.text

    summary = client.post(
        "/api/v2/tickets/rescore", json={"only_stale": False}
    ).json()
    assert summary["rescored"] == 1

    db.expire_all()
    after = db.get(models.Ticket, ticket.id).risk_probability
    assert after != before

    scored = [
        event for event in
        client.get("/api/v2/tickets/%s/events" % ticket.id).json()["events"]
        if event["event_type"] == "RISK_SCORED"
    ]
    assert len(scored) == 2
    assert scored[-1]["payload"]["previous_risk_probability"] == before
    assert scored[-1]["payload"]["risk_probability"] == after


def test_accepting_a_decision_made_by_a_different_model_is_refused(
    client, db, signed_in, make_policy, skilled_agent, open_ticket
):
    """The model half of the staleness check, exercised separately from policy.

    The decision row is immutable, so the older model version cannot be written
    onto an existing decision. A decision is inserted directly with a version
    string no artifact carries, which is exactly the state a rolled-back or
    replaced artifact would leave behind.
    """
    signed_in("dispatcher")
    policy = make_policy(priority=2)
    agent = skilled_agent("Resolver A")
    ticket = open_ticket()

    stale = models.AssignmentDecision(
        ticket_id=ticket.id,
        recommended_agent_id=agent.id,
        recommendation_state="recommended",
        risk_probability=0.5,
        predicted_duration_minutes=60.0,
        projected_wait_minutes=0.0,
        projected_lateness_minutes=0.0,
        model_version="uci-risk-2020-01-01-a1",
        policy_version=policy.version,
        candidate_payload_json={"chosen": {}, "eligible_agent_count": 1},
        reason_text="written under a model version that is no longer installed",
    )
    db.add(stale)
    db.commit()

    refused = client.post("/api/v2/assignment-decisions/%s/accept" % stale.id)
    assert refused.status_code == 409
    body = refused.json()["error"]
    assert body["code"] == "DECISION_STALE"
    assert "model_version" in body["details"]["drifted"]

    db.expire_all()
    assert db.get(models.Ticket, ticket.id).current_assignee_id is None


def test_rescore_skips_a_terminal_ticket(
    client, db, signed_in, make_policy, skilled_agent, open_ticket
):
    signed_in("manager")
    make_policy(priority=2)
    skilled_agent("Resolver A")
    closed = open_ticket()
    closed.status = "closed"
    db.commit()

    summary = client.post(
        "/api/v2/tickets/rescore", json={"only_stale": False}
    ).json()
    assert summary["considered"] == 0


# --- risk radar -------------------------------------------------------------


def test_risk_radar_puts_p1_first_then_overdue_work(
    client, db, signed_in, make_policy, skilled_agent, open_ticket
):
    signed_in("dispatcher")
    make_policy(priority=1, target_minutes=60)
    make_policy(priority=2, target_minutes=240)
    skilled_agent("Resolver A")
    overdue = open_ticket(priority=2, due_in_minutes=-30, reference="OVERDUE")
    fresh = open_ticket(priority=2, due_in_minutes=200, reference="FRESH")
    urgent = open_ticket(priority=1, due_in_minutes=30, reference="P1")

    rows = client.get("/api/v2/risk-radar").json()["tickets"]
    order = [row["external_reference"] for row in rows]
    assert order == ["P1", "OVERDUE", "FRESH"]
    assert rows[1]["overdue"] is True
    assert rows[1]["overdue_minutes"] > 0


def test_risk_radar_excludes_terminal_tickets(
    client, db, signed_in, make_policy, open_ticket
):
    signed_in("dispatcher")
    make_policy(priority=2)
    resolved = open_ticket(reference="DONE")
    resolved.status = "resolved"
    db.commit()

    assert client.get("/api/v2/risk-radar").json()["tickets"] == []


def test_the_full_history_survives_a_restart(
    client, db, engine, signed_in, make_policy, skilled_agent, open_ticket
):
    """Spec H.2: current state and audit trail both come back from the database."""
    signed_in("dispatcher")
    make_policy(priority=2)
    agent = skilled_agent("Resolver A")
    ticket = open_ticket()
    decision = recommend(client, [ticket.id]).json()["decisions"][0]
    client.post("/api/v2/assignment-decisions/%s/accept" % decision["decision_id"])

    url = str(engine.url)
    engine.dispose()

    from sqlalchemy.orm import Session

    from api.app_v2.db.session import make_engine

    fresh_engine = make_engine(url)
    with Session(bind=fresh_engine, future=True) as session:
        stored = session.get(models.Ticket, ticket.id)
        assert stored.current_assignee_id == agent.id
        types = session.scalars(
            select(models.TicketEvent.event_type)
            .where(models.TicketEvent.ticket_id == ticket.id)
            .order_by(models.TicketEvent.occurred_at.asc(), models.TicketEvent.id.asc())
        ).all()
    fresh_engine.dispose()
    assert "ASSIGNMENT_RECOMMENDED" in types
    assert "ASSIGNMENT_ACCEPTED" in types


def test_a_decision_stores_the_alternatives_the_solve_priced(
    client, db, signed_in, make_policy, skilled_agent, open_ticket
):
    """The ticket page shows alternatives from the payload, so they must be in it.

    Two resolvers hold the skill and one ticket is dispatched, so exactly one
    eligible resolver is left over. Its stored entry has to carry the projection
    and the cost the solve computed for it, not a placeholder.
    """
    signed_in("dispatcher")
    make_policy(priority=2)
    fast = skilled_agent("Resolver Fast", multiplier=0.5)
    slow = skilled_agent("Resolver Slow", multiplier=2.0)
    ticket = open_ticket()

    decision_id = recommend(client, [ticket.id]).json()["decisions"][0]["decision_id"]
    payload = client.get("/api/v2/assignment-decisions/%s" % decision_id).json()
    chosen = payload["candidate_payload"]["chosen"]
    alternatives = payload["candidate_payload"]["alternatives"]

    assert chosen["agent_id"] == fast.id
    assert [entry["agent_id"] for entry in alternatives] == [slow.id]
    assert alternatives[0]["display_name"] == "Resolver Slow"
    assert alternatives[0]["total_cost"] > chosen["total_cost"]
    assert alternatives[0]["projected_finish_in_minutes"] > 0
    assert payload["candidate_payload"]["alternatives_note"]


def test_a_ticket_nobody_can_work_stores_no_alternatives(
    client, db, signed_in, make_policy, skilled_agent, open_ticket
):
    signed_in("dispatcher")
    make_policy(priority=2)
    skilled_agent("Resolver Network", skill="network")
    ticket = open_ticket(skill="mainframe")

    decision = recommend(client, [ticket.id]).json()["decisions"][0]
    assert decision["state"] == "no_eligible_agent"
    detail = client.get(
        "/api/v2/assignment-decisions/%s" % decision["decision_id"]
    ).json()
    assert detail["candidate_payload"]["alternatives"] == []
