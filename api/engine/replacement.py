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
import math


def deteriorating_replacement(purchase, scrap, running_cost_by_year):
    """Average-annual-cost method for a deterioriating item (Unit IV).

    For replacement at the end of year n:
        total_cost(n) = purchase - scrap(n) + cumulative running cost through year n
        average_cost(n) = total_cost(n) / n
    `scrap` is either a single resale value (assumed constant across
    years) or a list of resale values aligned with `running_cost_by_year`.
    The optimal replacement year minimises average_cost.

    Hand method: build the same year-by-year table by hand -- cumulative
    running cost, total cost = purchase - scrap + cumulative running,
    average cost = total/year -- then read off the year with the smallest
    average cost.

    Data source: `purchase`, `scrap`, `running_cost_by_year` are CONFIG's
    illustrative fleet-economics figures (replacement_purchase_cost,
    replacement_scrap_by_year, replacement_running_cost_by_year) -- no
    real procurement dataset exists, see choose_replacements' docstring.
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

    Hand method: build the B_i renewal table by hand period by period
    (each B_i = new failures N*p_i plus failures among items already
    renewed in earlier periods), accumulate group-replacement average
    cost per candidate interval T, and compare its minimum against the
    individual-replacement steady-state average N*unit_cost/mean_life.

    Data source: `failure_prob_by_period`, `unit_replace_cost`,
    `group_replace_cost` are CONFIG's illustrative fleet-economics figures
    (group_failure_prob_by_period, group_unit_replace_cost,
    group_replace_cost); `n_items` is the current workstation count --
    see choose_replacements' docstring.
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


#: exp(alpha * 36) = 1.5  =>  alpha = ln(1.5) / 36. Calibration target: no
#: real hardware-aging dataset backs this number (UCI-498 has no hardware
#: telemetry), so it is pinned to a single, stated, checkable anchor --
#: "a 3-year-old workstation runs assignment costs about 50% hotter" --
#: rather than picked arbitrarily. sensitivity_analysis() below shows the
#: replacement conclusion barely moves if this anchor is wrong.
DEFAULT_ALPHA = math.log(1.5) / 36.0

#: Laptops are assumed to degrade faster than desktops (battery wear,
#: thermal headroom, more moving/wearable parts) -- same 1.5x anchor
#: reached at 24 months instead of 36. Documented assumption, not data.
ALPHA_BY_TYPE = {
    "desktop": DEFAULT_ALPHA,
    "laptop": math.log(1.5) / 24.0,
}

#: A maintenance event (cleaning, thermal paste, part swap) is assumed to
#: undo half the workstation's effective aging -- unlike a full hardware
#: replacement, which genuinely resets age_months to 0. Documented policy
#: knob, not data (no maintenance-outcome dataset exists either).
DEFAULT_MAINTENANCE_FRACTION = 0.5


def degradation_factor(age_months, alpha=DEFAULT_ALPHA):
    """Exponential degradation: factor = exp(alpha * age_months). Always
    >= 1.0, strictly increasing in age for alpha > 0, and exactly 1.0 at
    age 0 (a freshly replaced workstation). Default alpha is calibrated so
    factor ~= 1.5 at age_months=36 (see DEFAULT_ALPHA).

    Hand method: the closed-form formula itself, evaluated at the given
    age.

    Data source: `age_months` is caller-supplied (workstation_factors
    reads it from the workstation table); `alpha` is DEFAULT_ALPHA or
    ALPHA_BY_TYPE, both documented calibration constants (no real
    hardware-aging dataset exists -- see the module-level comment above
    DEFAULT_ALPHA).
    """
    return math.exp(alpha * max(age_months, 0))


def workstation_factors(workstations_df, alpha=DEFAULT_ALPHA, alphas_by_type=None):
    """The M3 hook: {workstation_id: degradation_factor} built from the
    `age_months` column m0_data produces. pipeline.py passes this straight
    into m3_assignment.build_cost_matrix(..., degradation=...); resetting
    a workstation's age_months to 0 (after a recommended replacement)
    naturally resets its factor to 1.0 on the next call.

    If `alphas_by_type` is given and workstations_df has a `type` column,
    each row uses its own type's alpha (falling back to `alpha` for an
    unrecognised type); otherwise every row uses the single `alpha`.

    Hand method: apply degradation_factor's formula to each workstation's
    own age_months row by row.

    Data source: `workstations_df` is the synthetic workstation table
    (age_months is m0_data's own synthetic column, since no real
    hardware-telemetry dataset exists); `alpha`/`alphas_by_type` default
    to this module's DEFAULT_ALPHA/ALPHA_BY_TYPE calibration constants.
    """
    has_type = alphas_by_type is not None and "type" in workstations_df.columns
    return {
        row.id: degradation_factor(
            row.age_months,
            alphas_by_type.get(row.type, alpha) if has_type else alpha,
        )
        for row in workstations_df.itertuples()
    }


def apply_maintenance(age_months, fraction=DEFAULT_MAINTENANCE_FRACTION):
    """A maintenance event reduces age by `fraction` rather than resetting
    it to 0 (that's what a full replacement does). age_months=24,
    fraction=0.5 -> 12: still older than new, cheaper than a full swap.

    Kept intentionally though the product only exposes full replacement
    (POST /api/hardware/replace resets age to 0): this is the partial-
    maintenance alternative the M7 write-up discusses, retained as the
    tested (tests/test_m7.py) reference formula rather than a product
    control, since the API has no maintenance-vs-replace decision surface
    to attach it to.

    Hand method: the formula itself -- multiply age by (1 - fraction).

    Data source: caller-supplied; syllabus demonstration, exercised in
    tests only (see the note above).
    """
    return max(age_months, 0) * (1.0 - fraction)


def replacement_age_for_threshold(alpha, threshold=1.5):
    """Age (months) at which the exponential degradation curve first
    reaches `threshold`, i.e. exp(alpha*age)=threshold => age=ln(threshold)/alpha.
    Closed-form inverse of degradation_factor; used by sensitivity_analysis.

    Hand method: invert degradation_factor's formula algebraically, as
    shown.

    Data source: `alpha` is one value from CONFIG's sensitivity_alphas
    sweep (or DEFAULT_ALPHA); `threshold` is CONFIG's degradation_threshold.
    """
    return math.log(threshold) / alpha


def sensitivity_analysis(alphas, workstations_df, threshold=1.5):
    """The honest answer to "you have no real hardware-aging data":
    sweep alpha across a plausible range and show the *conclusion*
    (which workstations get flagged for replacement) is stable, not just
    that the implied replacement age is a smooth function of alpha.

    For each alpha: the implied replacement age (months) where
    degradation_factor crosses `threshold`, and the resulting to-replace
    set (workstations already at or past that age). Reports how much the
    flagged set actually changes across the sweep, in both directions:
    largest set minus smallest, and vice versa.

    Hand method: for each alpha in the sweep, invert degradation_factor
    by hand (replacement_age_for_threshold) to get that alpha's implied
    replacement age, then mark every workstation at or past it; compare
    the marked sets across alphas for stable_core / disputed / flagged_any.

    Data source: `alphas` is CONFIG's sensitivity_alphas sweep;
    `workstations_df` is the synthetic workstation table's age_months
    column; `threshold` is CONFIG's degradation_threshold.
    """
    results = []
    flagged_sets = []
    for a in alphas:
        age = replacement_age_for_threshold(a, threshold)
        flagged = set(
            workstations_df.loc[workstations_df["age_months"] >= age, "id"]
        )
        flagged_sets.append(flagged)
        results.append({
            "alpha": a,
            "replace_age_months": age,
            "to_replace": sorted(flagged),
            "n_flagged": len(flagged),
        })

    union_all = set.union(*flagged_sets) if flagged_sets else set()
    intersection_all = set.intersection(*flagged_sets) if flagged_sets else set()

    return {
        "results": results,
        "threshold": threshold,
        "flagged_any": sorted(union_all),
        "stable_core": sorted(intersection_all),
        "disputed": sorted(union_all - intersection_all),
        "source": (
            "no real hardware-degradation dataset exists (UCI-498 carries no "
            "hardware telemetry); alpha is a documented assumption anchored at "
            "factor~=1.5 at 36 months -- this sweeps alpha over a plausible "
            "range and reports which workstations are flagged under every "
            "alpha ('stable_core') versus only some ('disputed')"
        ),
    }
