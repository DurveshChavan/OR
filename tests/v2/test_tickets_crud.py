"""Ticket CRUD, the deadline rule, and the events each change leaves behind."""
from datetime import timedelta

from api.app_v2.db import models
from api.app_v2.db.types import utcnow


def _create(client, **overrides):
    body = {
        "external_reference": "INC-TEST-0001",
        "priority": 2,
        "category": "Network",
        "required_skill": "network",
    }
    body.update(overrides)
    return client.post("/api/v2/tickets", json=body)


def test_create_ticket_sets_the_deadline_from_the_policy(client, signed_in, make_policy):
    signed_in("dispatcher")
    make_policy(priority=2, target_minutes=240)
    opened_at = utcnow().replace(microsecond=0)

    response = _create(client, opened_at=opened_at.isoformat())
    assert response.status_code == 201, response.text
    ticket = response.json()["ticket"]

    from datetime import datetime

    due = datetime.fromisoformat(ticket["sla_due_at"])
    assert due - opened_at == timedelta(minutes=240)
    assert ticket["status"] == "open"
    assert ticket["source"] == "manual"


def test_create_without_a_policy_for_the_priority_is_refused(client, signed_in, make_policy):
    signed_in("dispatcher")
    make_policy(priority=2)

    response = _create(client, priority=1)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SLA_POLICY_MISSING"


def test_creation_writes_its_events_in_the_same_transaction(
    client, db, signed_in, make_policy
):
    actor = signed_in("dispatcher")
    make_policy(priority=2)
    ticket_id = _create(client).json()["ticket"]["id"]

    events = client.get("/api/v2/tickets/%s/events" % ticket_id).json()["events"]
    types = [event["event_type"] for event in events]

    assert types[0] == "TICKET_CREATED"
    # Phase 1 has no risk artifact, so the ticket is honestly marked unscored
    # rather than given an invented probability.
    assert "MODEL_UNAVAILABLE" in types
    assert all(event["actor_user_id"] == actor.id for event in events)

    stored = db.get(models.Ticket, ticket_id)
    assert stored.risk_probability is None
    assert stored.risk_model_version is None


def test_a_failed_creation_leaves_no_ticket_behind(client, db, signed_in, make_policy):
    signed_in("dispatcher")
    make_policy(priority=2)
    _create(client, external_reference="INC-TEST-DUP")

    duplicate = _create(client, external_reference="INC-TEST-DUP")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "EXTERNAL_REFERENCE_IN_USE"

    matching = (
        db.query(models.Ticket)
        .filter(models.Ticket.external_reference == "INC-TEST-DUP")
        .count()
    )
    assert matching == 1


def test_patch_records_only_the_fields_that_changed(client, signed_in, make_policy):
    signed_in("dispatcher")
    make_policy(priority=2)
    ticket_id = _create(client).json()["ticket"]["id"]

    response = client.patch(
        "/api/v2/tickets/%s" % ticket_id,
        json={"priority": 2, "required_skill": "database"},
    )
    assert response.status_code == 200

    events = client.get("/api/v2/tickets/%s/events" % ticket_id).json()["events"]
    updates = [event for event in events if event["event_type"] == "TICKET_UPDATED"]
    assert len(updates) == 1
    assert set(updates[0]["payload"]["changes"]) == {"required_skill"}


def test_patch_does_not_move_an_existing_deadline(client, signed_in, make_policy):
    signed_in("dispatcher")
    make_policy(priority=2, target_minutes=240)
    make_policy(priority=1, target_minutes=60)
    created = _create(client).json()["ticket"]

    patched = client.patch(
        "/api/v2/tickets/%s" % created["id"], json={"priority": 1}
    ).json()["ticket"]

    assert patched["priority"] == 1
    assert patched["sla_due_at"] == created["sla_due_at"]


def test_list_is_ordered_by_deadline_then_id(client, signed_in, make_policy):
    signed_in("dispatcher")
    make_policy(priority=1, target_minutes=60)
    make_policy(priority=3, target_minutes=480)
    _create(client, external_reference="INC-TEST-LATE", priority=3)
    _create(client, external_reference="INC-TEST-SOON", priority=1)

    tickets = client.get("/api/v2/tickets").json()["tickets"]
    assert [t["external_reference"] for t in tickets] == ["INC-TEST-SOON", "INC-TEST-LATE"]


def test_event_history_is_ascending_and_stable(client, signed_in, make_policy):
    signed_in("dispatcher")
    make_policy(priority=2)
    ticket_id = _create(client).json()["ticket"]["id"]
    client.patch("/api/v2/tickets/%s" % ticket_id, json={"status": "assigned"})

    first = client.get("/api/v2/tickets/%s/events" % ticket_id).json()["events"]
    second = client.get("/api/v2/tickets/%s/events" % ticket_id).json()["events"]

    assert [event["id"] for event in first] == [event["id"] for event in second]
    occurrences = [event["occurred_at"] for event in first]
    assert occurrences == sorted(occurrences)


def test_unknown_ticket_returns_the_error_envelope(client, signed_in):
    signed_in("dispatcher")
    response = client.get("/api/v2/tickets/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TICKET_NOT_FOUND"


def test_state_and_history_survive_a_restart(client, engine, signed_in, make_policy):
    """The point of the phase: nothing lives in process memory."""
    signed_in("dispatcher")
    make_policy(priority=2)
    ticket_id = _create(client).json()["ticket"]["id"]

    from fastapi.testclient import TestClient

    from api.app_v2.db import session as session_module
    from api.app_v2.main import app

    session_module.set_engine(engine)
    with TestClient(app) as restarted:
        restarted.post(
            "/api/v2/login",
            json={"username": "dispatcher.test", "password": "local-demo-password"},
        )
        ticket = restarted.get("/api/v2/tickets/%s" % ticket_id)
        events = restarted.get("/api/v2/tickets/%s/events" % ticket_id)

    assert ticket.status_code == 200
    assert ticket.json()["ticket"]["id"] == ticket_id
    assert len(events.json()["events"]) >= 2
