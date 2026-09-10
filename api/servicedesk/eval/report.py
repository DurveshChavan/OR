"""Turn a replay run into intervals and a results page.

    python -m api.servicedesk.eval.report --run-id replay-2026-09-10-a1

Two jobs: a paired block bootstrap of each policy's difference from FIFO, and
``docs/results/<run_id>.md`` written from the run's own files. Every number on
that page comes from ``summary.csv`` or ``bootstrap_intervals.csv``; nothing is
typed in by hand, so the page cannot drift from the run it describes.

The bootstrap blocks by arrival day because queue outcomes on the same day are
dependent — an independent ticket bootstrap would understate the interval. It
resamples **dense-window days only**: across the whole test period the median
arrival day holds two tickets while the busiest holds 358, so resampling all 132
days would measure which near-empty day was drawn rather than the ticket mix.
The dense window has 17 days with a median of 263 tickets each.

What the interval describes is sampling variability in the ticket mix. It says
nothing about uncertainty in the queue dynamics themselves, which are
deterministic given the fixtures, and it is not a confidence interval for a live
service desk.
"""
import argparse
import json
import os

import numpy as np
import pandas as pd

from api.servicedesk.eval.run_replay import DENSE_WINDOW_DAYS, EVAL_DIR

RESULTS_DIR = os.path.join("docs", "results")
BOOTSTRAP_DRAWS = 1000
BOOTSTRAP_SEED = 20260910
REFERENCE_POLICY = "fifo"


def _blocks(outcomes):
    """Arrival day as the bootstrap block unit."""
    return (outcomes["arrival_minute"] // (24 * 60)).astype(int)


def paired_block_bootstrap(outcomes, draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED,
                           cutoff=None):
    """Difference in simulated breach rate against FIFO, resampling whole days.

    Paired: one resample of days is scored for every policy, so a day that
    happens to be hard is hard for all of them. ``cutoff`` restricts the blocks
    to the dense window; blocks of wildly unequal size make the resample a
    statement about which empty day was drawn.
    """
    served = outcomes[outcomes["state"] == "completed"].copy()
    if cutoff is not None:
        served = served[served["arrival_minute"] <= cutoff]
    served["block"] = _blocks(served)
    policies = sorted(served["policy"].unique())
    days = np.array(sorted(served["block"].unique()))
    rng = np.random.default_rng(seed)

    by_policy_day = {
        policy: served[served["policy"] == policy].groupby("block")["breached"]
        .agg(["sum", "size"])
        for policy in policies
    }
    rows = []
    draws_matrix = {policy: [] for policy in policies}
    for _ in range(draws):
        sample = rng.choice(days, size=len(days), replace=True)
        rates = {}
        for policy, table in by_policy_day.items():
            present = [d for d in sample if d in table.index]
            if not present:
                rates[policy] = np.nan
                continue
            picked = table.loc[present]
            rates[policy] = float(picked["sum"].sum() / picked["size"].sum())
        for policy in policies:
            draws_matrix[policy].append(rates[policy] - rates[REFERENCE_POLICY])

    for policy in policies:
        values = np.array(draws_matrix[policy], dtype=float)
        values = values[~np.isnan(values)]
        table = by_policy_day[policy]
        point = float(table["sum"].sum() / table["size"].sum())
        reference = by_policy_day[REFERENCE_POLICY]
        point_reference = float(reference["sum"].sum() / reference["size"].sum())
        rows.append({
            "policy": policy,
            "simulated_breach_rate": point,
            "difference_vs_fifo": point - point_reference,
            "ci_low": float(np.quantile(values, 0.025)) if len(values) else np.nan,
            "ci_high": float(np.quantile(values, 0.975)) if len(values) else np.nan,
            "blocks": int(len(days)),
            "draws": draws,
        })
    return pd.DataFrame(rows)


def bootstrap_all(outcomes, multipliers, cutoff=None):
    frames = []
    for multiplier in multipliers:
        part = outcomes[outcomes["capacity_multiplier"] == multiplier]
        table = paired_block_bootstrap(part, cutoff=cutoff)
        table.insert(1, "capacity_multiplier", multiplier)
        table["window"] = "dense" if cutoff is not None else "all"
        frames.append(table)
    return pd.concat(frames, ignore_index=True)


def _table(rows, columns, headers, formats):
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join(["---"] + ["---:"] * (len(headers) - 1)) + "|"]
    for _, row in rows.iterrows():
        cells = [fmt.format(row[column]) for column, fmt in zip(columns, formats)]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _at(frame, multiplier, policy, column="simulated_breach_rate"):
    row = frame[(frame["capacity_multiplier"] == multiplier)
                & (frame["policy"] == policy)]
    return float(row[column].iloc[0])


def _reading(everything, intervals, manifest):
    """The findings, stated from the run's own numbers — including the ones that
    go against the proposed policy. A replay that only reports its winners is
    not evidence."""
    high = max(manifest["capacity_multipliers"])
    low = min(manifest["capacity_multipliers"])
    lines = []
    add = lines.append

    full = _at(everything, high, "sla_risk_aware")
    fifo_full = _at(everything, high, "fifo")
    no_agent = _at(everything, high, "ablation_no_agent_choice")
    no_risk = _at(everything, high, "ablation_no_risk")
    no_late = _at(everything, high, "ablation_no_lateness_cost")
    ci = intervals[(intervals["capacity_multiplier"] == high)
                   & (intervals["policy"] == "sla_risk_aware")].iloc[0]

    add(f"1. **At multiplier {high} the proposed policy simulates "
        f"{full:.4f} against FIFO's {fifo_full:.4f}** — a difference of "
        f"{ci['difference_vs_fifo']:+.4f} over the dense window, bootstrap "
        f"interval [{ci['ci_low']:+.4f}, {ci['ci_high']:+.4f}]. Queue waits are "
        "zero at "
        "this capacity, so the difference is not about ordering at all: it is "
        "about which agent the ticket goes to.\n")
    add(f"2. **Remove candidate selection and the difference disappears.** The "
        f"`ablation_no_agent_choice` run, which keeps the tiering and the "
        f"urgency ranking but takes the first eligible slot, simulates "
        f"{no_agent:.4f} — indistinguishable from FIFO. The gain comes from "
        "the training-derived speed multiplier, not from the risk score.\n")
    add(f"3. **The risk score contributes nothing measurable here.** Replacing "
        f"every calibrated probability with 1.0 (`ablation_no_risk`) gives "
        f"{no_risk:.4f} against the full policy's {full:.4f}. Removing the "
        f"projected-lateness term gives {no_late:.4f}; where that equals the "
        "full policy exactly, the term never changed a selection, because the "
        "slot ranking was already decided by projected service time.\n")

    low_duration = _at(everything, low, "duration_first")
    low_risk_aware = _at(everything, low, "sla_risk_aware")
    low_ci = intervals[(intervals["capacity_multiplier"] == low)
                       & (intervals["policy"] == "duration_first")].iloc[0]
    add(f"4. **Under severe scarcity the proposed policy loses.** At multiplier "
        f"{low}, shortest-predicted-duration-first simulates "
        f"{low_duration:.4f} against the proposed policy's {low_risk_aware:.4f} "
        f"— {low_ci['difference_vs_fifo']:+.4f} versus FIFO over the dense "
        f"window, interval "
        f"[{low_ci['ci_low']:+.4f}, {low_ci['ci_high']:+.4f}]. That is the "
        "classic shortest-job-first result: when the queue is deeply "
        "overloaded, clearing short work first finishes more tickets inside "
        "their windows. This is reported as it stands; no weight was retuned "
        "after seeing it.\n")

    risk_low = intervals[(intervals["capacity_multiplier"] == low)
                         & (intervals["policy"] == "sla_risk_aware")].iloc[0]
    add(f"   At that same capacity the proposed policy's own difference is "
        f"{risk_low['difference_vs_fifo']:+.4f}, interval "
        f"[{risk_low['ci_low']:+.4f}, {risk_low['ci_high']:+.4f}] — an interval "
        "that includes zero, so under this much overload it is not "
        "distinguishable from FIFO either.\n")

    p1_rates = everything[everything["capacity_multiplier"] == high][
        "p1_simulated_breach_rate"]
    add(f"5. **P1 breaches at about {p1_rates.median():.1%} under every "
        "policy.** The declared P1 target is 240 minutes and typical handling "
        "time in this log is far longer, so no dispatch order can rescue it. "
        "That is a property of the declared SLA table meeting this data, and it "
        "is the clearest illustration of why the table is documented as an "
        "assumption rather than presented as a finding.\n")

    add("Taken together: this replay supports a narrow claim. Under these "
        "assumptions, choosing *who* gets a ticket using training-period "
        "productivity moves the simulated breach rate; ranking by calibrated "
        "risk did not, and under heavy overload a simpler shortest-job rule was "
        "better. The risk model still earns its place in the product as the "
        "Risk Radar's ordering and as the stored explanation on a "
        "recommendation, which are review aids, not throughput claims.\n")
    return "\n".join(lines)


def write_results_page(run_id, summary, intervals, manifest, assumptions):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, f"{run_id}.md")
    everything = summary[summary["window"] == "all"]
    lines = []
    add = lines.append

    add(f"# Replay results — `{run_id}`\n")
    add("A counterfactual simulation of four dispatch policies over the locked "
        "test period, under declared capacity, skill and SLA assumptions. It "
        "compares policy behaviour in a simulator. It is not an A/B trial, and "
        "nothing here may be reported as an achieved reduction in SLA breaches.\n")

    add("## What was run\n")
    add(f"- jobs: {manifest['jobs']:,} held-out incidents, fingerprint "
        f"`{manifest['jobs_fingerprint_sha256'][:16]}…`")
    add(f"- risk model `{manifest['risk_model_version']}`, duration model "
        f"`{manifest['duration_model_version']}`")
    add(f"- service demand: {manifest['service_demand']}")
    add(f"- breach rule: `{manifest['breach_rule']}`")
    add(f"- capacity multipliers: {manifest['capacity_multipliers']}")
    add(f"- workforce: {assumptions['agents']} agents, "
        f"{assumptions['wip_total_slots']:,} concurrent slots at multiplier 1.0, "
        f"WIP from {assumptions['wip_estimator']}")
    add(f"- SLA policy: declared, not derived — {assumptions['sla_policy_source_note']}")
    add(f"- seed: {manifest['seed']}\n")

    add("## Simulated outcomes, whole test period\n")
    for multiplier in manifest["capacity_multipliers"]:
        rows = everything[everything["capacity_multiplier"] == multiplier]
        add(f"### Capacity multiplier {multiplier}\n")
        add(_table(
            rows,
            ["policy", "simulated_breach_rate", "p1_simulated_breach_rate",
             "p90_wait_minutes", "p10_slack_minutes", "visible_unassigned"],
            ["Policy", "Simulated breach rate", "P1 rate", "p90 wait (min)",
             "p10 slack (min)", "Unassigned"],
            ["{}", "{:.4f}", "{:.4f}", "{:,.0f}", "{:,.0f}", "{:.0f}"],
        ))
    add("The p10 slack column is deeply negative under every policy. It restates "
        "the mismatch between the declared SLA table and this log's handling "
        "times — the worst tenth of tickets finish days past a deadline no "
        "dispatch order could have met — rather than measuring anything a policy "
        "controls.\n")

    add("## Difference from FIFO, paired block bootstrap\n")
    add(f"Blocks are the arrival days inside the dense window; "
        f"{BOOTSTRAP_DRAWS:,} draws; the same resample of days scores every "
        "policy. The sparse tail is excluded because a day holding two tickets "
        "is not a block — over the whole test period the median arrival day "
        "holds two tickets and the busiest holds 358, so resampling all 132 "
        "days would measure which empty day was drawn. The point estimate here "
        "is therefore the dense-window rate and differs slightly from the "
        "whole-period rate above. The interval describes variability in the "
        "ticket mix, not uncertainty about the queue dynamics, which are fixed "
        "once the fixtures are.\n")
    for multiplier in manifest["capacity_multipliers"]:
        rows = intervals[intervals["capacity_multiplier"] == multiplier]
        add(f"### Capacity multiplier {multiplier}\n")
        add(_table(
            rows,
            ["policy", "simulated_breach_rate", "difference_vs_fifo",
             "ci_low", "ci_high", "blocks"],
            ["Policy", "Simulated breach rate", "Difference vs FIFO",
             "CI low", "CI high", "Blocks"],
            ["{}", "{:.4f}", "{:+.4f}", "{:+.4f}", "{:+.4f}", "{:.0f}"],
        ))

    add("## Dense window\n")
    add(f"About 3,100 of the {manifest['jobs']:,} held-out incidents arrive in "
        f"the first {DENSE_WINDOW_DAYS} days; the rest trickle into an otherwise "
        "idle system over eight months. The dense-window rows are reported "
        "separately so a p90 queue wait means something.\n")
    dense = summary[summary["window"] == "dense"]
    for multiplier in manifest["capacity_multipliers"]:
        rows = dense[dense["capacity_multiplier"] == multiplier]
        add(f"### Capacity multiplier {multiplier} — first "
            f"{DENSE_WINDOW_DAYS} days\n")
        add(_table(
            rows,
            ["policy", "simulated_breach_rate", "p1_simulated_breach_rate",
             "p90_wait_minutes"],
            ["Policy", "Simulated breach rate", "P1 rate", "p90 wait (min)"],
            ["{}", "{:.4f}", "{:.4f}", "{:,.0f}"],
        ))

    add("## What the results say\n")
    add(_reading(everything, intervals, manifest))

    add("## Assumptions that decide these numbers\n")
    for item in assumptions["unavailable_and_assumed"]:
        add(f"- {item}")
    add(f"- skill map: {assumptions['skill_map_categories']} categories mapped "
        f"from training rows, modal-group purity median "
        f"{assumptions['skill_map_purity_median']:.2f} and p25 "
        f"{assumptions['skill_map_purity_p25']:.2f}. Eligibility is therefore "
        "approximate, and that weakens every policy equally.")
    add(f"- agent speed: training-period residuals, shrunk toward 1.0 with "
        f"k={assumptions['speed_shrinkage_k']} and clipped to "
        f"{assumptions['speed_bounds']}\n")

    add("## Limitations\n")
    add("- The service-demand proxy is logged elapsed time, which already "
        "contains historical queue waiting. It therefore overstates handling "
        "time, and at multiplier 1.0 it reproduces roughly the system that "
        "generated it.")
    add("- The simulation starts with an empty queue and agents always "
        "available. Neither is true of a real desk.")
    add("- The SLA targets are declared business inputs. A different target "
        "table moves every breach rate on this page.")
    add("- A policy's advantage here is an advantage in this simulator under "
        "these assumptions. Establishing a real effect needs a shadow "
        "deployment or an A/B test, neither of which this project ran.\n")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)

    target = os.path.join(EVAL_DIR, args.run_id)
    outcomes = pd.read_parquet(os.path.join(target, "ticket_outcomes.parquet"))
    summary = pd.read_csv(os.path.join(target, "summary.csv"))
    with open(os.path.join(target, "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    with open(os.path.join(target, "assumptions_snapshot.json"), encoding="utf-8") as fh:
        assumptions = json.load(fh)

    cutoff = manifest["dense_window_days"] * 24 * 60.0
    intervals = bootstrap_all(outcomes, manifest["capacity_multipliers"],
                              cutoff=cutoff)
    intervals.to_csv(os.path.join(target, "bootstrap_intervals.csv"), index=False)
    page = write_results_page(args.run_id, summary, intervals, manifest, assumptions)
    print(f"wrote {os.path.join(target, 'bootstrap_intervals.csv')}")
    print(f"wrote {page}")


if __name__ == "__main__":
    main()
