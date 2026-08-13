import numpy as np
import pytest

from api.engine.transport import (
    nwcr, least_cost, vam, modi, solve_transport_pulp, transport_cost, _balance,
)

# Hand-traced 3x3 balanced instance (supply == demand == 24).
# S1-D1 is deliberately expensive (20) so NWCR's blind top-left fill is
# forced into it, while VAM's penalty rule routes around it.
SUPPLY = [8, 6, 10]
DEMAND = [10, 4, 10]
COST = [[20, 6, 8], [6, 1, 3], [5, 9, 2]]


def _row_col_sums_match(alloc, supply, demand):
    alloc = np.array(alloc)
    return (
        np.allclose(alloc.sum(axis=1), supply)
        and np.allclose(alloc.sum(axis=0), demand)
    )


def test_nwcr_known_allocation_and_cost():
    alloc = nwcr(SUPPLY, DEMAND)
    assert _row_col_sums_match(alloc, SUPPLY, DEMAND)
    # hand trace: (S1,D1)=8, (S2,D1)=2, (S2,D2)=4, (S3,D3)=10
    assert transport_cost(alloc, COST) == 196.0


def test_vam_known_allocation_and_cost_beats_nwcr():
    alloc = vam(SUPPLY, DEMAND, COST)
    assert _row_col_sums_match(alloc, SUPPLY, DEMAND)
    # hand trace: (S1,D3)=8, (S2,D1)=2, (S2,D2)=4, (S3,D1)=8, (S3,D3)=2
    assert transport_cost(alloc, COST) == 124.0
    assert transport_cost(alloc, COST) <= transport_cost(nwcr(SUPPLY, DEMAND), COST)


def test_least_cost_is_feasible():
    alloc = least_cost(SUPPLY, DEMAND, COST)
    assert _row_col_sums_match(alloc, SUPPLY, DEMAND)


def test_pulp_optimum_matches_hand_optimum():
    result = solve_transport_pulp(SUPPLY, DEMAND, COST)
    assert result["total_cost"] == pytest.approx(124.0)


def test_modi_from_nwcr_reaches_pulp_optimum():
    start = nwcr(SUPPLY, DEMAND)
    assert transport_cost(start, COST) == 196.0  # confirm it starts suboptimal
    _, improved_cost = modi(start, COST)
    pulp_cost = solve_transport_pulp(SUPPLY, DEMAND, COST)["total_cost"]
    assert improved_cost == pytest.approx(pulp_cost)


def test_modi_from_vam_stays_at_pulp_optimum():
    start = vam(SUPPLY, DEMAND, COST)
    _, improved_cost = modi(start, COST)
    pulp_cost = solve_transport_pulp(SUPPLY, DEMAND, COST)["total_cost"]
    assert improved_cost == pytest.approx(pulp_cost)


def test_balance_adds_dummy_when_supply_exceeds_demand():
    supply, demand, cost = _balance([10, 10], [15], [[1, 2]])
    assert supply == [10, 10]
    assert demand == [15, 5]
    assert cost == [[1, 2, 0]]


def test_balance_adds_dummy_when_demand_exceeds_supply():
    supply, demand, cost = _balance([15], [10, 10], [[1, 2]])
    assert supply == [15, 5]
    assert demand == [10, 10]
    assert cost == [[1, 2], [0, 0]]


def test_unbalanced_problem_solved_via_pulp_and_nwcr_feasible():
    # 2 suppliers (10 each) feeding 1 real demand point (15) -> 5 units of
    # slack, balanced with a zero-cost dummy demand column.
    supply = [10, 10]
    demand = [15]
    cost = [[3], [5]]
    result = solve_transport_pulp(supply, demand, cost)
    assert result["allocation"].shape == (2, 2)  # dummy demand column added
    # cheapest supplier (cost 3) fills as much real demand as it can (10),
    # the pricier one (cost 5) covers the remaining 5, rest goes to dummy
    assert result["total_cost"] == pytest.approx(3 * 10 + 5 * 5)

    alloc = nwcr(supply, demand)
    assert _row_col_sums_match(alloc, [10, 10], [15, 5])
