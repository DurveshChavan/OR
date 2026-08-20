"""M1 — capacity allocation (Unit I: LPP / Simplex, solved via PuLP+CBC).

Formulation, per skill group s:
  decision variables : agents_s (integer, >= 0)
  minimize            : sum_s cost_s * agents_s
  subject to          : agents_s >= min_per_skill_s
                        agents_s >= ceil(demand_s / throughput_s)   (coverage)
                        sum_s cost_s * agents_s <= budget
This is a direct textbook LPP; PuLP's default CBC solver (prob.solve(), no
solver arg) runs branch-and-bound simplex under the hood.
"""
import math

import pulp


def allocate_capacity(demand_by_skill, cost_by_skill, budget, min_per_skill, throughput_by_skill):
    """Solve the capacity LPP and return the cheapest feasible staffing plan.

    Reading chosen where the brief was silent: `throughput_by_skill` (tickets
    one agent clears in the planning window) is required to turn `demand_s`
    into the coverage lower bound `ceil(demand_s / throughput_s)`, so it is
    threaded in as an explicit per-skill argument alongside `demand_by_skill`.

    Hand method: this is small enough to solve by hand as a bounded-
    variable LP -- since cost_by_skill are all positive, the cheapest
    feasible plan just sets each agents_s to its binding lower bound,
    max(min_per_skill_s, coverage_s), then checks the summed cost against
    budget; PuLP's branch-and-bound simplex reaches the same answer
    generally, including cases where that shortcut doesn't apply.

    Data source: `demand_by_skill` is derive_priority_mix/category_volumes
    scaled to the planning window; `throughput_by_skill` comes from the
    synthetic agent table's capacity field; `cost_by_skill`, `budget`, and
    `min_per_skill` are CONFIG business-policy assumptions (no UCI-498
    cost or budget field exists) -- see pipeline.py's size_capacity for
    exactly how each is assembled at runtime.
    """
    skills = list(demand_by_skill)
    prob = pulp.LpProblem("capacity_allocation", pulp.LpMinimize)

    agents = {
        s: pulp.LpVariable(f"agents_{s}", lowBound=0, cat="Integer")
        for s in skills
    }

    prob += pulp.lpSum(cost_by_skill[s] * agents[s] for s in skills)

    for s in skills:
        coverage = math.ceil(demand_by_skill[s] / throughput_by_skill[s])
        prob += agents[s] >= min_per_skill[s], f"min_{s}"
        prob += agents[s] >= coverage, f"coverage_{s}"

    prob += pulp.lpSum(cost_by_skill[s] * agents[s] for s in skills) <= budget, "budget"

    prob.solve()

    status = pulp.LpStatus[prob.status]
    if status != "Optimal":
        return {"status": status, "agents_per_skill": None, "total_cost": None}

    agents_per_skill = {s: int(round(agents[s].value())) for s in skills}
    total_cost = sum(cost_by_skill[s] * agents_per_skill[s] for s in skills)

    return {"status": status, "agents_per_skill": agents_per_skill, "total_cost": total_cost}
