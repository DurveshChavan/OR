"""The feature contract must reject exactly the columns the audit forbade.

The known answers here are not invented for the test: they are the verdict
column of the candidate-feature inventory in `data/reports/uci498_audit.md`.
If a column moves between allowed / audit-gated / forbidden, that report and
this test have to disagree first, which is the point.
"""
import pandas as pd
import pytest

from api.servicedesk.ml.feature_spec import (
    AUDIT_GATED_FIELDS,
    FORBIDDEN_FIELDS,
    INCIDENT_FEATURES_V1,
    LeakageError,
)

SPEC = INCIDENT_FEATURES_V1


@pytest.mark.parametrize("column", FORBIDDEN_FIELDS)
def test_forbidden_column_is_rejected(column):
    """Every name the audit marked FORBIDDEN, one at a time."""
    with pytest.raises(LeakageError) as excinfo:
        SPEC.validate_columns(["priority", column])
    assert column in str(excinfo.value)


def test_forbidden_list_matches_the_audit_verdict():
    """The nine columns the audit table marks FORBIDDEN, verbatim."""
    assert set(FORBIDDEN_FIELDS) == {
        "assigned_to", "resolved_by", "closed_code", "resolved_at", "closed_at",
        "reassignment_count", "reopen_count", "sys_mod_count", "made_sla",
    }
    assert AUDIT_GATED_FIELDS == ["assignment_group"]


def test_assignment_group_needs_written_approval():
    """Audit-gated is not the same as allowed: re-admitting it takes a caller
    that names it, and nothing in the shipped code does."""
    with pytest.raises(LeakageError) as excinfo:
        SPEC.validate_columns(["category", "assignment_group"])
    assert "assignment_group" in str(excinfo.value)

    SPEC.validate_columns(
        ["category", "assignment_group"], approved_gated=("assignment_group",)
    )


def test_allowed_creation_columns_pass():
    SPEC.validate_columns(list(SPEC.categorical) + [SPEC.source_timestamp])


def test_assignment_group_is_not_a_model_column():
    assert "assignment_group" not in SPEC.model_columns()
    assert "assignment_group" not in SPEC.source_columns()


def test_derived_columns_are_not_read_from_stored_data():
    """`opened_hour` is computed by the fitted pipeline. Storing it would invite
    a second, hand-written derivation in the API."""
    assert "opened_hour" in SPEC.model_columns()
    assert "opened_hour" not in SPEC.source_columns()
    assert SPEC.source_timestamp in SPEC.source_columns()


def test_validate_frame_reports_a_missing_feature_column():
    frame = pd.DataFrame({"priority": ["3 - Moderate"], "opened_at": [pd.Timestamp.now()]})
    with pytest.raises(ValueError) as excinfo:
        SPEC.validate_frame(frame)
    assert "impact" in str(excinfo.value)


def test_validate_frame_rejects_a_leaking_frame():
    columns = {c: ["x"] for c in SPEC.categorical}
    columns["opened_at"] = [pd.Timestamp("2016-03-01")]
    columns["resolved_by"] = ["Resolved by 149"]
    with pytest.raises(LeakageError):
        SPEC.validate_frame(pd.DataFrame(columns))


def test_as_dict_carries_what_a_model_card_has_to_state():
    spec = SPEC.as_dict()
    assert spec["feature_schema_version"] == "incident-features-v1"
    assert spec["unknown_category_behavior"] == "ignore"
    assert "u_symptom" in spec["missing_indicator"]
    assert "made_sla" in spec["forbidden"]


def test_priority_normalisation_accepts_both_forms():
    """The database writes 2, UCI wrote "2 - High", and the model knows only the
    second. Both have to land on the same trained level."""
    from api.servicedesk.ml.feature_spec import UnknownPriority, normalise_priority

    assert normalise_priority(2) == "2 - High"
    assert normalise_priority("2") == "2 - High"
    assert normalise_priority("2 - High") == "2 - High"
    assert normalise_priority(1) == "1 - Critical"
    assert normalise_priority(4) == "4 - Low"


def test_priority_normalisation_refuses_what_it_cannot_map():
    from api.servicedesk.ml.feature_spec import UnknownPriority, normalise_priority

    for value in (0, 5, None, "urgent", ""):
        with pytest.raises(UnknownPriority):
            normalise_priority(value)
