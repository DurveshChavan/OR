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
"""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from api.servicedesk.db import models
from api.servicedesk.db.types import utcnow
from api.servicedesk.errors import ApiError
from api.servicedesk.services import events, scoring

#: The fields a patch may change, each recorded in the TICKET_UPDATED payload.
PATCHABLE_FIELDS = (
    "priority",
    "status",
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
    policy = active_policy(db, payload.priority)
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
        status="open",
        priority=payload.priority,
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
            "unavailable_features": list(scoring.UNAVAILABLE_AT_DISPATCH),
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
    changes = {}
    for field in PATCHABLE_FIELDS:
        new_value = getattr(patch, field, None)
        if new_value is None:
            continue
        old_value = getattr(ticket, field)
        if new_value == old_value:
            continue
        if field == "status" and new_value not in models.TICKET_STATUSES:
            raise ApiError(
                "TICKET_STATUS_INVALID",
                "%r is not a ticket status." % new_value,
                status_code=422,
                details={"allowed": list(models.TICKET_STATUSES)},
            )
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
