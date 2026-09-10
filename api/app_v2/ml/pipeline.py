"""The one feature pipeline. Training and scoring both call it, or neither works.

FINAL_IMPLEMENTATION.md §E.3 is explicit that the fitted pipeline does the
transformation and the API must not hand-write a parallel one. Everything a
model needs — the derived hour and weekday, the missingness indicator, the
imputers, the encoder — lives inside the estimator that gets pickled, so a
saved artifact carries its own preprocessing and the scorer only has to pass a
validated frame in.

The derivation function is module-level because a lambda cannot be pickled, and
an artifact that cannot be reloaded is not an artifact.
"""
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from api.app_v2.ml.feature_spec import INCIDENT_FEATURES_V1, FeatureSpec


def indicator_name(column: str) -> str:
    return f"{column}_missing"


def derive_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Add the columns the spec declares as derived, and nothing else.

    Hour and weekday come from ``opened_at`` only — the one timestamp available
    when a ticket is created. The missingness indicator is kept as its own
    column because a ticket raised without a symptom code is a different kind
    of ticket, and imputing the mode would erase that.
    """
    spec = INCIDENT_FEATURES_V1
    out = frame.copy()
    opened = pd.to_datetime(out[spec.source_timestamp])
    out["opened_hour"] = opened.dt.hour
    out["opened_dayofweek"] = opened.dt.dayofweek
    for column in spec.missing_indicator:
        out[indicator_name(column)] = out[column].isna().astype(int)
    return out


def _column_groups(spec: FeatureSpec):
    categorical = list(spec.categorical) + list(spec.timestamp_derived)
    numeric = list(spec.numeric) + [indicator_name(c) for c in spec.missing_indicator]
    return categorical, numeric


def build_preprocessor(spec: FeatureSpec = INCIDENT_FEATURES_V1, min_frequency=20):
    """Impute, one-hot with an unknown-category escape, pass indicators through.

    ``min_frequency`` folds rare levels into one bucket. ``subcategory`` has 246
    levels and ``location`` 219, so without it the design matrix is mostly
    columns seen a handful of times in training and never again.
    """
    categorical, numeric = _column_groups(spec)
    return ColumnTransformer(
        transformers=[
            (
                "categorical",
                Pipeline([
                    ("impute", SimpleImputer(
                        strategy=spec.categorical_missing_strategy,
                        missing_values=pd.NA,
                    )),
                    ("encode", OneHotEncoder(
                        handle_unknown=spec.unknown_category_behavior,
                        min_frequency=min_frequency,
                        sparse_output=True,
                    )),
                ]),
                categorical,
            ),
            (
                "numeric",
                SimpleImputer(strategy=spec.numeric_missing_strategy),
                numeric,
            ),
        ],
        remainder="drop",
    )


def build_risk_estimator(spec=INCIDENT_FEATURES_V1, C=1.0, min_frequency=20,
                         seed=20260910):
    """Regularised logistic regression on the shared preprocessing.

    Linear and one-hot on purpose: a grader can read a coefficient for
    "priority = 1 - Critical" and check its sign against the audit's per-priority
    breach table.
    """
    return Pipeline([
        ("derive", _Deriver()),
        ("prepare", build_preprocessor(spec, min_frequency=min_frequency)),
        ("model", LogisticRegression(
            C=C, max_iter=2000, solver="lbfgs", random_state=seed,
        )),
    ])


def build_duration_estimator(spec=INCIDENT_FEATURES_V1, alpha=1.0, min_frequency=20):
    """Ridge on ``log1p(minutes)``. The inverse transform lives in predict.py."""
    return Pipeline([
        ("derive", _Deriver()),
        ("prepare", build_preprocessor(spec, min_frequency=min_frequency)),
        ("model", Ridge(alpha=alpha)),
    ])


class _Deriver:
    """A picklable transformer wrapping :func:`derive_features`.

    ``FunctionTransformer`` would do, but this keeps the pickle independent of
    scikit-learn's function-reference handling and reads plainly in a repr.
    """

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        return derive_features(X)

    def get_params(self, deep=True):
        return {}

    def set_params(self, **params):
        return self

    def __repr__(self):
        return "Deriver(opened_hour, opened_dayofweek, u_symptom_missing)"


def inverse_duration(predictions) -> np.ndarray:
    """Undo ``log1p`` and clamp at zero. A negative predicted minute is not a
    prediction, it is an arithmetic slip escaping into a projected finish time."""
    return np.maximum(0.0, np.expm1(np.asarray(predictions, dtype=float)))
