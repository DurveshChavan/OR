import os

import numpy as np
import pandas as pd
import pytest

from api.engine.data_layer import (
    clean_incidents, make_synthetic, load_incident_log,
    derive_priority_mix, derive_resolution_stats, derive_breach_rates,
    derive_region_volumes, derive_category_volumes, derive_incident_durations,
)


def _raw_fixture():
    return pd.DataFrame({
        "number": ["INC0001", "INC0002", "INC0003", "INC0004"],
        "priority": ["1 - High", "3 - Moderate", "2 - Medium", "4 - Low"],
        "assignment_group": ["Network", "Hardware", "Software", "Database"],
        "category": ["network", "hardware", "software", "database"],
        "location": ["Location 1", "Location 2", "Location 1", "Location 3"],
        "reassignment_count": [0, 1, 2, 0],
        "reopen_count": [0, 0, 1, 0],
        "made_sla": ["true", "false", "true", "true"],
        # dayfirst dd/mm/yyyy HH:MM strings, as in the UCI log
        "opened_at": ["01/01/2016 08:00", "02/01/2016 09:00", "03/01/2016 10:00", "04/01/2016 11:00"],
        "sys_updated_at": ["01/01/2016 08:30", "02/01/2016 09:15", "03/01/2016 10:05", "04/01/2016 11:10"],
        "resolved_at": ["01/01/2016 09:30", "02/01/2016 08:30", "03/01/2016 09:00", None],
    })


def _cleaned_fixture():
    """A tiny already-cleaned frame (as if output of clean_incidents) with
    hand-checkable derive_* answers -- see the comments in each test."""
    return pd.DataFrame({
        "number": ["INC1", "INC2", "INC3", "INC4", "INC5", "INC6"],
        "priority": [1, 1, 1, 2, 2, 3],
        "location": ["L1", "L1", "L2", "L1", "L3", "L2"],
        "category": ["C1", "C1", "C2", "C2", "C3", "C1"],
        "reassignment_count": [0, 1, 0, 0, 2, 0],
        "reopen_count": [0, 0, 0, 0, 0, 0],
        "made_sla": [True, False, True, False, True, True],
        "resolution_minutes": [100.0, 200.0, 50.0, 80.0, 120.0, 60.0],
        "opened_at": pd.to_datetime([
            "2026-01-01 00:00", "2026-01-02 00:00", "2026-01-03 00:00",
            "2026-01-04 00:00", "2026-01-05 00:00", "2026-01-06 00:00",
        ]),
        "updated_at": pd.to_datetime([
            "2026-01-01 01:00", "2026-01-02 04:00", "2026-01-03 00:30",
            "2026-01-04 02:00", "2026-01-05 06:00", "2026-01-06 01:00",
        ]),
        "resolved_at": pd.to_datetime([
            "2026-01-01 03:00", "2026-01-02 10:00", "2026-01-03 02:30",
            "2026-01-04 05:00", "2026-01-05 12:00", "2026-01-06 03:00",
        ]),
        "assignment_group": ["G"] * 6,
    })


def test_clean_incidents_resolution_minutes_and_sla():
    out = clean_incidents(_raw_fixture())

    # row 0: 08:00 -> 09:30 = 90 minutes, kept
    row0 = out[out["number"] == "INC0001"].iloc[0]
    assert row0["resolution_minutes"] == pytest.approx(90.0)
    assert bool(row0["made_sla"]) is True
    assert row0["priority"] == 1

    # row 1: resolved_at (08:30) before opened_at (09:00) -> negative duration, dropped
    assert "INC0002" not in out["number"].to_numpy()

    # row 2: 10:00 -> 09:00 next... actually same day 10:00->09:00 negative too, dropped
    assert "INC0003" not in out["number"].to_numpy()

    # row 3: resolved_at missing -> NaT duration, dropped
    assert "INC0004" not in out["number"].to_numpy()

    expected_cols = {
        "number", "priority", "assignment_group", "category", "location",
        "reassignment_count", "reopen_count", "made_sla", "resolution_minutes",
        "opened_at", "updated_at", "resolved_at",
    }
    assert set(out.columns) == expected_cols
    assert len(out) == 1


def test_clean_incidents_made_sla_is_bool_dtype():
    out = clean_incidents(_raw_fixture())
    assert out["made_sla"].dtype == bool


def test_make_synthetic_deterministic_and_shapes():
    result_a = make_synthetic(n_tickets=20, n_agents=5, n_workstations=3, seed=42)
    result_b = make_synthetic(n_tickets=20, n_agents=5, n_workstations=3, seed=42)

    assert set(result_a) == {"tickets", "agents", "workstations"}
    assert len(result_a["tickets"]) == 20
    assert len(result_a["agents"]) == 5
    assert len(result_a["workstations"]) == 3

    assert set(result_a["tickets"].columns) == {
        "id", "priority", "skill", "base_resolution_minutes", "workstation_id",
        "reassignment_count",
    }
    assert set(result_a["agents"].columns) == {"id", "skill", "capacity"}
    assert set(result_a["workstations"].columns) == {"id", "age_months", "type"}
    assert set(result_a["workstations"]["type"]) <= {"desktop", "laptop"}

    for key in result_a:
        pd.testing.assert_frame_equal(result_a[key], result_b[key])


def test_make_synthetic_different_seed_differs():
    result_a = make_synthetic(n_tickets=20, n_agents=5, n_workstations=3, seed=42)
    result_c = make_synthetic(n_tickets=20, n_agents=5, n_workstations=3, seed=7)
    assert not result_a["tickets"]["base_resolution_minutes"].equals(
        result_c["tickets"]["base_resolution_minutes"]
    )


def test_make_synthetic_fitted_samples_from_real_distribution():
    fitted = clean_incidents(_raw_fixture())
    result = make_synthetic(n_tickets=50, n_agents=4, n_workstations=2, seed=1, fitted=fitted)
    assert set(result["tickets"]["priority"].unique()) <= set(fitted["priority"].unique())
    assert set(result["tickets"]["base_resolution_minutes"].unique()) <= set(
        fitted["resolution_minutes"].unique()
    )


def test_make_synthetic_reassignment_count_from_fitted():
    fitted = clean_incidents(_raw_fixture())  # single surviving row, reassignment_count=0
    result = make_synthetic(n_tickets=10, n_agents=3, n_workstations=2, seed=3, fitted=fitted)
    assert set(result["tickets"]["reassignment_count"].unique()) <= set(fitted["reassignment_count"].unique())


def test_derive_priority_mix_known_fractions():
    result = derive_priority_mix(_cleaned_fixture())
    # 6 rows: priority 1x3, 2x2, 3x1 -> 0.5, 1/3, 1/6
    assert result["mix"] == pytest.approx({1: 0.5, 2: 1 / 3, 3: 1 / 6})


def test_derive_breach_rates_known_fractions():
    result = derive_breach_rates(_cleaned_fixture())
    # priority1 made_sla=[True,False,True] -> breach 1/3
    # priority2 made_sla=[False,True] -> breach 1/2
    # priority3 made_sla=[True] -> breach 0
    assert result["rates"] == pytest.approx({1: 1 / 3, 2: 0.5, 3: 0.0})


def test_derive_region_volumes_top_k():
    result = derive_region_volumes(_cleaned_fixture(), k=2)
    # location counts: L1=3 (INC1,INC2,INC4), L2=2 (INC3,INC6), L3=1 (INC5)
    assert result["volumes"] == {"L1": 3, "L2": 2}


def test_derive_category_volumes_all_and_top():
    result_all = derive_category_volumes(_cleaned_fixture())
    # category counts: C1=3 (INC1,INC2,INC6), C2=2 (INC3,INC4), C3=1 (INC5)
    assert result_all["volumes"] == {"C1": 3, "C2": 2, "C3": 1}
    result_top = derive_category_volumes(_cleaned_fixture(), top=2)
    assert result_top["volumes"] == {"C1": 3, "C2": 2}


def test_derive_resolution_stats_known_median_and_geometric_mean():
    result = derive_resolution_stats(_cleaned_fixture())
    # priority1 resolution_minutes=[100,200,50] -> sorted [50,100,200]
    # median (linear interp, n=3, pos=1.0) = 100
    # p90 (pos=1.8) = 100 + 0.8*(200-100) = 180
    p1 = result["stats"][1]
    assert p1["median"] == pytest.approx(100.0)
    assert p1["p90"] == pytest.approx(180.0)
    # geometric mean of 50,100,200 = cube root of 1,000,000 = 100 exactly
    assert p1["lognorm_scale"] == pytest.approx(100.0)
    assert p1["lognorm_s"] > 0


def test_derive_incident_durations_known_quantiles():
    result = derive_incident_durations(_cleaned_fixture())
    # priority-1 incidents INC1,INC2,INC3:
    # INC1: opened 00:00, first_update 01:00, resolved 03:00 -> triage=1h fix=2h
    # INC2: opened 00:00, first_update 04:00, resolved 10:00 -> triage=4h fix=6h
    # INC3: opened 00:00, first_update 00:30, resolved 02:30 -> triage=0.5h fix=2h
    # triage sorted [0.5,1,4]: p10(pos.2)=0.6 p50(pos1)=1.0 p90(pos1.8)=3.4
    # fix sorted [2,2,6]: p10(pos.2)=2.0 p50(pos1)=2.0 p90(pos1.8)=5.2
    assert result["triage"] == pytest.approx((0.6, 1.0, 3.4))
    assert result["fix"] == pytest.approx((2.0, 2.0, 5.2))
    assert result["n_triage"] == 3
    assert result["n_fix"] == 3


def test_derive_functions_sane_on_real_cached_data():
    """Sanity (not snapshot) check on the real 138k-row dataset when it's
    cached locally -- ranges/shapes only, no asserted exact values."""
    cache_path = os.path.join("data", "incident_event_log.csv")
    if not os.path.exists(cache_path):
        pytest.skip("no cached incident_event_log.csv; network fetch not exercised in tests")
    df = clean_incidents(load_incident_log(cache_dir="data"))

    mix = derive_priority_mix(df)["mix"]
    assert sum(mix.values()) == pytest.approx(1.0)

    rates = derive_breach_rates(df)["rates"]
    assert all(0.0 <= r <= 1.0 for r in rates.values())

    regions = derive_region_volumes(df, k=3)["volumes"]
    assert len(regions) == 3
    assert list(regions.values()) == sorted(regions.values(), reverse=True)

    durations = derive_incident_durations(df)
    for stage in ("triage", "fix"):
        p10, p50, p90 = durations[stage]
        assert 0 <= p10 <= p50 <= p90


@pytest.mark.slow
def test_load_incident_log_from_cache():
    cache_path = os.path.join("data", "incident_event_log.csv")
    if not os.path.exists(cache_path):
        pytest.skip("no cached incident_event_log.csv; network fetch not exercised in tests")
    df = load_incident_log(cache_dir="data")
    assert len(df) > 0
    assert "number" in df.columns
