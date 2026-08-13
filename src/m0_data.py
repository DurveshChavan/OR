"""M0 — data layer.

Loads UCI dataset 498 (Incident management process enriched event log),
cleans it into a tidy ticket table, and generates a seeded synthetic
ticket/agent/workstation universe fitted to that real data when available.
No OR technique here; this only feeds M1-M7.
"""
import os
import io
import zipfile
import urllib.request

import numpy as np
import pandas as pd

SKILL_GROUPS = ["network", "hardware", "software", "database", "access"]

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
    "1 - High" are reduced to their leading integer.
    """
    out = df.copy()
    out["opened_at"] = pd.to_datetime(out["opened_at"], dayfirst=True, errors="coerce")
    out["resolved_at"] = pd.to_datetime(out["resolved_at"], dayfirst=True, errors="coerce")

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
        "number", "priority", "assignment_group", "category",
        "reassignment_count", "reopen_count", "made_sla", "resolution_minutes",
    ]
    return out[keep].reset_index(drop=True)


def make_synthetic(n_tickets, n_agents, n_workstations, seed=42, fitted=None):
    """Generate a deterministic synthetic ticket/agent/workstation universe.

    If `fitted` (a cleaned real DataFrame from clean_incidents) is given,
    priority and resolution_minutes are sampled from its empirical
    distributions instead of a hardcoded fallback, so synthetic data is
    fitted to the real dataset's shape.
    """
    rng = np.random.default_rng(seed)

    if fitted is not None and len(fitted) > 0:
        priority_pool = fitted["priority"].dropna().to_numpy()
        resolution_pool = fitted["resolution_minutes"].dropna().to_numpy()
    else:
        priority_pool = np.array([1, 2, 3, 4])
        resolution_pool = np.array([15.0, 30.0, 60.0, 120.0, 240.0])

    workstations = pd.DataFrame({
        "id": [f"WS{i:03d}" for i in range(n_workstations)],
        "age_months": rng.integers(0, 60, size=n_workstations),
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
    })

    return {"tickets": tickets, "agents": agents, "workstations": workstations}
