"""Scoring a live ticket with the saved artifacts, and failing closed (spec E.6).

Two things separate this module from ``ml/predict.py``. First, it knows about
the ``tickets`` table: it turns a row into the frame the artifact was fitted on,
including the fields the operational table simply does not carry. Second, it
loads each artifact once per process, because unpickling a scikit-learn pipeline
on every ticket creation would make the rescore benchmark a measurement of
joblib.

Fail-closed is the whole contract here. A missing, unreadable or schema-
mismatched artifact raises :class:`ApiError` with code ``MODEL_UNAVAILABLE`` and
status 503. No caller invents a probability, and the one documented path that
still writes a ticket without a score records a ``MODEL_UNAVAILABLE`` event
saying which of those four things went wrong.

Three feature columns the model was trained on do not exist in the service desk ticket
table: ``impact``, ``urgency`` and ``u_symptom``. They are UCI fields with no
operational equivalent in this build, so they are passed as missing and the
artifact's own imputer fills them, exactly as it fills a missing value in
training data. That is a real limitation and it is stated in the model note the
API returns, not hidden behind a plausible number.
"""
from dataclasses import dataclass
from typing import Dict, List, Sequence

import pandas as pd

from api.servicedesk.errors import ApiError
from api.servicedesk.ml import predict
from api.servicedesk.ml.feature_spec import INCIDENT_FEATURES_V1

#: Feature columns the operational ticket table has no column for. Named here so
#: the gap is a declared constant a reader can find, not an omission in a dict.
UNAVAILABLE_AT_DISPATCH = ("impact", "urgency", "u_symptom")

#: Loaded artifacts, keyed by (model name, requested version). One process, one
#: unpickle per model.
_CACHE: dict = {}


@dataclass(frozen=True)
class TicketScore:
    """What the two artifacts say about one ticket, with their versions."""

    risk_probability: float
    predicted_duration_minutes: float
    risk_model_version: str
    duration_model_version: str


def reset_cache() -> None:
    """Drop loaded artifacts. Tests that swap a model directory call this."""
    _CACHE.clear()


def risk_scorer(version: str = None) -> predict.RiskScorer:
    return _load(predict.RiskScorer, predict.RISK_MODEL, version)


def duration_estimator(version: str = None) -> predict.DurationEstimator:
    return _load(predict.DurationEstimator, predict.DURATION_MODEL, version)


def _load(factory, name: str, version):
    key = (name, version)
    if key not in _CACHE:
        try:
            _CACHE[key] = factory(version=version)
        except predict.ModelUnavailable as error:
            raise _unavailable(name, str(error)) from error
    return _CACHE[key]


def _unavailable(model_name: str, reason: str) -> ApiError:
    """The one shape a fail-closed scoring failure takes."""
    return ApiError(
        "MODEL_UNAVAILABLE",
        "Model unavailable - manual dispatch. The %s model could not be used: %s"
        % (model_name, reason),
        status_code=503,
        details={"model": model_name, "reason": reason},
    )


def feature_row(ticket) -> dict:
    """One ticket as the feature columns the artifact expects.

    ``opened_at`` is left tz-aware; ``predict._Scorer._validated`` converts it to
    the log's naive clock, which is the single place that conversion happens.
    """
    row = {
        "priority": ticket.priority,
        "category": ticket.category,
        "subcategory": ticket.subcategory,
        "location": ticket.location,
        "contact_type": ticket.contact_type,
        "opened_at": ticket.opened_at,
    }
    for column in UNAVAILABLE_AT_DISPATCH:
        row[column] = None
    return row


def feature_frame(tickets: Sequence) -> pd.DataFrame:
    """A frame for a batch of tickets, in the order given.

    ``pd.NA`` rather than ``None`` because the fitted categorical imputer was
    built with ``missing_values=pd.NA``; a ``None`` in an object column would
    survive imputation and reach the encoder as an unseen category.
    """
    frame = pd.DataFrame([feature_row(ticket) for ticket in tickets])
    for column in INCIDENT_FEATURES_V1.categorical:
        if column in frame.columns:
            frame[column] = frame[column].astype("object").where(frame[column].notna(), pd.NA)
    return frame


def score_tickets(tickets: Sequence, risk_version=None,
                  duration_version=None) -> Dict[str, TicketScore]:
    """Score a batch in two vectorised calls, not two calls per ticket."""
    tickets = list(tickets)
    if not tickets:
        return {}
    scorer = risk_scorer(risk_version)
    estimator = duration_estimator(duration_version)
    frame = feature_frame(tickets)
    try:
        risks = scorer.score(frame)
        durations = estimator.minutes(frame)
    except predict.ModelUnavailable as error:
        raise _unavailable(predict.RISK_MODEL, str(error)) from error
    return {
        ticket.id: TicketScore(
            risk_probability=float(risk),
            predicted_duration_minutes=float(duration),
            risk_model_version=scorer.version,
            duration_model_version=estimator.version,
        )
        for ticket, risk, duration in zip(tickets, risks, durations)
    }


def score_ticket(ticket, risk_version=None, duration_version=None) -> TicketScore:
    """Score one ticket. Same path as a batch of one, so both agree by construction."""
    return score_tickets([ticket], risk_version, duration_version)[ticket.id]


def available_versions() -> List[str]:
    """Versions in use right now, for a health or model-status response."""
    return [
        risk_scorer().version,
        duration_estimator().version,
    ]
