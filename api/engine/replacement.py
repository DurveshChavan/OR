"""M7 — replacement analysis (Unit IV) + the M3 degradation feedback hook.

deteriorating_replacement: items that wear out gradually (rising running
cost, falling resale) -- replace at the age that minimises average annual
cost. group_vs_individual: items that fail suddenly (light-bulb style) --
compare blanket group replacement on a fixed interval against replacing
only as items fail.

workstation_factors is the exact function pipeline.py calls to build the
`degradation` dict that m3_assignment.build_cost_matrix multiplies its
cost entries by, closing the feedback loop described in CONTEXT.md.
"""


def deteriorating_replacement(purchase, scrap, running_cost_by_year):
    """Average-annual-cost method for a deterioriating item (Unit IV).

    For replacement at the end of year n:
        total_cost(n) = purchase - scrap(n) + cumulative running cost through year n
        average_cost(n) = total_cost(n) / n
    `scrap` is either a single resale value (assumed constant across
    years) or a list of resale values aligned with `running_cost_by_year`.
    The optimal replacement year minimises average_cost.
    """
    n_years = len(running_cost_by_year)
    if isinstance(scrap, (int, float)):
        scrap = [scrap] * n_years

    table = []
    cumulative_running = 0.0
    for year in range(1, n_years + 1):
        cumulative_running += running_cost_by_year[year - 1]
        total_cost = purchase - scrap[year - 1] + cumulative_running
        average_cost = total_cost / year
        table.append({
            "year": year,
            "cumulative_running_cost": cumulative_running,
            "total_cost": total_cost,
            "average_cost": average_cost,
        })

    best = min(table, key=lambda row: row["average_cost"])
    return {"table": table, "optimal_year": best["year"], "optimal_average_cost": best["average_cost"]}


def group_vs_individual(failure_prob_by_period, unit_replace_cost, group_replace_cost, n_items):
    """Sudden-failure replacement (Unit IV): compare a fixed group-
    replacement interval T against replacing only failed items.

    `failure_prob_by_period[i]` = probability a new item fails exactly in
    period i+1. Expected failures per period B_i follow the standard
    renewal recursion:
        B_1 = N*p_1
        B_i = N*p_i + sum_{j=1}^{i-1} B_j * p_{i-j}
    (items replaced on failure in period j are new again and can fail
    again later). Group-replacement average cost for interval T:
        (N*group_replace_cost + unit_replace_cost * sum_{i=1}^{T} B_i) / T
    Individual-only steady-state average cost per period:
        N * unit_replace_cost / mean_life,  mean_life = sum(i * p_i)
    """
    p = list(failure_prob_by_period)
    k = len(p)

    mean_life = sum((i + 1) * p[i] for i in range(k))
    individual_average_cost = n_items * unit_replace_cost / mean_life

    expected_failures = []
    for i in range(k):
        failures = n_items * p[i]
        for j in range(i):
            failures += expected_failures[j] * p[i - j - 1]
        expected_failures.append(failures)

    group_table = []
    cumulative_failures = 0.0
    for interval in range(1, k + 1):
        cumulative_failures += expected_failures[interval - 1]
        total_cost = n_items * group_replace_cost + unit_replace_cost * cumulative_failures
        group_table.append({"interval": interval, "average_cost": total_cost / interval})

    best_group = min(group_table, key=lambda row: row["average_cost"])
    cheaper_policy = "group" if best_group["average_cost"] < individual_average_cost else "individual"

    return {
        "individual_average_cost": individual_average_cost,
        "group_table": group_table,
        "optimal_group_interval": best_group["interval"],
        "optimal_group_average_cost": best_group["average_cost"],
        "cheaper_policy": cheaper_policy,
    }


def degradation_factor(age_months, alpha=0.02):
    """Linear degradation: factor = 1.0 + alpha * age_months. Always
    >= 1.0, monotonic non-decreasing in age, and exactly 1.0 at age 0
    (a freshly replaced workstation)."""
    return 1.0 + alpha * max(age_months, 0)


def workstation_factors(workstations_df, alpha=0.02):
    """The M3 hook: {workstation_id: degradation_factor} built from the
    `age_months` column m0_data produces. pipeline.py passes this straight
    into m3_assignment.build_cost_matrix(..., degradation=...); resetting
    a workstation's age_months to 0 (after a recommended replacement)
    naturally resets its factor to 1.0 on the next call."""
    return {
        row.id: degradation_factor(row.age_months, alpha)
        for row in workstations_df.itertuples()
    }
