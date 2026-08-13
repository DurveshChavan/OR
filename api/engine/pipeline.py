"""pipeline.py — wires M0 through M7 into one run and closes the
feedback loop: M7's per-workstation degradation factor multiplies M3's
cost matrix, ageing hardware away from the Hungarian optimum, and
replacement resets it back.
"""
import os

from api.engine.data_layer import load_incident_log, clean_incidents, make_synthetic
from api.engine.capacity import allocate_capacity
from api.engine.transport import solve_transport_pulp
from api.engine.assignment import build_cost_matrix, assign
from api.engine.sequencing import johnson_two_machine
from api.engine.decision import emv
from api.engine.cpm_pert import build_network, forward_backward, project_completion_probability
from api.engine.replacement import deteriorating_replacement, group_vs_individual, workstation_factors

SKILLS = ["network", "hardware", "software", "database", "access"]


def load_or_synthesize_data(seed=42, n_tickets=50, n_agents=150, n_workstations=20):
    """M0: fit the synthetic generator to the real cleaned log if it has
    been cached locally; otherwise fall back to pure synthetic data. No
    network fetch is attempted here -- that only happens if the caller
    has already run load_incident_log() once to populate the cache."""
    fitted = None
    cache_path = os.path.join("data", "incident_event_log.csv")
    if os.path.exists(cache_path):
        try:
            fitted = clean_incidents(load_incident_log(cache_dir="data"))
        except Exception:
            fitted = None
    return make_synthetic(n_tickets, n_agents, n_workstations, seed=seed, fitted=fitted)


def size_capacity(tickets, agents):
    """M1: LPP sizing one agent headcount per skill group."""
    demand_by_skill = tickets["skill"].value_counts().to_dict()
    throughput_by_skill = agents.groupby("skill")["capacity"].mean().to_dict()
    skills = set(demand_by_skill) | set(throughput_by_skill)
    for s in skills:
        throughput_by_skill.setdefault(s, 1.0)
        demand_by_skill.setdefault(s, 0)

    cost_by_skill = {s: 100.0 for s in skills}
    min_per_skill = {s: 1 for s in skills}
    budget = sum(cost_by_skill.values()) * 20

    return allocate_capacity(demand_by_skill, cost_by_skill, budget, min_per_skill, throughput_by_skill)


def distribute_regions():
    """M2: a fixed synthetic 3-region ticket-routing transportation
    problem (M0 carries no region field to drive this from real data)."""
    supply = [30, 25, 20]
    demand = [28, 27, 20]
    cost = [[4, 6, 8], [6, 4, 7], [9, 7, 5]]
    return solve_transport_pulp(supply, demand, cost)


def assignment_stage(tickets, agents, degradation=None):
    """M3: build the cost matrix (optionally aged) and run Hungarian
    assignment. Returned alongside the matrix so callers can diff stages."""
    matrix = build_cost_matrix(tickets, agents, degradation=degradation)
    result = assign(matrix)
    return {"matrix": matrix, **result}


def _reassigned_tickets(pairs_a, pairs_b):
    """Ticket (row) indices whose serving agent (or served/dropped status)
    differs between two assignment stages."""
    map_a = dict(pairs_a)
    map_b = dict(pairs_b)
    keys = set(map_a) | set(map_b)
    return sorted(k for k in keys if map_a.get(k) != map_b.get(k))


def choose_replacements(workstations, alpha=0.02):
    """M7: run the standard deteriorating-item analysis (a fixed
    purchase/resale/running-cost policy, independent of any one
    workstation) to get the fleet's economic replacement age, then flag
    every workstation at or past that age for replacement. Also runs
    group_vs_individual on a representative sudden-failure profile purely
    to exercise/demo that method."""
    deteriorating = deteriorating_replacement(
        purchase=2000,
        scrap=[1400, 1000, 700, 450, 250, 150],
        running_cost_by_year=[100, 150, 250, 400, 600, 850],
    )
    replace_threshold_months = deteriorating["optimal_year"] * 12

    to_replace = workstations.loc[
        workstations["age_months"] >= replace_threshold_months, "id"
    ].tolist()

    group = group_vs_individual(
        failure_prob_by_period=[0.2, 0.3, 0.5],
        unit_replace_cost=2,
        group_replace_cost=0.5,
        n_items=len(workstations),
    )

    return {
        "to_replace": to_replace,
        "replace_threshold_months": replace_threshold_months,
        "deteriorating": deteriorating,
        "group": group,
    }


def sequence_sample_batch(tickets, sample_size=4):
    """M4: Johnson's rule on a small sample of tickets, treating each
    ticket's own time as machine-1 (triage) and half that as machine-2
    (QA verification)."""
    sample = tickets.head(sample_size)
    jobs = {
        row.id: (row.base_resolution_minutes, row.base_resolution_minutes / 2)
        for row in sample.itertuples()
    }
    return johnson_two_machine(jobs)


def make_escalation_decision():
    """M5: EMV over a small resolve/escalate payoff table."""
    acts = ["resolve-in-place", "escalate-L2", "escalate-vendor"]
    payoff = [[80, 20], [60, 50], [40, 70]]  # cols: quick-fix, complex
    probs = [0.7, 0.3]
    result = emv(payoff, probs)
    return {"acts": acts, **result}


def plan_major_incident(deadline_hours=8):
    """M6: a small CPM/PERT network for a major-incident response."""
    activities = {
        "triage": (1, []),
        "diagnose": (2, ["triage"]),
        "fix": ((2, 3, 5), ["diagnose"]),
        "verify": (1, ["fix"]),
    }
    G = build_network(activities)
    schedule = forward_backward(G)
    probability = project_completion_probability(G, deadline_hours)
    return {"schedule": schedule, "probability": probability}


def run_pipeline(seed=42, verbose=True):
    data = load_or_synthesize_data(seed=seed)
    tickets, agents, workstations = data["tickets"], data["agents"], data["workstations"]

    m1_result = size_capacity(tickets, agents)
    m2_result = distribute_regions()

    baseline = assignment_stage(tickets, agents, degradation=None)

    aged_factors = workstation_factors(workstations)
    aged = assignment_stage(tickets, agents, degradation=aged_factors)
    reassigned_after_ageing = _reassigned_tickets(baseline["pairs"], aged["pairs"])

    replacement = choose_replacements(workstations)
    replaced_workstations = workstations.copy()
    replaced_workstations.loc[
        replaced_workstations["id"].isin(replacement["to_replace"]), "age_months"
    ] = 0
    post_factors = workstation_factors(replaced_workstations)
    post = assignment_stage(tickets, agents, degradation=post_factors)
    reassigned_after_replacement = _reassigned_tickets(aged["pairs"], post["pairs"])

    m4_result = sequence_sample_batch(tickets)
    m5_result = make_escalation_decision()
    m6_result = plan_major_incident()

    stages = {
        "baseline": {"total_cost": baseline["total_cost"], "reassigned": 0},
        "aged": {"total_cost": aged["total_cost"], "reassigned": len(reassigned_after_ageing)},
        "post_replacement": {
            "total_cost": post["total_cost"],
            "reassigned": len(reassigned_after_replacement),
        },
    }

    if verbose:
        _print_report(m1_result, m2_result, stages, replacement, m4_result, m5_result, m6_result)

    return {
        "data": data,
        "m1": m1_result,
        "m2": m2_result,
        "baseline": baseline,
        "aged": aged,
        "post_replacement": post,
        "replacement": replacement,
        "stages": stages,
        "m4": m4_result,
        "m5": m5_result,
        "m6": m6_result,
    }


def _print_report(m1_result, m2_result, stages, replacement, m4_result, m5_result, m6_result):
    print("=== M1 capacity plan ===")
    print(f"status={m1_result['status']} agents_per_skill={m1_result['agents_per_skill']}")

    print("\n=== M2 regional distribution ===")
    print(f"total_cost={m2_result['total_cost']:.1f}")

    print("\n=== M3/M7 feedback loop: baseline -> aged -> post-replacement ===")
    print(f"{'stage':<18}{'total_cost':>12}{'reassigned':>12}")
    for name in ("baseline", "aged", "post_replacement"):
        row = stages[name]
        print(f"{name:<18}{row['total_cost']:>12.1f}{row['reassigned']:>12d}")
    print(
        f"workstations replaced (age >= {replacement['replace_threshold_months']} months): "
        f"{replacement['to_replace']}"
    )

    print("\n=== M4 sequencing sample ===")
    print(f"sequence={m4_result['sequence']} makespan={m4_result['makespan']:.1f} min")

    print("\n=== M5 escalation decision (EMV) ===")
    print(f"chosen={m5_result['acts'][m5_result['best_index']]} EMV={m5_result['best_value']:.2f}")

    print("\n=== M6 major-incident plan ===")
    sched = m6_result["schedule"]
    prob = m6_result["probability"]
    print(
        f"critical_path={sched['critical_path']} duration={sched['project_duration']:.1f}h "
        f"P(finish<=deadline)={prob['probability']:.2f}"
    )


if __name__ == "__main__":
    run_pipeline()
