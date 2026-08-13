import pulp

from api.engine.capacity import allocate_capacity


def test_allocate_capacity_known_optimum_coverage_and_min_binding():
    # network: coverage = ceil(10/5) = 2 > min 1  -> coverage constraint binds
    # database: coverage = ceil(5/10) = 1 < min 3 -> min_per_skill constraint binds
    demand_by_skill = {"network": 10, "database": 5}
    throughput_by_skill = {"network": 5, "database": 10}
    cost_by_skill = {"network": 100, "database": 50}
    min_per_skill = {"network": 1, "database": 3}
    budget = 10_000

    result = allocate_capacity(
        demand_by_skill, cost_by_skill, budget, min_per_skill, throughput_by_skill
    )

    assert result["status"] == "Optimal"
    assert result["agents_per_skill"] == {"network": 2, "database": 3}
    assert result["total_cost"] == 100 * 2 + 50 * 3  # 350


def test_allocate_capacity_budget_forces_infeasible():
    # coverage alone needs 2 network agents @100 = 200, which already exceeds
    # a budget of 50 -> no feasible integer solution.
    demand_by_skill = {"network": 10}
    throughput_by_skill = {"network": 5}
    cost_by_skill = {"network": 100}
    min_per_skill = {"network": 1}
    budget = 50

    result = allocate_capacity(
        demand_by_skill, cost_by_skill, budget, min_per_skill, throughput_by_skill
    )

    assert result["status"] == "Infeasible"
