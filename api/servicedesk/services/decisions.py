"""Turning a dispatch solve into immutable rows, and acting on one afterwards.

``dispatch.py`` holds the arithmetic and knows nothing about a database. This
module is the other half: it reads the tickets, agents and policies, hands plain
numbers to the solver, and writes what came back as one immutable decision per
ticket plus the events that explain it.

Three properties are enforced here rather than assumed:

* **Every requested ticket gets a row.** A tier is padded with visible queue
  columns before the solve, so a ticket with no free slot produces a ``queued``
  decision. A ticket no active agent can work produces ``no_eligible_agent``
  before the solve is reached. Neither is a silent omission.
* **The recommendation is never the assignment.** Nothing in this module sets
  ``current_assignee_id`` during recommendation. Only accept and override do,
  and both re-verify eligibility at that moment.
* **A decision row is written once.** Acceptance and override add events; they
  never touch the decision. That is what lets a ticket page show what was
  recommended beside what a human actually chose.
"""
import uuid
from datetime import timedelta
from typing import Dict, List, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from api.servicedesk.db import models
from api.servicedesk.db.types import utcnow
from api.servicedesk.errors import ApiError
from api.servicedesk.services import dispatch, eligibility, events, reasons, scoring

#: A decision is stale once the policy or the model behind it has moved on.
#: Accepting a stale decision is refused; the dispatcher rescores first.
STALE_CODES = ("DECISION_STALE",)


def recommend(db: DbSession, actor: models.User, ticket_ids: Sequence[str],
              as_of=None, mode: str = "batch") -> List[models.AssignmentDecision]:
    """Produce one immutable decision per requested ticket (spec D.3, F.2).

    The caller commits. Everything written here - decisions and events alike -
    belongs to the same transaction as the solve that produced it.
    """
    as_of = as_of or utcnow()
    ordered_ids = sorted(set(ticket_ids))
    if not ordered_ids:
        raise ApiError("NO_TICKETS_REQUESTED", "Request at least one ticket.", 422)
    if len(ordered_ids) > dispatch.MAX_BATCH_SIZE:
        raise ApiError(
            "BATCH_TOO_LARGE",
            "A batch may hold at most %d tickets; %d were requested."
            % (dispatch.MAX_BATCH_SIZE, len(ordered_ids)),
            status_code=422,
            details={"max_batch_size": dispatch.MAX_BATCH_SIZE},
        )

    tickets = _open_tickets(db, ordered_ids)
    policies = _policies(db, {ticket.priority for ticket in tickets})
    capacities = eligibility.load_capacities(db)
    scores = scoring.score_tickets(tickets)
    batch_id = uuid.uuid4().hex if mode == "batch" else None

    views, speeds, eligible_counts, no_agent = _build_views(
        tickets, capacities, scores, as_of
    )
    written: Dict[str, models.AssignmentDecision] = {}

    for ticket in no_agent:
        written[ticket.id] = _write_no_eligible_agent(
            db, actor, ticket, scores[ticket.id], policies[ticket.priority], batch_id
        )

    remaining_slots = _free_slots(capacities, as_of)
    by_id = {ticket.id: ticket for ticket in tickets}
    for tier in dispatch.PRIORITY_TIERS:
        tier_views = [view for view in views if view.priority == tier]
        if not tier_views:
            continue
        tier_views = dispatch.tier_order(tier_views, policies)
        slots = dispatch.stable_slot_order(remaining_slots)
        padded = slots + dispatch.queue_slots(len(tier_views), start_index=len(slots))
        chosen, priced = dispatch.solve_tier_with_candidates(
            tier_views, padded, policies, speeds
        )

        consumed = set()
        for view in tier_views:
            candidate = chosen[view.ticket_id]
            ticket = by_id[view.ticket_id]
            written[ticket.id] = _write_candidate_decision(
                db, actor, ticket, view, candidate, policies[tier],
                scores[ticket.id], eligible_counts[ticket.id], batch_id, as_of,
                alternatives=dispatch.ranked_alternatives(
                    priced[view.ticket_id], candidate
                ),
            )
            if not candidate.is_queue_slot:
                consumed.add((candidate.agent_id, candidate.slot_index))
        # A slot consumed by this tier is gone before the next tier sees the
        # matrix. That is what makes "P1 consumes its slots before P2-P4" true
        # of the data rather than of the loop order alone.
        remaining_slots = [
            slot for slot in remaining_slots
            if (slot.agent_id, slot.slot_index) not in consumed
        ]

    return [written[ticket_id] for ticket_id in ordered_ids if ticket_id in written]


def _open_tickets(db: DbSession, ticket_ids) -> List[models.Ticket]:
    """Every requested ticket, or a failure naming exactly which ones failed."""
    rows = db.scalars(
        select(models.Ticket).where(models.Ticket.id.in_(list(ticket_ids)))
    ).all()
    found = {row.id: row for row in rows}
    missing = [ticket_id for ticket_id in ticket_ids if ticket_id not in found]
    not_open = sorted(
        row.id for row in rows if row.status in models.TERMINAL_TICKET_STATUSES
    )
    if missing or not_open:
        raise ApiError(
            "TICKETS_NOT_DISPATCHABLE",
            "%d requested ticket(s) do not exist and %d are already closed."
            % (len(missing), len(not_open)),
            status_code=422,
            details={"missing": missing, "terminal": not_open},
        )
    return [found[ticket_id] for ticket_id in ticket_ids]


def _policies(db: DbSession, priorities) -> Dict[int, dispatch.PolicyRates]:
    rows = db.scalars(
        select(models.SlaPolicy).where(models.SlaPolicy.priority.in_(sorted(priorities)))
    ).all()
    found = {row.priority: dispatch.PolicyRates.from_row(row) for row in rows}
    missing = sorted(set(priorities) - set(found))
    if missing:
        raise ApiError(
            "SLA_POLICY_MISSING",
            "No SLA policy is configured for priority %s."
            % ", ".join(str(p) for p in missing),
            status_code=409,
            details={"priorities": missing},
        )
    return found


def _build_views(tickets, capacities, scores, as_of):
    """Split the batch into solvable views and tickets nobody can work.

    ``speeds`` maps ``(ticket_id, agent_id)`` to the efficiency multiplier of
    that pairing. Being in the mapping *is* the permission, so the matrix builder
    never has to look a skill up and cannot price a cell it was not allowed to.
    """
    views = []
    speeds = {}
    eligible_counts = {}
    no_agent = []
    for ticket in tickets:
        holders = eligibility.eligible_for(ticket, capacities)
        eligible_counts[ticket.id] = len(holders)
        if not holders:
            no_agent.append(ticket)
            continue
        for capacity in holders:
            speeds[(ticket.id, capacity.agent_id)] = capacity.multiplier_for(
                ticket.required_skill
            )
        score = scores[ticket.id]
        views.append(
            dispatch.TicketView(
                ticket_id=ticket.id,
                priority=ticket.priority,
                required_skill=ticket.required_skill,
                due_in_minutes=dispatch.minutes_between(ticket.sla_due_at, as_of),
                risk_probability=score.risk_probability,
                predicted_duration_minutes=score.predicted_duration_minutes,
            )
        )
    return views, speeds, eligible_counts, no_agent


def _free_slots(capacities, as_of) -> List[dispatch.SlotView]:
    """One column per free WIP slot, ordered by agent id then slot number.

    ``available_in_minutes`` comes from the agent's ``next_available_at``
    projection and is the same for every slot of one agent: the WIP limit caps
    how many tickets a resolver may hold at once, while effort is serial, so the
    next piece of work starts when the current one is projected to clear. A null
    projection means the resolver can start now.

    The speed multiplier is a property of the pairing, not of the slot, so it is
    left at 1.0 here and supplied per cell by the matrix builder.
    """
    slots = []
    for capacity in capacities:
        available = 0.0
        if capacity.next_available_at is not None:
            available = max(0.0, dispatch.minutes_between(capacity.next_available_at, as_of))
        for index in range(capacity.free_slots):
            slots.append(
                dispatch.SlotView(
                    agent_id=capacity.agent_id,
                    slot_index=index,
                    display_name=capacity.display_name,
                    speed_multiplier=1.0,
                    available_in_minutes=available,
                )
            )
    return dispatch.stable_slot_order(slots)


def _write_candidate_decision(db, actor, ticket, view, candidate, policy, score,
                              eligible_count, batch_id, as_of, alternatives=()):
    """Persist one solved candidate as a decision plus its event."""
    payload = _candidate_payload(view, candidate, policy, eligible_count, alternatives)

    if candidate.is_queue_slot:
        reason = reasons.queued_reason(ticket.required_skill, eligible_count, 0)
        decision = _insert_decision(
            db, ticket, "queued", None, score, policy, payload, reason, batch_id,
            projected_finish_at=None, wait_minutes=None, lateness_minutes=None,
        )
        events.record(
            db, ticket.id, "QUEUED_FOR_TRIAGE", actor_user_id=actor.id,
            decision_id=decision.id,
            payload={"batch_id": batch_id, "eligible_agents": eligible_count},
        )
        return decision

    reason = reasons.recommended_reason(
        candidate.as_payload(), score.risk_probability, view.due_in_minutes,
        eligible_count,
    )
    decision = _insert_decision(
        db, ticket, "recommended", candidate.agent_id, score, policy, payload,
        reason, batch_id,
        projected_finish_at=as_of + timedelta(minutes=candidate.projected_finish_in_minutes),
        wait_minutes=candidate.projected_wait_minutes,
        lateness_minutes=candidate.projected_lateness_minutes,
    )
    events.record(
        db, ticket.id, "ASSIGNMENT_RECOMMENDED", actor_user_id=actor.id,
        decision_id=decision.id,
        payload={
            "batch_id": batch_id,
            "recommended_agent_id": candidate.agent_id,
            "total_cost": round(candidate.total_cost, 6),
        },
    )
    _maybe_recommend_escalation(db, actor, ticket, decision, score, policy)
    return decision


def _write_no_eligible_agent(db, actor, ticket, score, policy, batch_id):
    reason = reasons.no_eligible_agent_reason(ticket.required_skill)
    payload = {
        "alternatives": [],
        "alternatives_note": dispatch.ALTERNATIVES_NOTE,
        "eligible_agent_count": 0,
        "required_skill": ticket.required_skill,
        "tie_break_policy_version": dispatch.TIE_BREAK_POLICY_VERSION,
        "tie_break_epsilon": dispatch.TIE_EPSILON,
    }
    decision = _insert_decision(
        db, ticket, "no_eligible_agent", None, score, policy, payload, reason,
        batch_id, projected_finish_at=None, wait_minutes=None, lateness_minutes=None,
    )
    events.record(
        db, ticket.id, "NO_ELIGIBLE_AGENT", actor_user_id=actor.id,
        decision_id=decision.id,
        payload={"batch_id": batch_id, "required_skill": ticket.required_skill},
    )
    return decision


def _insert_decision(db, ticket, state, agent_id, score, policy, payload, reason,
                     batch_id, projected_finish_at, wait_minutes, lateness_minutes):
    decision = models.AssignmentDecision(
        ticket_id=ticket.id,
        batch_id=batch_id,
        recommended_agent_id=agent_id,
        recommendation_state=state,
        risk_probability=score.risk_probability,
        predicted_duration_minutes=score.predicted_duration_minutes,
        projected_wait_minutes=wait_minutes,
        projected_finish_at=projected_finish_at,
        projected_lateness_minutes=lateness_minutes,
        model_version=score.risk_model_version,
        policy_version=policy.version,
        candidate_payload_json=payload,
        reason_text=reason,
    )
    db.add(decision)
    db.flush()
    return decision


def _candidate_payload(view, chosen, policy, eligible_count, alternatives=()) -> dict:
    """Everything the solve saw for this ticket, plus what it chose.

    ``alternatives`` is the rest of this ticket's own matrix row, cheapest
    first, one entry per eligible resolver. It is stored rather than recomputed
    for display because a recomputed alternative would be priced against a later
    moment's availability and would not be the comparison the solve actually
    made.

    No hidden outcome and no future field (spec C.2): the payload holds inputs,
    cost components and the tie-break value, and nothing that could only be known
    after the work was done.
    """
    return {
        "alternatives": [candidate.as_payload() for candidate in alternatives],
        "alternatives_note": dispatch.ALTERNATIVES_NOTE,
        "as_of_due_in_minutes": round(view.due_in_minutes, 3),
        "chosen": chosen.as_payload(),
        "eligible_agent_count": eligible_count,
        "policy": {
            "priority": policy.priority,
            "target_minutes": policy.target_minutes,
            "grace_minutes": policy.grace_minutes,
            "breach_penalty_per_minute": policy.breach_penalty_per_minute,
            "late_penalty_per_minute": policy.late_penalty_per_minute,
            "overdue_recovery_penalty_per_minute":
                policy.overdue_recovery_penalty_per_minute,
            "holding_cost_per_minute": policy.holding_cost_per_minute,
            "version": policy.version,
        },
        "predicted_duration_minutes": round(view.predicted_duration_minutes, 3),
        "risk_probability": round(view.risk_probability, 6),
        "tie_break_epsilon": dispatch.TIE_EPSILON,
        "tie_break_policy_version": dispatch.TIE_BREAK_POLICY_VERSION,
    }


def _maybe_recommend_escalation(db, actor, ticket, decision, score, policy):
    """An escalation recommendation is an event, never an automatic action (B.2)."""
    if score.risk_probability < policy.escalation_threshold:
        return
    events.record(
        db, ticket.id, "ESCALATION_RECOMMENDED", actor_user_id=actor.id,
        decision_id=decision.id,
        payload={
            "risk_probability": score.risk_probability,
            "escalation_threshold": policy.escalation_threshold,
            "note": "recommendation only; no vendor or L2 action is taken by the system",
        },
    )


# --- acting on a decision ---------------------------------------------------

#: A rescore writes a new ``RISK_SCORED`` event only when the score moves by at
#: least this much, or when the model or policy version behind it changed. Below
#: it, a rescore is a no-op and the history stays readable instead of filling
#: with identical rows (spec D.5).
MATERIAL_RISK_CHANGE = 0.005


def get_decision(db: DbSession, decision_id: str) -> models.AssignmentDecision:
    decision = db.get(models.AssignmentDecision, decision_id)
    if decision is None:
        raise ApiError(
            "DECISION_NOT_FOUND", "No recommendation exists with that id.",
            status_code=404, details={"decision_id": decision_id},
        )
    return decision


def check_not_stale(db: DbSession, ticket, decision: models.AssignmentDecision) -> None:
    """Refuse to act on a recommendation whose policy or model has moved on.

    A stale recommendation is not wrong, it is simply no longer the answer to
    today's question, and accepting one would put a number in the audit trail
    that the current configuration would not produce. The dispatcher rescores.
    """
    policy = db.scalar(
        select(models.SlaPolicy).where(models.SlaPolicy.priority == ticket.priority)
    )
    current_model = scoring.risk_scorer().version
    drifted = {}
    if policy is not None and policy.version != decision.policy_version:
        drifted["policy_version"] = {
            "decision": decision.policy_version, "current": policy.version,
        }
    if decision.model_version != current_model:
        drifted["model_version"] = {
            "decision": decision.model_version, "current": current_model,
        }
    if drifted:
        raise ApiError(
            "DECISION_STALE",
            "This recommendation was made under a different policy or model "
            "version. Rescore before accepting it.",
            status_code=409,
            details={"decision_id": decision.id, "drifted": drifted},
        )


def accept(db: DbSession, actor: models.User, decision_id: str):
    """Assign the recommended agent, if that agent is still able to take it."""
    decision = get_decision(db, decision_id)
    ticket = _lock_ticket(db, decision.ticket_id)
    if decision.recommendation_state != "recommended":
        raise ApiError(
            "DECISION_NOT_ACCEPTABLE",
            "This decision is a %s outcome, so there is nothing to accept."
            % decision.recommendation_state,
            status_code=409, details={"decision_id": decision.id},
        )
    if ticket.status in models.TERMINAL_TICKET_STATUSES:
        raise ApiError(
            "TICKET_NOT_OPEN",
            "Ticket is %s, so it cannot be assigned." % ticket.status,
            status_code=409, details={"ticket_id": ticket.id},
        )
    check_not_stale(db, ticket, decision)

    capacity, is_active = eligibility.capacity_for(db, decision.recommended_agent_id)
    # Re-verified now, not at recommendation time: an earlier accept in the same
    # batch may already have taken this resolver's last slot.
    eligibility.check_assignable(ticket, capacity, is_active)

    _assign(db, ticket, decision.recommended_agent_id,
            decision.predicted_duration_minutes, capacity)
    events.record(
        db, ticket.id, "ASSIGNMENT_ACCEPTED", actor_user_id=actor.id,
        decision_id=decision.id,
        payload={
            "agent_id": decision.recommended_agent_id,
            "decision_id": decision.id,
            "policy_version": decision.policy_version,
            "model_version": decision.model_version,
        },
    )
    return ticket, decision


def override(db: DbSession, actor: models.User, decision_id: str, agent_id: str,
             reason: str):
    """Assign someone else, on the record, without touching the recommendation."""
    typed = (reason or "").strip()
    if not typed:
        raise ApiError(
            "OVERRIDE_REASON_REQUIRED",
            "An override needs a written reason.",
            status_code=422, details={"decision_id": decision_id},
        )
    decision = get_decision(db, decision_id)
    ticket = _lock_ticket(db, decision.ticket_id)
    if ticket.status in models.TERMINAL_TICKET_STATUSES:
        raise ApiError(
            "TICKET_NOT_OPEN",
            "Ticket is %s, so it cannot be assigned." % ticket.status,
            status_code=409, details={"ticket_id": ticket.id},
        )

    capacity, is_active = eligibility.capacity_for(db, agent_id)
    eligibility.check_assignable(ticket, capacity, is_active)

    recommended_name = None
    if decision.recommended_agent_id:
        recommended, _active = eligibility.capacity_for(db, decision.recommended_agent_id)
        recommended_name = recommended.display_name

    _assign(db, ticket, agent_id, decision.predicted_duration_minutes, capacity)
    events.record(
        db, ticket.id, "ASSIGNMENT_OVERRIDDEN", actor_user_id=actor.id,
        decision_id=decision.id,
        payload={
            "recommendation_id": decision.id,
            "recommended_agent_id": decision.recommended_agent_id,
            "chosen_agent_id": agent_id,
            "reason": typed,
            "narrative": reasons.override_reason(
                recommended_name, capacity.display_name, typed
            ),
            "policy_version": decision.policy_version,
            "model_version": decision.model_version,
        },
    )
    return ticket, decision


def _lock_ticket(db: DbSession, ticket_id: str) -> models.Ticket:
    """Read the ticket for update where the dialect supports it.

    SQLite serialises writes at the connection level and ignores the clause, so
    this is a PostgreSQL guarantee and a no-op in the offline demo. Saying so
    here is better than a comment claiming both dialects lock rows.
    """
    query = select(models.Ticket).where(models.Ticket.id == ticket_id)
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        query = query.with_for_update()
    ticket = db.scalar(query)
    if ticket is None:
        raise ApiError(
            "TICKET_NOT_FOUND", "No ticket exists with that id.",
            status_code=404, details={"ticket_id": ticket_id},
        )
    return ticket


def _assign(db, ticket, agent_id, predicted_duration_minutes, capacity):
    """Set the current assignment and advance the resolver's availability.

    ``next_available_at`` is a projection, not a calendar: it moves forward by
    the predicted service time of the work just accepted, measured from whichever
    is later, now or the resolver's existing projection. Dispatch reads it as the
    earliest minute the next piece of work could start.
    """
    now = utcnow()
    ticket.current_assignee_id = agent_id
    ticket.status = "assigned"
    agent = db.get(models.Agent, agent_id)
    minutes = float(predicted_duration_minutes or 0.0) * capacity.multiplier_for(
        ticket.required_skill
    )
    start = max(now, agent.next_available_at or now)
    agent.next_available_at = start + timedelta(minutes=minutes)
    db.flush()


def rescore(db: DbSession, actor: models.User, only_stale: bool = True,
            stale_after_minutes: int = 5, as_of=None) -> dict:
    """Rescore every non-terminal ticket, writing an event only where it matters.

    **What can actually move a score, stated because it is narrower than the name
    suggests.** Every feature the artifact reads - priority, category,
    subcategory, location, contact type and the opening timestamp - is fixed when
    the ticket is created. Nothing in the feature row reads the clock. So calling
    this on an unchanged ticket with an unchanged artifact returns the same
    number by construction, and the material-change test correctly writes
    nothing. A rescore earns its place in exactly three situations:

    * a ticket was created before any artifact was installed and is unscored;
    * a dispatcher patched a field the model reads, most often the priority;
    * a different model artifact is now the latest one.

    That is what "manual rescore after material policy or availability changes"
    (spec D.5) amounts to in this build, and it is worth being blunt about it
    rather than implying the score drifts on its own. A time-varying score would
    need a feature the artifact was never fitted on, so it is not available here.

    Idempotent for the same ticket, model, policy and as-of minute. It never
    reassigns an accepted ticket - assignment is not touched anywhere in this
    function.
    """
    as_of = as_of or utcnow()
    query = select(models.Ticket).where(
        models.Ticket.status.notin_(models.TERMINAL_TICKET_STATUSES)
    )
    if only_stale:
        cutoff = as_of - timedelta(minutes=stale_after_minutes)
        query = query.where(
            (models.Ticket.last_scored_at.is_(None))
            | (models.Ticket.last_scored_at <= cutoff)
        )
    tickets = db.scalars(query.order_by(models.Ticket.id.asc())).all()
    if not tickets:
        return {"considered": 0, "rescored": 0, "unchanged": 0}

    scores = scoring.score_tickets(tickets)
    rescored = 0
    for ticket in tickets:
        score = scores[ticket.id]
        moved = (
            ticket.risk_probability is None
            or abs(score.risk_probability - ticket.risk_probability) >= MATERIAL_RISK_CHANGE
            or ticket.risk_model_version != score.risk_model_version
        )
        ticket.last_scored_at = as_of
        if not moved:
            continue
        previous = ticket.risk_probability
        ticket.risk_probability = score.risk_probability
        ticket.risk_model_version = score.risk_model_version
        db.flush()
        events.record(
            db, ticket.id, "RISK_SCORED", actor_user_id=actor.id,
            payload={
                "risk_probability": score.risk_probability,
                "previous_risk_probability": previous,
                "predicted_duration_minutes": score.predicted_duration_minutes,
                "risk_model_version": score.risk_model_version,
                "unavailable_features": scoring.unavailable_features(ticket),
                "trigger": "manual_rescore",
            },
        )
        rescored += 1
    db.flush()
    return {
        "considered": len(tickets),
        "rescored": rescored,
        "unchanged": len(tickets) - rescored,
    }
