"""Opt-in benchmark of the full manual-rescore path (spec H.5).

    pytest -m performance -q

Excluded from the default run by ``addopts`` in ``pytest.ini``, because a
hardware-dependent timing has no business failing a correctness suite on someone
else's laptop.

What is measured is the whole path the endpoint runs: read the open tickets,
build the feature frame, load and call both artifacts, and write the risk fields
and events transactionally. Loading the artifact is excluded from the timed runs
by one warm-up pass, because unpickling happens once per process in the running
API and including it would measure joblib rather than the rescore.

The number this produces is a regression baseline for one demo machine on one
date. It is not a latency claim about anything else, and ``docs/performance.md``
says so in those words.
"""

import os
import platform
import statistics
import time
from datetime import timedelta

import pytest

from api.servicedesk.db import models
from api.servicedesk.db.session import session_scope, set_engine
from api.servicedesk.db.types import utcnow
from api.servicedesk.services import decisions as decision_service
from api.servicedesk.services import scoring, security

#: Fixed by the plan: 500 open tickets, 80 agents.
TICKET_COUNT = 500
AGENT_COUNT = 80
#: Predeclared before any timing was recorded.
WARM_RUNS = 1
TIMED_RUNS = 5

SKILLS = ("network", "database", "hardware", "desktop")
RESULTS_PATH = os.path.join("docs", "performance.md")

pytestmark = pytest.mark.performance


@pytest.fixture
def loaded_desk(engine, database_url):
    """A seeded desk: one manager, 80 agents, 500 unscored open tickets.

    Deterministic by construction - every field is a function of the row index,
    so two runs on the same machine benchmark the same work.
    """
    set_engine(engine)
    db = session_scope()
    manager = models.User(
        username="perf.manager",
        password_hash=security.hash_password("local-demo-password"),
        role="manager",
    )
    db.add(manager)
    for priority, target in ((1, 60), (2, 240), (3, 480), (4, 1440)):
        db.add(models.SlaPolicy(
            priority=priority, target_minutes=target,
            breach_penalty_per_minute=20.0 / priority,
            late_penalty_per_minute=18.0 / priority,
            overdue_recovery_penalty_per_minute=24.0 / priority,
            holding_cost_per_minute=1.0 / priority,
            escalation_threshold=0.5 + 0.1 * priority,
            version=1,
            source_note="benchmark fixture; not an organisational SLA policy",
        ))
    db.flush()

    for index in range(AGENT_COUNT):
        agent = models.Agent(display_name="Resolver %03d" % index, wip_limit=3)
        db.add(agent)
        db.flush()
        db.add(models.AgentSkill(
            agent_id=agent.id, skill=SKILLS[index % len(SKILLS)],
            efficiency_multiplier=1.0, is_primary=True,
        ))

    opened_at = utcnow() - timedelta(hours=6)
    for index in range(TICKET_COUNT):
        priority = (index % 4) + 1
        db.add(models.Ticket(
            external_reference="PERF-%04d" % index,
            source="seed_demo", status="open", priority=priority,
            category="Network", subcategory="Connectivity", location="Pune",
            contact_type="Phone", required_skill=SKILLS[index % len(SKILLS)],
            opened_at=opened_at + timedelta(minutes=index),
            sla_due_at=opened_at + timedelta(minutes=index + 60 * priority),
        ))
    db.commit()
    yield db, manager
    db.close()


def test_full_rescore_path_at_500_tickets_and_80_agents(loaded_desk, engine):
    db, manager = loaded_desk
    scoring.reset_cache()

    for _ in range(WARM_RUNS):
        warm = decision_service.rescore(db, manager, only_stale=False)
        db.commit()
    # The fixture tickets start unscored, so the warm-up is the pass that writes
    # every score and every event. Asserting it here is what stops the timed runs
    # from silently measuring a path with no event writes in it at all.
    assert warm["rescored"] == TICKET_COUNT

    samples = []
    for _ in range(TIMED_RUNS):
        started = time.perf_counter()
        summary = decision_service.rescore(db, manager, only_stale=False)
        db.commit()
        samples.append((time.perf_counter() - started) * 1000.0)

    assert summary["considered"] == TICKET_COUNT
    # Every feature the artifact reads is fixed at ticket creation, so a second
    # pass over unchanged tickets must move no score and write no event.
    assert summary["rescored"] == 0
    median = statistics.median(samples)
    p95 = sorted(samples)[max(0, int(round(0.95 * len(samples))) - 1)]
    _write_report(engine, median, p95, samples, summary)

    # A loose guard rail, not a target: it fails only if something has become
    # slow by an order of magnitude, which is the regression this test exists
    # to catch.
    assert median < 30_000.0


def _write_report(engine, median, p95, samples, summary):
    """Record the measurement with the machine it was taken on (spec H.5)."""
    body = _REPORT_TEMPLATE.format(
        date=utcnow().strftime("%Y-%m-%d"),
        machine="%s %s, Python %s" % (
            platform.system(), platform.machine(), platform.python_version()
        ),
        processor=platform.processor() or "unreported",
        dialect=engine.dialect.name,
        tickets=TICKET_COUNT,
        agents=AGENT_COUNT,
        warm=WARM_RUNS,
        timed=TIMED_RUNS,
        median="%.1f" % median,
        p95="%.1f" % p95,
        samples=", ".join("%.1f" % sample for sample in samples),
        rescored=summary["rescored"],
        unchanged=summary["unchanged"],
        risk_model=scoring.risk_scorer().version,
        duration_model=scoring.duration_estimator().version,
    )
    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8") as handle:
        handle.write(body)


_REPORT_TEMPLATE = """# Performance baseline

Generated by `pytest -m performance -q` on {date}. This is a regression baseline
for one machine, not a latency claim about any other environment. Re-running it
overwrites this file, which is the point: a stale number here would be worse than
no number.

## What was measured

The full manual-rescore path, the same function the manager-only endpoint calls:
read every non-terminal ticket, build one feature frame, score it with both saved
artifacts, write the risk fields, and write `RISK_SCORED` events, all inside one
transaction that is then committed.

Artifact loading is not in the timed runs. It happens once per process in the
running API, so a warm-up pass pays for it first; including it would measure
joblib rather than the rescore.

## Machine and mode

| Item | Value |
|---|---|
| Machine | {machine} |
| Processor | {processor} |
| Database | {dialect} |
| Risk model | `{risk_model}` |
| Duration model | `{duration_model}` |

## Fixture

{tickets} open tickets, {agents} active agents with one skill each, four SLA
policies. Every field is a function of the row index, so the fixture is the same
work on every run.

## Result

| Metric | Milliseconds |
|---|---:|
| Median of {timed} timed runs | {median} |
| p95 | {p95} |

Warm-up runs: {warm}. Individual timed runs, in order: {samples}.

The warm-up pass scored all {tickets} tickets and wrote their events, because
the fixture creates them unscored. The last timed run considered every ticket
and rescored {rescored}, leaving {unchanged} unchanged.

That zero is the correct steady state, not a fault. Every feature the artifact
reads is fixed when a ticket is created, so rescoring an unchanged ticket with an
unchanged artifact returns the same number and the material-change test writes
nothing. The timed figure below therefore measures reading the tickets, building
one feature frame, both model calls, and the commit. Event writing is exercised
by the warm-up rather than by the timed runs, and a workload where many scores
had genuinely moved would be slower than this.
"""
