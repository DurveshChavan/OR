"""The machine register and its replacement advice, checked against hand tables.

Two worked instances are written out below in full. Both were computed on paper
before the code was run, which is what makes this a test of the arithmetic
rather than a snapshot of whatever the implementation happened to produce first.

Instance 1 — deteriorating item (one machine)
---------------------------------------------
purchase 10,000; resale constant 2,000; running cost by year
1,000 / 2,000 / 3,000 / 5,000.

    year  cumulative  total = 10000 - 2000 + cumulative   average = total / year
      1       1,000                 9,000                        9,000.00
      2       3,000                11,000                        5,500.00
      3       6,000                14,000                        4,666.67
      4      11,000                19,000                        4,750.00

The average cost turns upward at year 4, so the optimal replacement year is 3
and the optimal average cost is 14,000 / 3 = 4,666.67.

Instance 2 — sudden failure (a fleet)
--------------------------------------
N = 100, failure probabilities 0.1 / 0.2 / 0.3 / 0.4, unit replacement 20,
group replacement 5.

    mean life = 1(0.1) + 2(0.2) + 3(0.3) + 4(0.4) = 3.0
    individual-only average cost = 100 x 20 / 3 = 666.67

    B1 = 100(0.1)                                            = 10
    B2 = 100(0.2) + B1(0.1)                                  = 21
    B3 = 100(0.3) + B1(0.2) + B2(0.1)                        = 34.1
    B4 = 100(0.4) + B1(0.3) + B2(0.2) + B3(0.1)              = 50.61

    T = 1: (100(5) + 20(10))      / 1 = 700.00
    T = 2: (500 + 20(31))         / 2 = 560.00
    T = 3: (500 + 20(65.1))       / 3 = 600.67
    T = 4: (500 + 20(115.71))     / 4 = 703.55

The group interval of 2 periods at 560.00 beats replacing on failure at 666.67,
so the cheaper policy is group replacement.
"""
from datetime import timedelta

import pytest

from api.servicedesk.db import models
from api.servicedesk.db.types import utcnow
from api.servicedesk.services import hardware

RUNNING = [1000.0, 2000.0, 3000.0, 5000.0]
SCRAP = [2000.0]
PURCHASE = 10000.0


@pytest.fixture
def machine(db):
    def _make(age_months=0, asset_tag="WS-0001", running=None, scrap=None,
              recorded_days_ago=0, machine_type="desktop"):
        row = models.Machine(
            asset_tag=asset_tag,
            location="HQ",
            machine_type=machine_type,
            age_months=age_months,
            age_recorded_at=utcnow() - timedelta(days=recorded_days_ago),
            purchase_cost=PURCHASE,
            scrap_value_by_year_json=list(SCRAP if scrap is None else scrap),
            running_cost_by_year_json=list(RUNNING if running is None else running),
            source_note="asset register export, 2026-09",
        )
        db.add(row)
        db.commit()
        return row
    return _make


# --- the arithmetic ---------------------------------------------------------


def test_the_average_cost_table_matches_the_hand_table(db, machine):
    advice = hardware.replacement_advice(machine())
    table = {row["year"]: row for row in advice["table"]}

    assert table[1]["total_cost"] == pytest.approx(9000.0)
    assert table[2]["total_cost"] == pytest.approx(11000.0)
    assert table[3]["total_cost"] == pytest.approx(14000.0)
    assert table[4]["total_cost"] == pytest.approx(19000.0)

    assert table[1]["average_cost"] == pytest.approx(9000.0)
    assert table[2]["average_cost"] == pytest.approx(5500.0)
    assert table[3]["average_cost"] == pytest.approx(4666.67, abs=0.01)
    assert table[4]["average_cost"] == pytest.approx(4750.0)


def test_the_optimal_year_is_where_the_average_turns_upward(db, machine):
    advice = hardware.replacement_advice(machine())
    assert advice["optimal_replacement_year"] == 3
    assert advice["optimal_average_cost"] == pytest.approx(4666.67, abs=0.01)


def test_a_machine_past_its_optimal_year_is_told_to_replace_now(db, machine):
    advice = hardware.replacement_advice(machine(age_months=40))
    assert advice["verdict"] == "replace_now"
    # Optimal year 3 is month 36; a 40-month-old machine is four months past it.
    assert advice["months_until_due"] == pytest.approx(-4.0, abs=0.2)


def test_a_machine_within_six_months_of_its_optimal_year_is_replace_soon(db, machine):
    advice = hardware.replacement_advice(machine(age_months=32))
    assert advice["verdict"] == "replace_soon"


def test_a_young_machine_is_kept(db, machine):
    advice = hardware.replacement_advice(machine(age_months=6))
    assert advice["verdict"] == "keep"
    assert advice["months_until_due"] == pytest.approx(30.0, abs=0.2)


def test_a_recorded_age_is_carried_forward_rather_than_read_as_current(db, machine):
    """A manager types an age once; reading it a year later would understate it."""
    row = machine(age_months=24, recorded_days_ago=365)
    assert hardware.current_age_months(row) == pytest.approx(36.0, abs=0.2)


def test_misaligned_cost_years_are_refused_rather_than_padded(db, machine):
    row = machine(running=[1000.0, 2000.0, 3000.0], scrap=[2000.0, 1500.0])
    with pytest.raises(Exception) as failure:
        hardware.replacement_advice(row)
    assert failure.value.code == "MACHINE_COSTS_MISALIGNED"


# --- group replacement ------------------------------------------------------


def test_group_replacement_matches_the_hand_renewal_table(db):
    analysis = hardware.fleet_group_advice(
        n_items=100,
        failure_prob_by_period=[0.1, 0.2, 0.3, 0.4],
        unit_replace_cost=20.0,
        group_replace_cost=5.0,
    )
    costs = {row["interval"]: row["average_cost"] for row in analysis["group_table"]}
    assert costs[1] == pytest.approx(700.00, abs=0.01)
    assert costs[2] == pytest.approx(560.00, abs=0.01)
    assert costs[3] == pytest.approx(600.67, abs=0.01)
    assert costs[4] == pytest.approx(703.55, abs=0.01)

    assert analysis["individual_average_cost"] == pytest.approx(666.67, abs=0.01)
    assert analysis["optimal_group_interval"] == 2
    assert analysis["cheaper_policy"] == "group"


def test_failure_probabilities_that_do_not_cover_a_life_are_refused(db):
    with pytest.raises(Exception) as failure:
        hardware.fleet_group_advice(
            n_items=10,
            failure_prob_by_period=[0.1, 0.2],
            unit_replace_cost=20.0,
            group_replace_cost=5.0,
        )
    assert failure.value.code == "FAILURE_PROBABILITIES_INVALID"


# --- evidence is counted, never inferred ------------------------------------


def test_linked_tickets_are_counted_and_unlinked_ones_are_not(
    db, machine, make_ticket
):
    row = machine()
    linked_open = make_ticket(external_reference="INC-L1")
    linked_open.machine_id = row.id
    linked_closed = make_ticket(external_reference="INC-L2")
    linked_closed.machine_id = row.id
    linked_closed.status = "closed"
    make_ticket(external_reference="INC-U1")
    db.commit()

    evidence = hardware.evidence_for(db, row)
    assert evidence.linked_tickets == 2
    assert evidence.open_linked_tickets == 1


def test_the_reason_says_where_the_numbers_came_from(db, machine):
    row = machine(age_months=40)
    advice = hardware.replacement_advice(row)
    reason = hardware.explain(advice, hardware.evidence_for(db, row))
    assert "Replace now" in reason
    assert "asset register export, 2026-09" in reason
    assert "No ticket has been linked" in reason


# --- through the API --------------------------------------------------------


def test_a_manager_registers_a_machine_and_reads_its_advice(client, signed_in):
    signed_in("manager")
    created = client.post(
        "/api/machines",
        json={
            "asset_tag": "WS-API-1",
            "location": "HQ",
            "machine_type": "desktop",
            "age_months": 40,
            "purchase_cost": PURCHASE,
            "scrap_value_by_year": SCRAP,
            "running_cost_by_year": RUNNING,
            "source_note": "asset register export, 2026-09",
        },
    )
    assert created.status_code == 201, created.text
    machine_id = created.json()["machine"]["id"]

    advice = client.get("/api/machines/%s/replacement-advice" % machine_id)
    assert advice.status_code == 200, advice.text
    body = advice.json()["advice"]
    assert body["verdict"] == "replace_now"
    assert body["optimal_replacement_year"] == 3
    assert len(body["table"]) == 4
    assert body["source_note"] == "asset register export, 2026-09"


def test_a_dispatcher_may_read_the_register_but_not_write_it(client, signed_in):
    signed_in("dispatcher")
    assert client.get("/api/machines").status_code == 200
    refused = client.post(
        "/api/machines",
        json={
            "asset_tag": "WS-API-2",
            "purchase_cost": PURCHASE,
            "scrap_value_by_year": SCRAP,
            "running_cost_by_year": RUNNING,
            "source_note": "n/a",
        },
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "NOT_PERMITTED"


def test_linking_a_ticket_to_a_machine_is_recorded_as_a_human_statement(
    client, db, signed_in, make_policy, make_ticket, machine
):
    signed_in("dispatcher")
    make_policy(priority=2)
    row = machine(asset_tag="WS-LINK-1")
    ticket = make_ticket(external_reference="INC-LINK-1")

    linked = client.put(
        "/api/tickets/%s/machine" % ticket.id, json={"machine_id": row.id}
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["ticket"]["machine_id"] == row.id

    history = client.get("/api/tickets/%s/events" % ticket.id).json()["events"]
    update = [e for e in history if e["event_type"] == "TICKET_UPDATED"][-1]
    assert update["payload"]["field"] == "machine_id"
    assert update["payload"]["asset_tag"] == "WS-LINK-1"
    assert update["actor_user_id"]

    cleared = client.put(
        "/api/tickets/%s/machine" % ticket.id, json={"machine_id": None}
    )
    assert cleared.json()["ticket"]["machine_id"] is None


def test_the_fleet_view_puts_the_most_overdue_machine_first(client, signed_in, machine):
    signed_in("manager")
    machine(asset_tag="WS-YOUNG", age_months=6)
    machine(asset_tag="WS-OLD", age_months=48)

    rows = client.get("/api/replacement-advice").json()["advice"]
    assert [row["asset_tag"] for row in rows][:2] == ["WS-OLD", "WS-YOUNG"]
    assert rows[0]["verdict"] == "replace_now"


def test_replacement_advice_does_not_touch_dispatch(
    client, db, signed_in, make_policy, make_agent, make_ticket, machine
):
    """A machine flagged for replacement must not change a recommendation.

    This is the claim the report makes in words; here it is the claim the test
    makes about the data. The same ticket is recommended before and after it is
    linked to a machine that is years past its replacement age, and the
    recommended resolver and stored reason have to be identical.
    """
    signed_in("dispatcher")
    make_policy(priority=2)
    agent = make_agent(display_name="Resolver One", skills=("network",))
    ticket = make_ticket(external_reference="INC-NO-EFFECT", required_skill="network")

    # The same instant for both solves. Urgency is a function of the minutes
    # left on the deadline, so two calls a second apart differ by a fraction of
    # a currency unit for reasons that have nothing to do with hardware; pinning
    # `as_of` is what makes "identical" mean identical.
    as_of = utcnow().isoformat()
    before = client.post(
        "/api/assignment-decisions",
        json={"ticket_ids": [ticket.id], "mode": "single", "as_of": as_of},
    ).json()["decisions"][0]

    row = machine(asset_tag="WS-ANCIENT", age_months=60)
    client.put("/api/tickets/%s/machine" % ticket.id, json={"machine_id": row.id})

    after = client.post(
        "/api/assignment-decisions",
        json={"ticket_ids": [ticket.id], "mode": "single", "as_of": as_of},
    ).json()["decisions"][0]

    assert before["recommended_agent"]["id"] == agent.id
    assert after["recommended_agent"]["id"] == before["recommended_agent"]["id"]
    assert after["risk_probability"] == before["risk_probability"]
    assert after["reason"] == before["reason"]
