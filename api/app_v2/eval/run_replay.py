"""Run every policy over identical exogenous fixtures, at every declared capacity.

    python -m api.app_v2.eval.run_replay

Order matters and is fixed: build the workforce from training rows, score the
held-out incidents with the frozen artifacts, build the exogenous jobs once,
then hand a copy of that same job list to each policy in turn. No policy is
constructed before its fixtures exist.

Outputs land in ``data/eval/<run_id>/``: per-ticket outcomes, a summary row per
policy and capacity, the assumption register, and a manifest naming the model
versions, source hash, seed and fixture digest.
"""
import argparse
import json
import os
from datetime import datetime, timezone

import pandas as pd

from api.app_v2.eval.emulation import (
    CAPACITY_MULTIPLIERS,
    SLA_POLICY,
    SLA_POLICY_SOURCE_NOTE,
    build_training_profile,
    load_emulation_records,
)
from api.app_v2.eval.jobs import build_exogenous_jobs, build_test_frame, jobs_fingerprint, to_dataframe
from api.app_v2.eval.policies import ablations, all_policies
from api.app_v2.eval.replay import run_policy, summarise
from api.app_v2.ingest.uci498 import MANIFEST_PATH, PROCESSED_PARQUET, PROCESSED_SCHEMA
from api.app_v2.ml.predict import DurationEstimator, RiskScorer

EVAL_DIR = os.path.join("data", "eval")
DEFAULT_SEED = 20260910
#: The held-out period is 3,499 incidents across nine months, but about 3,100 of
#: them arrive in the first sixteen days; the rest trickle into an otherwise idle
#: system. Metrics are reported over both windows, separately, because mixing
#: them silently would make a p90 queue wait meaningless.
DENSE_WINDOW_DAYS = 16


def score_test_rows(test_rows):
    """Frozen artifacts, applied to held-out rows. Predictions only."""
    risk = RiskScorer()
    duration = DurationEstimator()
    return (
        risk.score(test_rows), duration.minutes(test_rows),
        {"risk_model_version": risk.version, "duration_model_version": duration.version},
    )


def dense_cutoff(jobs):
    return DENSE_WINDOW_DAYS * 24 * 60.0


def run(run_id=None, seed=DEFAULT_SEED, multipliers=CAPACITY_MULTIPLIERS):
    run_id = run_id or f"replay-{datetime.now().strftime('%Y-%m-%d')}-a1"
    prepared = pd.read_parquet(PROCESSED_PARQUET)
    training_records = load_emulation_records(prepared, split="train")
    profile = build_training_profile(training_records)

    test_rows = build_test_frame(prepared)
    risk, duration, versions = score_test_rows(test_rows)
    jobs = build_exogenous_jobs(test_rows, profile, risk, duration, seed)
    fingerprint = jobs_fingerprint(jobs)
    cutoff = dense_cutoff(jobs)

    outcomes, summaries = [], []
    for multiplier in multipliers:
        agents = profile.with_capacity(multiplier)
        for policy in all_policies() + ablations():
            frame = run_policy(jobs, agents, policy)
            frame["policy"] = policy.name
            frame["capacity_multiplier"] = multiplier
            outcomes.append(frame)
            summaries.append(summarise(frame, policy.name, multiplier, "all"))
            dense = frame[frame["arrival_minute"] <= cutoff]
            summaries.append(summarise(dense, policy.name, multiplier, "dense"))
            print(f"  {multiplier:>5.2f} {policy.name:16s} "
                  f"breach={summaries[-2]['simulated_breach_rate']:.4f} "
                  f"p90wait={summaries[-2]['p90_wait_minutes']:,.0f} "
                  f"unassigned={summaries[-2]['visible_unassigned']}")

    target = os.path.join(EVAL_DIR, run_id)
    os.makedirs(target, exist_ok=True)
    all_outcomes = pd.concat(outcomes, ignore_index=True)
    all_outcomes.to_parquet(os.path.join(target, "ticket_outcomes.parquet"), index=False)
    summary = pd.DataFrame(summaries)
    summary.to_csv(os.path.join(target, "summary.csv"), index=False)
    to_dataframe(jobs).to_parquet(os.path.join(target, "exogenous_jobs.parquet"),
                                  index=False)

    with open(MANIFEST_PATH, encoding="utf-8") as fh:
        data_manifest = json.load(fh)
    with open(PROCESSED_SCHEMA, encoding="utf-8") as fh:
        schema = json.load(fh)
    manifest = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed": seed,
        "capacity_multipliers": list(multipliers),
        "policies": [policy.name for policy in all_policies()],
        "ablations": [policy.name for policy in ablations()],
        "jobs_fingerprint_sha256": fingerprint,
        "jobs": len(jobs),
        "service_demand": "held-out empirical duration (resolved_at - opened_at)",
        "breach_rule": "simulated_finish_minute > configured_sla_due_minute",
        "source_sha256": data_manifest["sha256"],
        "prepare_code_version": data_manifest["prepare_code_version"],
        "feature_schema_version": data_manifest["feature_schema_version"],
        "split": schema["split"],
        "dense_window_days": DENSE_WINDOW_DAYS,
        **versions,
    }
    with open(os.path.join(target, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    assumptions = dict(profile.assumptions)
    assumptions["sla_policy"] = {str(k): v for k, v in SLA_POLICY.items()}
    assumptions["sla_policy_source_note"] = SLA_POLICY_SOURCE_NOTE
    assumptions["capacity_multipliers"] = list(multipliers)
    with open(os.path.join(target, "assumptions_snapshot.json"), "w",
              encoding="utf-8") as fh:
        json.dump(assumptions, fh, indent=2, sort_keys=True, default=str)

    print(f"wrote {target}")
    return target, summary, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--multipliers", default=None,
                        help="comma-separated override of the declared sweep")
    args = parser.parse_args(argv)
    multipliers = (
        tuple(float(x) for x in args.multipliers.split(","))
        if args.multipliers else CAPACITY_MULTIPLIERS
    )
    run(run_id=args.run_id, seed=args.seed, multipliers=multipliers)


if __name__ == "__main__":
    main()
