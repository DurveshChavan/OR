"""The ITIL priority matrix, and how impact and urgency reach the risk model.

Known answer, from the data rather than from the code: cross-tabulating the
23,323 prepared UCI-498 incidents by (impact, urgency) against priority gives
exactly one priority per pair -

    impact  urgency   priority   incidents
      1        1          1          185
      1        2          2          101
      2        1          2          210
      2        2          3       22,197
      2        3          4           15
      3        2          4           57
      3        3          4          558

(1, 3) and (3, 1) never occur; the formula extrapolates them to 3.
"""
import os
from types import SimpleNamespace

import pandas as pd
import pytest

from api.servicedesk.errors import ApiError
from api.servicedesk.services import scoring, triage

UCI_OBSERVED = {(1, 1): 1, (1, 2): 2, (2, 1): 2, (2, 2): 3, (2, 3): 4, (3, 2): 4, (3, 3): 4}
PREPARED = os.path.join("data", "processed", "uci498", "incidents_v1.parquet")


@pytest.mark.parametrize("pair, priority", sorted(UCI_OBSERVED.items()))
def test_the_formula_reproduces_every_pair_the_log_contains(pair, priority):
    assert triage.priority_from_impact_urgency(*pair) == priority


def test_the_two_unobserved_pairs_extrapolate_to_three():
    assert triage.priority_from_impact_urgency(1, 3) == 3
    assert triage.priority_from_impact_urgency(3, 1) == 3


@pytest.mark.skipif(not os.path.exists(PREPARED), reason="prepared UCI-498 parquet not present")
def test_the_log_itself_maps_each_pair_to_one_priority():
    frame = pd.read_parquet(PREPARED, columns=["impact", "urgency", "priority"])
    level = lambda label: int(str(label)[0])
    observed = {
        (level(i), level(u)): sorted({level(p) for p in group["priority"]})
        for (i, u), group in frame.groupby(["impact", "urgency"])
    }
    assert observed == {pair: [priority] for pair, priority in UCI_OBSERVED.items()}


def test_an_explicit_priority_that_contradicts_the_pair_is_refused():
    with pytest.raises(ApiError) as caught:
        triage.resolve_priority(priority=4, impact=1, urgency=1)
    assert caught.value.code == "PRIORITY_MATRIX_MISMATCH"
    assert caught.value.details["derived_priority"] == 1


def test_without_the_pair_the_operator_priority_stands_and_is_required():
    assert triage.resolve_priority(3, impact=1, urgency=None) == (3, "operator")
    with pytest.raises(ApiError) as caught:
        triage.resolve_priority(None, impact=None, urgency=2)
    assert caught.value.code == "PRIORITY_REQUIRED"


def _ticket(**levels):
    return SimpleNamespace(
        id="t", priority=1, category="Category 26", subcategory="Subcategory 174",
        location="Location 204", contact_type="Phone",
        opened_at=pd.Timestamp("2016-05-20 10:00", tz="UTC"), **levels,
    )


def test_the_pair_reaches_the_model_in_its_training_label_form():
    row = scoring.feature_row(_ticket(impact=1, urgency=3))
    assert row["impact"] == "1 - High"
    assert row["urgency"] == "3 - Low"
    assert row["u_symptom"] is None


def test_only_genuinely_missing_features_are_listed():
    assert scoring.unavailable_features(_ticket(impact=1, urgency=1)) == ["u_symptom"]
    assert scoring.unavailable_features(_ticket(impact=None, urgency=2)) == ["impact", "u_symptom"]


def test_a_confirmed_urgency_changes_the_score():
    """A label the encoder did not recognise would score like a missing one.

    That is the silent failure STATE.md records for priority, so the check is
    that setting the pair moves the probability, not merely that it runs.
    """
    with_pair = scoring.score_ticket(_ticket(impact=1, urgency=1)).risk_probability
    without = scoring.score_ticket(_ticket(impact=None, urgency=None)).risk_probability
    assert with_pair != pytest.approx(without, abs=0.01)
