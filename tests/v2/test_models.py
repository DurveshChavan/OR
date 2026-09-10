"""Model plumbing, with answers worked out by hand.

Nothing here checks that a metric is good. It checks that the arithmetic is the
arithmetic we claim: the baseline counts what it says it counts, a log-target
inverse cannot emit a negative minute, capacity metrics rank the way a reviewer
would, and an artifact refuses to score when its schema no longer matches.

The two artifact tests skip when `models/` is empty, so a fresh clone that has
not trained yet reports a gap rather than a failure.
"""
import numpy as np
import pandas as pd
import pytest

from api.app_v2.ml import evaluation
from api.app_v2.ml.artifacts import latest_version
from api.app_v2.ml.baselines import PriorityBreachRate, PriorityCategoryMedianDuration
from api.app_v2.ml.feature_spec import INCIDENT_FEATURES_V1, LeakageError
from api.app_v2.ml.pipeline import derive_features, inverse_duration
from api.app_v2.ml.predict import DurationEstimator, ModelUnavailable, RiskScorer


def ticket(priority="3 - Moderate", category="Category 1", opened="2016-03-01 14:30",
           u_symptom="Symptom 72", **overrides):
    row = {
        "priority": priority, "impact": "2 - Medium", "urgency": "2 - Medium",
        "category": category, "subcategory": "Subcategory 7",
        "location": "Location 143", "contact_type": "Phone",
        "u_symptom": u_symptom, "opened_at": pd.Timestamp(opened),
    }
    row.update(overrides)
    return row


# --------------------------------------------------------------------------
# Baselines — the numbers below are counted by hand from the fixture
# --------------------------------------------------------------------------

def test_priority_breach_rate_counts_the_training_period():
    """Four P1 of which two breach, two P3 of which none do: 0.5 and 0.0."""
    train = pd.DataFrame({
        "priority": ["1 - Critical"] * 4 + ["3 - Moderate"] * 2,
        "label_breach": [True, True, False, False, False, False],
    })
    baseline = PriorityBreachRate().fit(train)
    assert baseline.rates_ == {"1 - Critical": 0.5, "3 - Moderate": 0.0}
    assert baseline.overall_ == pytest.approx(2 / 6)

    scored = baseline.predict_proba(pd.DataFrame({
        "priority": ["1 - Critical", "3 - Moderate", "4 - Low"],
    }))
    # An unseen priority gets the training base rate, not zero and not a guess.
    assert list(scored) == pytest.approx([0.5, 0.0, 2 / 6])


def test_baseline_cannot_be_moved_by_test_labels():
    """It is fitted on training data only, so rewriting later labels is inert."""
    train = pd.DataFrame({
        "priority": ["2 - High", "2 - High"], "label_breach": [True, False],
    })
    baseline = PriorityBreachRate().fit(train)
    before = baseline.predict_proba(pd.DataFrame({"priority": ["2 - High"]}))

    test = pd.DataFrame({"priority": ["2 - High"] * 50, "label_breach": [True] * 50})
    after = baseline.predict_proba(test)[:1]
    assert before == pytest.approx(after)
    assert before[0] == 0.5


def test_duration_baseline_falls_back_a_level_at_a_time():
    train = pd.DataFrame({
        "priority": ["1 - Critical", "1 - Critical", "1 - Critical", "3 - Moderate"],
        "category": ["Network", "Network", "Email", "Network"],
        "duration_minutes": [10.0, 30.0, 100.0, 500.0],
    })
    baseline = PriorityCategoryMedianDuration().fit(train)
    # (Critical, Network) median of 10 and 30
    assert baseline.medians_["1 - Critical||Network"] == 20.0
    # Critical overall median of 10, 30, 100
    assert baseline.priority_medians_["1 - Critical"] == 30.0

    predicted = baseline.predict(pd.DataFrame({
        "priority": ["1 - Critical", "1 - Critical", "4 - Low"],
        "category": ["Network", "Database", "Database"],
    }))
    # exact pair -> pair median; unseen category -> priority median;
    # unseen priority -> overall median of 10, 30, 100, 500
    assert list(predicted) == pytest.approx([20.0, 30.0, 65.0])


# --------------------------------------------------------------------------
# Transformations
# --------------------------------------------------------------------------

def test_inverse_duration_never_returns_a_negative_minute():
    """A ridge on log1p can predict a negative; a negative minute must not reach
    a projected finish time."""
    predicted = inverse_duration([-5.0, -0.001, 0.0, np.log1p(120.0)])
    assert list(predicted[:3]) == [0.0, 0.0, 0.0]
    assert predicted[3] == pytest.approx(120.0)


def test_derive_features_reads_only_opened_at():
    """2016-03-01 14:30 is a Tuesday, so hour 14 and weekday 1."""
    frame = pd.DataFrame([ticket(), ticket(u_symptom=None)])
    derived = derive_features(frame)
    assert list(derived["opened_hour"]) == [14, 14]
    assert list(derived["opened_dayofweek"]) == [1, 1]
    assert list(derived["u_symptom_missing"]) == [0, 1]


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def test_precision_and_recall_at_capacity_rank_by_risk():
    """Two of four tickets reviewed; the top two hold one of the two breaches."""
    y = [True, False, True, False]
    p = [0.9, 0.8, 0.7, 0.1]
    at_half = evaluation.precision_recall_at_capacity(y, p, 0.5)
    assert at_half["reviewed"] == 2
    assert at_half["precision"] == 0.5
    assert at_half["recall"] == 0.5


def test_expected_calibration_error_is_zero_when_predictions_match_reality():
    y = [True, False] * 50
    p = [0.5] * 100
    assert evaluation.expected_calibration_error(y, p) == pytest.approx(0.0)


def test_expected_calibration_error_measures_the_gap_it_claims():
    """Everything predicted at 0.9, nothing breaches: the gap is 0.9."""
    y = [False] * 20
    p = [0.9] * 20
    assert evaluation.expected_calibration_error(y, p) == pytest.approx(0.9)


def test_reliability_table_bins_and_counts():
    table = evaluation.reliability_table([True, True, False, False],
                                         [0.95, 0.91, 0.05, 0.01])
    assert len(table) == 2
    assert {row["n"] for row in table} == {2}
    assert table[0]["observed_rate"] == 0.0
    assert table[-1]["observed_rate"] == 1.0


# --------------------------------------------------------------------------
# Artifacts. Skipped when nothing has been trained in this checkout.
# --------------------------------------------------------------------------

needs_risk = pytest.mark.skipif(
    latest_version("sla_risk") is None,
    reason="no sla_risk artifact; run `python -m api.app_v2.ml.train_risk`",
)
needs_duration = pytest.mark.skipif(
    latest_version("duration") is None,
    reason="no duration artifact; run `python -m api.app_v2.ml.train_duration`",
)


@needs_risk
def test_risk_scorer_returns_a_probability():
    scorer = RiskScorer()
    value = scorer.score_one(ticket())
    assert 0.0 <= value <= 1.0
    assert scorer.version.startswith("uci-risk-")


@needs_risk
def test_an_unseen_category_scores_instead_of_raising():
    """`handle_unknown="ignore"` is what keeps a new category out of the
    manual-dispatch path."""
    scorer = RiskScorer()
    assert 0.0 <= scorer.score_one(ticket(category="Category never seen")) <= 1.0


@needs_risk
def test_a_missing_feature_blocks_scoring():
    scorer = RiskScorer()
    incomplete = {k: v for k, v in ticket().items() if k != "impact"}
    with pytest.raises(ModelUnavailable) as excinfo:
        scorer.score_one(incomplete)
    assert "impact" in str(excinfo.value)


@needs_risk
def test_a_leaking_request_is_refused_at_the_scorer():
    scorer = RiskScorer()
    leaking = dict(ticket())
    leaking["resolved_at"] = pd.Timestamp("2016-03-02 10:00")
    with pytest.raises(LeakageError):
        scorer.score(pd.DataFrame([leaking]))


@needs_risk
def test_a_schema_mismatch_fails_closed():
    """An artifact built against another feature schema must not be scored with
    silently different columns."""
    from dataclasses import replace

    other = replace(INCIDENT_FEATURES_V1, version="incident-features-v99")
    with pytest.raises(ModelUnavailable) as excinfo:
        RiskScorer(spec=other)
    assert "incident-features-v99" in str(excinfo.value)


@needs_risk
def test_a_missing_version_fails_closed():
    with pytest.raises(ModelUnavailable):
        RiskScorer(version="uci-risk-1999-01-01-a1")


def api_request(priority, opened="2026-09-09T10:00:00Z"):
    """A payload shaped the way `POST /api/v2/tickets` sends one: integer
    priority, tz-aware UTC timestamp, no label, split or incident id."""
    return {
        "priority": priority, "impact": "2 - Medium", "urgency": "2 - Medium",
        "category": "Category 55", "subcategory": "Subcategory 170",
        "location": "Location 143", "contact_type": "Phone",
        "u_symptom": None, "opened_at": opened,
    }


@needs_risk
def test_an_integer_priority_scores_the_same_as_its_label_form():
    """The database column is an integer 1-4; the model was fitted on
    "2 - High". Without the mapping the encoder zeroes the priority block and
    still returns a plausible probability, which is the worst kind of bug."""
    scorer = RiskScorer()
    for number, label in ((1, "1 - Critical"), (2, "2 - High"),
                          (3, "3 - Moderate"), (4, "4 - Low")):
        as_int = scorer.score_one(api_request(number))
        as_label = scorer.score_one(api_request(label))
        assert as_int == pytest.approx(as_label)


@needs_risk
def test_priority_actually_moves_the_score():
    """If every priority scored alike, the priority block would be dead. In this
    log priority 2 breaches 97.1% of the time and priority 4 only 17.3%, so the
    order is data, not intuition."""
    scorer = RiskScorer()
    assert scorer.score_one(api_request(2)) > scorer.score_one(api_request(4))


@needs_risk
def test_an_unmappable_priority_fails_closed():
    scorer = RiskScorer()
    with pytest.raises(ModelUnavailable) as excinfo:
        scorer.score_one(api_request(9))
    assert "priority" in str(excinfo.value)


@needs_risk
def test_a_tz_aware_timestamp_is_accepted_and_read_as_utc():
    """The database stores UTC; the training data is the log's naive clock. The
    hour has to survive the crossing, not shift by an offset."""
    scorer = RiskScorer()
    frame = scorer._validated(pd.DataFrame([api_request(3, "2026-09-09T10:00:00Z")]))
    assert frame["opened_at"].iloc[0] == pd.Timestamp("2026-09-09 10:00:00")
    assert frame["opened_at"].dt.tz is None


@needs_risk
def test_a_score_is_never_a_certainty():
    """Isotonic maps an all-positive bin to exactly 1.0. A recommendation does
    not get to tell a dispatcher that a breach is certain."""
    scorer = RiskScorer()
    scores = [scorer.score_one(api_request(p)) for p in (1, 2, 3, 4)]
    assert all(0.0 < s < 1.0 for s in scores)


@needs_duration
def test_duration_estimator_returns_non_negative_minutes():
    estimator = DurationEstimator()
    minutes = estimator.minutes(pd.DataFrame([ticket(), ticket(priority="1 - Critical")]))
    assert (minutes >= 0).all()
    assert estimator.version.startswith("uci-duration-")


@needs_risk
def test_the_locked_test_result_is_recorded_and_beats_the_baseline():
    """The shipping gate from the plan: a candidate that cannot beat
    `P(breach | priority)` on the locked test period is not worth shipping. If
    this ever fails, the answer is to report the loss, not to retune."""
    metrics = RiskScorer().metrics["models"]
    baseline = metrics["baseline (priority only)"]["test"]
    shipped = metrics["logistic + isotonic on validation (shipped)"]["test"]
    assert shipped["roc_auc"] > baseline["roc_auc"]
    assert shipped["pr_auc"] > baseline["pr_auc"]
    # Calibration is the reason the shipped model is the calibrated one.
    uncalibrated = metrics["logistic (uncalibrated)"]["test"]
    assert shipped["expected_calibration_error"] < uncalibrated["expected_calibration_error"]
