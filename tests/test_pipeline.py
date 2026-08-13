import pandas as pd
import pytest

from api.engine.replacement import workstation_factors
from api.engine.pipeline import assignment_stage, run_pipeline, _reassigned_tickets


def _scarcity_fixture():
    # same crafted pattern as test_m3: 3 tickets sharing one skill, only 2
    # agents of that skill -> Hungarian must drop one ticket, so ageing
    # one workstation enough is guaranteed to flip which ticket gets served.
    tickets = pd.DataFrame({
        "id": ["T1", "T2", "T3"],
        "skill": ["network"] * 3,
        "base_resolution_minutes": [10, 11, 12],
        "workstation_id": ["WS1", "WS2", "WS3"],
    })
    agents = pd.DataFrame({"id": ["A1", "A2"], "skill": ["network", "network"]})
    workstations = pd.DataFrame({
        "id": ["WS1", "WS2", "WS3"],
        "age_months": [0, 0, 0],
    })
    return tickets, agents, workstations


def test_ageing_raises_cost_and_reassigns_on_crafted_instance():
    tickets, agents, workstations = _scarcity_fixture()

    baseline = assignment_stage(tickets, agents, degradation=None)

    aged_workstations = workstations.copy()
    aged_workstations.loc[aged_workstations["id"] == "WS1", "age_months"] = 50  # factor 1+0.02*50=2.0
    aged_factors = workstation_factors(aged_workstations)
    aged = assignment_stage(tickets, agents, degradation=aged_factors)

    assert aged["total_cost"] >= baseline["total_cost"]
    reassigned = _reassigned_tickets(baseline["pairs"], aged["pairs"])
    assert len(reassigned) >= 1


def test_replacement_restores_factor_and_lowers_cost():
    tickets, agents, workstations = _scarcity_fixture()

    baseline = assignment_stage(tickets, agents, degradation=None)

    aged_workstations = workstations.copy()
    aged_workstations.loc[aged_workstations["id"] == "WS1", "age_months"] = 50
    aged_factors = workstation_factors(aged_workstations)
    aged = assignment_stage(tickets, agents, degradation=aged_factors)
    assert aged["total_cost"] > baseline["total_cost"]

    replaced_workstations = aged_workstations.copy()
    replaced_workstations.loc[replaced_workstations["id"] == "WS1", "age_months"] = 0
    post_factors = workstation_factors(replaced_workstations)
    assert post_factors["WS1"] == 1.0

    post = assignment_stage(tickets, agents, degradation=post_factors)
    assert post["total_cost"] < aged["total_cost"]
    assert post["total_cost"] == pytest.approx(baseline["total_cost"])


def test_run_pipeline_end_to_end_deterministic_seed():
    result = run_pipeline(seed=42, verbose=False)

    for key in ("data", "m1", "m2", "baseline", "aged", "post_replacement", "stages", "m4", "m5", "m6"):
        assert key in result

    stages = result["stages"]
    assert stages["baseline"]["total_cost"] >= 0
    assert stages["aged"]["total_cost"] >= stages["baseline"]["total_cost"]
    assert stages["post_replacement"]["total_cost"] <= stages["aged"]["total_cost"]

    assert result["m1"]["status"] == "Optimal"
    assert result["m4"]["makespan"] > 0
    assert result["m5"]["best_index"] in (0, 1, 2)
    assert result["m6"]["schedule"]["critical_path"]


def test_run_pipeline_reproducible_across_calls():
    a = run_pipeline(seed=42, verbose=False)
    b = run_pipeline(seed=42, verbose=False)
    assert a["stages"] == b["stages"]
