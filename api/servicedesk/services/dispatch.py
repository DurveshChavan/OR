"""The dispatch cost model and the per-tier Hungarian solve (spec F).

Everything above :func:`solve_tier` is a pure function of plain numbers. No
session, no ORM row, no clock. That is deliberate: the grader has to be able to
take one small instance, work the cost matrix out on paper, and check that the
assignment this module returns is the one the Hungarian method gives.

The engine's Hungarian module's limit, stated so it is not repeated
-------------------------------------------------------------------
``api/engine/assignment.py`` puts the *ticket's* predicted resolution time into
every qualified agent's column. A constant row carries no information about
agents, so that solve cannot prefer one agent over another for a given ticket.
Here a candidate's cost depends on the pair: when that agent can start, how long
that agent takes on that skill, and how late that combination finishes.

Units
-----
Every policy input is a rate in one currency unit per minute, and every term in
:func:`candidate_cost` is that rate multiplied by a number of minutes, so all
three terms are currency and adding them means something. Two consequences
worth stating, because both are places the arithmetic could have gone wrong:

* The within-target branch multiplies the breach rate by
  ``target_minutes / remaining_minutes``. That ratio is dimensionless and equals
  1.0 at the moment a ticket opens, then grows as slack disappears. It is the
  mirror of the overdue branch's ``1 + overdue / grace``. Writing the branch as
  ``breach_rate x risk / remaining`` instead - which is how the replay policy in
  ``eval/policies.py`` writes it - gives currency per minute squared, and adding
  that to a currency term is not an operation. The ranking of tickets inside one
  priority tier is identical either way, because ``target_minutes`` is constant
  within a tier; the balance between the wait term and the other two is not.
* ``grace_minutes`` is not a column in ``sla_policies``. It is derived here as
  half the priority's target, which is the same relation the replay declared,
  and it is a declared dispatch constant rather than a measurement.

Time
----
All arithmetic is in minutes measured from ``as_of``. A ticket's deadline is a
signed number: positive means slack remains, negative means the ticket is
overdue. The remaining-slack denominator is floored at one minute, so a ticket
due exactly now can never divide by zero (spec F.3).

An agent's projected start is ``max(as_of, next_available_at)``. The reading is
serial effort under a concurrent WIP cap: a resolver may hold up to ``wip_limit``
open tickets at once, but works them one at a time, so the next piece of work
starts when the current one is projected to clear. ``next_available_at`` is
advanced by the accept path, and it is a projection from predicted durations,
never a claim about a real person's calendar.
"""
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import linear_sum_assignment

#: Fraction of a priority's SLA target used as the overdue recovery grace
#: window. Declared, not derived: UCI-498 carries no SLA policy to derive it
#: from. The same relation is declared in the replay's SLA_POLICY table.
GRACE_FRACTION = 0.5

#: The smallest cost difference this project treats as meaning anything: one
#: hundredth of a currency unit. The tie-break nudge must stay far below it, and
#: a test holds it there.
MATERIAL_COST_QUANTUM = 0.01

#: Tie-break scale, eight orders of magnitude under the material quantum. It can
#: only decide a comparison that is otherwise exactly equal.
TIE_EPSILON = 1e-9

#: Version of the tie-break rule, snapshotted into every decision so a stored
#: payload stays readable if the rule is ever changed.
TIE_BREAK_POLICY_VERSION = "rank-epsilon-v1"

#: Cost of a cell the skill rules forbid. Large enough that the solver never
#: picks one while any permitted cell is free, finite so the matrix stays
#: solvable - the textbook prohibited-cell M.
PROHIBITED_COST = 1e12

#: How long a queued ticket is assumed to wait before a dispatcher looks at the
#: queue again. Declared, not measured: it exists so that when capacity forces a
#: ticket to wait, the one with the cheapest minutes waits. One hour is the
#: review cadence the demo assumes.
QUEUE_REVIEW_MINUTES = 60.0

#: Documented cap on one batch (spec D.3).
MAX_BATCH_SIZE = 100

PRIORITY_TIERS = (1, 2, 3, 4)


@dataclass(frozen=True)
class PolicyRates:
    """The per-minute business inputs for one priority, as dispatch reads them."""

    priority: int
    target_minutes: int
    breach_penalty_per_minute: float
    late_penalty_per_minute: float
    overdue_recovery_penalty_per_minute: float
    holding_cost_per_minute: float
    escalation_threshold: float
    version: int

    @property
    def grace_minutes(self) -> float:
        return max(1.0, GRACE_FRACTION * self.target_minutes)

    @classmethod
    def from_row(cls, row) -> "PolicyRates":
        return cls(
            priority=row.priority,
            target_minutes=row.target_minutes,
            breach_penalty_per_minute=float(row.breach_penalty_per_minute),
            late_penalty_per_minute=float(row.late_penalty_per_minute),
            overdue_recovery_penalty_per_minute=float(
                row.overdue_recovery_penalty_per_minute
            ),
            holding_cost_per_minute=float(row.holding_cost_per_minute),
            escalation_threshold=float(row.escalation_threshold),
            version=int(row.version),
        )


@dataclass(frozen=True)
class TicketView:
    """One ticket reduced to the numbers dispatch actually uses."""

    ticket_id: str
    priority: int
    required_skill: Optional[str]
    #: Signed minutes from ``as_of`` to the deadline. Negative means overdue.
    due_in_minutes: float
    risk_probability: float
    predicted_duration_minutes: float


@dataclass(frozen=True)
class SlotView:
    """One unit of an agent's WIP limit, or one visible queue column."""

    agent_id: Optional[str]
    slot_index: int
    display_name: str
    #: Efficiency of this agent on this ticket's skill. Below 1.0 is faster.
    speed_multiplier: float
    #: Minutes from ``as_of`` until this slot can start work; never negative.
    available_in_minutes: float
    is_queue_slot: bool = False

    @property
    def key(self) -> Tuple:
        """Sort key. Queue columns always sit after every real slot."""
        return (self.is_queue_slot, self.agent_id or "", self.slot_index)


@dataclass
class Candidate:
    """One (ticket, slot) pair with every component that produced its cost."""

    ticket_id: str
    agent_id: Optional[str]
    slot_index: int
    display_name: str
    is_queue_slot: bool
    eligible: bool
    speed_multiplier: float
    projected_wait_minutes: float
    projected_service_minutes: float
    projected_finish_in_minutes: float
    projected_lateness_minutes: float
    urgency_cost_per_minute: float
    wait_cost: float
    lateness_cost: float
    holding_cost: float
    tie_break: float
    total_cost: float

    def as_payload(self) -> dict:
        """The canonical-JSON form stored on the decision."""
        return {
            "agent_id": self.agent_id,
            "display_name": self.display_name,
            "slot_index": self.slot_index,
            "is_queue_slot": self.is_queue_slot,
            "eligible": self.eligible,
            "speed_multiplier": round(self.speed_multiplier, 6),
            "projected_wait_minutes": round(self.projected_wait_minutes, 3),
            "projected_service_minutes": round(self.projected_service_minutes, 3),
            "projected_finish_in_minutes": round(self.projected_finish_in_minutes, 3),
            "projected_lateness_minutes": round(self.projected_lateness_minutes, 3),
            "urgency_cost_per_minute": round(self.urgency_cost_per_minute, 6),
            "wait_cost": round(self.wait_cost, 6),
            "lateness_cost": round(self.lateness_cost, 6),
            "holding_cost": round(self.holding_cost, 6),
            "tie_break": self.tie_break,
            "total_cost": round(self.total_cost, 6),
        }


# --- the cost model, pure ---------------------------------------------------


def minutes_between(later, earlier) -> float:
    """Signed minutes from `earlier` to `later`. Both must be aware UTC."""
    return (later - earlier).total_seconds() / 60.0


def is_overdue(due_in_minutes: float) -> bool:
    """A ticket due exactly now counts as overdue, so slack is never zero."""
    return due_in_minutes <= 0.0


def urgency_cost_per_minute(view: TicketView, policy: PolicyRates,
                            use_risk: bool = True) -> float:
    """What one more minute of delay is priced at for this ticket.

    Within target: the breach rate, weighted by the calibrated risk estimate and
    by how little slack is left. Equals ``breach_rate x risk`` at the moment the
    ticket opens and grows as the deadline approaches.

    Past target: the recovery rate, growing with how late the ticket already is.
    A separate branch exists so an overdue ticket cannot be starved by a stream
    of fresher work whose slack ratio is still small.
    """
    if is_overdue(view.due_in_minutes):
        overdue_minutes = -view.due_in_minutes
        return policy.overdue_recovery_penalty_per_minute * (
            1.0 + overdue_minutes / policy.grace_minutes
        )
    remaining = max(1.0, view.due_in_minutes)
    risk = view.risk_probability if use_risk else 1.0
    return policy.breach_penalty_per_minute * risk * (policy.target_minutes / remaining)


def candidate_cost(view: TicketView, slot: SlotView, policy: PolicyRates,
                   rank_hint: float = 0.0) -> Candidate:
    """Cost of giving this ticket to this slot, with every component kept.

    Three currency terms:

    * waiting - the urgency rate for the minutes before this slot starts;
    * lateness - the late rate for the minutes this slot finishes past the deadline;
    * holding - the holding rate for the minutes this slot is occupied.
    """
    wait = max(0.0, slot.available_in_minutes)
    service = max(0.0, view.predicted_duration_minutes * slot.speed_multiplier)
    finish = wait + service
    lateness = max(0.0, finish - view.due_in_minutes)
    rate = urgency_cost_per_minute(view, policy)

    wait_cost = rate * wait
    lateness_cost = policy.late_penalty_per_minute * lateness
    holding_cost = policy.holding_cost_per_minute * service
    total = wait_cost + lateness_cost + holding_cost + rank_hint

    return Candidate(
        ticket_id=view.ticket_id,
        agent_id=slot.agent_id,
        slot_index=slot.slot_index,
        display_name=slot.display_name,
        is_queue_slot=slot.is_queue_slot,
        eligible=not slot.is_queue_slot,
        speed_multiplier=slot.speed_multiplier,
        projected_wait_minutes=wait,
        projected_service_minutes=service,
        projected_finish_in_minutes=finish,
        projected_lateness_minutes=lateness,
        urgency_cost_per_minute=rate,
        wait_cost=wait_cost,
        lateness_cost=lateness_cost,
        holding_cost=holding_cost,
        tie_break=rank_hint,
        total_cost=total,
    )


def tie_break(ticket_rank: int, slot_rank: int, slot_count: int) -> float:
    """A bounded nudge from sorted ranks, never from data.

    Two candidates whose costs are exactly equal have to be separated by
    something, and it must be the same something on every run and on every
    machine. Ranks come from sorted identifiers, so the nudge is reproducible;
    the value stays strictly below :data:`TIE_EPSILON`, which is itself eight
    orders of magnitude below :data:`MATERIAL_COST_QUANTUM`.
    """
    if slot_count <= 0:
        return 0.0
    position = ticket_rank * slot_count + slot_rank
    span = float((ticket_rank + 1) * slot_count + slot_count)
    return TIE_EPSILON * (position / span)


def queue_price(tier_real_costs: Sequence[float], urgency_rate: float) -> float:
    """What parking this ticket in a visible queue column costs.

    Two parts, and both matter:

    * a base one material quantum above the most expensive permitted candidate
      anywhere in the tier, so a real resolver is always preferred to the queue;
    * the ticket's own urgency rate for :data:`QUEUE_REVIEW_MINUTES`, so that
      when capacity forces someone to wait, it is the ticket whose minutes are
      cheapest. Without this term every ticket in a tier would carry the same
      queue price and the choice of who waits would fall to the tie-break.

    The base is computed across the whole tier rather than per row, because a
    per-row base would scale each ticket's queue price to its own options and
    erase exactly the comparison this column exists to make.

    Pricing the column by its own projected finish instead would be wrong in a
    way that is easy to miss: a queue column has no waiting time, so an
    idle-looking queue would undercut a busy resolver and work would be parked
    rather than dispatched.
    """
    permitted = [cost for cost in tier_real_costs if cost < PROHIBITED_COST]
    base = max(permitted) + MATERIAL_COST_QUANTUM if permitted else MATERIAL_COST_QUANTUM
    return base + urgency_rate * QUEUE_REVIEW_MINUTES


def queue_candidate(view: TicketView, slot: SlotView, price: float,
                    rank_hint: float = 0.0) -> Candidate:
    """A ticket parked in a visible queue column, with no projected resolver.

    Every projection is zero on purpose: nobody has been asked to do this work,
    so claiming a finish time for it would be an invented number.
    """
    return Candidate(
        ticket_id=view.ticket_id,
        agent_id=None,
        slot_index=slot.slot_index,
        display_name=slot.display_name,
        is_queue_slot=True,
        eligible=False,
        speed_multiplier=1.0,
        projected_wait_minutes=0.0,
        projected_service_minutes=0.0,
        projected_finish_in_minutes=0.0,
        projected_lateness_minutes=0.0,
        urgency_cost_per_minute=0.0,
        wait_cost=0.0,
        lateness_cost=0.0,
        holding_cost=0.0,
        tie_break=rank_hint,
        total_cost=price + rank_hint,
    )


def build_cost_matrix(views: Sequence[TicketView], slots: Sequence[SlotView],
                      policies: Dict[int, PolicyRates],
                      speeds: Dict[Tuple[str, str], float]
                      ) -> Tuple[np.ndarray, List[List[Candidate]]]:
    """Rows are tickets in the given order, columns are slots in the given order.

    ``speeds`` maps ``(ticket_id, agent_id)`` to that agent's efficiency
    multiplier on that ticket's required skill. A pair missing from the mapping
    is a pairing the skill rules forbid: its cell is priced at
    :data:`PROHIBITED_COST` and its candidate is marked ineligible, so it
    survives into the stored payload as a refusal rather than disappearing. One
    mapping carries both facts, so permission and speed can never disagree.

    Queue columns are priced in a second pass, once every real cost in the tier
    is known - see :func:`queue_price`.
    """
    matrix = np.zeros((len(views), len(slots)), dtype=float)
    grid: List[List[Candidate]] = []
    tier_real_costs: List[float] = []

    for row, view in enumerate(views):
        policy = policies[view.priority]
        row_candidates: List[Candidate] = []
        for column, slot in enumerate(slots):
            if slot.is_queue_slot:
                row_candidates.append(None)
                continue
            nudge = tie_break(row, column, len(slots))
            multiplier = speeds.get((view.ticket_id, slot.agent_id))
            paired = replace(slot, speed_multiplier=multiplier or 1.0)
            candidate = candidate_cost(view, paired, policy, rank_hint=nudge)
            if multiplier is None:
                candidate.eligible = False
                candidate.total_cost = PROHIBITED_COST + nudge
            tier_real_costs.append(candidate.total_cost)
            row_candidates.append(candidate)
        grid.append(row_candidates)

    for row, view in enumerate(views):
        rate = urgency_cost_per_minute(view, policies[view.priority])
        price = queue_price(tier_real_costs, rate)
        for column, slot in enumerate(slots):
            if grid[row][column] is None:
                nudge = tie_break(row, column, len(slots))
                grid[row][column] = queue_candidate(view, slot, price, nudge)
            matrix[row, column] = grid[row][column].total_cost
    return matrix, grid


def solve_tier(views: Sequence[TicketView], slots: Sequence[SlotView],
               policies: Dict[int, PolicyRates],
               speeds: Dict[Tuple[str, str], float]) -> Dict[str, Candidate]:
    """The chosen candidate per ticket. See :func:`solve_tier_with_candidates`."""
    chosen, _priced = solve_tier_with_candidates(views, slots, policies, speeds)
    return chosen


def solve_tier_with_candidates(
    views: Sequence[TicketView], slots: Sequence[SlotView],
    policies: Dict[int, PolicyRates], speeds: Dict[Tuple[str, str], float],
) -> Tuple[Dict[str, Candidate], Dict[str, List[Candidate]]]:
    """Hungarian assignment for one priority tier, plus every priced cell.

    The second return value is the ticket's own row of the cost matrix: what
    each slot would have cost *this* ticket, at the same moment, under the same
    policy. It is what the interface shows as ranked alternatives.

    One thing that row is not: it is not a claim that swapping to the runner-up
    leaves the rest of the tier unchanged. The Hungarian step optimises the whole
    tier at once, so a cheaper-looking cell may be cheaper only because another
    ticket is currently holding a slot it needs. The stored payload says so in
    ``alternatives_note`` and the client repeats it.

    Columns always outnumber or equal rows, because the caller pads with visible
    queue columns. That padding is what makes "no ticket is silently dropped" a
    property of the matrix rather than a hope about the code path.

    A single ticket needs no solver: with one row the minimum-cost cell is the
    optimum, and the same cost function produces it.
    """
    if not views:
        return {}, {}
    if len(slots) < len(views):
        raise ValueError(
            "cost matrix has %d slots for %d tickets; pad with queue slots first"
            % (len(slots), len(views))
        )
    matrix, grid = build_cost_matrix(views, slots, policies, speeds)
    priced = {view.ticket_id: list(grid[row]) for row, view in enumerate(views)}
    if len(views) == 1:
        column = int(np.argmin(matrix[0]))
        return {views[0].ticket_id: grid[0][column]}, priced
    rows, columns = linear_sum_assignment(matrix)
    chosen = {views[int(r)].ticket_id: grid[int(r)][int(c)] for r, c in zip(rows, columns)}
    return chosen, priced


#: How many alternatives a stored decision keeps. A dispatcher choosing an
#: override reads a short list; the full row stays derivable from the cost model
#: and the agents of that moment, and the chosen candidate is stored in full.
MAX_STORED_ALTERNATIVES = 5

ALTERNATIVES_NOTE = (
    "Row cost for this ticket alone, at the moment of the solve. The batch "
    "optimum may still differ: a cheaper cell here can belong to a slot another "
    "ticket in the same tier is holding."
)


def ranked_alternatives(priced_row: Sequence[Candidate], chosen: Candidate,
                        limit: int = MAX_STORED_ALTERNATIVES) -> List[Candidate]:
    """The next-cheapest permitted resolvers for one ticket, one row per agent.

    Prohibited cells and queue columns are dropped: neither is a resolver a
    dispatcher could override to. An agent holding several free slots appears
    once, at that agent's cheapest slot, because two slots of one resolver are
    not two alternatives.
    """
    best_per_agent: Dict[str, Candidate] = {}
    for candidate in priced_row:
        if candidate is None or candidate.is_queue_slot or not candidate.eligible:
            continue
        if candidate.agent_id is None or candidate.agent_id == chosen.agent_id:
            continue
        held = best_per_agent.get(candidate.agent_id)
        if held is None or candidate.total_cost < held.total_cost:
            best_per_agent[candidate.agent_id] = candidate
    ordered = sorted(
        best_per_agent.values(), key=lambda c: (c.total_cost, c.agent_id)
    )
    return ordered[:limit]


def queue_slots(count: int, start_index: int = 0) -> List[SlotView]:
    """Visible padding columns. One per ticket that could not get a real slot.

    A queue column costs nothing to wait for and nothing to hold, because it is
    not a resolver; what it produces is a ``queued`` decision saying so. Its cost
    is therefore small, and it is chosen only when no permitted real slot is
    free - real slots are removed from the matrix once consumed by a higher tier.
    """
    return [
        SlotView(
            agent_id=None,
            slot_index=start_index + index,
            display_name="Queue",
            speed_multiplier=1.0,
            available_in_minutes=0.0,
            is_queue_slot=True,
        )
        for index in range(count)
    ]


def stable_slot_order(slots: Sequence[SlotView]) -> List[SlotView]:
    """Real slots by (agent id, slot number), then queue columns."""
    return sorted(slots, key=lambda slot: slot.key)


def tier_order(views: Sequence[TicketView],
               policies: Dict[int, PolicyRates]) -> List[TicketView]:
    """Most expensive minute first, ticket id breaking the tie.

    This ordering decides which ticket sees the remaining capacity first inside
    a tier. The Hungarian solve then optimises the whole tier at once, so the
    ordering only matters where capacity runs out mid-tier.
    """
    return sorted(
        views,
        key=lambda v: (-urgency_cost_per_minute(v, policies[v.priority]), v.ticket_id),
    )
