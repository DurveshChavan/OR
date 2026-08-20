"""M0 — data layer.

Loads UCI dataset 498 (Incident management process enriched event log),
cleans it into a tidy ticket table, generates a seeded synthetic
ticket/agent/workstation universe fitted to that real data when available,
and derives the empirical distributions/rates M1-M7 use in place of
hardcoded constants (see derive_* below; pipeline.py's CONFIG dict is the
only place a magic number is still allowed to live, and only when nothing
in this dataset can supply it -- each such CONFIG entry carries a comment
saying why).
No OR technique here; this only feeds M1-M7.
"""
import os
import io
import zipfile
import urllib.request

import numpy as np
import pandas as pd

SKILL_GROUPS = ["network", "hardware", "software", "database", "access"]
WORKSTATION_TYPES = ["desktop", "laptop"]

UCI_ZIP_URL = (
    "https://archive.ics.uci.edu/static/public/498/"
    "incident+management+process+enriched+event+log.zip"
)


def load_incident_log(cache_dir="data"):
    """Load UCI dataset 498 as a raw DataFrame.

    Dataset 498 is zip-hosted, so ucimlrepo may return an empty/None
    frame for it. Strategy: local cache -> ucimlrepo API -> direct zip
    download from the UCI archive. Result is cached to
    <cache_dir>/incident_event_log.csv so later calls are offline.
    """
    os.makedirs(cache_dir, exist_ok=True)
    local_csv = os.path.join(cache_dir, "incident_event_log.csv")
    if os.path.exists(local_csv):
        return pd.read_csv(local_csv, na_values="?", low_memory=False)

    try:
        from ucimlrepo import fetch_ucirepo
        ds = fetch_ucirepo(id=498)
        df = ds.data.original
        if df is not None and len(df) > 0:
            df.to_csv(local_csv, index=False)
            return df
    except Exception:
        pass

    raw = urllib.request.urlopen(UCI_ZIP_URL).read()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = [n for n in z.namelist() if n.endswith(".csv")][0]
        df = pd.read_csv(z.open(name), na_values="?", low_memory=False)
    df.to_csv(local_csv, index=False)
    return df


def clean_incidents(df):
    """Clean a raw incident log into the tidy subset M0 exposes downstream.

    resolution_minutes = (resolved_at - opened_at) in minutes; rows where
    this is null or negative are dropped (bad/missing timestamps).
    made_sla is normalised to a real bool; priority strings like
    "1 - High" are reduced to their leading integer. `location` and the
    three raw timestamps (opened_at, updated_at = sys_updated_at,
    resolved_at) are kept as datetimes -- the derive_* functions below
    need them for region volumes and stage-duration estimates.
    """
    out = df.copy()
    out["opened_at"] = pd.to_datetime(out["opened_at"], dayfirst=True, errors="coerce")
    out["resolved_at"] = pd.to_datetime(out["resolved_at"], dayfirst=True, errors="coerce")
    out["updated_at"] = pd.to_datetime(out["sys_updated_at"], dayfirst=True, errors="coerce")

    out["resolution_minutes"] = (
        out["resolved_at"] - out["opened_at"]
    ).dt.total_seconds() / 60.0
    out = out[out["resolution_minutes"].notna() & (out["resolution_minutes"] >= 0)]

    out["made_sla"] = (
        out["made_sla"].astype(str).str.strip().str.lower().map({"true": True, "false": False})
    )

    out["priority"] = out["priority"].astype(str).str.extract(r"(\d+)")[0]
    out = out[out["priority"].notna()]
    out["priority"] = out["priority"].astype(int)

    keep = [
        "number", "priority", "assignment_group", "category", "location",
        "reassignment_count", "reopen_count", "made_sla", "resolution_minutes",
        "opened_at", "updated_at", "resolved_at",
    ]
    return out[keep].reset_index(drop=True)


def derive_priority_mix(df):
    """Empirical priority distribution: value_counts(normalize=True) over
    the cleaned ticket log. {priority: proportion}; proportions sum to 1."""
    counts = df["priority"].value_counts(normalize=True).sort_index()
    return {
        "mix": {int(k): float(v) for k, v in counts.items()},
        "source": f"empirical priority share, value_counts(normalize=True) over N={len(df)} cleaned tickets",
    }


def derive_resolution_stats(df):
    """Per-priority resolution-time distribution: median and p90
    (empirical quantiles, numpy default linear interpolation) plus a
    2-parameter lognormal fit by closed-form MLE on resolution_minutes>0:
        s = std(ln x), scale = exp(mean(ln x))   (loc fixed at 0)
    These are the exact maximum-likelihood estimators for a lognormal, so
    no iterative solver is needed -- hand-checkable from the raw data.

    Kept intentionally though pipeline.py's derive_all doesn't call it:
    independently tested (tests/test_m0.py) as part of M0's derivation
    surface, but nothing downstream currently consumes a per-priority
    resolution-time distribution at runtime (M3/M4 use
    base_resolution_minutes directly, not this fitted distribution).
    """
    stats = {}
    for priority, group in df.groupby("priority"):
        x = group["resolution_minutes"].to_numpy()
        x = x[x > 0]
        log_x = np.log(x)
        stats[int(priority)] = {
            "median": float(np.quantile(x, 0.5)),
            "p90": float(np.quantile(x, 0.9)),
            "lognorm_s": float(log_x.std()),
            "lognorm_scale": float(np.exp(log_x.mean())),
            "n": int(len(x)),
        }
    return {
        "stats": stats,
        "source": (
            "per-priority resolution_minutes quantiles + closed-form lognormal "
            "MLE (s=std(ln x), scale=exp(mean(ln x))) over cleaned tickets"
        ),
    }


def derive_breach_rates(df):
    """Empirical SLA-breach probability per priority: P(made_sla == False)."""
    rates = df.groupby("priority")["made_sla"].apply(lambda s: float((~s).mean()))
    return {
        "rates": {int(k): float(v) for k, v in rates.items()},
        "source": f"empirical P(made_sla==False) per priority over N={len(df)} cleaned tickets",
    }


def derive_region_volumes(df, k=3):
    """Top-k ticket-volume locations, treated as M2's candidate regions
    (raw counts, insertion order = descending volume). pipeline.py scales
    these proportionally to its own planning-window size before using them
    as transportation-problem supplies -- the *shape* of the split across
    regions is real data, the *absolute* planning-window volume is not."""
    counts = df["location"].value_counts().head(k)
    return {
        "volumes": {str(loc): int(n) for loc, n in counts.items()},
        "source": f"top-{k} of {df['location'].nunique()} distinct locations by ticket count in the cleaned log",
    }


def derive_category_volumes(df, top=None):
    """Ticket counts per category (all, or the top-N if `top` is given).
    UCI-498's category field is anonymized ("Category 55" etc.) with no
    semantic mapping to this project's skill groups -- a caller that needs
    a skill-group demand signal must document how it maps category rank to
    skill name (see pipeline.py's CONFIG-documented assumption for M1)."""
    counts = df["category"].value_counts()
    if top is not None:
        counts = counts.head(top)
    return {
        "volumes": {str(cat): int(n) for cat, n in counts.items()},
        "source": f"ticket counts per category over N={len(df)} cleaned tickets ({df['category'].nunique()} distinct categories)",
    }


def derive_incident_durations(df):
    """Priority-1 stage-duration estimates, aggregated per INCIDENT.

    UCI-498 is an *event log*: a ticket `number` has one row per state
    change, so averaging opened_at/sys_updated_at/resolved_at across raw
    rows measures update cadence, not incident duration. This aggregates
    by `number` first:
        opened        = min(opened_at) over the incident's rows
        first_update  = min(updated_at) among rows with updated_at > opened_at
        resolved      = max(resolved_at) over the incident's rows
        triage proxy  = first_update - opened   (time to first substantive touch)
        fix proxy     = resolved - first_update (time from first touch to close)
    Returned as (p10, p50, p90) hours per stage -- PERT's own
    (optimistic, modal, pessimistic) shape, ready for build_network. The
    empirical p90s are heavy-tailed (a real long tail of slow-to-close
    critical incidents, consistent with this priority's own breach rate
    from derive_breach_rates) -- that tail is reported as-is, not trimmed.
    """
    p1 = df[df["priority"] == 1]
    opened = p1.groupby("number")["opened_at"].min()
    resolved = p1.groupby("number")["resolved_at"].max()
    after = p1[p1["updated_at"] > p1["opened_at"]]
    first_update = after.groupby("number")["updated_at"].min()

    g = pd.DataFrame({"opened": opened, "resolved": resolved}).join(
        first_update.rename("first_update")
    ).dropna()
    g = g[g["resolved"] >= g["opened"]]

    triage_h = (g["first_update"] - g["opened"]).dt.total_seconds() / 3600.0
    fix_h = (g["resolved"] - g["first_update"]).dt.total_seconds() / 3600.0
    triage_h = triage_h[triage_h > 0]
    fix_h = fix_h[fix_h > 0]

    def _p10_50_90(series):
        return (
            float(np.quantile(series, 0.1)),
            float(np.quantile(series, 0.5)),
            float(np.quantile(series, 0.9)),
        )

    return {
        "triage": _p10_50_90(triage_h),
        "fix": _p10_50_90(fix_h),
        "n_triage": int(len(triage_h)),
        "n_fix": int(len(fix_h)),
        "source": (
            f"priority-1 incidents grouped by `number` (n_triage={len(triage_h)}, "
            f"n_fix={len(fix_h)}); triage=first post-open update-opened_at, "
            f"fix=resolved_at-that first update; (p10,p50,p90) hours"
        ),
    }


def make_synthetic(n_tickets, n_agents, n_workstations, seed=42, fitted=None):
    """Generate a deterministic synthetic ticket/agent/workstation universe.

    If `fitted` (a cleaned real DataFrame from clean_incidents) is given,
    priority, resolution_minutes and reassignment_count are sampled from
    its empirical distributions instead of a hardcoded fallback, so
    synthetic data is fitted to the real dataset's shape. Each
    workstation gets a `type` (desktop/laptop, uniform) since M7 ages the
    two types on different curves.
    """
    rng = np.random.default_rng(seed)

    if fitted is not None and len(fitted) > 0:
        priority_pool = fitted["priority"].dropna().to_numpy()
        resolution_pool = fitted["resolution_minutes"].dropna().to_numpy()
        reassignment_pool = fitted["reassignment_count"].dropna().to_numpy()
    else:
        priority_pool = np.array([1, 2, 3, 4])
        resolution_pool = np.array([15.0, 30.0, 60.0, 120.0, 240.0])
        # documented fallback: skewed toward 0, occasional 1-2 reassignments
        reassignment_pool = np.array([0, 0, 0, 1, 1, 2])

    workstations = pd.DataFrame({
        "id": [f"WS{i:03d}" for i in range(n_workstations)],
        "age_months": rng.integers(0, 60, size=n_workstations),
        "type": rng.choice(WORKSTATION_TYPES, size=n_workstations),
    })

    agents = pd.DataFrame({
        "id": [f"A{i:03d}" for i in range(n_agents)],
        "skill": rng.choice(SKILL_GROUPS, size=n_agents),
        "capacity": rng.integers(1, 6, size=n_agents),
    })

    tickets = pd.DataFrame({
        "id": [f"T{i:05d}" for i in range(n_tickets)],
        "priority": rng.choice(priority_pool, size=n_tickets).astype(int),
        "skill": rng.choice(SKILL_GROUPS, size=n_tickets),
        "base_resolution_minutes": rng.choice(resolution_pool, size=n_tickets),
        "workstation_id": rng.choice(workstations["id"].to_numpy(), size=n_tickets),
        "reassignment_count": rng.choice(reassignment_pool, size=n_tickets).astype(int),
    })

    return {"tickets": tickets, "agents": agents, "workstations": workstations}
