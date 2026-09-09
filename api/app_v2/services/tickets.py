"""Ticket creation and correction.

Phase 1 has no risk model: the artifact and its feature schema arrive in
phase 2. Rather than invent a score, a ticket created now is stored unscored and
carries a ``MODEL_UNAVAILABLE`` event saying so, which is exactly the documented
manual-fallback path in spec C.3. When the artifact exists, scoring joins this
same transaction and an unscored ticket becomes the exception it is meant to be.
"""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from api.app_v2.db import models
from api.app_v2.db.types import utcnow
from api.app_v2.errors import ApiError
from api.app_v2.services import events

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


def create_ticket(db: DbSession, actor: models.User, payload, source: str = "manual"):
    """Create one ticket with a fixed deadline and its opening events.

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
    events.record(
        db,
        ticket.id,
        "MODEL_UNAVAILABLE",
        actor_user_id=actor.id,
        payload={
            "stage": "ticket_creation",
            "reason": "no risk model artifact is installed in this build",
        },
    )
    return ticket


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
