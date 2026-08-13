import os

import pandas as pd
import pytest

from api.engine.data_layer import clean_incidents, make_synthetic, load_incident_log


def _raw_fixture():
    return pd.DataFrame({
        "number": ["INC0001", "INC0002", "INC0003", "INC0004"],
        "priority": ["1 - High", "3 - Moderate", "2 - Medium", "4 - Low"],
        "assignment_group": ["Network", "Hardware", "Software", "Database"],
        "category": ["network", "hardware", "software", "database"],
        "reassignment_count": [0, 1, 2, 0],
        "reopen_count": [0, 0, 1, 0],
        "made_sla": ["true", "false", "true", "true"],
        # dayfirst dd/mm/yyyy HH:MM strings, as in the UCI log
        "opened_at": ["01/01/2016 08:00", "02/01/2016 09:00", "03/01/2016 10:00", "04/01/2016 11:00"],
        "resolved_at": ["01/01/2016 09:30", "02/01/2016 08:30", "03/01/2016 09:00", None],
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
        "number", "priority", "assignment_group", "category",
        "reassignment_count", "reopen_count", "made_sla", "resolution_minutes",
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
    }
    assert set(result_a["agents"].columns) == {"id", "skill", "capacity"}
    assert set(result_a["workstations"].columns) == {"id", "age_months"}

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


@pytest.mark.slow
def test_load_incident_log_from_cache():
    cache_path = os.path.join("data", "incident_event_log.csv")
    if not os.path.exists(cache_path):
        pytest.skip("no cached incident_event_log.csv; network fetch not exercised in tests")
    df = load_incident_log(cache_dir="data")
    assert len(df) > 0
    assert "number" in df.columns
