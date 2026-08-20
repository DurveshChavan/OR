import time

import numpy as np
import pandas as pd
import pytest

from api.engine.assignment import build_cost_matrix, pad_to_square, assign, INFEASIBLE


def test_assign_3x3_diagonal_dominant_known_optimum():
    # off-diagonal cost (10) always dominates the diagonal (1,2,3), so the
    # unique optimum is the identity assignment by inspection.
    cost = [
        [1, 10, 10],
        [10, 2, 10],
        [10, 10, 3],
    ]
    result = assign(cost)
    assert sorted(result["pairs"]) == [(0, 0), (1, 1), (2, 2)]
    assert result["total_cost"] == pytest.approx(6.0)


def test_assign_3x4_rectangular_known_optimum():
    # same diagonal-dominant logic with a spare 4th agent column; the
    # optimum still ignores column 3 entirely.
    cost = [
        [1, 10, 10, 10],
        [10, 2, 10, 10],
        [10, 10, 3, 10],
    ]
    result = assign(cost)
    assert sorted(result["pairs"]) == [(0, 0), (1, 1), (2, 2)]
    assert result["total_cost"] == pytest.approx(6.0)
    assert all(c != 3 for _, c in result["pairs"])


def test_pad_to_square_fills_with_default():
    padded = pad_to_square([[1, 2, 3], [4, 5, 6]])
    assert padded.shape == (3, 3)
    assert np.array_equal(padded[:2, :3], np.array([[1, 2, 3], [4, 5, 6]]))
    assert np.all(padded[2, :] == INFEASIBLE)


def test_pad_to_square_custom_fill():
    padded = pad_to_square([[1, 2]], fill=0)
    assert padded.shape == (2, 2)
    assert padded[1, 0] == 0 and padded[1, 1] == 0


def _skill_mismatch_fixture():
    tickets = pd.DataFrame({
        "id": ["T1", "T2"],
        "skill": ["network", "hardware"],
        "base_resolution_minutes": [15, 20],
        "workstation_id": ["WS1", "WS2"],
    })
    agents = pd.DataFrame({"id": ["A1", "A2"], "skill": ["network", "network"]})
    return tickets, agents


def test_build_cost_matrix_marks_skill_mismatch_infeasible():
    tickets, agents = _skill_mismatch_fixture()
    matrix = build_cost_matrix(tickets, agents)
    # T1(network) matches both network agents at its own resolution time
    assert matrix[0, 0] == 15 and matrix[0, 1] == 15
    # T2(hardware) matches no network agent -> infeasible
    assert matrix[1, 0] == INFEASIBLE and matrix[1, 1] == INFEASIBLE


def test_build_cost_matrix_default_degradation_is_identity():
    tickets, agents = _skill_mismatch_fixture()
    no_arg = build_cost_matrix(tickets, agents)
    explicit_one = build_cost_matrix(tickets, agents, degradation={"WS1": 1.0, "WS2": 1.0})
    assert np.array_equal(no_arg, explicit_one)


def test_degradation_factor_changes_optimal_assignment():
    # 3 tickets, only 2 agents of the matching skill -> Hungarian must drop
    # one ticket. Costs are ticket-driven (agent-independent when skill
    # matches), so baseline drops the priciest ticket (T3); doubling T1's
    # workstation cost via degradation makes T1 the one worth dropping
    # instead, which is a genuine change in WHICH tickets get served.
    tickets = pd.DataFrame({
        "id": ["T1", "T2", "T3"],
        "skill": ["network"] * 3,
        "base_resolution_minutes": [10, 11, 12],
        "workstation_id": ["WS1", "WS2", "WS3"],
    })
    agents = pd.DataFrame({"id": ["A1", "A2"], "skill": ["network", "network"]})

    baseline_matrix = build_cost_matrix(tickets, agents)
    baseline = assign(baseline_matrix)
    served_baseline = {r for r, _ in baseline["pairs"]}
    assert served_baseline == {0, 1}  # T1, T2 served; T3 (priciest) dropped
    assert baseline["total_cost"] == pytest.approx(21.0)

    degraded_matrix = build_cost_matrix(tickets, agents, degradation={"WS1": 2.0})
    degraded = assign(degraded_matrix)
    served_degraded = {r for r, _ in degraded["pairs"]}
    assert served_degraded == {1, 2}  # T2, T3 served; T1 (now priciest) dropped
    assert degraded["total_cost"] == pytest.approx(23.0)

    assert served_baseline != served_degraded


def test_degradation_factor_aligns_by_ticket_not_by_workstation_order():
    # Two tickets share WS1 (factor 2.0), one sits on WS2 (factor 3.0).
    # A vectorized implementation that indexes the degradation vector by
    # unique-workstation position instead of mapping each ticket's own
    # workstation_id would silently scramble which factor lands on which
    # row -- this fixture has enough tickets-per-workstation variation to
    # catch that (the single-ticket-per-workstation fixture above cannot).
    tickets = pd.DataFrame({
        "id": ["T1", "T2", "T3"],
        "skill": ["network"] * 3,
        "base_resolution_minutes": [10, 20, 30],
        "workstation_id": ["WS1", "WS1", "WS2"],
    })
    agents = pd.DataFrame({"id": ["A1"], "skill": ["network"]})

    matrix = build_cost_matrix(tickets, agents, degradation={"WS1": 2.0, "WS2": 3.0})
    assert matrix[:, 0] == pytest.approx([20.0, 40.0, 90.0])


def test_build_cost_matrix_200x200_under_half_second():
    rng = np.random.default_rng(42)
    n = 200
    skills = ["network", "hardware", "software", "access"]
    tickets = pd.DataFrame({
        "id": [f"T{i}" for i in range(n)],
        "skill": rng.choice(skills, size=n),
        "base_resolution_minutes": rng.uniform(5, 60, size=n),
        "workstation_id": [f"WS{i % 50}" for i in range(n)],
    })
    agents = pd.DataFrame({
        "id": [f"A{i}" for i in range(n)],
        "skill": rng.choice(skills, size=n),
    })
    degradation = {f"WS{i}": 1.0 + 0.01 * i for i in range(50)}

    start = time.perf_counter()
    matrix = build_cost_matrix(tickets, agents, degradation=degradation)
    elapsed = time.perf_counter() - start

    assert matrix.shape == (n, n)
    assert elapsed < 0.5  # generous bound; vectorized build should be near-instant
