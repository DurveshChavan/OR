# Model card — SLA-risk `uci-risk-2026-09-10-a1`

Predicts, at ticket creation time, the probability that an incident ends its life with `made_sla == False`. The score ranks urgency inside the dispatch policy. It is not a statement about any agent.

## Data

- source: `f41dba115f5bae26…` (SHA-256 of the raw UCI-498 log, full value in `data/manifests/uci498.json`)
- prepared by: `uci498-prepare-1`, feature schema `incident-features-v1`
- incidents: train 16,326 | validation 3,498 | locked test 3,499
- train ends `2016-05-02T15:15:00.000000000`, test starts `2016-05-16T14:31:00.000000000`
- breach rate by split: train 44.2%, validation 24.4%, test 24.4%

## Features

Creation-time fields only, read from the first ordered record: `priority`, `impact`, `urgency`, `category`, `subcategory`, `location`, `contact_type`, `u_symptom`, plus `opened_hour`, `opened_dayofweek` derived from `opened_at` and a missingness indicator for `u_symptom`.

Excluded and enforced by `FeatureSpec`: `assigned_to`, `resolved_by`, `closed_code`, `resolved_at`, `closed_at`, `reassignment_count`, `reopen_count`, `sys_mod_count`, `made_sla`. `assignment_group` is excluded as well — the audit found it already populated on 96.4% of first records, so it encodes a routing decision a human had already made.

## Method

- estimator: logistic regression on one-hot features, `C=1.0`, `min_frequency=20`, seed 20260910
- selection: roc_auc on the validation period only, over 9 candidates
- calibration: isotonic, fitted on the validation period, chosen before any test number was produced
- the locked test period was scored once, after the artifact was frozen

## Results

Precision and recall are at a 20% review capacity: the reviewer opens the riskiest fifth of the tickets.

### Validation period

| Model | ROC-AUC | PR-AUC | Brier | ECE | Mean predicted | Precision@20% | Recall@20% |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline (priority only) | 0.5469 | 0.2954 | 0.2146 | 0.1967 | 0.441 | 0.286 | 0.234 |
| logistic (uncalibrated) | 0.7472 | 0.5066 | 0.1735 | 0.1262 | 0.370 | 0.496 | 0.407 |
| logistic + isotonic on validation (shipped) | 0.7517 | 0.4965 | 0.1538 | 0.0000 | 0.244 | 0.504 | 0.414 |
| logistic + isotonic on train CV (sensitivity) | 0.7442 | 0.5017 | 0.1750 | 0.1341 | 0.378 | 0.506 | 0.415 |

Observed breach rate in this period: 24.4%.

The shipped model's calibration map was **fitted on this period**, so its validation ECE is in-sample and means nothing on its own. The test table below carries the honest calibration number.

### Test period

| Model | ROC-AUC | PR-AUC | Brier | ECE | Mean predicted | Precision@20% | Recall@20% |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline (priority only) | 0.5505 | 0.3020 | 0.2142 | 0.1974 | 0.442 | 0.294 | 0.241 |
| logistic (uncalibrated) | 0.7392 | 0.4896 | 0.1904 | 0.1664 | 0.411 | 0.493 | 0.404 |
| logistic + isotonic on validation (shipped) | 0.7383 | 0.4707 | 0.1608 | 0.0406 | 0.280 | 0.490 | 0.401 |
| logistic + isotonic on train CV (sensitivity) | 0.7385 | 0.4900 | 0.1894 | 0.1692 | 0.414 | 0.490 | 0.401 |

Observed breach rate in this period: 24.4%.

## Warm-up sensitivity (predeclared)

Declared in Phase 2A before the test period was scored: refit on training data with the log's first 21 days removed (cutoff `2016-03-21 01:16:00`, 5,629 rows), reusing the already-selected hyperparameters. The opening weeks run at 57.6% / 96.1% / 67.6% breach against 18-27% from mid-April on.

| Model | ROC-AUC | PR-AUC | Brier | ECE | Mean predicted | Precision@20% | Recall@20% |
|---|---:|---:|---:|---:|---:|---:|---:|
| warm-up excluded (test) | 0.7578 | 0.4987 | 0.1555 | 0.0307 | 0.265 | 0.510 | 0.418 |

## Known limitations

- The training period breaches at 44.2% and the test period at 24.4%. Any probability learned on the first is over-confident on the second; the ECE column is where that shows.
- UCI-498 carries no ticket text, so nothing here is comparable to the text classifiers in the surveyed literature.
- The label is a ServiceNow compliance flag, not a business judgement about whether the customer was harmed.
- The score is ticket-level. It says nothing about which agent should take the ticket; that comes from eligibility, load and projected finish in the dispatch policy.
- Priority 2 breaches more often than priority 1 in this log (97.1% against 80.5%). The model reproduces the data; it does not correct it.
