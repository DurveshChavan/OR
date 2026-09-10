"""Train the handling-duration model offline.

    python -m api.servicedesk.ml.train_duration

Same discipline as the risk model: recorded split, selection on validation,
one pass over the locked test period, artifact plus card.

The target is ``resolved_at - opened_at`` in minutes — the audit rejected
``closed_at`` because the resolve-to-close gap is a fixed ~5-day auto-close
timer. The distribution has a long right tail (p50 ≈ 22h, p99 ≈ 2,843h), so the
model fits ``log1p(minutes)`` and the headline error is the median absolute
error, not the mean.

What this prediction is used for matters: the dispatch policy turns it into a
projected finish time. It is an estimate of how long tickets like this one have
historically taken, waiting included, and the replay's limitations section says
so.
"""
import argparse
import json
from datetime import datetime, timezone

import numpy as np

from api.servicedesk.ingest.uci498 import MANIFEST_PATH
from api.servicedesk.ml import evaluation
from api.servicedesk.ml.artifacts import save_artifact
from api.servicedesk.ml.baselines import PriorityCategoryMedianDuration
from api.servicedesk.ml.feature_spec import INCIDENT_FEATURES_V1
from api.servicedesk.ml.pipeline import build_duration_estimator, inverse_duration
from api.servicedesk.ml.train_risk import load_prepared, read_recorded_split

MODEL_NAME = "duration"
TARGET = "duration_minutes"
#: Declared before fitting: candidates differ only in ridge strength and in how
#: aggressively rare categories are folded together.
CANDIDATE_GRID = [
    {"alpha": a, "min_frequency": m}
    for a in (0.3, 1.0, 3.0, 10.0)
    for m in (10, 20, 50)
]
#: Selection metric, on validation only. Median absolute error, because the mean
#: is dominated by a handful of month-long incidents.
SELECTION_METRIC = "median_absolute_error_minutes"


def fit_candidates(train, validation, grid=CANDIDATE_GRID):
    results = []
    target = np.log1p(train[TARGET].to_numpy())
    for params in grid:
        estimator = build_duration_estimator(**params)
        estimator.fit(train, target)
        predicted = inverse_duration(estimator.predict(validation))
        scores = evaluation.regression_metrics(
            validation[TARGET], predicted, "validation"
        )
        results.append({"params": params, "estimator": estimator, "scores": scores})
    results.sort(key=lambda r: r["scores"][SELECTION_METRIC])
    return results


def predict_minutes(model, frame):
    if isinstance(model, PriorityCategoryMedianDuration):
        return model.predict(frame)
    return inverse_duration(model.predict(frame))


def evaluate_all(models, parts):
    return {
        name: {
            split: evaluation.regression_metrics(
                parts[split][TARGET], predict_minutes(model, parts[split]), split
            )
            for split in ("validation", "test")
        }
        for name, model in models.items()
    }


def _row(name, metrics):
    return (
        f"| {name} | {metrics['median_absolute_error_minutes']:,.1f} | "
        f"{metrics['mean_absolute_error_minutes']:,.1f} | "
        f"{metrics['p90_absolute_error_minutes']:,.1f} | "
        f"{metrics['median_predicted_minutes']:,.1f} |"
    )


def write_card(version, metadata, results, schema):
    counts = schema["split"]["split_counts"]
    lines = []
    add = lines.append
    add(f"# Model card — handling duration `{version}`\n")
    add("Predicts elapsed minutes from `opened_at` to `resolved_at` for a ticket "
        "described only by what is known when it is created. The dispatch policy "
        "uses it for projected finish times.\n")

    add("## Data\n")
    add(f"- source: SHA-256 `{metadata['source_manifest_sha256'][:16]}…`, feature "
        f"schema `{metadata['feature_schema_version']}`")
    add(f"- incidents: train {counts['train']:,} | validation "
        f"{counts['validation']:,} | locked test {counts['test']:,}")
    add(f"- target: `{TARGET}` = `resolved_at - opened_at`. `closed_at` is "
        "rejected: its gap from `resolved_at` is a fixed ~5-day auto-close "
        "timer, so a `closed_at` target would be largely constant.\n")

    add("## Method\n")
    add(f"- estimator: ridge regression on `log1p(minutes)`, "
        f"`alpha={metadata['hyperparameters']['alpha']}`, "
        f"`min_frequency={metadata['hyperparameters']['min_frequency']}`")
    add("- inverse transform: `max(0, expm1(prediction))`, with a test proving a "
        "negative minute cannot escape")
    add(f"- selection: {SELECTION_METRIC} on validation only, over "
        f"{len(CANDIDATE_GRID)} candidates")
    add("- baseline: median duration by (priority, category), training period "
        "only, falling back to the priority median and then the overall median\n")

    add("## Results — minutes\n")
    for split in ("validation", "test"):
        add(f"### {split.capitalize()} period\n")
        add("| Model | Median abs. error | Mean abs. error | p90 abs. error | "
            "Median predicted |")
        add("|---|---:|---:|---:|---:|")
        for name, per_split in results.items():
            add(_row(name, per_split[split]))
        add("")
        actual = results["baseline (priority x category median)"][split]
        add(f"Median actual duration in this period: "
            f"{actual['median_actual_minutes']:,.1f} minutes.\n")

    add("## Known limitations\n")
    add("- Logged elapsed time contains historical queue waiting. This is a "
        "handling-time proxy, not pure service time, and the replay inherits "
        "that limitation.")
    add("- The p90 absolute error is large in absolute terms because the target "
        "spans minutes to months. No per-ticket confidence interval is exposed, "
        "because none has been estimated.")
    add("- The model reads creation-time fields only. It cannot see that a "
        "ticket was reassigned four times, which is most of what makes a long "
        "incident long.")
    add("- No resolver identity is used. Agent speed multipliers are a separate, "
        "training-period residual calculation in the replay.\n")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Train the duration model.")
    parser.add_argument("--version", default=None)
    args = parser.parse_args(argv)
    version = args.version or f"uci-duration-{datetime.now().strftime('%Y-%m-%d')}-a1"

    frame = load_prepared()
    parts, schema = read_recorded_split(frame)
    train, validation = parts["train"], parts["validation"]

    baseline = PriorityCategoryMedianDuration().fit(train)
    ranked = fit_candidates(train, validation)
    best = ranked[0]
    print(f"selected {best['params']} on validation {SELECTION_METRIC}="
          f"{best['scores'][SELECTION_METRIC]:,.1f} minutes")

    models = {
        "baseline (priority x category median)": baseline,
        "ridge on log1p(minutes)": best["estimator"],
    }
    results = evaluate_all(models, parts)

    with open(MANIFEST_PATH, encoding="utf-8") as fh:
        manifest = json.load(fh)
    metadata = {
        "model_name": MODEL_NAME,
        "target": f"{TARGET} (resolved_at - opened_at, minutes)",
        "target_transform": "log1p; inverse max(0, expm1(x))",
        "feature_schema_version": INCIDENT_FEATURES_V1.version,
        "feature_spec": INCIDENT_FEATURES_V1.as_dict(),
        "hyperparameters": best["params"],
        "selection_metric": SELECTION_METRIC,
        "selection_split": "validation",
        "source_manifest_sha256": manifest["sha256"],
        "prepare_code_version": manifest["prepare_code_version"],
        "split": schema["split"],
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "baseline": baseline.as_dict(),
    }
    metrics = {
        "models": results,
        "selection_table": [
            {"params": r["params"], SELECTION_METRIC: r["scores"][SELECTION_METRIC]}
            for r in ranked
        ],
    }
    card = write_card(version, metadata, results, schema)
    target = save_artifact(MODEL_NAME, version, best["estimator"], metadata,
                           metrics, card)

    print(f"wrote {target}")
    for name, per_split in results.items():
        test = per_split["test"]
        print(f"  test | {name:38s} medae={test['median_absolute_error_minutes']:,.1f} "
              f"mae={test['mean_absolute_error_minutes']:,.1f} "
              f"p90={test['p90_absolute_error_minutes']:,.1f}")
    return target


if __name__ == "__main__":
    main()
