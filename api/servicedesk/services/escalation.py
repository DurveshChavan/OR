"""The human half of escalation (spec B.1 dispatcher story 2, B.2).

Phase 3 wrote ``ESCALATION_RECOMMENDED`` whenever a calibrated risk estimate
crossed the priority's threshold. Nothing consumed it: the recommendation sat in
the history with no way for a person to answer it. This module is that answer,
and it is deliberately the smallest thing that can be true.

Acknowledging does exactly one thing: it appends an ``ESCALATION_ACKNOWLEDGED``
event naming the actor, the note they typed, and the recommendation they are
responding to when there is one. It routes nothing to L2, opens nothing with a
vendor, and does not move the ticket's status, because the system has no
authority to do any of those and pretending otherwise in a demo is exactly the
overclaim spec B.2 forbids.

A dispatcher may also raise a concern on a ticket the model did not flag. That
case is recorded with ``following_recommendation = false`` so the history
distinguishes "a human agreed with the model" from "a human went first".
"""
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from api.servicedesk.db import models
from api.servicedesk.errors import ApiError
from api.servicedesk.services import events


def latest_recommendation_event(db: DbSession, ticket_id: str):
    """The most recent ``ESCALATION_RECOMMENDED`` on this ticket, if any."""
    return db.scalars(
        select(models.TicketEvent)
        .where(models.TicketEvent.ticket_id == ticket_id)
        .where(models.TicketEvent.event_type == "ESCALATION_RECOMMENDED")
        .order_by(
            models.TicketEvent.occurred_at.desc(), models.TicketEvent.id.desc()
        )
        .limit(1)
    ).first()


def acknowledge(db: DbSession, actor: models.User, ticket: models.Ticket, note: str):
    """Record a human's response to escalation on one open ticket."""
    if ticket.status in models.TERMINAL_TICKET_STATUSES:
        raise ApiError(
            "TICKET_NOT_OPEN",
            "Ticket %s is %s, so there is no live escalation to acknowledge."
            % (ticket.external_reference or ticket.id, ticket.status),
            status_code=409,
            details={"ticket_id": ticket.id, "status": ticket.status},
        )
    recommendation = latest_recommendation_event(db, ticket.id)
    event = events.record(
        db,
        ticket.id,
        "ESCALATION_ACKNOWLEDGED",
        actor_user_id=actor.id,
        decision_id=recommendation.decision_id if recommendation is not None else None,
        payload={
            "note": note.strip(),
            "following_recommendation": recommendation is not None,
            "acknowledged_event_id": (
                recommendation.id if recommendation is not None else None
            ),
            "risk_probability": ticket.risk_probability,
            "risk_model_version": ticket.risk_model_version,
            "effect": (
                "recorded acknowledgement only; no L2 or vendor action is taken "
                "by the system and the ticket status is unchanged"
            ),
        },
    )
    return event, recommendation
