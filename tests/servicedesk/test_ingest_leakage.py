"""Preparation must produce one row per incident, from the right rows.

The fixture log is five hand-written incidents whose answers are worked out on
paper in `EXPECTED` below: which row supplies features, which supplies the
label, what the duration is in minutes, and which incidents are dropped and
why. A snapshot of whatever the code happened to output first would prove
nothing here, because the failure this phase has to exclude — features read
from a later row, duration read from `closed_at`, a label paired with the wrong
ticket — produces perfectly plausible output.

The last two tests run against the real log when it is present. They restate
the audit's own counts, so a preparation change that moves them fails here
before it reaches a model card.
"""
import os

import pandas as pd
import pytest

from api.servicedesk.ingest import uci498
from api.servicedesk.ml.feature_spec import FORBIDDEN_FIELDS, INCIDENT_FEATURES_V1

# One row of the raw event log. Timestamps are day-first, as UCI writes them.
COLUMNS = [
    "number", "sys_updated_at", "sys_mod_count", "opened_at", "made_sla",
    "resolved_at", "closed_at", "priority", "impact", "urgency", "category",
    "subcategory", "location", "contact_type", "u_symptom", "assignment_group",
    "assigned_to", "resolved_by", "closed_code", "reassignment_count",
    "reopen_count",
]


def event(number, updated, mod, opened, made_sla, resolved="?", closed="?",
          priority="3 - Moderate", category="Category 1"):
    return {
        "number": number,
        "sys_updated_at": updated,
        "sys_mod_count": mod,
        "opened_at": opened,
        "made_sla": made_sla,
        "resolved_at": resolved,
        "closed_at": closed,
        "priority": priority,
        "impact": "2 - Medium",
        "urgency": "2 - Medium",
        "category": category,
        "subcategory": "Subcategory 7",
        "location": "Location 143",
        "contact_type": "Phone",
        "u_symptom": "Symptom 72",
        "assignment_group": "Group 56",
        "assigned_to": "Resolver 89",
        "resolved_by": "Resolved by 149",
        "closed_code": "code 5",
        "reassignment_count": 0,
        "reopen_count": 0,
    }


#: INC001 breaches: it opens at 09:00, its priority is edited to Critical on a
#: later row (which must not become the feature), it resolves at 11:00 and the
#: system auto-closes it five days later.
#: INC002 is compliant and short.
#: INC003 never resolves, INC004 resolves in zero minutes, INC005 carries a
#: resolved_at before its opened_at. All three are dropped, not repaired.
FIXTURE_EVENTS = [
    event("INC001", "01/03/2016 09:00", 0, "01/03/2016 09:00", "True"),
    event("INC001", "01/03/2016 10:00", 1, "01/03/2016 09:00", "True",
          priority="1 - Critical", category="Category 99"),
    event("INC001", "01/03/2016 12:00", 2, "01/03/2016 09:00", "False",
          resolved="01/03/2016 11:00", closed="06/03/2016 11:00",
          priority="1 - Critical", category="Category 99"),

    event("INC002", "02/03/2016 08:00", 0, "02/03/2016 08:00", "True"),
    event("INC002", "02/03/2016 09:00", 1, "02/03/2016 08:00", "True",
          resolved="02/03/2016 08:30", closed="07/03/2016 08:30"),

    event("INC003", "03/03/2016 08:00", 0, "03/03/2016 08:00", "True"),
    event("INC003", "03/03/2016 09:00", 1, "03/03/2016 08:00", "False",
          closed="08/03/2016 08:00"),

    event("INC004", "04/03/2016 08:00", 0, "04/03/2016 08:00", "True",
          resolved="04/03/2016 08:00", closed="09/03/2016 08:00"),

    event("INC005", "05/03/2016 08:00", 0, "05/03/2016 08:00", "True",
          resolved="05/03/2016 07:00", closed="10/03/2016 07:00"),
]

#: Worked out by hand from FIXTURE_EVENTS, before the code was run.
EXPECTED = {
    "INC001": {"priority": "3 - Moderate", "category": "Category 1",
               "label_breach": True, "duration_minutes": 120.0},
    "INC002": {"priority": "3 - Moderate", "category": "Category 1",
               "label_breach": False, "duration_minutes": 30.0},
}
DROPPED = ["INC003", "INC004", "INC005"]


@pytest.fixture
def fixture_log(tmp_path):
    path = tmp_path / "incident_event_log.csv"
    pd.DataFrame(FIXTURE_EVENTS, columns=COLUMNS).to_csv(path, index=False)
    return str(path)


@pytest.fixture
def prepared(fixture_log):
    frame, _ = uci498.prepare(raw_path=fixture_log, write=False)
    return frame


def test_one_row_per_incident(prepared):
    assert list(prepared["incident_id"]) == ["INC001", "INC002"]
    assert prepared["incident_id"].is_unique


def test_features_come_from_the_first_record(prepared):
    """INC001's priority is edited to Critical after opening. A model asked to
    triage at creation time cannot see that edit."""
    row = prepared.set_index("incident_id").loc["INC001"]
    assert row["priority"] == EXPECTED["INC001"]["priority"]
    assert row["category"] == EXPECTED["INC001"]["category"]


def test_label_comes_from_the_final_record(prepared):
    labels = prepared.set_index("incident_id")["label_breach"].to_dict()
    assert labels == {k: v["label_breach"] for k, v in EXPECTED.items()}


def test_duration_is_measured_to_resolved_not_closed(prepared):
    """INC001 resolves after 120 minutes and auto-closes five days later. Using
    `closed_at` would record 7,320 minutes of a fixed timer as handling time."""
    durations = prepared.set_index("incident_id")["duration_minutes"].to_dict()
    assert durations == {k: v["duration_minutes"] for k, v in EXPECTED.items()}
    assert 7320.0 not in durations.values()


def test_invalid_incidents_are_dropped_not_repaired(prepared):
    """No resolved_at, zero duration, and resolved-before-opened all leave, and
    none of them is clamped, imputed or back-filled into a usable row."""
    for number in DROPPED:
        assert number not in set(prepared["incident_id"])


def test_row_order_in_the_raw_file_does_not_change_the_output(tmp_path):
    """The ordering rule, not the file's row order, decides which row is first."""
    forward = tmp_path / "forward.csv"
    reversed_ = tmp_path / "reversed.csv"
    frame = pd.DataFrame(FIXTURE_EVENTS, columns=COLUMNS)
    frame.to_csv(forward, index=False)
    frame.iloc[::-1].to_csv(reversed_, index=False)

    a, _ = uci498.prepare(raw_path=str(forward), write=False)
    b, _ = uci498.prepare(raw_path=str(reversed_), write=False)
    pd.testing.assert_frame_equal(a, b)


def test_no_forbidden_column_survives_preparation(prepared):
    """The raw fixture carries every forbidden field. None reaches the output."""
    for column in FORBIDDEN_FIELDS:
        assert column not in prepared.columns
    assert "assignment_group" not in prepared.columns
    INCIDENT_FEATURES_V1.validate_frame(prepared)


def test_splits_are_chronological_and_disjoint(prepared):
    frame = prepared
    assert set(frame["split"]) <= {"train", "validation", "test"}
    for earlier, later in (("train", "validation"), ("validation", "test")):
        left = frame.loc[frame["split"] == earlier, "opened_at"]
        right = frame.loc[frame["split"] == later, "opened_at"]
        if len(left) and len(right):
            assert left.max() < right.min()


def test_a_single_opened_at_never_straddles_two_splits():
    """The cut is pushed to the end of a tied timestamp, so the split can be
    reproduced from the recorded boundary times alone."""
    tied = pd.Timestamp("2016-03-01 09:00")
    frame = pd.DataFrame({
        "incident_id": [f"INC{i:03d}" for i in range(10)],
        # rows 6, 7 and 8 share one opened_at, and the 70% cut lands inside it
        "opened_at": [
            pd.Timestamp("2016-03-01") + pd.Timedelta(hours=i) for i in range(6)
        ] + [tied, tied, tied] + [pd.Timestamp("2016-03-02")],
    })
    ordered, boundaries = uci498.assign_chronological_split(frame)
    by_time = ordered.groupby("opened_at")["split"].nunique()
    assert by_time.max() == 1
    assert boundaries["split_counts"]["train"] == 9  # cut at 7, pushed to 9


def test_split_counts_sum_to_the_prepared_row_count():
    frame = pd.DataFrame({
        "incident_id": [f"INC{i:03d}" for i in range(100)],
        "opened_at": [
            pd.Timestamp("2016-03-01") + pd.Timedelta(minutes=i) for i in range(100)
        ],
    })
    ordered, boundaries = uci498.assign_chronological_split(frame)
    counts = boundaries["split_counts"]
    assert counts == {"train": 70, "validation": 15, "test": 15}
    assert sum(counts.values()) == len(ordered)


# --------------------------------------------------------------------------
# Against the real log, when it is present. data/ is git-ignored, so a fresh
# clone skips these rather than failing.
# --------------------------------------------------------------------------

real_log = pytest.mark.skipif(
    not os.path.exists(uci498.RAW_PATH),
    reason=f"raw log not present at {uci498.RAW_PATH}; run `fetch` to obtain it",
)


@real_log
def test_real_log_matches_the_audited_counts():
    """23,323 valid incidents at 38.28% breach prevalence — the numbers
    `data/reports/uci498_audit.md` states and STATE.md already quotes."""
    frame, boundaries = uci498.prepare(write=False)
    assert len(frame) == 23_323
    assert round(float(frame["label_breach"].mean()) * 100, 2) == 38.28
    counts = boundaries["split_counts"]
    assert counts["train"] == 16_326
    assert counts["validation"] == 3_498
    assert counts["test"] == 3_499


@real_log
def test_real_log_carries_no_forbidden_column():
    frame, _ = uci498.prepare(write=False)
    INCIDENT_FEATURES_V1.validate_frame(frame)
    assert "assignment_group" not in frame.columns
