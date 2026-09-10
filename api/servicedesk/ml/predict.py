"""Load a saved artifact and score with it. No training, no transformation.

§E.6 requires the API to fail closed: an artifact that is missing, unreadable or
built against a different feature schema must block automated recommendation
rather than produce a number. Everything here raises :class:`ModelUnavailable`
for those cases, and the caller turns that into the documented
"model unavailable — manual dispatch" state with its own event.

The transformation lives inside the pickled pipeline. This module validates the
frame it is handed and calls the estimator; it never rebuilds a feature.
"""
import os

import numpy as np
import pandas as pd

from api.servicedesk.ml.artifacts import artifact_dir, latest_version, load_artifact
from api.servicedesk.ml.feature_spec import (
    INCIDENT_FEATURES_V1,
    UnknownPriority,
    normalise_priority,
)
from api.servicedesk.ml.pipeline import inverse_duration

RISK_MODEL = "sla_risk"
DURATION_MODEL = "duration"


class ModelUnavailable(RuntimeError):
    """No usable artifact. The caller must not invent a score."""


class _Scorer:
    """Shared loading and validation for both models."""

    name = ""

    def __init__(self, version=None, spec=INCIDENT_FEATURES_V1):
        self.spec = spec
        self.version = version or latest_version(self.name)
        if not self.version:
            raise ModelUnavailable(
                f"no {self.name} artifact under models/{self.name}/; train one "
                f"with `python -m api.servicedesk.ml.train_{self.name.split('_')[-1]}`"
            )
        directory = artifact_dir(self.name, self.version)
        if not os.path.isdir(directory):
            raise ModelUnavailable(f"{self.name} version {self.version} not found")
        try:
            payload = load_artifact(self.name, self.version)
        except Exception as error:  # unreadable pickle, truncated file, bad json
            raise ModelUnavailable(
                f"{self.name} artifact {self.version} could not be loaded: {error}"
            ) from error

        stored_schema = payload.get("feature_schema_version")
        if stored_schema != spec.version:
            raise ModelUnavailable(
                f"{self.name} artifact {self.version} was built against feature "
                f"schema {stored_schema!r}, this build expects {spec.version!r}"
            )
        self.estimator = payload["estimator"]
        self.metadata = payload
        self.metrics = payload.get("metrics", {})

    def _validated(self, frame):
        """Check the frame, then put it in the form the artifact was fitted on.

        The API stores priority as an integer and timestamps as tz-aware UTC;
        the model was fitted on UCI's label form and naive timestamps. Both are
        reconciled here rather than at each call site, because the failure mode
        is silent: a one-hot encoder with `handle_unknown="ignore"` answers an
        unrecognised priority with an all-zero block and a plausible-looking
        probability.
        """
        if isinstance(frame, dict):
            frame = pd.DataFrame([frame])
        missing = [c for c in self.spec.source_columns() if c not in frame.columns]
        if missing:
            raise ModelUnavailable(
                f"cannot score: request is missing {', '.join(missing)}"
            )
        self.spec.validate_columns(frame.columns)

        frame = frame.copy()
        try:
            frame["priority"] = [normalise_priority(v) for v in frame["priority"]]
        except UnknownPriority as error:
            raise ModelUnavailable(str(error)) from error

        opened = pd.to_datetime(frame[self.spec.source_timestamp], utc=True)
        # Training timestamps are the log's own naive clock. Comparing a UTC
        # offset against them would shift every derived hour by the offset.
        frame[self.spec.source_timestamp] = opened.dt.tz_localize(None)
        return frame


#: Isotonic calibration maps an all-positive bin to exactly 1.0, and priority 2
#: breaches 97.1% of the time in this log, so untouched output does reach 1.000.
#: A recommendation that tells a dispatcher a ticket will breach with certainty
#: overstates what a model fitted on 16,326 incidents can know, so scores are
#: clipped. The clip is at the display boundary, never inside training or the
#: reported metrics.
PROBABILITY_FLOOR = 0.001
PROBABILITY_CEILING = 0.999


class RiskScorer(_Scorer):
    """Calibrated probability that a ticket ends its life in SLA breach."""

    name = RISK_MODEL

    def score(self, frame) -> np.ndarray:
        raw = self.estimator.predict_proba(self._validated(frame))[:, 1]
        return np.clip(raw, PROBABILITY_FLOOR, PROBABILITY_CEILING)

    def score_one(self, ticket) -> float:
        return float(self.score(ticket)[0])


class DurationEstimator(_Scorer):
    """Predicted handling minutes. Never negative — see `inverse_duration`."""

    name = DURATION_MODEL

    def minutes(self, frame) -> np.ndarray:
        return inverse_duration(self.estimator.predict(self._validated(frame)))

    def minutes_one(self, ticket) -> float:
        return float(self.minutes(ticket)[0])
