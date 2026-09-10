"""The single feature contract shared by preparation, training and scoring.

FINAL_IMPLEMENTATION.md §E.3 asks for one ``FeatureSpec`` object rather than a
column list copied into four places. Everything downstream — the prepared
parquet, the training script, the API scorer, the replay — reads its allowed
and forbidden columns from here, so a leaking column has to be added in exactly
one file that a test is watching.

The allow / audit-gate / forbid split is not a judgement call made here. It is
the measured outcome recorded in ``data/reports/uci498_audit.md``:

  * ``assignment_group`` is populated on 96.4% of first records, so it encodes a
    routing action a human had already taken before the decision this project
    evaluates. Audit-gated, excluded by default.
  * ``assigned_to``, ``resolved_by``, ``closed_code``, ``resolved_at``,
    ``closed_at`` are resolution outcomes.
  * ``reassignment_count``, ``reopen_count``, ``sys_mod_count`` develop after the
    opening decision.
  * ``made_sla`` is the label and is never a feature.
"""
from dataclasses import dataclass, field
from typing import Iterable, Sequence

#: Ordering rule for the raw event log, stated once for the whole project. One
#: incident `number` has many rows; every downstream claim depends on which row
#: is treated as the decision-time snapshot, so the rule is named, not left
#: implicit in a sort call. Stable mergesort, first row = features, last = label.
ORDER_RULE = ("sys_updated_at", "sys_mod_count", "_row_index")

#: Fields available at (or before) ticket creation — the plan's allow-list.
CREATION_FIELDS = [
    "priority", "impact", "urgency", "category", "subcategory",
    "location", "contact_type", "opened_at", "u_symptom",
]
#: Allowed only if the audit proves the field is set before the routing
#: decision being evaluated. The audit proved the opposite; see module docstring.
AUDIT_GATED_FIELDS = ["assignment_group"]
#: Never a feature: resolution or prior-routing outcome leakage.
FORBIDDEN_FIELDS = [
    "assigned_to", "resolved_by", "closed_code", "resolved_at", "closed_at",
    "reassignment_count", "reopen_count", "sys_mod_count", "made_sla",
]

#: UCI-498 writes priority as a label ("3 - Moderate"); the service desk `tickets` table
#: stores it as an integer 1-4. The model was fitted on the label form, and a
#: one-hot encoder with `handle_unknown="ignore"` turns an unrecognised value
#: into an all-zero block **without raising** — the single most predictive field
#: would vanish and the score would still look plausible. So the two forms are
#: reconciled here, in one place, and an unmappable value is an error.
PRIORITY_LEVELS = {
    1: "1 - Critical",
    2: "2 - High",
    3: "3 - Moderate",
    4: "4 - Low",
}


class UnknownPriority(ValueError):
    """A priority that cannot be mapped to a level the model was trained on."""


def normalise_priority(value):
    """Accept 1-4, "2", or "2 - High"; return the trained label form."""
    if value in PRIORITY_LEVELS.values():
        return value
    try:
        number = int(str(value).strip().split(" ")[0])
    except (TypeError, ValueError):
        raise UnknownPriority(f"priority {value!r} is not 1-4 or a known level")
    if number not in PRIORITY_LEVELS:
        raise UnknownPriority(f"priority {value!r} is not 1-4 or a known level")
    return PRIORITY_LEVELS[number]


#: Name of the incident-level label column in prepared data.
LABEL_COLUMN = "label_breach"
#: Name of the duration-model target in prepared data (minutes, resolved-based).
DURATION_COLUMN = "duration_minutes"


class LeakageError(ValueError):
    """A forbidden or audit-gated column reached a feature path."""


@dataclass(frozen=True)
class FeatureSpec:
    """What a model may read, how missing values are treated, and what is banned.

    ``categorical`` and ``numeric`` are the columns handed to the serialized
    scikit-learn pipeline. ``timestamp_derived`` names the columns the pipeline
    computes from ``source_timestamp``; they are not stored in prepared data,
    because storing a derived column invites a second, hand-written derivation
    somewhere else.
    """

    version: str
    categorical: Sequence[str]
    numeric: Sequence[str]
    timestamp_derived: Sequence[str]
    source_timestamp: str
    missing_indicator: Sequence[str]
    forbidden: Sequence[str] = field(default=tuple(FORBIDDEN_FIELDS))
    audit_gated: Sequence[str] = field(default=tuple(AUDIT_GATED_FIELDS))
    categorical_missing_strategy: str = "most_frequent"
    numeric_missing_strategy: str = "median"
    unknown_category_behavior: str = "ignore"

    def source_columns(self) -> list:
        """Columns read straight from prepared data (derived ones excluded)."""
        return list(self.categorical) + list(self.numeric) + [self.source_timestamp]

    def model_columns(self) -> list:
        """Columns the fitted pipeline sees, after timestamp derivation."""
        return (
            list(self.categorical)
            + list(self.numeric)
            + list(self.timestamp_derived)
        )

    def validate_columns(self, columns: Iterable[str], approved_gated=()) -> None:
        """Raise if any column is banned, or gated without written approval.

        ``approved_gated`` exists so that re-admitting ``assignment_group`` is a
        deliberate act with a named caller, not a quiet default. Nothing in the
        shipped code passes it.
        """
        names = list(columns)
        banned = [c for c in names if c in set(self.forbidden)]
        gated = [
            c for c in names
            if c in set(self.audit_gated) and c not in set(approved_gated)
        ]
        if banned:
            raise LeakageError(
                "forbidden column(s) reached a feature path: "
                + ", ".join(sorted(banned))
                + " — these are resolution or prior-routing outcomes"
            )
        if gated:
            raise LeakageError(
                "audit-gated column(s) used without approval: "
                + ", ".join(sorted(gated))
                + " — see data/reports/uci498_audit.md, routing-field leakage timing"
            )

    def validate_frame(self, frame) -> None:
        """Check a DataFrame both ways: nothing banned, nothing missing."""
        self.validate_columns(frame.columns)
        missing = [c for c in self.source_columns() if c not in frame.columns]
        if missing:
            raise ValueError(
                "prepared frame is missing required feature column(s): "
                + ", ".join(missing)
            )

    def as_dict(self) -> dict:
        """Serialisable form, copied into schema files and model cards."""
        return {
            "feature_schema_version": self.version,
            "categorical": list(self.categorical),
            "numeric": list(self.numeric),
            "timestamp_derived": list(self.timestamp_derived),
            "source_timestamp": self.source_timestamp,
            "missing_indicator": list(self.missing_indicator),
            "forbidden": list(self.forbidden),
            "audit_gated": list(self.audit_gated),
            "categorical_missing_strategy": self.categorical_missing_strategy,
            "numeric_missing_strategy": self.numeric_missing_strategy,
            "unknown_category_behavior": self.unknown_category_behavior,
        }


#: The one spec in use. Both the risk model and the duration model read the same
#: creation-time fields; they differ in target, not in what they are allowed to
#: see.
#:
#: ``u_symptom`` is kept despite 23.0% missingness and 500 distinct values: it is
#: the caller-reported symptom, recorded on the first record, so it is genuinely
#: available at dispatch time. Its missingness is itself informative (a ticket
#: raised without a symptom code is a different kind of ticket), so it carries an
#: explicit indicator rather than being silently imputed. High cardinality is
#: handled by the encoder's ``min_frequency``, not by dropping the column.
INCIDENT_FEATURES_V1 = FeatureSpec(
    version="incident-features-v1",
    categorical=(
        "priority", "impact", "urgency", "category", "subcategory",
        "location", "contact_type", "u_symptom",
    ),
    numeric=(),
    timestamp_derived=("opened_hour", "opened_dayofweek"),
    source_timestamp="opened_at",
    missing_indicator=("u_symptom",),
)
