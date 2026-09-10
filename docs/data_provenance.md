# Data provenance

Every dataset this project touches, where it came from, and what was done to it.
No number in the report may cite a source that is not listed here.

## UCI-498 — Incident management process enriched event log

| Field | Value |
|---|---|
| Source | UCI Machine Learning Repository, dataset 498 |
| URL | https://archive.ics.uci.edu/dataset/498/incident+management+process+enriched+event+log |
| Origin | ServiceNow incident management platform of an unnamed organisation, anonymised |
| Licence | CC BY 4.0 (confirm on the dataset page before publication) |
| Local cache | `data/incident_event_log.csv` (gitignored) |
| SHA-256 | recorded in `data/reports/uci498_audit.md` at audit time |
| Raw events | 141,712 |
| Unique incidents | 24,918 |
| Valid incidents after preparation | 23,323 |
| Coverage | March 2016 – (see audit report for exact opened_at range) |

### What the dataset does and does not contain

Contains: structured incident fields (priority, impact, urgency, category,
subcategory, location, contact type), anonymised actor and group identifiers,
lifecycle timestamps, an `made_sla` compliance flag, and per-event state.

**Does not contain: any ticket text.** There is no `description` or
`short_description` column. This is a hard structural property of the dataset and
it determines what tasks are possible — see `literature_gap_audit.md`.

### Preparation rules (fixed, audited)

1. Order each incident's rows by `(sys_updated_at, sys_mod_count, row_index)`,
   stable sort.
2. The **first** ordered row carrying a valid `opened_at` is the decision-time
   snapshot. It is the only legal source of model features.
3. The **last** ordered row supplies labels and outcome measurement only.
4. Exactly one feature row per incident.

### Label: `made_sla`

Audited and accepted. `made_sla` is a live compliance flag, so it changes value
during 36.6% of incident lifecycles — but the change is strictly **latching**:
every incident is `True`, `False`, or exactly one `True → False`. **Zero
incidents ever un-breach.** The final-record value is therefore a genuine
terminal outcome, and `made_sla == False` is a defensible incident-level breach
label.

Breach prevalence over valid incidents: **38.28%**. Not a rare-event problem.

| Priority | Breach rate | n |
|---|---:|---:|
| 1 – Critical | 80.54% | 185 |
| 2 – High | 97.11% | 311 |
| 3 – Moderate | 36.13% | 23,681 |
| 4 – Low | 14.89% | 732 |

Two features of this table must be stated in the report rather than smoothed
over. Priority 2 breaches *more often* than priority 1, which is not the
ordering a severity model would predict. And priority 3 is 95% of the dataset,
so any aggregate metric is effectively a priority-3 metric.

### Duration: `resolved_at`, not `closed_at`

`closed_at` was **rejected** as a completion timestamp. The gap
`closed_at − resolved_at` has an interquartile range of roughly 120.2h to 120.8h
— a fixed ~5-day auto-close timer, not a business event. Measured
`closed_at − opened_at`, 25.4% of incidents fall inside a single one-hour band.

Service duration is defined as **`resolved_at − opened_at`**, which shows the
spread a handling-time model needs (p25 ≈ 0.4h, p50 ≈ 22.2h). 1,556 incidents
have no `resolved_at` and are dropped, not imputed.

### Excluded fields and why

| Field | Status | Reason |
|---|---|---|
| `assignment_group` | **excluded** | Populated on 96.4% of first records — encodes a routing action a human already took. Using it lets the model read the answer it is meant to recommend. |
| `assigned_to`, `resolved_by`, `closed_code`, `resolved_at`, `closed_at` | forbidden | Resolution outcome. |
| `reassignment_count`, `reopen_count`, `sys_mod_count` | forbidden | Develop after the opening decision. |
| `made_sla` | label only | Never a feature. |

## Datasets deliberately NOT used

**Backblaze Drive Stats.** Out of scope. It has no ticket-level join to UCI-498,
so it cannot support any claim about ticket routing. It may only be revisited as
a separately labelled storage-asset appendix, and only if the project title
cannot be changed and every core gate is already green. See
`FINAL_IMPLEMENTATION.md` §L.

**The legacy synthetic universe.** The previous build sampled real distributions
into a randomly generated ticket/agent/workstation population. It is retained as
Operations Research viva material only and supplies no number in the v2 result.

## Regeneration

```
python -m api.app_v2.ingest.uci498 fetch     # -> data/manifests/uci498.json
python -m api.app_v2.ingest.uci498 audit     # -> data/reports/uci498_audit.md
python -m api.app_v2.ingest.uci498 prepare   # -> data/processed/uci498/incidents_v1.parquet
```

`fetch` adopts an existing local file and never re-downloads without `--force`:
a fresh pull could be a different snapshot, and its SHA-256 would then disagree
with the hash quoted in the audit report and in every model card. Phase 2
promoted this code out of `scripts/audit_uci498.py`; the audit output was
checked to be byte-identical afterwards apart from its generated-at line.

Raw and prepared data stay gitignored. The audit report and its CSV companions
are the committed evidence.
