"""UCI-498 ingestion: ``fetch`` the log, ``audit`` it, ``prepare`` incident rows.

    python -m api.servicedesk.ingest.uci498 fetch
    python -m api.servicedesk.ingest.uci498 audit
    python -m api.servicedesk.ingest.uci498 prepare

This is the promotion of ``scripts/audit_uci498.py`` that PHASE_2 calls for. The
audit logic and its ordering rule are carried over unchanged, because the
numbers it produced are already quoted in ``notes/phases/STATE.md`` and will be
cited in every model card; a rewrite that moved one of them would silently
invalidate prose that is already written. The new work here is ``fetch`` (hash
and manifest the raw file) and ``prepare`` (one row per incident, split
recorded, ready for training).

What the audit settled, and what this module therefore hard-codes:

  * label — ``made_sla == False`` on the final ordered record. The flag latches:
    of 24,918 incidents, 0 ever return from False to True.
  * duration — ``resolved_at - opened_at``. Never ``closed_at``: the
    resolve-to-close gap is a fixed ~5-day auto-close timer.
  * features — first ordered record only; ``assignment_group`` excluded.

Reads raw data. Writes only under ``data/processed/``, ``data/manifests/`` and
``data/reports/``. Raw data is never modified.
"""
import argparse
import hashlib
import io
import json
import os
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from api.servicedesk.ml.feature_spec import (
    AUDIT_GATED_FIELDS,
    CREATION_FIELDS,
    FORBIDDEN_FIELDS,
    INCIDENT_FEATURES_V1,
    ORDER_RULE,
)

RAW_DIR = os.path.join("data", "raw", "uci498")
#: The audited file. Its SHA-256 is quoted in data/reports/uci498_audit.md and
#: in every downstream manifest, so this path is not interchangeable with the
#: second copy under data/incident+management+process+enriched+event+log/.
RAW_PATH = os.path.join("data", "incident_event_log.csv")
REPORT_DIR = os.path.join("data", "reports")
REPORT_MD = os.path.join(REPORT_DIR, "uci498_audit.md")
PROCESSED_DIR = os.path.join("data", "processed", "uci498")
PROCESSED_PARQUET = os.path.join(PROCESSED_DIR, "incidents_v1.parquet")
PROCESSED_SCHEMA = os.path.join(PROCESSED_DIR, "incidents_v1.schema.json")
MANIFEST_PATH = os.path.join("data", "manifests", "uci498.json")

SOURCE_URL = "https://archive.ics.uci.edu/dataset/498/incident+management+process+enriched+event+log"
ZIP_URL = (
    "https://archive.ics.uci.edu/static/public/498/"
    "incident+management+process+enriched+event+log.zip"
)
CITATION = (
    "UCI ML Repository, dataset 498, *Incident management process enriched "
    "event log* (ServiceNow-derived, anonymised)."
)
LICENSE = "CC BY 4.0 (UCI Machine Learning Repository terms)"
#: Bumped whenever preparation semantics change, so a manifest identifies the
#: code that produced the parquet, not just the data that went in.
PREPARE_CODE_VERSION = "uci498-prepare-1"

#: Chronological split, fixed by the plan (§E.4) and by PHASE_2.
TRAIN_FRACTION = 0.70
VALIDATION_FRACTION = 0.15

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


# --------------------------------------------------------------------------
# fetch
# --------------------------------------------------------------------------

def write_manifest(digest, raw_events, unique_incidents, prepared=None,
                   split_boundaries=None):
    """Record where the data came from and what was built from it.

    Every field the plan asks for (§ "Data manifests and model cards") lives
    here, including the SHA-256 that model cards cite back to.
    """
    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
    manifest = {
        "source_url": SOURCE_URL,
        "archive_url": ZIP_URL,
        "citation": CITATION,
        "license": LICENSE,
        "local_path": RAW_PATH.replace(os.sep, "/"),
        "sha256": digest,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "raw_events": int(raw_events),
        "unique_incidents": int(unique_incidents),
        "prepare_code_version": PREPARE_CODE_VERSION,
        "feature_schema_version": INCIDENT_FEATURES_V1.version,
        "label_definition": "made_sla == False on the final ordered record",
        "duration_definition": "resolved_at - opened_at (closed_at rejected: ~5-day auto-close timer)",
        "ordering_rule": list(ORDER_RULE),
    }
    if prepared is not None:
        manifest["prepared_incidents"] = int(prepared)
    if split_boundaries is not None:
        manifest.update(split_boundaries)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    return manifest


def fetch(force=False):
    """Make sure the raw log is present locally, then hash and manifest it.

    An existing valid file is adopted, never re-downloaded. A fresh pull from
    UCI could be a different snapshot, and its SHA-256 would then disagree with
    the hash already quoted in the audit report, the manifests and the model
    cards. ``--force`` is the only path that downloads, and it is a deliberate
    act of re-basing every one of those documents.
    """
    if os.path.exists(RAW_PATH) and not force:
        digest = sha256(RAW_PATH)
        df = pd.read_csv(RAW_PATH, na_values="?", low_memory=False, usecols=["number"])
        manifest = write_manifest(digest, len(df), df["number"].nunique())
        print(f"adopted existing {RAW_PATH}")
        print(f"sha256={digest}")
        print(f"raw events={len(df):,} incidents={df['number'].nunique():,}")
        print(f"wrote {MANIFEST_PATH}")
        return manifest

    os.makedirs(RAW_DIR, exist_ok=True)
    print(f"downloading {ZIP_URL}")
    raw = urllib.request.urlopen(ZIP_URL).read()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = [n for n in archive.namelist() if n.endswith(".csv")]
        if not names:
            sys.exit("archive contains no CSV; UCI may have changed the packaging")
        with archive.open(names[0]) as member:
            payload = member.read()
    target = os.path.join(RAW_DIR, "incident_event_log.csv")
    with open(target, "wb") as fh:
        fh.write(payload)

    df = pd.read_csv(target, na_values="?", low_memory=False)
    required = {"number", "opened_at", "made_sla", "sys_updated_at", "sys_mod_count"}
    missing = required - set(df.columns)
    if missing:
        sys.exit(f"downloaded CSV is missing required column(s): {sorted(missing)}")

    digest = sha256(target)
    print(f"wrote {target}")
    print(f"sha256={digest}")
    print(
        "NOTE: this file is at data/raw/uci498/. The audited path is "
        f"{RAW_PATH}; every document citing a SHA-256 must be re-based before "
        "the new file is used."
    )
    return write_manifest(digest, len(df), df["number"].nunique())


# --------------------------------------------------------------------------
# prepare
# --------------------------------------------------------------------------

def assign_chronological_split(valid, train_fraction=TRAIN_FRACTION,
                               validation_fraction=VALIDATION_FRACTION):
    """Label each incident train / validation / test by ``opened_at`` order.

    The cut is taken at a row index and then pushed forward to the end of the
    tied timestamp, so one ``opened_at`` value never straddles two splits. That
    makes the split reproducible from the two recorded boundary timestamps
    alone — which is what model cards and replay fixtures cite, rather than a
    percentage that a later run might round differently.
    """
    ordered = valid.sort_values(["opened_at", "incident_id"], kind="mergesort")
    opened = ordered["opened_at"].to_numpy()
    n = len(ordered)

    def cut(index):
        if index >= n:
            return n
        boundary = opened[index - 1] if index > 0 else opened[0]
        # advance past every row sharing the boundary timestamp
        return int(np.searchsorted(opened, boundary, side="right"))

    train_end = cut(int(n * train_fraction))
    validation_end = cut(int(n * (train_fraction + validation_fraction)))

    split = np.empty(n, dtype=object)
    split[:train_end] = "train"
    split[train_end:validation_end] = "validation"
    split[validation_end:] = "test"
    ordered = ordered.assign(split=split)

    def at(i):
        # A split can be empty on a small fixture; report that as null rather
        # than raising, so the boundaries stay inspectable either way.
        return str(opened[i]) if 0 <= i < n else None

    boundaries = {
        "train_end_opened_at": at(train_end - 1),
        "validation_start_opened_at": at(train_end),
        "validation_end_opened_at": at(validation_end - 1),
        "test_start_opened_at": at(validation_end),
        "split_counts": {
            "train": int(train_end),
            "validation": int(validation_end - train_end),
            "test": int(n - validation_end),
        },
    }
    return ordered, boundaries


def prepare(raw_path=RAW_PATH, write=True):
    """Build exactly one feature row per valid incident.

    Features come from the first ordered record; label and duration come from
    the final one. Nothing on the forbidden list survives into the output, and
    ``FeatureSpec.validate_frame`` is called on the result so that the file
    itself, not just the training script, is proven clean.
    """
    df = load_raw(raw_path)
    ordered = df.sort_values(list(ORDER_RULE), kind="mergesort")
    grouped = ordered.groupby("number", sort=False)
    first = grouped.head(1).set_index("number")
    final = grouped.tail(1).set_index("number")

    sla_final = normalise_sla(final["made_sla"])
    opened = first["opened_at"]
    resolved = final["resolved_at"]
    duration = (resolved - opened).dt.total_seconds() / 60.0

    # Every column is assigned onto one index (the incident number), so first-
    # record and final-record values cannot drift out of alignment. Building the
    # frame from a dict of differently-indexed Series silently reorders rows and
    # pairs a ticket's features with another ticket's label.
    incidents = pd.DataFrame(index=first.index)
    incidents["incident_id"] = first.index.astype(str)
    incidents["opened_at"] = opened
    for col in INCIDENT_FEATURES_V1.categorical:
        incidents[col] = first[col] if col in first.columns else pd.NA
    made_sla = sla_final.astype("boolean")
    incidents["label_breach"] = ~made_sla
    incidents["duration_minutes"] = duration
    incidents["_resolved_at"] = resolved

    valid = incidents[
        incidents["opened_at"].notna()
        & incidents["_resolved_at"].notna()
        & incidents["label_breach"].notna()
        & (incidents["duration_minutes"] > 0)
    ].copy()
    valid = valid.drop(columns=["_resolved_at"]).reset_index(drop=True)
    valid["label_breach"] = valid["label_breach"].astype(bool)

    prepared, boundaries = assign_chronological_split(valid)
    prepared = prepared.reset_index(drop=True)

    # The invariants the plan states as asserts, kept as asserts.
    assert prepared["incident_id"].is_unique, "preparation produced duplicate incidents"
    INCIDENT_FEATURES_V1.validate_frame(prepared)

    if not write:
        return prepared, boundaries

    os.makedirs(PROCESSED_DIR, exist_ok=True)
    prepared.to_parquet(PROCESSED_PARQUET, index=False)

    digest = sha256(raw_path)
    schema = {
        "prepared_file": PROCESSED_PARQUET.replace(os.sep, "/"),
        "prepare_code_version": PREPARE_CODE_VERSION,
        "source_sha256": digest,
        "source_path": raw_path.replace(os.sep, "/"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "incident_count": int(len(prepared)),
        "label_column": "label_breach",
        "label_definition": "made_sla == False on the final ordered record",
        "label_prevalence": float(prepared["label_breach"].mean()),
        # Recorded because it is large and it constrains how the risk model may
        # be reported: the breach rate falls from 44% in the training period to
        # 24% in the locked test period. A chronological split does not hide
        # that drift, it exposes it.
        "label_prevalence_by_split": {
            str(k): float(v)
            for k, v in prepared.groupby("split")["label_breach"].mean().items()
        },
        # Weekly prevalence is recorded because the split-level number hides
        # where the shift happens: the first three weeks of the log run at
        # 56% / 96% / 66% breach and the rate settles near 21-25% from
        # mid-April on. Any claim about model calibration on the locked test
        # period has to be read against this table.
        "label_prevalence_by_open_week": {
            str(k): {"n": int(v["n"]), "breach_rate": float(v["breach_rate"])}
            for k, v in prepared.assign(
                _week=prepared["opened_at"].dt.to_period("W").astype(str)
            ).groupby("_week")["label_breach"].agg(
                n="size", breach_rate="mean"
            ).iterrows()
        },
        "duration_column": "duration_minutes",
        "duration_definition": "resolved_at - opened_at, minutes",
        "ordering_rule": list(ORDER_RULE),
        "split": boundaries,
        "feature_spec": INCIDENT_FEATURES_V1.as_dict(),
        "dtypes": {c: str(t) for c, t in prepared.dtypes.items()},
    }
    with open(PROCESSED_SCHEMA, "w", encoding="utf-8") as fh:
        json.dump(schema, fh, indent=2, sort_keys=True)

    write_manifest(
        digest, len(df), df["number"].nunique(),
        prepared=len(prepared), split_boundaries={"split": boundaries},
    )

    print(f"wrote {PROCESSED_PARQUET} ({len(prepared):,} incidents)")
    print(f"wrote {PROCESSED_SCHEMA}")
    print(f"wrote {MANIFEST_PATH}")
    counts = boundaries["split_counts"]
    print(
        "split: train={train:,} validation={validation:,} test={test:,}".format(**counts)
    )
    print(f"train ends {boundaries['train_end_opened_at']} | "
          f"test starts {boundaries['test_start_opened_at']}")
    print(f"breach prevalence={prepared['label_breach'].mean() * 100:.2f}%")
    return prepared, boundaries


# --------------------------------------------------------------------------
# audit
# --------------------------------------------------------------------------

def audit():
    if not os.path.exists(RAW_PATH):
        sys.exit(f"raw log not found at {RAW_PATH}; run `fetch` first")
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
      f"by `api/servicedesk/ingest/uci498.py audit`.\n")
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    fetch_parser = sub.add_parser("fetch", help="hash and manifest the raw log")
    fetch_parser.add_argument(
        "--force", action="store_true",
        help="download a fresh copy even if a local file exists (re-bases every "
             "document that cites the current SHA-256)",
    )
    sub.add_parser("audit", help="regenerate data/reports/uci498_audit.md")
    sub.add_parser("prepare", help="write one feature row per valid incident")

    args = parser.parse_args(argv)
    if args.command == "fetch":
        fetch(force=args.force)
    elif args.command == "audit":
        audit()
    else:
        prepare()


if __name__ == "__main__":
    main()
