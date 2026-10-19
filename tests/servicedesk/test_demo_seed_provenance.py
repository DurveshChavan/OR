"""The demo seed's provenance claims, checked against the dataset itself.

The seed says three things about its tickets: that every one is a real UCI-498
incident, that every one comes from the held-out split the models never saw,
and that the record's own fields are carried across unchanged. Those are the
claims the footer repeats to a reader and the report repeats to an examiner, so
they are checked here rather than asserted in a comment.

The processed dataset lives under ``data/``, which is not committed, so these
tests skip when it is absent instead of failing a checkout that never had it.
The rest of the file - the outcome coverage the demo depends on - is checked
without the dataset, because it is a property of the table alone.
"""
import collections
import os

import pytest

from api.servicedesk.cli import seed_demo

PARQUET = os.path.join("data", "processed", "uci498", "incidents_v1.parquet")

PRIORITY_NUMBER = {
    "1 - Critical": 1,
    "2 - High": 2,
    "3 - Moderate": 3,
    "4 - Low": 4,
}


@pytest.fixture(scope="module")
def dataset():
    if not os.path.exists(PARQUET):
        pytest.skip("processed UCI-498 dataset not present in this checkout")
    pandas = pytest.importorskip("pandas")
    return pandas.read_parquet(PARQUET).set_index("incident_id")


def test_every_seeded_ticket_is_a_real_incident(dataset):
    missing = [row[0] for row in seed_demo.DEMO_TICKETS if row[0] not in dataset.index]
    assert missing == []


def test_every_seeded_ticket_comes_from_the_held_out_split(dataset):
    """The demo must not display a prediction for a row the model was fitted on.

    This is the one that matters. A demo seeded from the training split shows
    the model its own memorised examples and calls the answer a prediction; the
    numbers would look better and mean nothing.
    """
    trained_on = {
        row[0]: dataset.loc[row[0], "split"]
        for row in seed_demo.DEMO_TICKETS
        if dataset.loc[row[0], "split"] != "test"
    }
    assert trained_on == {}


def test_seeded_fields_are_the_records_own_values(dataset):
    """Nothing in the ticket table is a nicer-sounding substitute."""
    for reference, priority, category, subcategory, location, contact, _ in (
        seed_demo.DEMO_TICKETS
    ):
        record = dataset.loc[reference]
        assert PRIORITY_NUMBER[record["priority"]] == priority, reference
        assert record["category"] == category, reference
        assert record["subcategory"] == subcategory, reference
        assert record["location"] == location, reference
        assert record["contact_type"] == contact, reference


def test_seeded_impact_and_urgency_are_the_records_own_and_agree_with_priority(dataset):
    from api.servicedesk.services.triage import priority_from_impact_urgency

    assert set(seed_demo.DEMO_TICKET_LEVELS) == {row[0] for row in seed_demo.DEMO_TICKETS}
    for reference, priority, *_ in seed_demo.DEMO_TICKETS:
        impact, urgency = seed_demo.DEMO_TICKET_LEVELS[reference]
        record = dataset.loc[reference]
        assert (int(record["impact"][0]), int(record["urgency"][0])) == (impact, urgency), reference
        assert priority_from_impact_urgency(impact, urgency) == priority, reference


def test_every_staffed_category_can_actually_be_dispatched():
    """A demo whose default state is "cannot dispatch" teaches the wrong thing.

    An earlier roster left the busiest category one slot short so that a
    ``queued`` decision would show up. What a reader actually saw was most of
    the queue refusing to dispatch, because the three resolvers holding that
    skill filled up and the other six could not take it. So the rule is now the
    opposite: if a category is staffed at all, it is staffed well enough to take
    every seeded ticket in it.
    """
    slots = collections.Counter()
    for _, wip_limit, skills in seed_demo.DEMO_AGENTS:
        for skill, _multiplier, _primary in skills:
            slots[skill] += wip_limit

    demand = collections.Counter(row[2] for row in seed_demo.DEMO_TICKETS)

    short = {
        category: (demand[category], slots[category])
        for category in demand
        if slots[category] and demand[category] > slots[category]
    }
    assert not short, "staffed but oversubscribed, so the demo cannot dispatch: %s" % short


def test_one_category_is_deliberately_unstaffed():
    """The refusal path needs exactly one clear case, and keeps it."""
    slots = collections.Counter()
    for _, wip_limit, skills in seed_demo.DEMO_AGENTS:
        for skill, _multiplier, _primary in skills:
            slots[skill] += wip_limit

    demand = collections.Counter(row[2] for row in seed_demo.DEMO_TICKETS)
    unstaffed = [category for category in demand if slots[category] == 0]
    assert unstaffed, "every category is staffed, so no_eligible_agent never occurs"
    assert len(unstaffed) == 1, (
        "more than one category has nobody qualified, which reads as a broken "
        "roster rather than a demonstrated outcome: %s" % unstaffed
    )


def test_two_seeded_tickets_open_far_enough_back_to_be_overdue():
    """Risk Radar needs a recovery group without anyone waiting for one."""
    target_minutes = {policy[0]: policy[1] for policy in seed_demo.DEMO_POLICIES}
    overdue = [
        reference
        for reference, priority, _c, _s, _l, _t, age_minutes in seed_demo.DEMO_TICKETS
        if age_minutes > target_minutes[priority]
    ]
    assert len(overdue) >= 2, overdue


def test_the_linked_machines_name_seeded_tickets():
    references = {row[0] for row in seed_demo.DEMO_TICKETS}
    assert set(seed_demo.DEMO_TICKET_MACHINE_LINKS) <= references
