"""Train the SLA-risk model offline.

    python -m api.servicedesk.ml.train_risk

Order of operations is the whole point, so it is stated here and followed
literally:

1. read the prepared incidents and their **recorded** split — never recompute a
   percentage, or the model card and the replay can disagree about which
   incidents are test;
2. fit the priority-only baseline on training data;
3. fit candidate logistic models on training data and choose one on
   **validation** ROC-AUC;
4. calibrate with the method declared below, before any test number exists;
5. evaluate every model on the locked test period exactly once;
6. write the artifact, its metrics and its card.

The training period runs at 44.2% breach and the test period at 24.4% (see
`notes/phases/STATE.md`, Phase 2A finding 1). A model calibrated on training
data will therefore be over-confident on test data. That is measured and
reported here rather than tuned away.
"""
import argparse
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator

from api.servicedesk.ingest.uci498 import MANIFEST_PATH, PROCESSED_PARQUET, PROCESSED_SCHEMA
from api.servicedesk.ml import evaluation
from api.servicedesk.ml.artifacts import save_artifact
from api.servicedesk.ml.baselines import PriorityBreachRate
from api.servicedesk.ml.feature_spec import INCIDENT_FEATURES_V1
from api.servicedesk.ml.pipeline import build_risk_estimator

MODEL_NAME = "sla_risk"
SEED = 20260910

#: Declared before any model was fitted.
#: Selection uses validation ROC-AUC — a ranking metric, because the dispatch
#: policy consumes the score as an ordering. Calibration is fixed separately
#: below and is not part of the search.
SELECTION_METRIC = "roc_auc"
CANDIDATE_GRID = [
    {"C": c, "min_frequency": m}
    for c in (0.1, 1.0, 3.0)
    for m in (10, 20, 50)
]
#: Isotonic, fitted on the validation period. Validation holds 3,498 incidents,
#: comfortably above the few hundred at which isotonic overfits, and it is the
#: period adjacent to the test period — which is what a deployment recalibrating
#: on recent data would do. The train-CV variant is fitted too and reported as a
#: sensitivity, so the choice is visible rather than assumed.
CALIBRATION_METHOD = "isotonic"
#: The warm-up sensitivity predeclared in Phase 2A: refit on training data with
#: the log's opening three weeks removed, using the already-selected
#: hyperparameters. No second selection happens here.
WARMUP_EXCLUSION_DAYS = 21


def load_prepared(path=PROCESSED_PARQUET):
    if not os.path.exists(path):
        raise SystemExit(
            f"prepared data not found at {path}; run "
            "`python -m api.servicedesk.ingest.uci498 prepare` first"
        )
    return pd.read_parquet(path)


def read_recorded_split(frame, schema_path=PROCESSED_SCHEMA):
    """Split by the recorded ``split`` column and check it against the schema.

    The check exists because a silent disagreement between the parquet and the
    schema file is exactly the kind of thing that only surfaces when a replay
    fixture and a model card quote different test sets.
    """
    parts = {name: frame[frame["split"] == name].copy()
             for name in ("train", "validation", "test")}
    with open(schema_path, encoding="utf-8") as fh:
        schema = json.load(fh)
    recorded = schema["split"]["split_counts"]
    for name, part in parts.items():
        if len(part) != recorded[name]:
            raise SystemExit(
                f"{name} split holds {len(part):,} rows but the schema records "
                f"{recorded[name]:,}; rerun prepare before training"
            )
    return parts, schema


def fit_candidates(train, validation, grid=CANDIDATE_GRID):
    """Fit every candidate on training data, score each on validation only."""
    results = []
    for params in grid:
        estimator = build_risk_estimator(seed=SEED, **params)
        estimator.fit(train, train["label_breach"])
        scores = evaluation.classification_metrics(
            validation["label_breach"],
            estimator.predict_proba(validation)[:, 1],
            "validation",
        )
        results.append({"params": params, "estimator": estimator, "scores": scores})
    results.sort(key=lambda r: -r["scores"][SELECTION_METRIC])
    return results


def calibrate(estimator, calibration_frame):
    """Wrap a fitted estimator in the declared calibrator."""
    # FrozenEstimator is scikit-learn 1.6+'s replacement for cv="prefit": the
    # wrapped pipeline is not refitted, only the calibration map is learned.
    calibrated = CalibratedClassifierCV(
        FrozenEstimator(estimator), method=CALIBRATION_METHOD
    )
    calibrated.fit(calibration_frame, calibration_frame["label_breach"])
    return calibrated


def train_cv_calibrated(train, params):
    """The sensitivity variant: calibration learned inside the training period.

    It never sees validation data, so its validation numbers are honest; it also
    learns the training period's 44% base rate, which is the drift problem in
    concrete form.
    """
    calibrated = CalibratedClassifierCV(
        build_risk_estimator(seed=SEED, **params),
        method=CALIBRATION_METHOD,
        cv=5,
    )
    calibrated.fit(train, train["label_breach"])
    return calibrated


def warmup_excluded(train, days=WARMUP_EXCLUSION_DAYS):
    """Training rows after the log's opening weeks."""
    start = train["opened_at"].min()
    cutoff = start + pd.Timedelta(days=days)
    return train[train["opened_at"] >= cutoff].copy(), cutoff


def probability(model, frame):
    if isinstance(model, PriorityBreachRate):
        return model.predict_proba(frame)
    return model.predict_proba(frame)[:, 1]


def evaluate_all(models, parts):
    """The single pass over the locked test period."""
    out = {}
    for name, model in models.items():
        out[name] = {
            split: evaluation.classification_metrics(
                parts[split]["label_breach"], probability(model, parts[split]), split
            )
            for split in ("validation", "test")
        }
    return out


def build_metadata(schema, params, selection):
    with open(MANIFEST_PATH, encoding="utf-8") as fh:
        manifest = json.load(fh)
    return {
        "model_name": MODEL_NAME,
        "target": "label_breach (made_sla == False on the final ordered record)",
        "feature_schema_version": INCIDENT_FEATURES_V1.version,
        "feature_spec": INCIDENT_FEATURES_V1.as_dict(),
        "hyperparameters": params,
        "selection_metric": SELECTION_METRIC,
        "selection_split": "validation",
        "calibration": {
            "method": CALIBRATION_METHOD,
            "fitted_on": "validation period (prefit)",
        },
        "seed": SEED,
        "source_manifest_sha256": manifest["sha256"],
        "prepare_code_version": manifest["prepare_code_version"],
        "split": schema["split"],
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "selection_table": selection,
    }


def _capacity_line(metrics, capacity=0.20):
    for row in metrics["review_capacity"]:
        if abs(row["capacity"] - capacity) < 1e-9:
            return row
    return metrics["review_capacity"][0]


def _metric_row(name, metrics):
    capacity = _capacity_line(metrics)
    return (
        f"| {name} | {metrics['roc_auc']:.4f} | {metrics['pr_auc']:.4f} | "
        f"{metrics['brier']:.4f} | {metrics['expected_calibration_error']:.4f} | "
        f"{metrics['mean_predicted']:.3f} | "
        f"{capacity['precision']:.3f} | {capacity['recall']:.3f} |"
    )


def write_card(version, metadata, results, warmup, schema):
    """The model card. Numbers only; no adjective the numbers do not support."""
    counts = schema["split"]["split_counts"]
    by_split = schema["label_prevalence_by_split"]
    lines = []
    add = lines.append
    add(f"# Model card — SLA-risk `{version}`\n")
    add("Predicts, at ticket creation time, the probability that an incident "
        "ends its life with `made_sla == False`. The score ranks urgency inside "
        "the dispatch policy. It is not a statement about any agent.\n")

    add("## Data\n")
    add(f"- source: `{metadata['source_manifest_sha256'][:16]}…` "
        f"(SHA-256 of the raw UCI-498 log, full value in `data/manifests/uci498.json`)")
    add(f"- prepared by: `{metadata['prepare_code_version']}`, feature schema "
        f"`{metadata['feature_schema_version']}`")
    add(f"- incidents: train {counts['train']:,} | validation "
        f"{counts['validation']:,} | locked test {counts['test']:,}")
    add(f"- train ends `{schema['split']['train_end_opened_at']}`, test starts "
        f"`{schema['split']['test_start_opened_at']}`")
    add(f"- breach rate by split: train {by_split['train'] * 100:.1f}%, "
        f"validation {by_split['validation'] * 100:.1f}%, "
        f"test {by_split['test'] * 100:.1f}%\n")

    add("## Features\n")
    add("Creation-time fields only, read from the first ordered record: "
        + ", ".join(f"`{c}`" for c in INCIDENT_FEATURES_V1.categorical)
        + f", plus `{'`, `'.join(INCIDENT_FEATURES_V1.timestamp_derived)}` derived "
          "from `opened_at` and a missingness indicator for `u_symptom`.\n")
    add("Excluded and enforced by `FeatureSpec`: "
        + ", ".join(f"`{c}`" for c in INCIDENT_FEATURES_V1.forbidden)
        + ". `assignment_group` is excluded as well — the audit found it already "
          "populated on 96.4% of first records, so it encodes a routing decision "
          "a human had already made.\n")

    add("## Method\n")
    add(f"- estimator: logistic regression on one-hot features, "
        f"`C={metadata['hyperparameters']['C']}`, "
        f"`min_frequency={metadata['hyperparameters']['min_frequency']}`, seed "
        f"{metadata['seed']}")
    add(f"- selection: {SELECTION_METRIC} on the validation period only, over "
        f"{len(CANDIDATE_GRID)} candidates")
    add(f"- calibration: {CALIBRATION_METHOD}, fitted on the validation period, "
        "chosen before any test number was produced")
    add("- the locked test period was scored once, after the artifact was frozen\n")

    add("## Results\n")
    add("Precision and recall are at a 20% review capacity: the reviewer opens "
        "the riskiest fifth of the tickets.\n")
    for split in ("validation", "test"):
        add(f"### {split.capitalize()} period\n")
        add("| Model | ROC-AUC | PR-AUC | Brier | ECE | Mean predicted | "
            "Precision@20% | Recall@20% |")
        add("|---|---:|---:|---:|---:|---:|---:|---:|")
        for name, per_split in results.items():
            add(_metric_row(name, per_split[split]))
        add("")
        add(f"Observed breach rate in this period: "
            f"{results['baseline (priority only)'][split]['base_rate'] * 100:.1f}%.\n")
        if split == "validation":
            add("The shipped model's calibration map was **fitted on this "
                "period**, so its validation ECE is in-sample and means nothing "
                "on its own. The test table below carries the honest "
                "calibration number.\n")

    add("## Warm-up sensitivity (predeclared)\n")
    add(f"Declared in Phase 2A before the test period was scored: refit on "
        f"training data with the log's first {WARMUP_EXCLUSION_DAYS} days removed "
        f"(cutoff `{warmup['cutoff']}`, {warmup['rows_removed']:,} rows), reusing "
        "the already-selected hyperparameters. The opening weeks run at 57.6% / "
        "96.1% / 67.6% breach against 18-27% from mid-April on.\n")
    add("| Model | ROC-AUC | PR-AUC | Brier | ECE | Mean predicted | "
        "Precision@20% | Recall@20% |")
    add("|---|---:|---:|---:|---:|---:|---:|---:|")
    add(_metric_row("warm-up excluded (test)", warmup["metrics"]["test"]))
    add("")

    add("## Known limitations\n")
    add("- The training period breaches at "
        f"{by_split['train'] * 100:.1f}% and the test period at "
        f"{by_split['test'] * 100:.1f}%. Any probability learned on the first is "
        "over-confident on the second; the ECE column is where that shows.")
    add("- UCI-498 carries no ticket text, so nothing here is comparable to the "
        "text classifiers in the surveyed literature.")
    add("- The label is a ServiceNow compliance flag, not a business judgement "
        "about whether the customer was harmed.")
    add("- The score is ticket-level. It says nothing about which agent should "
        "take the ticket; that comes from eligibility, load and projected "
        "finish in the dispatch policy.")
    add("- Priority 2 breaches more often than priority 1 in this log (97.1% "
        "against 80.5%). The model reproduces the data; it does not correct it.\n")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Train the SLA-risk model.")
    parser.add_argument("--version", default=None,
                        help="artifact version (default: uci-risk-<today>-a1)")
    args = parser.parse_args(argv)
    version = args.version or f"uci-risk-{datetime.now().strftime('%Y-%m-%d')}-a1"

    frame = load_prepared()
    parts, schema = read_recorded_split(frame)
    train, validation = parts["train"], parts["validation"]

    baseline = PriorityBreachRate().fit(train)
    ranked = fit_candidates(train, validation)
    best = ranked[0]
    print(f"selected {best['params']} on validation {SELECTION_METRIC}="
          f"{best['scores'][SELECTION_METRIC]:.4f}")

    shipped = calibrate(best["estimator"], validation)
    train_calibrated = train_cv_calibrated(train, best["params"])

    models = {
        "baseline (priority only)": baseline,
        "logistic (uncalibrated)": best["estimator"],
        "logistic + isotonic on validation (shipped)": shipped,
        "logistic + isotonic on train CV (sensitivity)": train_calibrated,
    }
    results = evaluate_all(models, parts)

    warm_train, cutoff = warmup_excluded(train)
    warm_estimator = build_risk_estimator(seed=SEED, **best["params"])
    warm_estimator.fit(warm_train, warm_train["label_breach"])
    warm_shipped = calibrate(warm_estimator, validation)
    warmup = {
        "cutoff": str(cutoff),
        "rows_removed": int(len(train) - len(warm_train)),
        "rows_kept": int(len(warm_train)),
        "metrics": {
            split: evaluation.classification_metrics(
                parts[split]["label_breach"],
                warm_shipped.predict_proba(parts[split])[:, 1],
                split,
            )
            for split in ("validation", "test")
        },
    }

    selection = [
        {"params": r["params"], SELECTION_METRIC: r["scores"][SELECTION_METRIC],
         "brier": r["scores"]["brier"]}
        for r in ranked
    ]
    metadata = build_metadata(schema, best["params"], selection)
    metadata["baseline"] = baseline.as_dict()
    metrics = {
        "models": {name: per_split for name, per_split in results.items()},
        "warmup_sensitivity": warmup,
        "selection_table": selection,
    }
    card = write_card(version, metadata, results, warmup, schema)
    target = save_artifact(MODEL_NAME, version, shipped, metadata, metrics, card)

    print(f"wrote {target}")
    for name, per_split in results.items():
        test = per_split["test"]
        print(f"  test | {name:46s} auc={test['roc_auc']:.4f} "
              f"pr={test['pr_auc']:.4f} brier={test['brier']:.4f} "
              f"ece={test['expected_calibration_error']:.4f}")
    warm_test = warmup["metrics"]["test"]
    print(f"  test | {'warm-up excluded (sensitivity)':46s} "
          f"auc={warm_test['roc_auc']:.4f} pr={warm_test['pr_auc']:.4f} "
          f"brier={warm_test['brier']:.4f} "
          f"ece={warm_test['expected_calibration_error']:.4f}")
    return target


if __name__ == "__main__":
    main()
