"""Ticket creation and correction.

Creation is one transaction: the deadline comes from the policy in force now,
the risk and duration artifacts score the ticket, and ``TICKET_CREATED`` plus
``RISK_SCORED`` are written beside the row (spec C.3). If scoring fails the
whole creation rolls back, so an unscored ticket is never quietly stored.

There is one documented exception. ``allow_manual_fallback`` lets a caller
create a ticket while the artifacts are unavailable; it writes the ticket
unscored and records a ``MODEL_UNAVAILABLE`` event carrying the reason, which is
the "model unavailable - manual dispatch" path spec E.6 requires. It is never
the default, so the failure has to be chosen rather than absorbed.

After creation, status moves only through a named transition - resolve, close,
reopen here, assignment in ``decisions``, review in ``escalation`` - each
written as a ``TICKET_UPDATED`` event with an ``action`` and a required note.
"""
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from api.servicedesk.db import models
from api.servicedesk.db.types import utcnow
from api.servicedesk.errors import ApiError
from api.servicedesk.services import eligibility, events, scoring, triage

#: The fields a patch may change, each recorded in the TICKET_UPDATED payload.
PATCHABLE_FIELDS = (
    "title",
    "description",
    "priority",
    "category",
    "subcategory",
    "location",
    "contact_type",
    "required_skill",
)


def active_policy(db: DbSession, priority: int) -> models.SlaPolicy:
    """The SLA policy for a priority, or a failure that names the gap."""
    policy = db.scalar(select(models.SlaPolicy).where(models.SlaPolicy.priority == priority))
    if policy is None:
        raise ApiError(
            "SLA_POLICY_MISSING",
            "No SLA policy is configured for priority %d, so no deadline can be set."
            % priority,
            status_code=409,
            details={"priority": priority},
        )
    return policy


def create_ticket(db: DbSession, actor: models.User, payload, source: str = "manual",
                  allow_manual_fallback: bool = False):
    """Create one ticket with a fixed deadline, a score, and its opening events.

    The deadline is stored, not derived on read: a later policy edit must not
    move a deadline a team has already been working against.
    """
    opened_at = payload.opened_at or utcnow()
    priority, priority_source = triage.resolve_priority(
        payload.priority, payload.impact, payload.urgency
    )
    policy = active_policy(db, priority)
    if payload.external_reference and _reference_taken(db, payload.external_reference):
        raise ApiError(
            "EXTERNAL_REFERENCE_IN_USE",
            "Another ticket already uses the reference %s." % payload.external_reference,
            status_code=409,
            details={"external_reference": payload.external_reference},
        )

    ticket = models.Ticket(
        external_reference=payload.external_reference,
        source=source,
        title=payload.title,
        description=payload.description,
        status="open",
        priority=priority,
        impact=payload.impact,
        urgency=payload.urgency,
        category=payload.category,
        subcategory=payload.subcategory,
        location=payload.location,
        contact_type=payload.contact_type,
        required_skill=payload.required_skill,
        opened_at=opened_at,
        sla_due_at=opened_at + timedelta(minutes=policy.target_minutes),
    )
    db.add(ticket)
    db.flush()

    events.record(
        db,
        ticket.id,
        "TICKET_CREATED",
        actor_user_id=actor.id,
        payload={
            "priority": ticket.priority,
            "impact": ticket.impact,
            "urgency": ticket.urgency,
            "priority_source": priority_source,
            "required_skill": ticket.required_skill,
            "source": source,
            "sla_policy_version": policy.version,
            "sla_target_minutes": policy.target_minutes,
        },
    )
    score_ticket_in_transaction(db, actor, ticket, allow_manual_fallback)
    return ticket


def score_ticket_in_transaction(db: DbSession, actor: models.User,
                                ticket: models.Ticket,
                                allow_manual_fallback: bool = False):
    """Score `ticket`, write the score onto it, and record what happened.

    Returns the :class:`~api.servicedesk.services.scoring.TicketScore`, or ``None``
    when the manual-fallback path was taken. The caller's transaction is not
    committed here: the score and its event land with the row they describe.
    """
    try:
        score = scoring.score_ticket(ticket)
    except ApiError as error:
        if not allow_manual_fallback:
            raise
        events.record(
            db,
            ticket.id,
            "MODEL_UNAVAILABLE",
            actor_user_id=actor.id,
            payload={"stage": "ticket_creation", "reason": error.message},
        )
        return None

    ticket.risk_probability = score.risk_probability
    ticket.risk_model_version = score.risk_model_version
    ticket.last_scored_at = utcnow()
    db.flush()
    events.record(
        db,
        ticket.id,
        "RISK_SCORED",
        actor_user_id=actor.id,
        payload={
            "risk_probability": score.risk_probability,
            "predicted_duration_minutes": score.predicted_duration_minutes,
            "risk_model_version": score.risk_model_version,
            "duration_model_version": score.duration_model_version,
            "unavailable_features": scoring.unavailable_features(ticket),
        },
    )
    return score


def _reference_taken(db: DbSession, reference: str) -> bool:
    return (
        db.scalar(
            select(models.Ticket.id).where(models.Ticket.external_reference == reference)
        )
        is not None
    )


def patch_ticket(db: DbSession, actor: models.User, ticket: models.Ticket, patch):
    """Apply a correction and record what changed, field by field."""
    if patch.priority is not None:
        # A ticket whose priority came from its impact and urgency keeps that
        # agreement: a different number here is refused, not stored beside them.
        triage.resolve_priority(patch.priority, ticket.impact, ticket.urgency)
    changes = {}
    for field in PATCHABLE_FIELDS:
        new_value = getattr(patch, field, None)
        if new_value is None:
            continue
        old_value = getattr(ticket, field)
        if new_value == old_value:
            continue
        setattr(ticket, field, new_value)
        changes[field] = {"from": old_value, "to": new_value}

    if not changes:
        return ticket, {}

    db.flush()
    events.record(
        db,
        ticket.id,
        "TICKET_UPDATED",
        actor_user_id=actor.id,
        payload={"changes": changes},
    )
    return ticket, changes


def resolve_ticket(db: DbSession, actor: models.User, ticket: models.Ticket, note: str):
    """Mark the work done, stamp the time, and record the SLA outcome.

    The outcome is read against ``sla_due_at``, which never moves after
    creation, so "met" means met against the deadline the team was given.
    Leaving ``assigned`` takes the ticket out of the resolver's work in progress
    (``eligibility.OCCUPYING_STATUSES``), which is what frees the WIP slot.
    """
    if ticket.status == "escalation_review":
        raise ApiError(
            "ESCALATION_REVIEW_ACTIVE",
            "Close the escalation review on this ticket before resolving it.",
            status_code=409,
            details={"ticket_id": ticket.id, "escalation_target": ticket.escalation_target},
        )
    _require_status(ticket, ("open", "assigned"), "resolved")
    now = utcnow()
    previous_status = ticket.status
    ticket.status = "resolved"
    ticket.resolved_at = now
    db.flush()
    past_deadline = (now - ticket.sla_due_at).total_seconds() / 60.0
    return events.record(
        db, ticket.id, "TICKET_UPDATED", actor_user_id=actor.id,
        payload={
            "action": "ticket_resolved",
            "previous_status": previous_status,
            "status": ticket.status,
            "note": note.strip(),
            "resolver_agent_id": ticket.current_assignee_id,
            "sla_met": past_deadline <= 0,
            "minutes_past_deadline": round(max(0.0, past_deadline), 1),
            "resolver_available_from": _release_resolver(db, ticket.current_assignee_id, now),
        },
    )


def close_ticket(db: DbSession, actor: models.User, ticket: models.Ticket, note: str):
    """Confirm a resolution and end the ticket's working life."""
    _require_status(ticket, ("resolved",), "closed")
    ticket.status = "closed"
    db.flush()
    return events.record(
        db, ticket.id, "TICKET_UPDATED", actor_user_id=actor.id,
        payload={"action": "ticket_closed", "previous_status": "resolved",
                 "status": ticket.status, "note": note.strip()},
    )


def reopen_ticket(db: DbSession, actor: models.User, ticket: models.Ticket, note: str):
    """Send a resolved or closed ticket back to the dispatch queue.

    It returns unassigned, so the next solve prices it against today's
    resolvers rather than handing it back to someone who may now be full. The
    deadline does not move - a ticket reopened after its deadline is overdue,
    which is the truth - and the event keeps who resolved it and when.
    """
    _require_status(ticket, ("resolved", "closed"), "reopened")
    previous = {"previous_status": ticket.status,
                "previous_assignee_id": ticket.current_assignee_id,
                "previous_resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None}
    ticket.status = "open"
    ticket.current_assignee_id = None
    ticket.resolved_at = None
    db.flush()
    return events.record(
        db, ticket.id, "TICKET_UPDATED", actor_user_id=actor.id,
        payload={"action": "ticket_reopened", "status": ticket.status,
                 "note": note.strip(), **previous},
    )


def _require_status(ticket: models.Ticket, allowed, becoming: str) -> None:
    if ticket.status not in allowed:
        raise ApiError(
            "TICKET_TRANSITION_INVALID",
            "Ticket %s is %s, so it cannot be %s." % (
                ticket.external_reference or ticket.id, ticket.status, becoming),
            status_code=409,
            details={"ticket_id": ticket.id, "status": ticket.status, "allowed_from": list(allowed)},
        )


def _release_resolver(db: DbSession, agent_id, now):
    """Bring a resolver's projected availability forward when their queue empties.

    ``next_available_at`` was pushed out by the predicted service time when the
    work was accepted. If that work finished early and nothing else is open on
    their desk, they are free now, not at the projection. With other work still
    open the projection is left alone: how long that work takes is not known.
    """
    agent = db.get(models.Agent, agent_id) if agent_id else None
    if agent is None or agent.next_available_at is None or agent.next_available_at <= now:
        return None
    still_open = db.scalar(
        select(func.count()).select_from(models.Ticket)
        .where(models.Ticket.current_assignee_id == agent_id)
        .where(models.Ticket.status.in_(eligibility.OCCUPYING_STATUSES))
    )
    if still_open:
        return None
    agent.next_available_at = now
    db.flush()
    return now.isoformat()


def get_ticket(db: DbSession, ticket_id: str) -> models.Ticket:
    ticket = db.get(models.Ticket, ticket_id)
    if ticket is None:
        raise ApiError(
            "TICKET_NOT_FOUND",
            "No ticket exists with that id.",
            status_code=404,
            details={"ticket_id": ticket_id},
        )
    return ticket
