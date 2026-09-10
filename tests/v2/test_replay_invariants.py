"""The replay must be incapable of validating itself.

Every test here is an attempt to break that. A benchmark where the model can
influence the outcome it is scored against produces numbers that look like
evidence and are not, and it fails silently — the simulation still runs, the
table still fills in, the proposed policy still wins.

The fixtures are small and hand-built so each expected value can be checked on
paper. Two tests touch the real data because the guard they check
(`build_training_profile` refusing test rows) is only meaningful against the
real split.
"""
import os

import numpy as np
import pandas as pd
import pytest

from api.app_v2.eval import emulation, jobs as jobs_module
from api.app_v2.eval.emulation import Agent, NotTrainingData, SLA_POLICY
from api.app_v2.eval.jobs import (
    HIDDEN_OUTCOME_FIELDS,
    Job,
    JobView,
    build_exogenous_jobs,
    jobs_fingerprint,
)
from api.app_v2.eval.policies import (
    TIE_EPSILON,
    DurationFirst,
    Fifo,
    PriorityOnly,
    SlaRiskAware,
    Slot,
    _tie_break,
)
from api.app_v2.eval.replay import build_slots, run_policy, summarise

HOUR = 60.0


def view(incident_id, arrival=0.0, priority=3, skill="Group A", due=None,
         predicted=60.0, risk=0.5):
    return JobView(
        incident_id=incident_id,
        arrival_minute=arrival,
        priority=priority,
        required_skill=skill,
        sla_due_minute=arrival + SLA_POLICY[priority]["target_minutes"] if due is None else due,
        predicted_duration_minutes=predicted,
        risk_probability=risk,
    )


def job(incident_id, service, **kwargs):
    return Job(view=view(incident_id, **kwargs), service_minutes=service)


def agent(agent_id="R1", skills=("Group A",), wip=1, speed=1.0):
    return Agent(agent_id, frozenset(skills), wip, speed, training_incidents=100)


def test_a_policy_cannot_see_the_service_demand():
    """`JobView` carries no demand field and no route back to the job that has
    one. A view holding `self._job` would pass an attribute check and still leak."""
    one = job("INC1", service=500.0)
    fields = set(JobView.__dataclass_fields__)
    for hidden in HIDDEN_OUTCOME_FIELDS:
        assert hidden not in fields
    assert not any(
        isinstance(value, Job) for value in vars(one.view).values()
    ), "JobView holds a reference back to its Job"
    with pytest.raises(AttributeError):
        one.view.service_minutes


def test_predictions_cannot_move_the_stored_demand():
    """Change every prediction; the exogenous demand must not follow."""
    rows = pd.DataFrame({
        "incident_id": ["INC1", "INC2"],
        "opened_at": pd.to_datetime(["2016-05-16 09:00", "2016-05-16 10:00"]),
        "priority": ["3 - Moderate", "1 - Critical"],
        "category": ["Category 1", "Category 2"],
        "duration_minutes": [120.0, 900.0],
    })
    profile = emulation.TrainingProfile((), {}, "Group A", {})
    first = build_exogenous_jobs(rows, profile, [0.1, 0.2], [10.0, 20.0], seed=1)
    second = build_exogenous_jobs(rows, profile, [0.9, 0.8], [999.0, 5.0], seed=1)

    assert [j.service_minutes for j in first] == [120.0, 900.0]
    assert [j.service_minutes for j in second] == [120.0, 900.0]
    assert [j.view.sla_due_minute for j in first] == [j.view.sla_due_minute for j in second]


def test_every_policy_in_a_scenario_gets_the_same_fixtures():
    """The fingerprint covers arrivals, deadlines, predictions and demand, and
    running a policy must not disturb any of them."""
    fixtures = (job("INC1", 100.0), job("INC2", 200.0, arrival=30.0))
    before = jobs_fingerprint(fixtures)
    for policy in (Fifo(), PriorityOnly(), DurationFirst(), SlaRiskAware()):
        run_policy(fixtures, (agent(),), policy)
        assert jobs_fingerprint(fixtures) == before


def test_fifo_is_invariant_to_the_model_outputs():
    """The strong version: replace every prediction and rerun. If FIFO's result
    moves, something in the loop is reading a model where it should not."""
    base = (
        job("INC1", 100.0, arrival=0.0, predicted=10.0, risk=0.1),
        job("INC2", 300.0, arrival=5.0, predicted=20.0, risk=0.2),
        job("INC3", 50.0, arrival=7.0, predicted=30.0, risk=0.3),
    )
    scrambled = tuple(
        Job(view=JobView(
            **{**vars(j.view),
               "predicted_duration_minutes": 999.0 - j.view.predicted_duration_minutes,
               "risk_probability": 1.0 - j.view.risk_probability}),
            service_minutes=j.service_minutes)
        for j in base
    )
    agents = (agent(wip=1),)
    first = run_policy(base, agents, Fifo())
    second = run_policy(scrambled, agents, Fifo())
    pd.testing.assert_frame_equal(
        first.drop(columns=[]), second.drop(columns=[]), check_exact=True
    )


def test_a_run_is_deterministic():
    fixtures = (job("INC1", 100.0), job("INC2", 90.0, arrival=1.0), job("INC3", 5.0))
    agents = (agent(wip=1, speed=1.3), agent("R2", wip=1, speed=0.8))
    a = run_policy(fixtures, agents, SlaRiskAware())
    b = run_policy(fixtures, agents, SlaRiskAware())
    pd.testing.assert_frame_equal(a, b, check_exact=True)


def test_breach_is_decided_only_by_the_clock():
    """A high-risk ticket that finishes early does not breach; a low-risk ticket
    that finishes late does. The risk model ranks; it never writes an outcome."""
    fixtures = (
        job("EARLY", service=10.0, priority=3, risk=0.99),
        job("LATE", service=5000.0, priority=3, risk=0.01),
    )
    outcomes = run_policy(fixtures, (agent(wip=2),), Fifo()).set_index("incident_id")
    assert outcomes.loc["EARLY", "breached"] is np.False_ or not outcomes.loc["EARLY", "breached"]
    assert outcomes.loc["LATE", "breached"]
    # 1,440-minute target for priority 3, so the boundary is arithmetic
    assert outcomes.loc["LATE", "finish_minute"] > outcomes.loc["LATE", "sla_due_minute"]


def test_capacity_multiplier_moves_capacity_and_nothing_else():
    original = agent(wip=10, speed=1.4, skills=("Group A", "Group B"))
    scaled = original.scaled(0.5)
    assert scaled.wip_limit == 5
    assert scaled.skills == original.skills
    assert scaled.speed_multiplier == original.speed_multiplier
    # capacity never rounds an agent out of existence
    assert original.scaled(0.01).wip_limit == 1


def test_p1_is_not_starved_by_a_lower_priority_ticket():
    """One free slot, a P4 that has waited all morning and a P1 that just
    arrived. Tiering has to take the P1; FIFO by construction takes the P4."""
    waiting = [
        view("P4-OLD", arrival=0.0, priority=4),
        view("P1-NEW", arrival=300.0, priority=1),
    ]
    slots = [Slot("R1", 0, 1.0, frozenset({"Group A"}))]
    chosen, _ = SlaRiskAware().choose(waiting, slots, now=300.0)
    assert chosen.incident_id == "P1-NEW"
    chosen_fifo, _ = Fifo().choose(waiting, slots, now=300.0)
    assert chosen_fifo.incident_id == "P4-OLD"


def test_an_overdue_ticket_stays_eligible_and_gains_priority():
    """Recovery urgency for a ticket 12 hours past its deadline must exceed the
    urgency of one still inside its window, and it must be pickable."""
    policy = SlaRiskAware()
    inside = view("INSIDE", arrival=0.0, priority=3, risk=0.9)
    overdue = view("OVERDUE", arrival=0.0, priority=3, risk=0.1)
    now = SLA_POLICY[3]["target_minutes"] + 12 * HOUR
    assert policy.urgency(overdue, now) > policy.urgency(inside, 0.0)

    slots = [Slot("R1", 0, 1.0, frozenset({"Group A"}))]
    chosen, _ = policy.choose([inside, overdue], slots, now=now)
    assert chosen.incident_id in {"INSIDE", "OVERDUE"}
    # both are overdue at this clock; the more overdue one wins
    later = view("LATER", arrival=-600.0, priority=3, due=0.0, risk=0.1)
    chosen, _ = policy.choose([inside, later], slots, now=now)
    assert chosen.incident_id == "LATER"


def test_no_ticket_is_silently_dropped():
    """A skill no agent holds produces a visible state, not a missing row."""
    fixtures = (
        job("SERVED", 30.0, skill="Group A"),
        job("ORPHAN", 30.0, skill="Group Z"),
    )
    outcomes = run_policy(fixtures, (agent(skills=("Group A",)),), Fifo())
    assert len(outcomes) == len(fixtures)
    states = outcomes.set_index("incident_id")["state"].to_dict()
    assert states == {"SERVED": "completed", "ORPHAN": "no_eligible_agent"}
    assert summarise(outcomes, "fifo", 1.0)["visible_unassigned"] == 1


def test_the_tie_break_cannot_outweigh_a_real_cost():
    """The smallest declared rate is 0.1 per minute. The epsilon has to be far
    below anything that could represent a business difference."""
    smallest_rate = min(p["holding_cost_per_minute"] for p in SLA_POLICY.values())
    nudge = _tie_break(view("INC1"), Slot("R1", 0, 1.0, frozenset({"Group A"})))
    assert 0.0 <= nudge <= TIE_EPSILON
    assert TIE_EPSILON < smallest_rate * 1e-6


def test_the_tie_break_is_stable_across_processes():
    """A salted `hash()` would make two sessions disagree about a tie."""
    import subprocess
    import sys

    code = (
        "from api.app_v2.eval.policies import _tie_break, Slot;"
        "from api.app_v2.eval.jobs import JobView;"
        "v=JobView('INC1',0.0,3,'Group A',100.0,10.0,0.5);"
        "print('%.18f' % _tie_break(v, Slot('R1',0,1.0,frozenset({'Group A'}))))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, cwd=os.getcwd())
    assert result.returncode == 0, result.stderr
    here = _tie_break(view("INC1"), Slot("R1", 0, 1.0, frozenset({"Group A"})))
    assert float(result.stdout.strip()) == pytest.approx(here, abs=1e-18)


def test_slots_expand_in_a_stable_order():
    agents = (agent("R2", wip=2), agent("R1", wip=1))
    keys = [slot.key for slot in build_slots(agents)]
    assert keys == [("R1", 0), ("R2", 0), ("R2", 1)]


# --------------------------------------------------------------------------
# Against the real split
# --------------------------------------------------------------------------

from api.app_v2.ingest.uci498 import PROCESSED_PARQUET  # noqa: E402

needs_prepared = pytest.mark.skipif(
    not os.path.exists(PROCESSED_PARQUET),
    reason="prepared data absent; run `python -m api.app_v2.ingest.uci498 prepare`",
)


@needs_prepared
def test_the_workforce_profile_refuses_test_period_rows():
    """The emulation reads `resolved_by` and `assignment_group`, which the model
    may never see. The guard is what keeps that read inside the training period,
    and it has to refuse rather than filter."""
    prepared = pd.read_parquet(PROCESSED_PARQUET)
    test_rows = emulation.load_emulation_records(prepared, split="test")
    with pytest.raises(NotTrainingData) as excinfo:
        emulation.build_training_profile(test_rows)
    assert "test" in str(excinfo.value)

    mixed = pd.concat([
        emulation.load_emulation_records(prepared, split="train").head(50),
        test_rows.head(5),
    ])
    with pytest.raises(NotTrainingData):
        emulation.build_training_profile(mixed)


@needs_prepared
def test_the_skill_map_is_built_from_training_categories_only():
    prepared = pd.read_parquet(PROCESSED_PARQUET)
    train = emulation.load_emulation_records(prepared, split="train")
    profile = emulation.build_training_profile(train)
    assert profile.assumptions["skill_map_categories"] > 0
    assert profile.assumptions["source"] == "training-period incidents only"
    # a category absent from training still resolves, to the declared fallback
    assert profile.required_skill("Category never seen") == profile.fallback_skill
