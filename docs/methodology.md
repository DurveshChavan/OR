# Methodology

**Status: skeleton.** Each section names the phase that owns it and fills as
that phase completes.

## 1. Problem statement
_(Phase 0 — pending final wording from `literature_gap_audit.md`)_

## 2. Data — COMPLETE

See `data_provenance.md`. Source, ordering rule, label audit, duration
definition and field exclusions are settled and evidenced in
`data/reports/uci498_audit.md`.

Key decisions already fixed:
- one feature row per incident, taken from the first ordered record only;
- `made_sla == False` on the final record is the breach label (latching flag,
  zero un-breaches across 24,918 incidents);
- service duration is `resolved_at - opened_at`; `closed_at` is rejected as a
  ~5-day auto-close artefact;
- `assignment_group` is excluded as prior-routing leakage.

## 3. Feature specification
_(Phase 2)_ One `FeatureSpec` object shared by preparation, training, prediction
and tests. Holds schema version, allowed columns, categorical/numeric/time
handling, missing-value treatment, forbidden columns and unknown-category
behaviour. Forbidden columns are rejected by validation, proven by test.

## 4. Risk model
_(Phase 2)_ Chronological 70/15/15 split by `opened_at`. Baseline is the
training-only empirical `P(breach | priority)`. Candidate is regularised
logistic regression with one-hot encoding and probability calibration.
Selection uses validation only; the test split stays locked until the artifact
is frozen. Report calibration, Brier score, ROC-AUC, PR-AUC, and
precision/recall at an explicitly stated review capacity.

Base rate is 38.28%, so this is not a rare-event problem — but PR-AUC is
reported alongside ROC-AUC regardless.

## 5. Duration model
_(Phase 2)_ Target `log1p(resolved_at - opened_at)`, inverse-transformed with a
tested `max(0, expm1(·))`. Compared against a train-only priority/category
median baseline. Report median absolute error, MAE and p90 absolute error on the
locked test period.

## 6. Dispatch policy
_(Phase 3)_ Tiered: P1 capacity reserved before P2–P4, then priority-specific
cost-per-minute rates. Overdue tickets move to an explicit recovery class and
cannot starve. Hungarian assignment runs per tier over eligible WIP slots, with
sorted IDs and a bounded deterministic epsilon for ties. All policy numbers are
visible manager-editable business inputs — no free `w1`/`w2`/`w3` weights.

Every recommendation stores its own candidate payload and the reason string
rendered from it; the client displays the stored reason and never regenerates
one.

## 7. Counterfactual replay
_(Phase 2)_ Exogenous job list built before any policy runs. Policies compared:
FIFO, priority-only, duration-first, SLA-risk-aware. Block bootstrap by arrival
day. Invariant tests prove no policy can read hidden outcome columns and that
model predictions cannot alter stored service demand.

## 8. Audit and reproducibility
_(Phases 1 and 3)_ Immutable recommendations; append-only events enforced by
database triggers in both PostgreSQL and SQLite; actor attribution on every
mutation; model and policy version snapshotted into every decision.

## 9. Operations Research appendix — retained
The legacy LP, transportation, Hungarian, Johnson sequencing, decision/game
theory, CPM-PERT and replacement modules stay runnable and hand-verifiable for
the oral examination. They are a section of the product rather than a separate demo, and the
replacement analysis is what the Hardware screen computes.
