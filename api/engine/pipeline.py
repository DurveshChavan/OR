"""pipeline.py — wires M0 through M7 into one causal chain, not seven
independent demos. The story, module by module:

  M1 (capacity) funds a headcount per skill -> M3 draws its agent pool
  ONLY from those funded agents (top-n by capacity, this project's
  per-agent "speed" proxy, per skill). M3's initial assignment feeds
  M4, which sequences the actual assigned batch with Johnson's rule
  (triage/fix split from real per-incident duration proportions) and
  records each ticket's scheduled completion time. M4's completion time
  vs a CONFIG SLA deadline gives each ticket's time-to-breach, fed into
  M5's escalation_decision -- and M6's incident-completion probability
  can force a ticket through escalation even when its own EMV wouldn't.
  M5's escalate-L2 tickets go back through M3, restricted to "senior"
  agents (a CONFIG capacity threshold); escalate-vendor tickets leave
  the internal queue and carry a vendor cost; the standard pool is
  re-sequenced now that some tickets have left it. The resulting
  funded-and-escalation-adjusted (standard + senior-agent-L2) ticket/
  agent split is what M7's three-stage (baseline/aged/replaced) table
  runs on, so hardware ageing is measured against the real chain, not a
  toy full-roster assignment nobody downstream would actually see.

Every number that IS in UCI-498 comes from api.engine.data_layer's
derive_* functions, run once here against the cached real log (or a
documented CONFIG fallback if no cache exists -- no network fetch is
ever attempted from inside the pipeline). Every number that ISN'T in the
dataset (business policy: costs, budgets, penalties, SLA deadlines,
undatable CPM stages, hardware-aging alpha) lives in the CONFIG dict
below, each entry commented with why it can't be derived.
"""
import math
import os

import pandas as pd

from api.engine.data_layer import (
    load_incident_log, clean_incidents, make_synthetic,
    derive_priority_mix, derive_breach_rates,
    derive_region_volumes, derive_category_volumes, derive_incident_durations,
    SKILL_GROUPS,
)
from api.engine.capacity import allocate_capacity
from api.engine.transport import solve_transport_pulp
from api.engine.assignment import build_cost_matrix, assign
from api.engine.sequencing import johnson_two_machine
from api.engine.decision import escalation_decision
from api.engine.cpm_pert import build_network, forward_backward, project_completion_probability
from api.engine.replacement import (
    deteriorating_replacement, group_vs_individual, workstation_factors,
    sensitivity_analysis, ALPHA_BY_TYPE,
)

CACHE_PATH = os.path.join("data", "incident_event_log.csv")

CONFIG = {
    # ---- M1 capacity ---------------------------------------------------
    # UCI-498 carries no payroll data; flat monthly per-agent cost in
    # currency-agnostic units. Override once real HR cost data exists.
    "capacity_cost_per_agent": 120.0,
    # headroom policy: budget = this many agents' worth of cost per skill
    # group. Not derivable from the dataset.
    "capacity_budget_agents_per_skill": 15,
    "capacity_min_agents_per_skill": 1,
    # absolute ticket volume the capacity plan is sized against; the
    # *split* across skills comes from derive_category_volumes (real
    # data) -- this constant only sets the *scale*, since UCI-498 doesn't
    # specify a planning-window size.
    "capacity_planning_window_tickets": 60,

    # ---- M2 transport ---------------------------------------------------
    "region_count": 3,
    # absolute ticket volume the regional-routing LP is sized against
    # (same role as capacity_planning_window_tickets, for M2's supply
    # side); derive_region_volumes supplies the real per-region *split*.
    "transport_planning_window_tickets": 90,
    # support-centre intake capacities: a business policy input (how many
    # tickets each of 3 support centres can take), not a UCI-498
    # quantity -- documented placeholder, editable via an API layer later.
    "support_centre_capacity": [34, 33, 31],
    # relative routing/handling overhead per (region, centre) pair -- a
    # user input describing logistics friction, not something the
    # dataset models.
    "routing_overhead_cost": [
        [5, 7, 9],
        [7, 5, 8],
        [9, 8, 5],
    ],

    # ---- M3 funded-agent pool -------------------------------------------
    # "senior" is a CONFIG threshold on the existing capacity field, not a
    # new random attribute: capacity in [1,5], senior = the top two
    # bands. Documented policy, not data (UCI-498 has no seniority field).
    "senior_capacity_threshold": 4,

    # ---- M4/M5 SLA deadlines ---------------------------------------------
    # typical ITIL priority-based resolution-SLA windows, hours.
    # UCI-498 records only the breach OUTCOME (made_sla), never the
    # deadline itself, so this is a documented industry-convention
    # placeholder, not a derived figure.
    "sla_deadline_hours_by_priority": {1: 4.0, 2: 8.0, 3: 24.0, 4: 72.0},

    # ---- M5 escalation ---------------------------------------------------
    # SLA-breach penalty per priority: UCI-498 has no monetary-penalty
    # field, so this is a documented proxy scaled by priority severity.
    "sla_penalty_by_priority": {1: 500.0, 2: 250.0, 3: 100.0, 4: 40.0},
    # labour cost per escalation act -- also not in the dataset.
    "escalation_labour_cost": {
        "resolve-in-place": 15.0,
        "escalate-L2": 45.0,
        "escalate-vendor": 110.0,
    },
    # each act's own breach-probability multiplier: escalation is modelled
    # as buying specialist attention that lowers breach likelihood, not
    # just costing more labour -- without this an EMV model never picks
    # escalation (see decision.escalation_decision's docstring).
    # Documented policy assumption, no UCI-498 equivalent.
    "escalation_breach_reduction": {"escalate-L2": 0.5, "escalate-vendor": 0.25},
    "reassignment_breach_bump": 0.15,

    # ---- M6 CPM/PERT ---------------------------------------------------
    # triage/fix come from derive_incident_durations (real priority-1
    # incident data); the richer network's other stages have no UCI-498
    # timestamp to derive from, so they're fixed (a,m,b) hour estimates --
    # documented, conservative, override via CONFIG once real stage
    # timing data exists.
    "cpm_stage_defaults": {
        "diagnose": (1.0, 2.0, 4.0),
        "notify_stakeholders": (0.1, 0.25, 0.5),
        "verify": (0.5, 1.0, 2.0),
        "rca_draft": (1.0, 2.0, 4.0),
        "close": (0.1, 0.25, 0.5),
    },
    "cpm_deadline_hours": 240.0,
    # M6 -> M5 gate: below this confidence of finishing the major
    # incident on time, its own (priority-1) tickets are forced through
    # escalation regardless of their individual EMV call. A business
    # risk-tolerance choice (round, common risk-management convention),
    # not derived from any one observed probability.
    "major_incident_probability_threshold": 0.95,

    # ---- M7 replacement ---------------------------------------------------
    # fleet economics: illustrative purchase/resale/running-cost figures
    # (no real procurement-cost dataset exists for this project).
    "replacement_purchase_cost": 2000.0,
    "replacement_scrap_by_year": [1400.0, 1000.0, 700.0, 450.0, 250.0, 150.0],
    "replacement_running_cost_by_year": [100.0, 150.0, 250.0, 400.0, 600.0, 850.0],
    "group_failure_prob_by_period": [0.2, 0.3, 0.5],
    "group_unit_replace_cost": 2.0,
    "group_replace_cost": 0.5,
    # degradation_factor threshold that defines "worth replacing"; swept
    # by sensitivity_analysis rather than trusted at one value.
    "degradation_threshold": 1.5,
    "sensitivity_alphas": [
        math.log(1.5) / 24, math.log(1.5) / 30, math.log(1.5) / 36,
        math.log(1.5) / 48, math.log(1.5) / 60,
    ],
}


def _load_cleaned_log():
    """Load+clean the cached real UCI-498 log if it exists; None
    otherwise. No network fetch is attempted here -- that only happens if
    the caller has already run load_incident_log() once to populate the
    cache. Per project rule, missing data is never a hard failure."""
    if not os.path.exists(CACHE_PATH):
        return None
    try:
        return clean_incidents(load_incident_log(cache_dir="data"))
    except Exception:
        return None


def _scale_to_total(volumes, total):
    """Rescale a {key: count} dict so its values sum to ~`total`, keeping
    relative proportions; every key keeps at least 1. Turns a real
    dataset's *shape* into a concrete planning-window *scale*."""
    s = sum(volumes.values())
    return {k: max(1, round(v / s * total)) for k, v in volumes.items()}


def derive_all(cleaned):
    """Run every M0 derive_* function once against the cached real log,
    or fall back to CONFIG-documented placeholder distributions when no
    cache exists. Returns one dict of {name: derive_*() result}, each
    result carrying its own "source" string."""
    if cleaned is not None and len(cleaned) > 0:
        return {
            "priority_mix": derive_priority_mix(cleaned),
            "breach": derive_breach_rates(cleaned),
            "regions": derive_region_volumes(cleaned, k=CONFIG["region_count"]),
            "categories": derive_category_volumes(cleaned, top=len(SKILL_GROUPS)),
            "durations": derive_incident_durations(cleaned),
        }

    fallback_source = (
        "no cached UCI-498 log (data/incident_event_log.csv); "
        "CONFIG-documented fallback distribution, not real data"
    )
    return {
        "priority_mix": {"mix": {1: 0.05, 2: 0.10, 3: 0.65, 4: 0.20}, "source": fallback_source},
        "breach": {"rates": {1: 0.10, 2: 0.08, 3: 0.05, 4: 0.03}, "source": fallback_source},
        "regions": {
            "volumes": {"Region A": 3, "Region B": 2, "Region C": 1},
            "source": fallback_source,
        },
        "categories": {
            "volumes": {s: len(SKILL_GROUPS) - i for i, s in enumerate(SKILL_GROUPS)},
            "source": fallback_source,
        },
        "durations": {
            "triage": (0.5, 2.0, 6.0), "fix": (1.0, 4.0, 12.0),
            "n_triage": 0, "n_fix": 0, "source": fallback_source,
        },
    }


def load_or_synthesize_data(seed=42, n_tickets=50, n_agents=150, n_workstations=20, cleaned=None):
    """M0: fit the synthetic generator to the real cleaned log if one is
    given (or found cached); otherwise fall back to pure synthetic data."""
    if cleaned is None:
        cleaned = _load_cleaned_log()
    return make_synthetic(n_tickets, n_agents, n_workstations, seed=seed, fitted=cleaned)


def size_capacity(agents, categories, cost_by_skill=None, budget=None, min_per_skill=None):
    """M1: LPP sizing one agent headcount per skill group -- this
    funded headcount is what M1->M3 wiring (select_funded_agents) later
    restricts the assignable agent pool to.

    demand_by_skill: UCI-498's category field is anonymized ("Category
    55" etc.) with no semantic mapping to this project's skill names, so
    the top-N categories by real ticket volume are mapped by RANK onto
    SKILL_GROUPS (documented assumption) and scaled to CONFIG's
    planning-window size. throughput_by_skill comes from the actual agent
    roster (real, this run's data). cost_by_skill/budget/min_per_skill
    default to CONFIG's policy inputs but can be overridden by a caller
    (e.g. api/main.py's POST /api/staffing, passing a user's own values
    through unchanged -- no OR logic in that handler, just parameters).
    """
    ranked = list(categories["volumes"].items())[: len(SKILL_GROUPS)]
    proxy = {SKILL_GROUPS[i]: count for i, (_cat, count) in enumerate(ranked)}
    demand_by_skill = _scale_to_total(proxy, CONFIG["capacity_planning_window_tickets"])

    throughput_by_skill = agents.groupby("skill")["capacity"].mean().to_dict()
    for s in SKILL_GROUPS:
        throughput_by_skill.setdefault(s, 1.0)

    if cost_by_skill is None:
        cost_by_skill = {s: CONFIG["capacity_cost_per_agent"] for s in SKILL_GROUPS}
    if min_per_skill is None:
        min_per_skill = {s: CONFIG["capacity_min_agents_per_skill"] for s in SKILL_GROUPS}
    if budget is None:
        budget = sum(cost_by_skill.values()) * CONFIG["capacity_budget_agents_per_skill"]

    result = allocate_capacity(demand_by_skill, cost_by_skill, budget, min_per_skill, throughput_by_skill)
    result["demand_by_skill"] = demand_by_skill
    result["cost_by_skill"] = cost_by_skill
    result["budget"] = budget
    result["min_per_skill"] = min_per_skill
    result["source"] = (
        f"demand: top-{len(SKILL_GROUPS)} categories by volume ({categories['source']}) "
        f"mapped by rank to skill groups, scaled to {CONFIG['capacity_planning_window_tickets']} "
        f"tickets; cost/budget/min: CONFIG (business policy, not data) unless overridden by the caller"
    )
    return result


def select_funded_agents(agents, agents_per_skill):
    """M1 -> M3: keep only the top agents_per_skill[skill] agents per
    skill group, ranked by `capacity` (this project's "base speed" proxy)
    descending, ties broken by id for determinism. If a skill group has
    fewer real agents than were funded, every agent of that skill is kept
    (you can't staff more than exist)."""
    parts = []
    for skill, n in agents_per_skill.items():
        if not n:
            continue
        pool = agents[agents["skill"] == skill].sort_values(
            ["capacity", "id"], ascending=[False, True]
        )
        parts.append(pool.head(int(n)))
    if not parts:
        return agents.iloc[0:0]
    return pd.concat(parts, ignore_index=True)


def _assert_no_unfunded_agent(pairs, agents_used, agents, agents_per_skill):
    """Pipeline assertion for the M1->M3 contract: every agent actually
    used in `pairs` must be inside the funded set -- recomputed here
    independently from the full roster + agents_per_skill (not just
    trusting that `agents_used` was already filtered correctly), so this
    catches a future wiring bug, not just restates the filter."""
    funded_ids = set(select_funded_agents(agents, agents_per_skill)["id"])
    used_ids = {agents_used.iloc[c]["id"] for _r, c in pairs}
    unfunded = used_ids - funded_ids
    assert not unfunded, f"assignment used unfunded agent(s): {sorted(unfunded)}"


def distribute_regions(regions, capacities=None, cost=None):
    """M2: regional ticket routing. Supply = real per-region ticket
    volumes (derive_region_volumes), scaled to CONFIG's planning-window
    total. Demand (`capacities`) and the routing-overhead `cost` matrix
    default to CONFIG's business-policy inputs but can be overridden by a
    caller (api/main.py's POST /api/distribution) -- neither is a dataset
    quantity either way.
    """
    scaled = _scale_to_total(regions["volumes"], CONFIG["transport_planning_window_tickets"])
    supply = list(scaled.values())
    demand = capacities if capacities is not None else CONFIG["support_centre_capacity"]
    cost_matrix = cost if cost is not None else CONFIG["routing_overhead_cost"]

    result = solve_transport_pulp(supply, demand, cost_matrix)
    result["supply"] = supply
    result["demand"] = demand
    result["cost"] = cost_matrix
    result["source"] = (
        f"supply: {regions['source']}, scaled to {CONFIG['transport_planning_window_tickets']} "
        f"tickets; demand & routing cost: CONFIG (business policy, not data) unless overridden"
    )
    return result


def assignment_stage(tickets, agents, degradation=None):
    """M3: build the cost matrix (optionally aged) and run Hungarian
    assignment over exactly the (tickets, agents) handed in -- callers
    (pipeline.py) decide which subset that is; this function never
    widens the pool itself."""
    if len(tickets) == 0 or len(agents) == 0:
        return {"matrix": None, "pairs": [], "total_cost": 0.0}
    matrix = build_cost_matrix(tickets, agents, degradation=degradation)
    result = assign(matrix)
    return {"matrix": matrix, **result}


def _reassigned_tickets(pairs_a, pairs_b):
    """Ticket (row) indices whose serving agent (or served/dropped status)
    differs between two assignment stages over the SAME ticket/agent
    frames (row/col indices only make sense when both sides share them).

    Kept intentionally though no runtime caller currently uses it: the
    client (TicketAssignment.jsx) recomputes this same diff from the
    baseline/aged pairs the API already returns, so wiring this in would
    duplicate rather than replace that logic. Retained as the tested
    reference implementation (tests/test_pipeline.py) of what "moved
    tickets" means.
    """
    map_a = dict(pairs_a)
    map_b = dict(pairs_b)
    keys = set(map_a) | set(map_b)
    return sorted(k for k in keys if map_a.get(k) != map_b.get(k))


def _triage_share(durations):
    """M0 -> M4: the empirical triage-share of resolution time, from
    derive_incident_durations' median (p50) triage/fix hours. Only
    priority-1 incidents have a large enough real sample to split stages
    from (see derive_incident_durations), so this ratio is applied as a
    general proportion to every ticket's own base_resolution_minutes, not
    just priority-1 ones -- a documented assumption, not a per-priority
    derivation."""
    triage_p50, fix_p50 = durations["triage"][1], durations["fix"][1]
    total = triage_p50 + fix_p50
    return 0.5 if total <= 0 else triage_p50 / total


def sequence_tickets(tickets_df, triage_share):
    """M3 -> M4: Johnson's rule over the WHOLE given ticket batch (the
    actual assignment, not a fixed-size sample). Triage and fix are
    treated as two shared stations every ticket in the batch flows
    through in the same order -- one flow shop -- which is what makes
    running Johnson's rule over an arbitrary batch coherent. stage-1
    (triage) = base_resolution_minutes * triage_share, stage-2 (fix) =
    the remainder (see _triage_share). Returns the usual johnson_two_machine
    result plus completion_minutes: {ticket_id: scheduled finish time
    (machine-2 end) -- what M4->M5 wiring compares against each ticket's
    SLA deadline}.
    """
    if len(tickets_df) == 0:
        return {"sequence": [], "makespan": 0.0, "schedule": [], "completion_minutes": {}}
    jobs = {
        row.id: (
            row.base_resolution_minutes * triage_share,
            row.base_resolution_minutes * (1.0 - triage_share),
        )
        for row in tickets_df.itertuples()
    }
    result = johnson_two_machine(jobs)
    result["completion_minutes"] = {row["job"]: row["m2_end"] for row in result["schedule"]}
    return result


def _incident_forces_escalation(probability_result, threshold):
    """M6 -> M5 gate: below CONFIG's risk-tolerance threshold, the major
    incident is no longer trusted to finish on time -- its own tickets no
    longer get to rely solely on their individual EMV call (see
    route_escalations' `force_priority1`)."""
    return probability_result["probability"] < threshold


def route_escalations(tickets_df, breach, completion_minutes, force_priority1=False):
    """M4 -> M5 (and the M6 -> M5 gate, applied via `force_priority1`):
    for each ticket, time_to_breach_hours = its CONFIG SLA deadline (by
    priority) minus its scheduled completion time (M4's sequence), fed
    into escalation_decision. If `force_priority1`, a priority-1 ticket
    that would otherwise stay resolve-in-place is bumped to escalate-L2
    -- the incident-level schedule risk (M6) overrides that one ticket's
    own EMV call. Returns one row per ticket."""
    rows = []
    for row in tickets_df.itertuples():
        completion = completion_minutes.get(row.id)
        deadline_h = CONFIG["sla_deadline_hours_by_priority"][row.priority]
        time_to_breach = (deadline_h - completion / 60.0) if completion is not None else None

        decision = escalation_decision(
            pd.Series({"priority": row.priority, "reassignment_count": row.reassignment_count}),
            breach["rates"], CONFIG["sla_penalty_by_priority"], CONFIG["escalation_labour_cost"],
            breach_reduction=CONFIG["escalation_breach_reduction"],
            reassignment_bump=CONFIG["reassignment_breach_bump"],
            time_to_breach_hours=time_to_breach,
        )
        act = decision["acts"][decision["best_index"]]
        forced = False
        if force_priority1 and row.priority == 1 and act == "resolve-in-place":
            act = "escalate-L2"
            forced = True

        rows.append({
            "ticket_id": row.id, "priority": row.priority, "act": act,
            "forced_by_incident_risk": forced,
            "time_to_breach_hours": time_to_breach, "decision": decision,
        })
    return rows


def split_by_escalation(tickets_df, escalation_rows):
    """M5 -> M3: partition tickets by their escalation act.
    escalate-vendor tickets leave the internal queue entirely (a vendor
    cost is charged instead of an internal assignment); escalate-L2
    tickets move to the senior-agent pool; everyone else (resolve-in-
    place) stays in the standard pool."""
    act_by_id = {r["ticket_id"]: r["act"] for r in escalation_rows}
    standard_ids = {tid for tid, a in act_by_id.items() if a == "resolve-in-place"}
    l2_ids = {tid for tid, a in act_by_id.items() if a == "escalate-L2"}
    vendor_ids = {tid for tid, a in act_by_id.items() if a == "escalate-vendor"}

    return {
        "standard_tickets": tickets_df[tickets_df["id"].isin(standard_ids)].reset_index(drop=True),
        "l2_tickets": tickets_df[tickets_df["id"].isin(l2_ids)].reset_index(drop=True),
        "vendor_ids": sorted(vendor_ids),
        "counts": {
            "resolve-in-place": len(standard_ids),
            "escalate-L2": len(l2_ids),
            "escalate-vendor": len(vendor_ids),
        },
    }


def choose_replacements(workstations):
    """M7: deteriorating_replacement and group_vs_individual run on
    CONFIG's illustrative fleet-economics figures (no real procurement
    dataset exists) and are reported for their own sake. The actual
    to_replace flag comes from sensitivity_analysis' flagged_any: every
    workstation flagged under AT LEAST ONE alpha in a plausible sweep --
    a cautious action policy for hardware nobody has aging data for.
    sensitivity's stable_core (flagged under EVERY alpha) is reported
    alongside as the high-confidence subset of that same list; disputed
    is the rest, worth a closer look before acting on it at scale.
    """
    deteriorating = deteriorating_replacement(
        purchase=CONFIG["replacement_purchase_cost"],
        scrap=CONFIG["replacement_scrap_by_year"],
        running_cost_by_year=CONFIG["replacement_running_cost_by_year"],
    )
    group = group_vs_individual(
        failure_prob_by_period=CONFIG["group_failure_prob_by_period"],
        unit_replace_cost=CONFIG["group_unit_replace_cost"],
        group_replace_cost=CONFIG["group_replace_cost"],
        n_items=len(workstations),
    )
    sensitivity = sensitivity_analysis(
        CONFIG["sensitivity_alphas"], workstations, threshold=CONFIG["degradation_threshold"]
    )

    return {
        "to_replace": sensitivity["flagged_any"],
        "deteriorating": deteriorating,
        "group": group,
        "sensitivity": sensitivity,
        "source": (
            "deteriorating/group fleet economics: CONFIG (illustrative, no real "
            f"procurement dataset); to_replace (flagged under >=1 plausible alpha, "
            f"stable_core={sensitivity['stable_core']} is the subset flagged under "
            f"every alpha): {sensitivity['source']}"
        ),
    }


def plan_major_incident(durations, deadline_hours=None):
    """M6: major-incident response network with two genuine merge points
    (verify waits on both fix and notify-stakeholders; close waits on
    both verify and rca-draft) -- the critical path is a real selection
    among paths, not a single chain. triage/fix durations come from
    derive_incident_durations (real priority-1 incident data); the other
    stages have no UCI-498 timestamp to derive from and use CONFIG's
    fixed (a,m,b) estimates. `deadline_hours` defaults to CONFIG but can
    be overridden by a caller (api/main.py's GET /api/incident?deadline_hours=,
    for the UI's deadline input) without touching CONFIG itself. Its
    completion probability (at the CONFIG default) feeds the M6->M5 gate
    (see _incident_forces_escalation) -- only the CACHED default-deadline
    result is used there, never a caller-supplied override.
    """
    if deadline_hours is None:
        deadline_hours = CONFIG["cpm_deadline_hours"]
    stages = CONFIG["cpm_stage_defaults"]
    activities = {
        "triage": (durations["triage"], []),
        "diagnose": (stages["diagnose"], ["triage"]),
        "notify_stakeholders": (stages["notify_stakeholders"], ["triage"]),
        "fix": (durations["fix"], ["diagnose"]),
        "verify": (stages["verify"], ["fix", "notify_stakeholders"]),
        "rca_draft": (stages["rca_draft"], ["fix"]),
        "close": (stages["close"], ["verify", "rca_draft"]),
    }
    G = build_network(activities)
    schedule = forward_backward(G)
    probability = project_completion_probability(G, deadline_hours)
    edges = [(pred, act) for act, (_dur, preds) in activities.items() for pred in preds]
    return {
        "schedule": schedule,
        "probability": probability,
        "edges": edges,
        "source": (
            f"triage/fix: {durations['source']}; diagnose/notify_stakeholders/verify/"
            f"rca_draft/close: CONFIG (no UCI-498 proxy for these stages)"
        ),
    }


def _combined_stage(standard_tickets, funded_agents, l2_tickets, senior_agents, degradation):
    """M7 -> M3: run the aged/replaced degradation factor over BOTH
    halves of the funded-and-escalation-adjusted assignment (the standard
    pool against funded agents, the escalate-L2 pool against senior
    agents) and sum their cost -- this is "the whole chain", not just the
    standard pool, so hardware ageing is measured against what the rest
    of the pipeline actually produced."""
    standard = assignment_stage(standard_tickets, funded_agents, degradation=degradation)
    l2 = assignment_stage(l2_tickets, senior_agents, degradation=degradation)
    return {
        "standard": standard, "l2": l2,
        "total_cost": standard["total_cost"] + l2["total_cost"],
    }


def run_pipeline(seed=42, verbose=True):
    cleaned = _load_cleaned_log()
    derived = derive_all(cleaned)
    data = load_or_synthesize_data(seed=seed, cleaned=cleaned)
    tickets, agents, workstations = data["tickets"], data["agents"], data["workstations"]

    # ---- M1 -> M3: fund headcount, restrict the assignable agent pool --
    m1_result = size_capacity(agents, derived["categories"])
    funded_agents = select_funded_agents(agents, m1_result["agents_per_skill"]).reset_index(drop=True)
    senior_agents = funded_agents[
        funded_agents["capacity"] >= CONFIG["senior_capacity_threshold"]
    ].reset_index(drop=True)

    initial = assignment_stage(tickets, funded_agents, degradation=None)
    _assert_no_unfunded_agent(initial["pairs"], funded_agents, agents, m1_result["agents_per_skill"])
    assigned_ids = {tickets.iloc[r]["id"] for r, _c in initial["pairs"]}
    assigned_tickets = tickets[tickets["id"].isin(assigned_ids)].reset_index(drop=True)

    # ---- M3 -> M4: sequence the actual assignment -----------------------
    triage_share = _triage_share(derived["durations"])
    initial_sequence = sequence_tickets(assigned_tickets, triage_share)

    # ---- M6 (independent of M3/M4) + its M5 gate -------------------------
    m6_result = plan_major_incident(derived["durations"])
    force = _incident_forces_escalation(
        m6_result["probability"], CONFIG["major_incident_probability_threshold"]
    )

    # ---- M4 -> M5 (+ M6 -> M5 gate) --------------------------------------
    escalation_rows = route_escalations(
        assigned_tickets, derived["breach"], initial_sequence["completion_minutes"],
        force_priority1=force,
    )
    split = split_by_escalation(assigned_tickets, escalation_rows)
    vendor_cost = split["counts"]["escalate-vendor"] * CONFIG["escalation_labour_cost"]["escalate-vendor"]

    # ---- M5 -> M3 (senior re-assignment) + M3 -> M4 (re-sequence) -------
    final_sequence = sequence_tickets(split["standard_tickets"], triage_share)
    escalated_ids = {r["ticket_id"] for r in escalation_rows if r["act"] != "resolve-in-place"}
    resequenced_ids = {
        tid for tid, t in final_sequence["completion_minutes"].items()
        if t != initial_sequence["completion_minutes"].get(tid)
    }
    changed_tickets = sorted(escalated_ids | resequenced_ids)

    # ---- M2 (independent of the ticket-level chain) ---------------------
    m2_result = distribute_regions(derived["regions"])

    # ---- M7 -> M3: three-stage table on the funded-and-escalation-
    # adjusted assignment --------------------------------------------------
    aged_factors = workstation_factors(workstations, alphas_by_type=ALPHA_BY_TYPE)
    replacement = choose_replacements(workstations)
    replaced_workstations = workstations.copy()
    flagged = replaced_workstations["id"].isin(replacement["to_replace"])
    replaced_workstations.loc[flagged, "age_months"] = 0
    post_factors = workstation_factors(replaced_workstations, alphas_by_type=ALPHA_BY_TYPE)

    baseline_stage = _combined_stage(
        split["standard_tickets"], funded_agents, split["l2_tickets"], senior_agents, None
    )
    aged_stage = _combined_stage(
        split["standard_tickets"], funded_agents, split["l2_tickets"], senior_agents, aged_factors
    )
    replaced_stage = _combined_stage(
        split["standard_tickets"], funded_agents, split["l2_tickets"], senior_agents, post_factors
    )

    stages = {
        "baseline": {"total_cost": baseline_stage["total_cost"], "vendor_cost": vendor_cost},
        "aged": {"total_cost": aged_stage["total_cost"], "vendor_cost": vendor_cost},
        "replaced": {"total_cost": replaced_stage["total_cost"], "vendor_cost": vendor_cost},
    }

    m5_result = {
        "rows": escalation_rows,
        "counts": split["counts"],
        "vendor_cost": vendor_cost,
        "vendor_ids": split["vendor_ids"],
        "changed_tickets": changed_tickets,
        "forced_by_incident_risk": force,
        "source": (
            f"breach probability: {derived['breach']['source']}; SLA deadlines & "
            f"breach reduction & labour cost: CONFIG (no monetary breach-cost or "
            f"deadline field in UCI-498)"
        ),
    }

    if verbose:
        _print_report(
            cleaned, m1_result, m2_result, initial, final_sequence, m5_result,
            m6_result, replacement, stages,
        )

    return {
        "data": data,
        "m1": m1_result,
        "m2": m2_result,
        "assignment": {
            "initial": initial,
            "baseline": baseline_stage,
            "funded_agents": funded_agents,
            "senior_agents": senior_agents,
        },
        "m4": final_sequence,
        "m5": m5_result,
        "m6": m6_result,
        "replacement": replacement,
        "stages": stages,
    }


def _print_report(cleaned, m1_result, m2_result, initial, final_sequence, m5_result,
                   m6_result, replacement, stages):
    print("=== M0 data source ===")
    if cleaned is not None:
        print(f"real UCI-498 log, {len(cleaned)} cleaned tickets ({CACHE_PATH})")
    else:
        print(f"no cached UCI-498 log at {CACHE_PATH}; CONFIG-documented fallback distributions used")

    print("\n=== M1 -> M3: capacity funds the assignable agent pool ===")
    print(f"status={m1_result['status']} agents_per_skill={m1_result['agents_per_skill']}")
    print(f"source: {m1_result['source']}")
    print(f"initial assignment: {len(initial['pairs'])} tickets served, cost={initial['total_cost']:.1f}")

    print("\n=== M2 regional distribution (independent of the ticket chain) ===")
    print(f"total_cost={m2_result['total_cost']:.1f}")
    print(f"source: {m2_result['source']}")

    print("\n=== M3 -> M4: sequence of the standard (post-escalation) pool ===")
    print(f"sequence={final_sequence['sequence']} makespan={final_sequence['makespan']:.1f} min")

    print("\n=== M6 major-incident plan -> M5 gate ===")
    sched = m6_result["schedule"]
    prob = m6_result["probability"]
    print(
        f"critical_path={sched['critical_path']} duration={sched['project_duration']:.1f}h "
        f"P(finish<=deadline)={prob['probability']:.2f} "
        f"(threshold={CONFIG['major_incident_probability_threshold']}, "
        f"forces escalation={m5_result['forced_by_incident_risk']})"
    )
    print(f"source: {m6_result['source']}")

    print("\n=== M4 -> M5 -> M3: escalation decisions and their effect ===")
    print(f"counts: {m5_result['counts']}  vendor_cost={m5_result['vendor_cost']:.1f}")
    print(f"tickets whose agent/position changed due to escalation: {len(m5_result['changed_tickets'])}")
    print(f"source: {m5_result['source']}")

    print("\n=== M7 -> M3: three-stage table on the funded-and-escalation-adjusted assignment ===")
    print(f"{'stage':<12}{'total_cost':>12}{'vendor_cost':>14}")
    for name in ("baseline", "aged", "replaced"):
        row = stages[name]
        print(f"{name:<12}{row['total_cost']:>12.1f}{row['vendor_cost']:>14.1f}")
    print(f"workstations replaced (flagged under >=1 plausible alpha): {replacement['to_replace']}")
    print(f"source: {replacement['source']}")


if __name__ == "__main__":
    run_pipeline()
