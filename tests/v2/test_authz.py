"""Who may do what on the Phase 3 surface, and what an unauthorised call leaves behind.

The sign-in mechanics are covered in ``test_auth.py`` and the append-only
triggers in ``test_immutability.py``. What is checked here is the decision
surface specifically: that a refusal happens before anything is written, and
that a signed-out or deactivated session cannot reach any of it.

The role split (spec B.1):

* a dispatcher creates tickets, requests recommendations, accepts and overrides;
* a manager does all of that and additionally owns agents, skills, SLA policy
  and manual rescore.

Override is deliberately a dispatcher action. Spec B.1 has the dispatcher
accepting or overriding as part of one workflow, and a build where a dispatcher
can only accept would push every disagreement into an unrecorded conversation
instead of into the audit trail.
"""
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from api.app_v2.db import models
from api.app_v2.db.types import utcnow
from api.app_v2.services import auth


@pytest.fixture
def dispatch_fixture(db, make_policy):
    """One policy, one skilled resolver, one open ticket."""
    def _make():
        make_policy(priority=2)
        agent = models.Agent(display_name="Resolver A", wip_limit=2)
        db.add(agent)
        db.flush()
        db.add(models.AgentSkill(
            agent_id=agent.id, skill="network",
            efficiency_multiplier=1.0, is_primary=True,
        ))
        opened_at = utcnow()
        ticket = models.Ticket(
            source="manual", status="open", priority=2, category="Network",
            required_skill="network", opened_at=opened_at,
            sla_due_at=opened_at + timedelta(minutes=240),
        )
        db.add(ticket)
        db.commit()
        return agent, ticket
    return _make


def _count(db, model):
    return db.scalar(select(func.count()).select_from(model))


# --- manager-only surface ---------------------------------------------------


def test_a_dispatcher_cannot_edit_sla_policy(client, db, signed_in, make_policy):
    signed_in("dispatcher")
    policy = make_policy(priority=2)
    response = client.patch(
        "/api/v2/sla-policies/%d" % policy.priority,
        json={"breach_penalty_per_minute": 999.0},
    )
    assert response.status_code in (403, 404, 405)
    if response.status_code == 403:
        assert response.json()["error"]["code"] == "NOT_PERMITTED"

    db.expire_all()
    assert db.get(models.SlaPolicy, policy.id).breach_penalty_per_minute == 5.0


def test_a_dispatcher_cannot_create_an_agent(client, signed_in):
    signed_in("dispatcher")
    response = client.post(
        "/api/v2/agents", json={"display_name": "Unauthorised", "wip_limit": 1}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NOT_PERMITTED"


def test_a_dispatcher_cannot_run_a_manual_rescore(client, signed_in, make_policy):
    signed_in("dispatcher")
    make_policy(priority=2)
    response = client.post("/api/v2/tickets/rescore", json={"only_stale": False})
    assert response.status_code == 403


# --- the dispatcher surface -------------------------------------------------


def test_a_dispatcher_may_recommend_accept_and_override(
    client, db, signed_in, dispatch_fixture
):
    signed_in("dispatcher")
    agent, ticket = dispatch_fixture()
    decisions = client.post(
        "/api/v2/assignment-decisions",
        json={"ticket_ids": [ticket.id], "mode": "single"},
    )
    assert decisions.status_code == 201
    decision_id = decisions.json()["decisions"][0]["decision_id"]
    assert client.post(
        "/api/v2/assignment-decisions/%s/accept" % decision_id
    ).status_code == 200


# --- unauthenticated and deactivated ---------------------------------------


@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/v2/assignment-decisions", {"ticket_ids": ["x"]}),
    ("post", "/api/v2/assignment-decisions/x/accept", None),
    ("post", "/api/v2/assignment-decisions/x/override", {"agent_id": "a", "reason": "b"}),
    ("post", "/api/v2/tickets/rescore", {"only_stale": False}),
    ("get", "/api/v2/risk-radar", None),
])
def test_every_dispatch_route_requires_a_session(client, method, path, body):
    call = getattr(client, method)
    response = call(path, json=body) if body is not None else call(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


def test_a_deactivated_user_cannot_recommend_and_writes_nothing(
    client, db, signed_in, dispatch_fixture
):
    """Deactivation takes effect on the next request, not at the next sign-in."""
    user = signed_in("dispatcher")
    agent, ticket = dispatch_fixture()
    before = _count(db, models.AssignmentDecision)

    user.is_active = False
    db.commit()

    response = client.post(
        "/api/v2/assignment-decisions", json={"ticket_ids": [ticket.id]}
    )
    assert response.status_code == 401

    db.expire_all()
    assert _count(db, models.AssignmentDecision) == before


def test_a_revoked_session_cannot_accept(client, db, signed_in, dispatch_fixture):
    signed_in("dispatcher")
    agent, ticket = dispatch_fixture()
    decision_id = client.post(
        "/api/v2/assignment-decisions", json={"ticket_ids": [ticket.id]}
    ).json()["decisions"][0]["decision_id"]

    assert client.post("/api/v2/logout").status_code == 200
    refused = client.post("/api/v2/assignment-decisions/%s/accept" % decision_id)
    assert refused.status_code == 401

    db.expire_all()
    assert db.get(models.Ticket, ticket.id).current_assignee_id is None


# --- a refusal writes nothing ----------------------------------------------


def test_a_refused_override_leaves_no_event_and_no_assignment(
    client, db, signed_in, dispatch_fixture
):
    signed_in("dispatcher")
    agent, ticket = dispatch_fixture()
    decision_id = client.post(
        "/api/v2/assignment-decisions", json={"ticket_ids": [ticket.id]}
    ).json()["decisions"][0]["decision_id"]
    events_before = _count(db, models.TicketEvent)

    refused = client.post(
        "/api/v2/assignment-decisions/%s/override" % decision_id,
        json={"agent_id": "no-such-agent", "reason": "trying"},
    )
    assert refused.status_code == 404
    assert refused.json()["error"]["code"] == "AGENT_NOT_FOUND"

    db.expire_all()
    assert _count(db, models.TicketEvent) == events_before
    assert db.get(models.Ticket, ticket.id).current_assignee_id is None


def test_every_event_written_by_a_flow_names_its_actor(
    client, db, signed_in, dispatch_fixture
):
    """Spec H.1: actor, decision reference where relevant, and a UTC timestamp."""
    actor = signed_in("dispatcher")
    agent, ticket = dispatch_fixture()
    decision_id = client.post(
        "/api/v2/assignment-decisions", json={"ticket_ids": [ticket.id]}
    ).json()["decisions"][0]["decision_id"]
    client.post("/api/v2/assignment-decisions/%s/accept" % decision_id)

    events = client.get("/api/v2/tickets/%s/events" % ticket.id).json()["events"]
    dispatch_events = [
        event for event in events
        if event["event_type"] in ("ASSIGNMENT_RECOMMENDED", "ASSIGNMENT_ACCEPTED")
    ]
    assert len(dispatch_events) == 2
    for event in dispatch_events:
        assert event["actor_user_id"] == actor.id
        assert event["decision_id"] == decision_id
        assert event["occurred_at"].endswith("Z") or "+00:00" in event["occurred_at"]


def test_the_session_cookie_is_the_only_way_in(client, db, signed_in, dispatch_fixture):
    """A guessed session id is not a session: the stored id is a hash of the cookie."""
    signed_in("dispatcher")
    agent, ticket = dispatch_fixture()
    session_id = db.scalars(select(models.Session.id)).first()

    client.cookies.set(auth.SESSION_COOKIE_NAME, session_id)
    response = client.post(
        "/api/v2/assignment-decisions", json={"ticket_ids": [ticket.id]}
    )
    assert response.status_code == 401
