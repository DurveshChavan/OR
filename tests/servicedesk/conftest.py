"""Fixtures for the service-desk suite.

Every database test runs against both supported dialects. SQLite always runs,
on a fresh file per test. PostgreSQL runs when ``DATABASE_URL_TEST_PG`` points
at a database that may be wiped; without it the PostgreSQL half is skipped with
that reason, and the exit gate for the phase reads as unverified rather than
green. A skipped dialect is a known gap, and it should look like one.

Schemas are built by running the real migrations, not ``create_all``, so a test
proves the migration path a deployment would take.
"""
import os
import uuid
from datetime import timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from api.servicedesk.db import models
from api.servicedesk.db.session import make_engine
from api.servicedesk.db.types import utcnow

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PG_URL_ENV = "DATABASE_URL_TEST_PG"


def alembic_config(url: str) -> Config:
    """An Alembic config pinned to this project and to one database URL."""
    config = Config(os.path.join(PROJECT_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(PROJECT_ROOT, "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def upgrade_to_head(url: str) -> None:
    """Run every migration against `url`."""
    command.upgrade(alembic_config(url), "head")


def _postgres_url():
    return os.environ.get(PG_URL_ENV)


@pytest.fixture(params=["sqlite", "postgresql"])
def database_url(request, tmp_path):
    """A URL for an empty database of the requested dialect, or a skip."""
    if request.param == "sqlite":
        return "sqlite:///" + str(tmp_path / "v2_test.sqlite3").replace("\\", "/")
    url = _postgres_url()
    if not url:
        pytest.skip(
            "PostgreSQL half of the dialect matrix not verified: set %s to a "
            "database that may be wiped" % PG_URL_ENV
        )
    _drop_everything(url)
    return url


def _drop_everything(url: str) -> None:
    """Return a PostgreSQL test database to empty before a migration run."""
    engine = make_engine(url)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
        connection.exec_driver_sql("CREATE SCHEMA public")
    engine.dispose()


@pytest.fixture
def engine(database_url):
    """An engine whose database is migrated to head."""
    upgrade_to_head(database_url)
    engine = make_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine):
    """One session per test, rolled back and closed at the end."""
    session = Session(bind=engine, expire_on_commit=False, future=True)
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def client(engine):
    """A TestClient whose application talks to this test's database."""
    from fastapi.testclient import TestClient

    from api.servicedesk.db import session as session_module
    from api.servicedesk.main import app

    previous = session_module._engine
    session_module.set_engine(engine)
    with TestClient(app) as test_client:
        yield test_client
    if previous is None:
        session_module._engine = None
        session_module._session_factory = None
    else:
        session_module.set_engine(previous)


@pytest.fixture
def demo_password():
    return "local-demo-password"


@pytest.fixture
def signed_in(client, db, demo_password):
    """Sign in as a user of the requested role and return the client."""
    from api.servicedesk.services import security

    def _sign_in(role="dispatcher", is_active=True):
        user = models.User(
            username="%s.test" % role,
            password_hash=security.hash_password(demo_password),
            role=role,
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        response = client.post(
            "/api/login", json={"username": user.username, "password": demo_password}
        )
        assert response.status_code == 200, response.text
        return user

    return _sign_in


# --- small factories -------------------------------------------------------
# They exist so a test states only the field it is actually about.


@pytest.fixture
def make_user(db):
    def _make(username=None, role="dispatcher", is_active=True):
        user = models.User(
            username=username or "user-%s" % uuid.uuid4().hex[:8],
            password_hash="not-a-real-hash",
            role=role,
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        return user

    return _make


@pytest.fixture
def make_agent(db):
    def _make(display_name="Resolver 17", wip_limit=4, is_active=True, skills=("network",)):
        agent = models.Agent(
            display_name=display_name, wip_limit=wip_limit, is_active=is_active
        )
        db.add(agent)
        db.flush()
        for index, skill in enumerate(skills):
            db.add(
                models.AgentSkill(
                    agent_id=agent.id,
                    skill=skill,
                    efficiency_multiplier=1.0,
                    is_primary=index == 0,
                )
            )
        db.commit()
        return agent

    return _make


@pytest.fixture
def make_policy(db):
    def _make(priority=2, target_minutes=240):
        policy = models.SlaPolicy(
            priority=priority,
            target_minutes=target_minutes,
            breach_penalty_per_minute=5.0,
            late_penalty_per_minute=4.0,
            overdue_recovery_penalty_per_minute=6.0,
            holding_cost_per_minute=0.5,
            escalation_threshold=0.7,
            version=1,
            source_note="illustrative demo policy; replace with organisational SLA policy",
        )
        db.add(policy)
        db.commit()
        return policy

    return _make


@pytest.fixture
def make_ticket(db):
    def _make(priority=2, status="open", source="manual", required_skill="network", **kwargs):
        opened_at = kwargs.pop("opened_at", utcnow())
        ticket = models.Ticket(
            source=source,
            status=status,
            priority=priority,
            required_skill=required_skill,
            opened_at=opened_at,
            sla_due_at=kwargs.pop("sla_due_at", opened_at + timedelta(minutes=240)),
            **kwargs,
        )
        db.add(ticket)
        db.commit()
        return ticket

    return _make


@pytest.fixture
def make_decision(db):
    def _make(ticket, agent=None, state="recommended", policy_version=1):
        decision = models.AssignmentDecision(
            ticket_id=ticket.id,
            recommended_agent_id=agent.id if agent is not None else None,
            recommendation_state=state,
            risk_probability=0.68,
            predicted_duration_minutes=41.2,
            projected_wait_minutes=11.0,
            projected_finish_at=utcnow() + timedelta(minutes=52),
            projected_lateness_minutes=0.0,
            model_version="test-risk-model",
            policy_version=policy_version,
            candidate_payload_json={"candidates": [], "tie_break_epsilon": 1e-9},
            reason_text="test recommendation",
        )
        db.add(decision)
        db.commit()
        return decision

    return _make


@pytest.fixture
def make_event(db):
    def _make(ticket, event_type="TICKET_CREATED", actor=None, decision=None, payload=None):
        event = models.TicketEvent(
            ticket_id=ticket.id,
            decision_id=decision.id if decision is not None else None,
            actor_user_id=actor.id if actor is not None else None,
            event_type=event_type,
            payload_json=payload or {"note": "test event"},
        )
        db.add(event)
        db.commit()
        return event

    return _make
