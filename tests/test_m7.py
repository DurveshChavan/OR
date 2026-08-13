import pandas as pd
import pytest

from src.m7_replacement import (
    deteriorating_replacement, group_vs_individual, degradation_factor,
    workstation_factors,
)


def test_deteriorating_replacement_known_optimal_year():
    # purchase=100, resale [60,40,25,15,10], running cost [10,15,25,40,60]
    # avg cost by year: 50, 42.5, 41.667, 43.75, 48 -> minimum at year 3
    result = deteriorating_replacement(
        purchase=100,
        scrap=[60, 40, 25, 15, 10],
        running_cost_by_year=[10, 15, 25, 40, 60],
    )
    assert result["optimal_year"] == 3
    assert result["optimal_average_cost"] == pytest.approx(125 / 3)
    assert [row["average_cost"] for row in result["table"]] == pytest.approx(
        [50.0, 42.5, 125 / 3, 43.75, 48.0]
    )


def test_deteriorating_replacement_constant_scrap():
    result = deteriorating_replacement(purchase=100, scrap=20, running_cost_by_year=[10, 20])
    # year1: total=100-20+10=90, avg=90; year2: total=100-20+30=110, avg=55
    assert result["table"][0]["total_cost"] == pytest.approx(90.0)
    assert result["table"][1]["average_cost"] == pytest.approx(55.0)


def test_group_vs_individual_known_cheaper_policy():
    # light-bulb style: p1=.2,p2=.3,p3=.5, N=10, individual cost=2, group cost=0.5
    # mean_life=2.3 -> individual avg = 20/2.3 = 8.6957
    # B1=2, B2=3.4, B3=6.28 -> group avg by interval: T1=9, T2=7.9, T3=9.4533
    # cheapest overall: group replacement every 2 periods (7.9 < 8.6957)
    result = group_vs_individual(
        failure_prob_by_period=[0.2, 0.3, 0.5],
        unit_replace_cost=2,
        group_replace_cost=0.5,
        n_items=10,
    )
    assert result["individual_average_cost"] == pytest.approx(20 / 2.3)
    assert [row["average_cost"] for row in result["group_table"]] == pytest.approx(
        [9.0, 7.9, 9.453333333333333]
    )
    assert result["optimal_group_interval"] == 2
    assert result["optimal_group_average_cost"] == pytest.approx(7.9)
    assert result["cheaper_policy"] == "group"


def test_degradation_factor_zero_at_age_zero_and_monotonic():
    assert degradation_factor(0) == 1.0
    ages = [0, 6, 12, 24, 48]
    factors = [degradation_factor(a) for a in ages]
    assert all(f >= 1.0 for f in factors)
    assert factors == sorted(factors)
    assert len(set(factors)) == len(factors)  # strictly increasing for alpha>0


def test_degradation_factor_alpha_scales_slope():
    slow = degradation_factor(12, alpha=0.01)
    fast = degradation_factor(12, alpha=0.05)
    assert 1.0 <= slow < fast


def test_workstation_factors_matches_degradation_factor_per_row():
    workstations = pd.DataFrame({"id": ["WS0", "WS1", "WS2"], "age_months": [0, 10, 30]})
    factors = workstation_factors(workstations)
    assert factors == {
        "WS0": degradation_factor(0),
        "WS1": degradation_factor(10),
        "WS2": degradation_factor(30),
    }
    assert factors["WS0"] == 1.0
    assert all(v >= 1.0 for v in factors.values())
