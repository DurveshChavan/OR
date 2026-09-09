import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)

# n_tickets=10 against n_agents=200 comfortably exceeds funded headcount
# per skill for every real UCI-498-derived demand shape, so the baseline
# assignment serves every ticket -- that's what makes "ageing strictly
# raises cost, replacement strictly lowers it" a guaranteed inequality
# rather than a coin flip on which ticket the Hungarian optimum drops.
SCENARIO_BODY = {"n_tickets": 10, "n_agents": 200, "n_workstations": 10, "seed": 42}


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_scenario_staffing_assignment_age_replace_happy_path():
    scenario = client.post("/api/scenario", json=SCENARIO_BODY)
    assert scenario.status_code == 200
    body = scenario.json()
    assert body["n_tickets"] == 10
    assert "data_source" in body
    assert set(body["derived_sources"]) == {
        "priority_mix", "breach", "regions", "categories", "durations",
    }

    staffing = client.get("/api/staffing")
    assert staffing.status_code == 200
    staffing_body = staffing.json()
    assert staffing_body["status"] == "Optimal"
    assert sum(staffing_body["agents_per_skill"].values()) > 0

    baseline = client.get("/api/assignment", params={"aged": False})
    assert baseline.status_code == 200
    baseline_body = baseline.json()
    # the whole point of the generous scenario: every ticket is servable
    assert baseline_body["n_tickets_served"] == 10
    baseline_cost = baseline_body["total_cost"]

    age = client.post("/api/hardware/age", json={"months": 60})
    assert age.status_code == 200
    age_body = age.json()
    assert age_body["baseline_cost"] == baseline_cost
    assert age_body["aged_cost"] > age_body["baseline_cost"]

    hardware = client.get("/api/hardware")
    assert hardware.status_code == 200
    to_replace = hardware.json()["to_replace"]
    assert len(to_replace) > 0  # 60 months of ageing must flag something

    replace = client.post("/api/hardware/replace", json={"workstation_ids": to_replace})
    assert replace.status_code == 200
    replace_body = replace.json()
    assert replace_body["aged_cost"] == age_body["aged_cost"]
    assert replace_body["replaced_cost"] < replace_body["aged_cost"]

    comparison = client.get("/api/comparison")
    assert comparison.status_code == 200
    comparison_body = comparison.json()
    assert comparison_body["baseline"] == baseline_cost
    assert comparison_body["aged"] == age_body["aged_cost"]
    assert comparison_body["replaced"] == replace_body["replaced_cost"]
    assert comparison_body["baseline"] < comparison_body["aged"]
    assert comparison_body["replaced"] < comparison_body["aged"]


def test_schedule_escalations_and_incident_are_wired():
    client.post("/api/scenario", json=SCENARIO_BODY)
    client.get("/api/staffing")

    schedule = client.get("/api/schedule")
    assert schedule.status_code == 200
    schedule_body = schedule.json()
    assert len(schedule_body["sequence"]) == len(schedule_body["entries"])
    assert schedule_body["makespan"] >= 0

    escalations = client.get("/api/escalations")
    assert escalations.status_code == 200
    esc_body = escalations.json()
    assert sum(esc_body["counts"].values()) == len(esc_body["rows"])

    incident = client.get("/api/incident")
    assert incident.status_code == 200
    incident_body = incident.json()
    assert incident_body["critical_path"]
    assert all(e[1] in {n["activity"] for n in incident_body["nodes"]} for e in incident_body["edges"])


def test_escalations_game_wires_all_four_game_theory_techniques():
    client.post("/api/scenario", json=SCENARIO_BODY)

    game = client.get("/api/escalations/game")
    assert game.status_code == 200
    body = game.json()

    assert body["acts"] == ["resolve-in-place", "escalate-L2"]
    assert len(body["matrix"]) == 2
    assert all(len(row) == len(body["priorities"]) for row in body["matrix"])

    # minimax theorem: graphical and LP values must agree regardless of
    # whether a pure-strategy saddle point exists.
    assert body["graphical"]["value"] == pytest.approx(body["mixed_strategy_lp"]["value"], abs=1e-3)
    if body["saddle_point"]["exists"]:
        assert body["saddle_point"]["value"] == pytest.approx(body["graphical"]["value"], abs=1e-3)


def test_distribution_get_and_post_override():
    client.post("/api/scenario", json=SCENARIO_BODY)

    baseline = client.get("/api/distribution")
    assert baseline.status_code == 200

    override = client.post(
        "/api/distribution",
        json={"capacities": [10, 10, 10], "cost_matrix": [[1, 2, 3], [4, 5, 6], [7, 8, 9]]},
    )
    assert override.status_code == 200
    assert override.json()["demand"] == [10, 10, 10]


def test_infeasible_staffing_budget_does_not_break_downstream_routes():
    """A budget too small to fund anyone is a legitimate user input on the
    Staffing Planner, and allocate_capacity answers it with status=Infeasible
    and agents_per_skill=None. Every downstream route must still respond
    instead of raising on that None (previously /api/assignment died with
    AttributeError, then with TypeError on the empty cost matrix).
    """
    client.post("/api/scenario", json=SCENARIO_BODY)

    infeasible = client.post("/api/staffing", json={"budget": 1.0})
    assert infeasible.status_code == 200
    assert infeasible.json()["status"] == "Infeasible"

    for route in (
        "/api/assignment", "/api/schedule", "/api/escalations",
        "/api/hardware", "/api/comparison", "/api/distribution",
    ):
        assert client.get(route).status_code == 200, route

    assignment = client.get("/api/assignment").json()
    assert assignment["pairs"] == []
    assert assignment["matrix"] == []
    assert assignment["n_tickets_served"] == 0

    # and the scenario recovers once a workable budget is supplied again
    recovered = client.post("/api/staffing", json={"budget": 9000.0})
    assert recovered.json()["status"] == "Optimal"
    assert client.get("/api/assignment").json()["n_tickets_served"] > 0
