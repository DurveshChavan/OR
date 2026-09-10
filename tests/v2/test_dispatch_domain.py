"""The dispatch cost model, checked against arithmetic done by hand.

Nothing here touches a database. Every expected number in this file was worked
out from the formulas in ``services/dispatch.py`` before the code was run, which
is the only kind of test that can catch the cost model being wrong rather than
merely being stable.

The worked instance
-------------------
Two priority-2 tickets, two resolvers, one slot each. The policy is
``target_minutes = 240``, ``breach = 10.0``, ``late = 4.0``, ``holding = 0.5``
per minute, so ``grace = 120``.

* Ticket A: 60 minutes of slack left, risk 0.50, predicted duration 100 minutes.
* Ticket B: 120 minutes of slack left, risk 0.25, predicted duration 100 minutes.
* Resolver FAST: free now, multiplier 0.5.
* Resolver SLOW: free in 30 minutes, multiplier 1.0.

Urgency rates:
    A: 10.0 x 0.50 x (240 / 60) = 20.0 per minute
    B: 10.0 x 0.25 x (240 / 120) = 5.0 per minute

Candidate costs, wait x urgency + late x lateness + holding x service:
    A-FAST: 0 + 4.0 x max(0, 50 - 60)=0 + 0.5 x 50   =  25.0
    A-SLOW: 20.0 x 30 = 600 + 4.0 x (130 - 60)=280 + 0.5 x 100 = 930.0
    B-FAST: 0 + 4.0 x max(0, 50 - 120)=0 + 0.5 x 50  =  25.0
    B-SLOW: 5.0 x 30 = 150 + 4.0 x max(0, 130 - 120)=40 + 50   = 240.0

Greedy on the tier order (A is more urgent, so A picks first) takes A-FAST at
25.0 and leaves B-SLOW at 240.0, total 265.0. The Hungarian optimum is A-SLOW
plus B-FAST at 930 + 25 = 955, or A-FAST plus B-SLOW at 265: the optimum here is
265.0 and greedy happens to find it. The instance that separates them is built
in ``test_hungarian_beats_greedy_when_the_greedy_pick_is_locally_cheap``.
"""
import pytest

from api.app_v2.services import dispatch

POLICY = dispatch.PolicyRates(
    priority=2,
    target_minutes=240,
    breach_penalty_per_minute=10.0,
    late_penalty_per_minute=4.0,
    overdue_recovery_penalty_per_minute=6.0,
    holding_cost_per_minute=0.5,
    escalation_threshold=0.7,
    version=1,
)
POLICIES = {2: POLICY, 1: POLICY, 4: POLICY}


def ticket(ticket_id, due_in, risk=0.5, duration=100.0, priority=2):
    return dispatch.TicketView(
        ticket_id=ticket_id,
        priority=priority,
        required_skill="network",
        due_in_minutes=due_in,
        risk_probability=risk,
        predicted_duration_minutes=duration,
    )


def slot(agent_id, available_in=0.0, index=0):
    return dispatch.SlotView(
        agent_id=agent_id,
        slot_index=index,
        display_name=agent_id,
        speed_multiplier=1.0,
        available_in_minutes=available_in,
    )


FAST = slot("agent-fast", available_in=0.0)
SLOW = slot("agent-slow", available_in=30.0)
TICKET_A = ticket("ticket-a", due_in=60.0, risk=0.50)
TICKET_B = ticket("ticket-b", due_in=120.0, risk=0.25)
SPEEDS = {
    ("ticket-a", "agent-fast"): 0.5,
    ("ticket-a", "agent-slow"): 1.0,
    ("ticket-b", "agent-fast"): 0.5,
    ("ticket-b", "agent-slow"): 1.0,
}


def approx(value):
    return pytest.approx(value, abs=1e-6)


# --- the rates --------------------------------------------------------------


def test_urgency_rate_matches_the_hand_calculation():
    assert dispatch.urgency_cost_per_minute(TICKET_A, POLICY) == approx(20.0)
    assert dispatch.urgency_cost_per_minute(TICKET_B, POLICY) == approx(5.0)


def test_urgency_equals_breach_times_risk_at_the_moment_of_opening():
    """The slack ratio is 1.0 when a ticket has its whole window left."""
    fresh = ticket("fresh", due_in=float(POLICY.target_minutes), risk=0.4)
    assert dispatch.urgency_cost_per_minute(fresh, POLICY) == approx(10.0 * 0.4)


def test_an_overdue_ticket_uses_the_recovery_branch_and_grows_with_lateness():
    at_deadline = ticket("t", due_in=0.0)
    just_late = ticket("t", due_in=-60.0)
    very_late = ticket("t", due_in=-240.0)

    # grace is half of 240, so 60 minutes late is one half-grace: 6.0 x 1.5.
    assert dispatch.urgency_cost_per_minute(at_deadline, POLICY) == approx(6.0)
    assert dispatch.urgency_cost_per_minute(just_late, POLICY) == approx(9.0)
    assert dispatch.urgency_cost_per_minute(very_late, POLICY) == approx(18.0)


def test_a_ticket_due_exactly_now_never_divides_by_zero():
    """Spec F.3: the zero-slack boundary is the recovery branch, not a crash."""
    assert dispatch.is_overdue(0.0)
    assert dispatch.urgency_cost_per_minute(ticket("t", due_in=0.0), POLICY) > 0.0


def test_remaining_slack_is_floored_at_one_minute():
    """A ticket 30 seconds from its deadline must not produce a rate of 40.0."""
    almost = ticket("t", due_in=0.5, risk=1.0)
    assert dispatch.urgency_cost_per_minute(almost, POLICY) == approx(
        10.0 * 1.0 * (240 / 1.0)
    )


# --- candidate costs --------------------------------------------------------


def test_candidate_costs_match_the_hand_calculation():
    from dataclasses import replace

    a_fast = dispatch.candidate_cost(TICKET_A, replace(FAST, speed_multiplier=0.5), POLICY)
    a_slow = dispatch.candidate_cost(TICKET_A, SLOW, POLICY)
    b_slow = dispatch.candidate_cost(TICKET_B, SLOW, POLICY)

    assert a_fast.total_cost == approx(25.0)
    assert a_slow.total_cost == approx(930.0)
    assert b_slow.total_cost == approx(240.0)

    # The components have to add up to the total, or the stored payload would
    # describe a different calculation from the one that ranked the candidate.
    assert a_slow.wait_cost + a_slow.lateness_cost + a_slow.holding_cost == approx(930.0)


def test_a_busier_agent_costs_more_for_the_same_ticket():
    """Availability changes candidate cost - the legacy build's constant row bug."""
    from dataclasses import replace

    idle = dispatch.candidate_cost(TICKET_A, FAST, POLICY)
    busy = dispatch.candidate_cost(TICKET_A, replace(FAST, available_in_minutes=45.0), POLICY)
    assert busy.total_cost > idle.total_cost


def test_the_cost_row_is_not_constant_across_agents():
    matrix, _grid = dispatch.build_cost_matrix(
        [TICKET_A], [FAST, SLOW], POLICIES, SPEEDS
    )
    assert matrix[0][0] != matrix[0][1]


# --- the solve --------------------------------------------------------------


def test_an_exact_skill_beats_a_pairing_the_rules_forbid():
    """A pairing missing from `speeds` is prohibited, not merely expensive."""
    speeds = {("ticket-a", "agent-slow"): 1.0}
    matrix, grid = dispatch.build_cost_matrix([TICKET_A], [FAST, SLOW], POLICIES, speeds)
    assert matrix[0][0] >= dispatch.PROHIBITED_COST
    assert grid[0][0].eligible is False
    assert grid[0][1].eligible is True

    chosen = dispatch.solve_tier([TICKET_A], [FAST, SLOW], POLICIES, speeds)
    assert chosen["ticket-a"].agent_id == "agent-slow"


def test_hungarian_beats_greedy_when_the_greedy_pick_is_locally_cheap():
    """A 2x2 instance where taking the cheapest cell first costs more overall.

    Worked by hand. Ticket U is urgent (20.0 per minute) and ticket V is not
    (5.0 per minute). Only resolver ONE can work V.

        U-ONE   = 0 + 4 x max(0, 20 - 60) + 0.5 x 20   =  10.0
        U-TWO   = 0 + 4 x max(0, 40 - 60) + 0.5 x 40   =  20.0
        V-ONE   = 0 + 4 x max(0, 20 - 120) + 0.5 x 20  =  10.0
        V-TWO   = prohibited

    Greedy over the tier order gives U the cheapest cell, U-ONE at 10.0, and V
    is then left with a prohibited column. Hungarian pays 20.0 for U-TWO and
    10.0 for V-ONE: 30.0 against a greedy assignment that cannot be completed.
    """
    urgent = ticket("ticket-u", due_in=60.0, risk=0.5, duration=40.0)
    relaxed = ticket("ticket-v", due_in=120.0, risk=0.25, duration=40.0)
    one = slot("agent-one")
    two = slot("agent-two")
    speeds = {
        ("ticket-u", "agent-one"): 0.5,
        ("ticket-u", "agent-two"): 1.0,
        ("ticket-v", "agent-one"): 0.5,
    }
    views = dispatch.tier_order([urgent, relaxed], POLICIES)
    assert [view.ticket_id for view in views] == ["ticket-u", "ticket-v"]

    chosen = dispatch.solve_tier(views, [one, two], POLICIES, speeds)
    assert chosen["ticket-u"].agent_id == "agent-two"
    assert chosen["ticket-v"].agent_id == "agent-one"
    assert chosen["ticket-u"].total_cost == approx(20.0 + chosen["ticket-u"].tie_break)
    assert chosen["ticket-v"].total_cost == approx(10.0 + chosen["ticket-v"].tie_break)


def test_a_single_ticket_needs_no_solver_and_agrees_with_the_matrix():
    chosen = dispatch.solve_tier([TICKET_A], [FAST, SLOW], POLICIES, SPEEDS)
    matrix, _grid = dispatch.build_cost_matrix([TICKET_A], [FAST, SLOW], POLICIES, SPEEDS)
    assert chosen["ticket-a"].agent_id == "agent-fast"
    assert chosen["ticket-a"].total_cost == approx(min(matrix[0]))


def test_more_tickets_than_slots_is_refused_rather_than_dropping_one():
    with pytest.raises(ValueError, match="pad with queue slots"):
        dispatch.solve_tier([TICKET_A, TICKET_B], [FAST], POLICIES, SPEEDS)


def test_padding_with_queue_columns_gives_every_ticket_an_outcome():
    views = dispatch.tier_order([TICKET_A, TICKET_B], POLICIES)
    padded = [FAST] + dispatch.queue_slots(2, start_index=1)
    chosen = dispatch.solve_tier(views, padded, POLICIES, SPEEDS)

    assert set(chosen) == {"ticket-a", "ticket-b"}
    placed = [c for c in chosen.values() if not c.is_queue_slot]
    queued = [c for c in chosen.values() if c.is_queue_slot]
    assert len(placed) == 1 and len(queued) == 1
    # The urgent ticket is the one that gets the only real slot.
    assert chosen["ticket-a"].agent_id == "agent-fast"


def test_a_queue_column_never_undercuts_an_available_resolver():
    """The failure this guards: an idle-looking queue parking dispatchable work.

    A queue column has no waiting time and no service time, so pricing it by its
    own projection would make it cheaper than every busy resolver.
    """
    padded = [SLOW] + dispatch.queue_slots(1, start_index=1)
    chosen = dispatch.solve_tier([TICKET_A], padded, POLICIES, SPEEDS)
    assert chosen["ticket-a"].agent_id == "agent-slow"


def test_queue_price_clears_the_worst_real_option_and_charges_for_urgency():
    """Base above every real candidate in the tier, plus one review cycle of urgency."""
    assert dispatch.queue_price([10.0, 240.0], 0.0) == approx(
        240.0 + dispatch.MATERIAL_COST_QUANTUM
    )
    assert dispatch.queue_price([10.0, 240.0], 20.0) == approx(
        240.0 + dispatch.MATERIAL_COST_QUANTUM + 20.0 * dispatch.QUEUE_REVIEW_MINUTES
    )
    # A tier where every pairing is prohibited still yields a finite price.
    assert dispatch.queue_price([dispatch.PROHIBITED_COST], 0.0) == approx(
        dispatch.MATERIAL_COST_QUANTUM
    )


def test_the_cheaper_minutes_are_the_ones_that_wait():
    """Two tickets, one real slot: the less urgent ticket takes the queue column.

    Both tickets cost 25.0 on the only free resolver, so nothing in the real
    columns separates them. What decides it is the price of waiting. The tier's
    worst permitted real cost is 25.0, so the queue base is 25.01, and each
    ticket adds its own urgency rate for one QUEUE_REVIEW_MINUTES cycle:

        A queued = 25.01 + 20.0 x 60 = 1225.01
        B queued = 25.01 +  5.0 x 60 =  325.01

    A on the resolver with B queued costs 25.0 + 325.01 = 350.01; the other way
    round costs 25.0 + 1225.01 = 1250.01. So B waits.
    """
    views = dispatch.tier_order([TICKET_A, TICKET_B], POLICIES)
    padded = [FAST] + dispatch.queue_slots(2, start_index=1)
    chosen = dispatch.solve_tier(views, padded, POLICIES, SPEEDS)
    assert chosen["ticket-a"].agent_id == "agent-fast"
    assert chosen["ticket-b"].is_queue_slot is True


# --- determinism ------------------------------------------------------------


def test_the_same_inputs_in_a_different_order_give_the_same_decision():
    forward = dispatch.solve_tier(
        dispatch.tier_order([TICKET_A, TICKET_B], POLICIES),
        dispatch.stable_slot_order([FAST, SLOW]), POLICIES, SPEEDS,
    )
    backward = dispatch.solve_tier(
        dispatch.tier_order([TICKET_B, TICKET_A], POLICIES),
        dispatch.stable_slot_order([SLOW, FAST]), POLICIES, SPEEDS,
    )
    assert {k: v.agent_id for k, v in forward.items()} == {
        k: v.agent_id for k, v in backward.items()
    }


def test_the_tie_break_stays_below_the_declared_material_threshold():
    """Bounded against a declared quantum, not against whatever the code emits."""
    for ticket_rank in range(50):
        for slot_rank in range(50):
            nudge = dispatch.tie_break(ticket_rank, slot_rank, 50)
            assert 0.0 <= nudge < dispatch.TIE_EPSILON
            assert nudge < dispatch.MATERIAL_COST_QUANTUM / 1e6


def test_the_tie_break_separates_two_identical_candidates():
    left = slot("agent-aaa")
    right = slot("agent-bbb")
    speeds = {("ticket-a", "agent-aaa"): 1.0, ("ticket-a", "agent-bbb"): 1.0}
    matrix, _grid = dispatch.build_cost_matrix(
        [TICKET_A], dispatch.stable_slot_order([right, left]), POLICIES, speeds
    )
    assert matrix[0][0] != matrix[0][1]
    assert abs(matrix[0][0] - matrix[0][1]) < dispatch.TIE_EPSILON


def test_slot_order_puts_queue_columns_after_every_real_slot():
    mixed = dispatch.queue_slots(2) + [SLOW, FAST]
    ordered = dispatch.stable_slot_order(mixed)
    assert [s.agent_id for s in ordered[:2]] == ["agent-fast", "agent-slow"]
    assert all(s.is_queue_slot for s in ordered[2:])


def test_tier_order_puts_the_most_expensive_minute_first():
    ordered = dispatch.tier_order([TICKET_B, TICKET_A], POLICIES)
    assert [view.ticket_id for view in ordered] == ["ticket-a", "ticket-b"]


def test_an_overdue_ticket_is_not_starved_by_a_fresher_one():
    """The recovery branch has to out-rank a fresh ticket of the same priority."""
    overdue = ticket("ticket-overdue", due_in=-180.0, risk=0.1)
    fresh = ticket("ticket-fresh", due_in=200.0, risk=0.9)
    ordered = dispatch.tier_order([fresh, overdue], POLICIES)
    assert ordered[0].ticket_id == "ticket-overdue"
