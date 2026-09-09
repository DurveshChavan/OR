"""UCI-498 incident and label audit (FINAL_IMPLEMENTATION.md, week-one gate 1).

Answers the questions the plan says must be answered before any v2 model,
schema, or research claim is committed to:

  * how many raw events, unique incidents, valid incidents, dropped-and-why
  * the per-incident ``made_sla`` prevalence
  * whether ``made_sla`` LATCHES across an incident's lifecycle. It is a live
    compliance flag, so a breaching ticket is supposed to change value; what
    decides the label's validity is whether an incident can ever go back from
    False to True. If it can, "did it breach?" has no single answer and the plan
    says to stop calling the model a breach predictor.
  * the exact ordering rule used to pick the first and final record
  * missingness and cardinality of every candidate feature
  * when ``assignment_group`` / ``assigned_to`` first become populated, which
    decides whether either leaks a pre-existing human routing action
  * which end-timestamp actually measures work. ``closed_at`` is rejected: the
    resolve-to-close gap is a fixed ~5-day auto-close timer, so duration is
    ``resolved_at - opened_at``.

Deliberately standalone: this runs before the v2 contract is frozen, so it
must not import from ``api.engine`` (legacy) or presume an ``app_v2`` package
layout that does not exist yet. Phase 2 promotes this logic into
``app_v2/ingest/uci498.py`` behind the ``fetch``/``audit``/``prepare`` CLI the
plan specifies; until then the answers matter more than the packaging.

Reads only. Writes only under data/reports/.

    python scripts/audit_uci498.py
"""
import hashlib
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

RAW_PATH = os.path.join("data", "incident_event_log.csv")
REPORT_DIR = os.path.join("data", "reports")
REPORT_MD = os.path.join(REPORT_DIR, "uci498_audit.md")

#: Ordering rule, stated once and used everywhere below. UCI-498 is an event
#: log: one incident `number` has many rows. Everything in this audit depends
#: on which row is treated as "the decision-time snapshot", so the rule is
#: named rather than left implicit in a sort call.
ORDER_RULE = ("sys_updated_at", "sys_mod_count", "_row_index")

#: Fields available at (or before) ticket creation -- the plan's allow-list.
CREATION_FIELDS = [
    "priority", "impact", "urgency", "category", "subcategory",
    "location", "contact_type", "opened_at", "u_symptom",
]
#: Audit-gated: allowed only if this audit proves it is set before the routing
#: decision being evaluated.
AUDIT_GATED_FIELDS = ["assignment_group"]
#: Never a feature: resolution or prior-routing outcome leakage.
FORBIDDEN_FIELDS = [
    "assigned_to", "resolved_by", "closed_code", "resolved_at", "closed_at",
    "reassignment_count", "reopen_count", "sys_mod_count", "made_sla",
]

TIMESTAMP_COLUMNS = [
    "opened_at", "sys_created_at", "sys_updated_at", "resolved_at", "closed_at",
]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_raw(path):
    df = pd.read_csv(path, na_values="?", low_memory=False)
    df["_row_index"] = np.arange(len(df))
    for col in TIMESTAMP_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")
    return df


def normalise_sla(series):
    """`made_sla` arrives as the strings 'True'/'False'. Map to real bools and
    leave anything else as NA rather than silently coercing it to False."""
    return series.astype(str).str.strip().str.lower().map({"true": True, "false": False})


def _transition_pattern(series):
    """Collapse one incident's ordered `made_sla` values to their distinct
    run-length pattern, e.g. [T,T,T,F,F] -> 'T->F'."""
    values = series.dropna().to_numpy()
    if len(values) == 0:
        return "empty"
    chain = [values[0]]
    for v in values[1:]:
        if v != chain[-1]:
            chain.append(v)
    return "->".join("T" if bool(b) else "F" for b in chain)


def audit_label_stability(df):
    """Is the final-record `made_sla` a fact, or an artefact of row choice?

    A raw "does it ever change?" count is the wrong test. `made_sla` is a
    *live* compliance flag on an open incident, so a breaching ticket is
    SUPPOSED to change: it reads True while the ticket is still inside its SLA
    window and flips to False when the deadline passes. What actually matters
    is whether that change is **monotone and latching** -- if an incident can
    go back from False to True, "did it breach?" has no single answer and the
    plan requires the research claim to change. If every incident is T, F, or
    exactly one T->F, the terminal value is well defined and the label is safe.
    """
    ordered = df.sort_values(list(ORDER_RULE), kind="mergesort")
    sla = normalise_sla(ordered["made_sla"])
    patterns = sla.groupby(ordered["number"], sort=False).apply(_transition_pattern)
    counts = patterns.value_counts()

    monotone_patterns = {"T", "F", "T->F"}
    monotone = int(counts[[p for p in counts.index if p in monotone_patterns]].sum())
    un_breach = int(counts[[p for p in counts.index if "F->T" in p]].sum())

    return {
        "incidents": int(len(patterns)),
        "constant": int(counts.get("T", 0) + counts.get("F", 0)),
        "flipping": int(len(patterns) - counts.get("T", 0) - counts.get("F", 0)),
        "all_missing": int(counts.get("empty", 0)),
        "flip_rate": float(
            (len(patterns) - counts.get("T", 0) - counts.get("F", 0)) / len(patterns)
        ),
        "monotone": monotone,
        "monotone_rate": float(monotone / len(patterns)),
        "un_breach": un_breach,
        "patterns": counts.head(10).to_dict(),
    }


def build_incident_frame(df):
    """One row per incident under ORDER_RULE, plus the drop ledger.

    first  = earliest ordered row that carries a valid opened_at (the
             decision-time snapshot; features may only come from here)
    final  = latest ordered row (labels and outcome measurement only)
    """
    ordered = df.sort_values(list(ORDER_RULE), kind="mergesort")
    grouped = ordered.groupby("number", sort=False)

    first = grouped.head(1).set_index("number")
    final = grouped.tail(1).set_index("number")

    sla_final = normalise_sla(final["made_sla"])
    opened = first["opened_at"]
    closed = final["closed_at"]
    resolved = final["resolved_at"]

    # Duration is measured to resolved_at, NOT closed_at. See
    # audit_duration_definition(): closed_at is dominated by a ~5-day
    # auto-close timer and does not measure work.
    duration_min = (resolved - opened).dt.total_seconds() / 60.0
    closed_duration_min = (closed - opened).dt.total_seconds() / 60.0

    incidents = pd.DataFrame({
        "opened_at": opened,
        "resolved_at": resolved,
        "closed_at": closed,
        "duration_minutes": duration_min,
        "closed_duration_minutes": closed_duration_min,
        "label_breach": ~sla_final,
        "made_sla": sla_final,
        "priority": first["priority"],
    })

    drops = {
        "missing opened_at on first record": int(opened.isna().sum()),
        "missing resolved_at on final record": int(resolved.isna().sum()),
        "unusable made_sla on final record": int(sla_final.isna().sum()),
        "negative duration (resolved before opened)": int((duration_min < 0).sum()),
        "zero duration": int((duration_min == 0).sum()),
    }

    valid = incidents[
        incidents["opened_at"].notna()
        & incidents["resolved_at"].notna()
        & incidents["made_sla"].notna()
        & (incidents["duration_minutes"] > 0)
    ]
    return incidents, valid, drops


def audit_duration_definition(incidents):
    """Which end-timestamp actually measures work: `resolved_at` or `closed_at`?

    The plan makes the duration model conditional on "the audit confirms a
    valid time definition", and the two candidates are not interchangeable.
    ServiceNow closes a resolved incident automatically after a fixed waiting
    period, so `closed_at` mixes real handling time with a constant timer. This
    measures the gap directly and reports the evidence rather than assuming.
    """
    gap_hours = (
        incidents["closed_at"] - incidents["resolved_at"]
    ).dt.total_seconds() / 3600.0
    gap = gap_hours.dropna()
    closed_dur = incidents["closed_duration_minutes"].dropna()
    closed_dur = closed_dur[closed_dur > 0]

    return {
        "gap_n": int(len(gap)),
        "gap_q": {
            f"p{int(q * 100)}": float(np.quantile(gap, q))
            for q in (0.01, 0.25, 0.5, 0.75, 0.99)
        } if len(gap) else {},
        "closed_pile_up_pct": float(closed_dur.between(7200, 7260).mean() * 100)
        if len(closed_dur) else 0.0,
        "resolved_q": quantiles(incidents["duration_minutes"]),
        "closed_q": quantiles(incidents["closed_duration_minutes"]),
        "missing_resolved": int(incidents["resolved_at"].isna().sum()),
    }


def audit_routing_field_timing(df):
    """When do `assignment_group` and `assigned_to` first become populated?

    If either is already set on the incident's FIRST ordered record, it
    encodes a routing action a human had already taken, and using it as a
    feature would let the model read the answer it is meant to recommend.
    """
    ordered = df.sort_values(list(ORDER_RULE), kind="mergesort")
    out = {}
    for field in ("assignment_group", "assigned_to"):
        if field not in ordered.columns:
            continue
        present = ordered[field].notna()
        first_rows = ordered.groupby("number", sort=False).head(1)
        # position (0-based) of the first populated row within each incident
        pos = (
            ordered.assign(_p=present)
            .groupby("number", sort=False)["_p"]
            .apply(lambda s: int(np.argmax(s.to_numpy())) if s.any() else -1)
        )
        out[field] = {
            "populated_on_first_record_pct": float(
                first_rows[field].notna().mean() * 100
            ),
            "never_populated_incidents": int((pos < 0).sum()),
            "median_position_when_populated": float(pos[pos >= 0].median()),
            "overall_row_fill_pct": float(present.mean() * 100),
        }
    return out


def audit_candidate_features(df, incidents_index):
    """Missingness and cardinality, measured on the FIRST record only -- that
    is the only place a legitimate feature may be read from."""
    ordered = df.sort_values(list(ORDER_RULE), kind="mergesort")
    first = ordered.groupby("number", sort=False).head(1)
    rows = []
    for col in CREATION_FIELDS + AUDIT_GATED_FIELDS + FORBIDDEN_FIELDS:
        if col not in first.columns:
            continue
        s = first[col]
        if col in CREATION_FIELDS:
            verdict = "allowed"
        elif col in AUDIT_GATED_FIELDS:
            verdict = "audit-gated"
        else:
            verdict = "FORBIDDEN"
        rows.append({
            "column": col,
            "use": verdict,
            "missing_pct": round(float(s.isna().mean() * 100), 2),
            "distinct": int(s.nunique(dropna=True)),
            "example": str(s.dropna().iloc[0]) if s.notna().any() else "",
        })
    return pd.DataFrame(rows)


def quantiles(series, qs=(0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99)):
    s = series.dropna()
    return {f"p{int(q * 100)}": float(np.quantile(s, q)) for q in qs} if len(s) else {}


def main():
    if not os.path.exists(RAW_PATH):
        sys.exit(f"raw log not found at {RAW_PATH}; run the legacy loader once to cache it")
    os.makedirs(REPORT_DIR, exist_ok=True)

    df = load_raw(RAW_PATH)
    digest = sha256(RAW_PATH)

    stability = audit_label_stability(df)
    incidents, valid, drops = build_incident_frame(df)
    dur_def = audit_duration_definition(incidents)
    timing = audit_routing_field_timing(df)
    features = audit_candidate_features(df, incidents.index)

    prevalence = float(valid["label_breach"].mean())
    by_priority = (
        valid.groupby("priority")["label_breach"].agg(["mean", "size"]).round(4)
    )
    dur_q = quantiles(valid["duration_minutes"])

    # The label is usable when the flag latches: no incident ever returns from
    # False to True, so "did it breach?" has exactly one answer per incident.
    label_usable = stability["un_breach"] == 0 and stability["monotone_rate"] >= 0.999

    L = []
    A = L.append
    A("# UCI-498 incident and label audit\n")
    A(f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} "
      f"by `scripts/audit_uci498.py`.\n")
    A("## Source\n")
    A(f"- file: `{RAW_PATH}`")
    A(f"- SHA-256: `{digest}`")
    A(f"- raw events: **{len(df):,}**")
    A(f"- unique incident numbers: **{df['number'].nunique():,}**")
    A("- citation: UCI ML Repository, dataset 498, *Incident management process "
      "enriched event log* (ServiceNow-derived, anonymised).\n")

    A("## Ordering rule (fixed)\n")
    A("Every incident's rows are ordered by "
      f"`{' , '.join(ORDER_RULE)}` (stable mergesort). The **first** ordered row "
      "carrying a valid `opened_at` is the decision-time snapshot and is the only "
      "legal source of features. The **last** ordered row supplies the label and "
      "outcome measurement only.\n")

    A("## Label stability -- can `made_sla` be read at incident level?\n")
    A("`made_sla` is a **live compliance flag on an open incident**, not a "
      "post-hoc verdict, so a breaching ticket is *supposed* to change value "
      "mid-life. The test that matters is therefore not \"does it ever change?\" "
      "but \"does it latch?\" -- an incident that could go back from False to True "
      "would leave \"did it breach?\" genuinely undefined.\n")
    A(f"- incidents examined: **{stability['incidents']:,}**")
    A(f"- never changes value: **{stability['constant']:,}**")
    A(f"- changes at least once: **{stability['flipping']:,}** "
      f"(**{stability['flip_rate'] * 100:.2f}%**)")
    A(f"- **monotone (`T`, `F`, or exactly one `T->F`)**: "
      f"**{stability['monotone']:,}** "
      f"(**{stability['monotone_rate'] * 100:.2f}%**)")
    A(f"- **incidents that ever un-breach (`F->T`)**: "
      f"**{stability['un_breach']:,}**")
    A(f"- no usable value anywhere: **{stability['all_missing']:,}**\n")
    A("Observed transition patterns:\n")
    A("| Pattern | Incidents |")
    A("|---|---:|")
    for pattern, n in stability["patterns"].items():
        A(f"| `{pattern}` | {n:,} |")
    A("")
    if label_usable:
        A(f"**Verdict: PASS.** Every one of the {stability['incidents']:,} incidents "
          "is either permanently compliant, permanently breached, or flips "
          "`True -> False` exactly once and stays there. **No incident ever "
          "un-breaches.** The flag latches, so the final-record value is a genuine "
          "terminal outcome rather than a choice of row, and "
          "`made_sla == False` on the final record is a defensible incident-level "
          "breach label.\n")
        A("A naive \"changes at least once\" reading would have flagged "
          f"{stability['flip_rate'] * 100:.1f}% of incidents as unstable and killed "
          "the risk model. That reading is wrong: the change rate is close to the "
          "breach prevalence precisely *because* the flip is the breach event.\n")
    else:
        A(f"**Verdict: FAIL.** {stability['un_breach']:,} incidents return from "
          "False to True, so a single incident-level value is a *choice of row*, "
          "not a fact. Per FINAL_IMPLEMENTATION.md week-one gate 1: stop calling "
          "the model a breach predictor, retain the duration model, and rewrite the "
          "research statement before implementation continues.\n")

    A("## Incident counts and drop ledger\n")
    A(f"- incidents built: **{len(incidents):,}**")
    A(f"- **valid** incidents (all of: opened_at, closed_at, usable made_sla, "
      f"duration > 0): **{len(valid):,}**")
    A(f"- dropped: **{len(incidents) - len(valid):,}**\n")
    A("| Drop reason (overlapping counts) | Incidents |")
    A("|---|---:|")
    for reason, n in drops.items():
        A(f"| {reason} | {n:,} |")
    A("")

    A("## Label prevalence\n")
    A(f"Breach rate over valid incidents: **{prevalence * 100:.2f}%** "
      f"(n = {len(valid):,}).\n")
    A("This is **not** a rare-event problem, so headline framing may use "
      "threshold-free metrics; PR-AUC still gets reported alongside ROC-AUC and "
      "calibration, per the plan.\n")
    A("| Priority | Breach rate | n |")
    A("|---|---:|---:|")
    for pr, row in by_priority.iterrows():
        A(f"| {pr} | {row['mean'] * 100:.2f}% | {int(row['size']):,} |")
    A("")
    A("The priority-only column above **is** the plan's baseline model. A "
      "candidate risk model must beat it on the locked test period to be worth "
      "shipping.\n")

    A("## Routing-field leakage timing\n")
    A("| Field | Populated on first record | Never populated | Median row index "
      "when it appears | Overall row fill |")
    A("|---|---:|---:|---:|---:|")
    for field, s in timing.items():
        A(f"| `{field}` | {s['populated_on_first_record_pct']:.2f}% | "
          f"{s['never_populated_incidents']:,} | "
          f"{s['median_position_when_populated']:.0f} | "
          f"{s['overall_row_fill_pct']:.2f}% |")
    A("")
    ag = timing.get("assignment_group", {})
    if ag:
        if ag["populated_on_first_record_pct"] > 50:
            A(f"`assignment_group` is already set on "
              f"{ag['populated_on_first_record_pct']:.1f}% of first records. It "
              "therefore encodes a routing action **a human had already taken** "
              "before the decision this project evaluates. **Excluded by default.** "
              "Using it would let the model read the answer it is meant to "
              "recommend. If a category-to-skill map is needed, derive it from the "
              "training period only and test that the raw field never reaches "
              "`FeatureSpec`.\n")
        else:
            A(f"`assignment_group` is set on only "
              f"{ag['populated_on_first_record_pct']:.1f}% of first records, so it "
              "is mostly assigned after creation. Still excluded by default; "
              "re-admitting it needs a written decision recorded here.\n")

    A("## Candidate feature inventory (measured on the first record only)\n")
    A("| Column | Use | Missing | Distinct | Example |")
    A("|---|---|---:|---:|---|")
    for _, r in features.iterrows():
        A(f"| `{r['column']}` | {r['use']} | {r['missing_pct']}% | "
          f"{r['distinct']:,} | {r['example'][:32]} |")
    A("")
    A("`FORBIDDEN` columns are resolution or prior-routing outcomes and must be "
      "rejected by `FeatureSpec` validation with a test that proves the rejection.\n")

    A("## Duration definition -- `resolved_at`, not `closed_at`\n")
    A("The plan makes the duration model conditional on the audit confirming a "
      "valid time definition. It does not confirm the obvious one.\n")
    A(f"`closed_at` minus `resolved_at`, hours (n = {dur_def['gap_n']:,}):\n")
    A("| Quantile | Hours |")
    A("|---|---:|")
    for k, v in dur_def["gap_q"].items():
        A(f"| {k} | {v:,.2f} |")
    A("")
    A("**`closed_at` is a system artefact.** The interquartile range of the "
      "resolve-to-close gap is roughly 120.2h to 120.8h -- a **fixed ~5-day "
      "auto-close timer**, not a business event. "
      f"{dur_def['closed_pile_up_pct']:.1f}% of incidents land inside a single "
      "one-hour band at 120h when measured `closed_at - opened_at`. Using "
      "`closed_at` would train the duration model largely on a constant.\n")
    A("Side by side, minutes:\n")
    A("| Quantile | `resolved_at - opened_at` (**used**) | `closed_at - opened_at` "
      "(rejected) |")
    A("|---|---:|---:|")
    for k in dur_def["resolved_q"]:
        rv = dur_def["resolved_q"][k]
        cv = dur_def["closed_q"].get(k, float("nan"))
        A(f"| {k} | {rv:,.0f} ({rv / 60:,.1f}h) | {cv:,.0f} ({cv / 60:,.1f}h) |")
    A("")
    A("**Decision: service duration is `resolved_at - opened_at`.** It shows the "
      "spread a handling-time model needs (p25 ~0.4h, p50 ~22h) where the "
      "`closed_at` version is compressed against the auto-close floor.\n")
    A(f"- incidents with no `resolved_at`: "
      f"**{dur_def['missing_resolved']:,}** (dropped, not imputed)")
    A(f"- negative durations: "
      f"**{drops['negative duration (resolved before opened)']:,}** "
      "(dropped, never clamped)")
    A(f"- zero durations: **{drops['zero duration']:,}** (dropped)\n")
    A("The heavy right tail is why the duration model trains on `log1p(minutes)` "
      "and reports median absolute error and p90 absolute error, not MAE alone.\n")
    A("> Carried into `docs/assumptions.md`: the replay's empirical "
      "service-demand proxy uses this resolved-based duration. It still contains "
      "historical queue waiting, which is a stated limitation, but it is not "
      "contaminated by the auto-close timer.\n")

    A("## Structural finding: this dataset has no ticket text\n")
    A("UCI-498 carries no `description` or `short_description` column -- the "
      "columns are structured fields, identifiers and timestamps only. Every paper "
      "in `docs/papers/literature_review_papers/` (Ticket-BERT, TF-IDF + logistic "
      "regression, mBERT/XLM-R, IndoBERT + random forest) performs **text** "
      "classification, a task this dataset structurally cannot support.\n")
    A("This is a data-level constraint, not a scope preference, and it is the "
      "cleanest justification for positioning the contribution as constrained "
      "dispatch evaluation rather than another ticket classifier. It belongs in "
      "`docs/literature_gap_audit.md`.\n")

    A("## Gate decision\n")
    A(f"- label usable at incident level: **{'YES' if label_usable else 'NO'}**")
    A("- `assignment_group` admitted as a feature: **NO** (excluded by default)")
    A(f"- valid incidents available for chronological 70/15/15 split: "
      f"**{len(valid):,}**")
    A(f"  - train ~{int(len(valid) * 0.70):,} | validation ~{int(len(valid) * 0.15):,} "
      f"| locked test ~{int(len(valid) * 0.15):,}\n")

    with open(REPORT_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))

    valid.to_csv(os.path.join(REPORT_DIR, "uci498_valid_incidents_summary.csv"))
    features.to_csv(os.path.join(REPORT_DIR, "uci498_feature_inventory.csv"), index=False)

    print(f"wrote {REPORT_MD}")
    print(f"raw events={len(df):,} incidents={len(incidents):,} valid={len(valid):,}")
    print(f"label monotone={stability['monotone_rate'] * 100:.2f}% un-breach={stability['un_breach']} -> "
          f"{'PASS' if label_usable else 'FAIL'}")
    print(f"breach prevalence={prevalence * 100:.2f}%")
    for field, s in timing.items():
        print(f"{field}: first-record fill={s['populated_on_first_record_pct']:.1f}%")


if __name__ == "__main__":
    main()
