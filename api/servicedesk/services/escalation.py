"""Escalation: the recommendation, the human answer, and the way out again.

Phase 3 wrote ``ESCALATION_RECOMMENDED`` whenever a calibrated risk estimate
crossed the priority's threshold. Nothing consumed it: the recommendation sat in
the history with no way for a person to answer it.

Two functions answer it. (An earlier record-only acknowledgement endpoint was
removed: an action that changes nothing must not be labelled escalation. Old
``ESCALATION_ACKNOWLEDGED`` events stay in the history, which is append-only.)

``start_review`` is the action a dispatcher actually gets. It changes the
ticket's visible status, records **who the review is with** and when it opened,
and refuses any target this desk cannot reach. ``close_review`` ends it with a
stated outcome and puts the ticket back in the working queue. A state a ticket
can enter and never leave is the acknowledgement ritual one level up, so the way
out is part of the feature rather than a later idea.

One outcome, ``replacement_raised``, is where this module touches the asset
register: it needs the ticket-to-asset link a person stated, and it stores the
replacement verdict computed at that moment. That is the only connection between
a ticket and a machine in this system, and it is a human's statement from end to
end - nothing here infers that a machine caused an incident.

"""
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from api.servicedesk.db import models
from api.servicedesk.db.types import utcnow
from api.servicedesk.errors import ApiError
from api.servicedesk.services import events, hardware

#: What each target means in words, for the audit entry and the screen. The
#: names on the left are the only routes this desk has, and the sentences on the
#: right are what the person receiving the review is being asked to do.
TARGET_DESCRIPTIONS = {
    "senior_resolver": "a senior resolver is asked to take the ticket or advise on it",
    "duty_manager": "the duty manager is asked to decide priority, staffing or policy",
    "asset_replacement": "the linked machine is put to the replacement decision",
}

#: What each outcome means, same rule.
OUTCOME_DESCRIPTIONS = {
    "reassigned": "a different resolver now owns the ticket",
    "replacement_raised": "a hardware replacement was raised for the linked machine",
    "no_action": "the review found no change was needed",
}


#: How far back to look for the event that opened the live review. A review is
#: a short-lived state and its start is a handful of entries behind the newest
#: one; scanning the whole history of a long-lived ticket to find it would be
#: paying for the rare case on every close.
REVIEW_LOOKBACK_EVENTS = 50


def live_review_start_event(db: DbSession, ticket_id: str):
    """The event that opened the review currently running on this ticket.

    Newest first, stopping at the first close: anything before a close belongs
    to a review that already ended, and reading its payload would answer a
    question about the wrong review.
    """
    rows = db.scalars(
        select(models.TicketEvent)
        .where(models.TicketEvent.ticket_id == ticket_id)
        .where(models.TicketEvent.event_type == "TICKET_UPDATED")
        .order_by(
            models.TicketEvent.occurred_at.desc(), models.TicketEvent.id.desc()
        )
        .limit(REVIEW_LOOKBACK_EVENTS)
    ).all()
    for event in rows:
        action = (event.payload_json or {}).get("action")
        if action == "escalation_review_closed":
            return None
        if action == "escalation_review_started":
            return event
    return None


def start_review(
    db: DbSession,
    actor: models.User,
    ticket: models.Ticket,
    note: str,
    target: str,
):
    """Open an internal escalation review on one live ticket, with a named target.

    Unlike an acknowledgement, this is a real product action: the visible ticket
    status changes, the ticket records who the review is with and when it
    opened, and the audit entry states why.

    It remains deliberately narrow. Every target in ``ESCALATION_TARGETS`` is a
    route this desk operates - two of its own people, and the replacement
    decision this project computes. No external L2 queue or vendor integration
    exists here, so none is offered and no event may imply one was contacted.
    """
    if ticket.status in models.TERMINAL_TICKET_STATUSES:
        raise ApiError(
            "TICKET_NOT_OPEN",
            "Ticket %s is %s, so it cannot enter escalation review."
            % (ticket.external_reference or ticket.id, ticket.status),
            status_code=409,
            details={"ticket_id": ticket.id, "status": ticket.status},
        )
    if ticket.status == "escalation_review":
        raise ApiError(
            "ESCALATION_REVIEW_ALREADY_ACTIVE",
            "This ticket is already in escalation review with %s."
            % target_label(ticket.escalation_target),
            status_code=409,
            details={"ticket_id": ticket.id, "status": ticket.status},
        )
    if target not in models.ESCALATION_TARGETS:
        raise ApiError(
            "ESCALATION_TARGET_UNKNOWN",
            "%s is not a route this desk has. Choose one of: %s."
            % (target, ", ".join(models.ESCALATION_TARGETS)),
            status_code=422,
            details={"target": target, "allowed": list(models.ESCALATION_TARGETS)},
        )
    if target == "asset_replacement" and not ticket.machine_id:
        # The replacement route is the one place in this product where dispatch
        # and the asset register meet. Meeting them needs the ticket-to-asset
        # link a person stated; without it there is no machine to decide about,
        # and a review addressed to nothing is the ritual button again.
        raise ApiError(
            "TICKET_HAS_NO_MACHINE",
            "Link the affected machine to this ticket before sending it to the "
            "replacement decision.",
            status_code=422,
            details={"ticket_id": ticket.id},
        )

    previous_status = ticket.status
    ticket.status = "escalation_review"
    ticket.escalation_target = target
    ticket.escalation_opened_at = utcnow()
    db.flush()
    return events.record(
        db,
        ticket.id,
        "TICKET_UPDATED",
        actor_user_id=actor.id,
        payload={
            "action": "escalation_review_started",
            "previous_status": previous_status,
            "status": ticket.status,
            "escalation_target": target,
            # Who owned the ticket when the review opened. Closing as
            # "reassigned" is checked against this, so that outcome cannot
            # claim a change of owner that never happened.
            "previous_assignee_id": ticket.current_assignee_id,
            "note": note.strip(),
            "effect": (
                "ticket moved to internal escalation review, %s; no external L2 "
                "or vendor system was contacted" % TARGET_DESCRIPTIONS[target]
            ),
        },
    )


def close_review(
    db: DbSession,
    actor: models.User,
    ticket: models.Ticket,
    note: str,
    outcome: str,
):
    """Close a live review with a stated outcome and return the ticket to work.

    The status the ticket returns to is derived, not remembered: a ticket with an
    assignee is ``assigned`` and one without is ``open``. Reading the status back
    out of the event history would restore whatever was true when the review
    opened, which may be a fact about a resolver who has since been replaced.

    ``replacement_raised`` is the outcome that reaches the asset register. It
    requires the linked machine and stores the replacement verdict computed at
    this moment beside it, so the history says what the arithmetic said on the
    day rather than what it says when the record is read back months later.
    """
    if ticket.status != "escalation_review":
        raise ApiError(
            "ESCALATION_REVIEW_NOT_ACTIVE",
            "Ticket %s is %s, so there is no escalation review to close."
            % (ticket.external_reference or ticket.id, ticket.status),
            status_code=409,
            details={"ticket_id": ticket.id, "status": ticket.status},
        )
    if outcome not in models.ESCALATION_OUTCOMES:
        raise ApiError(
            "ESCALATION_OUTCOME_UNKNOWN",
            "%s is not an outcome this desk records. Choose one of: %s."
            % (outcome, ", ".join(models.ESCALATION_OUTCOMES)),
            status_code=422,
            details={"outcome": outcome, "allowed": list(models.ESCALATION_OUTCOMES)},
        )

    if outcome == "reassigned":
        # Same rule as the replacement outcome below, for the same reason.
        # "A different resolver now owns it" is a statement about the ticket,
        # not a mood. An entry asserting a change the row does not show is
        # precisely the record-only acknowledgement this module replaced, so
        # the outcome is refused rather than written.
        opened = live_review_start_event(db, ticket.id)
        previously = (opened.payload_json or {}).get("previous_assignee_id") if opened else None
        if not ticket.current_assignee_id or ticket.current_assignee_id == previously:
            raise ApiError(
                "ESCALATION_OUTCOME_NOT_TRUE",
                "This ticket has no new owner, so the review cannot close as "
                "reassigned. Assign the new resolver first and then close the "
                "review, or close it as reviewed with no change needed.",
                status_code=409,
                details={
                    "ticket_id": ticket.id,
                    "current_assignee_id": ticket.current_assignee_id,
                    "assignee_when_review_opened": previously,
                },
            )

    replacement = None
    if outcome == "replacement_raised":
        if not ticket.machine_id:
            raise ApiError(
                "TICKET_HAS_NO_MACHINE",
                "A replacement can only be raised against a linked machine. "
                "Link the affected asset, then close the review.",
                status_code=422,
                details={"ticket_id": ticket.id},
            )
        machine = hardware.get_machine(db, ticket.machine_id)
        advice = hardware.replacement_advice(machine)
        replacement = {
            "machine_id": machine.id,
            "asset_tag": machine.asset_tag,
            "verdict": advice["verdict"],
            "optimal_replacement_year": advice["optimal_replacement_year"],
            "months_until_due": advice["months_until_due"],
            "source_note": machine.source_note,
        }

    target = ticket.escalation_target
    ticket.status = "assigned" if ticket.current_assignee_id else "open"
    ticket.escalation_target = None
    ticket.escalation_opened_at = None
    db.flush()
    return events.record(
        db,
        ticket.id,
        "TICKET_UPDATED",
        actor_user_id=actor.id,
        payload={
            "action": "escalation_review_closed",
            "escalation_target": target,
            "outcome": outcome,
            "status": ticket.status,
            "note": note.strip(),
            "replacement": replacement,
            "effect": (
                "escalation review closed - %s; the ticket returned to %s"
                % (OUTCOME_DESCRIPTIONS[outcome], ticket.status)
            ),
        },
    )


def target_label(target) -> str:
    """The target as a person reads it, never the stored key."""
    return {
        "senior_resolver": "a senior resolver",
        "duty_manager": "the duty manager",
        "asset_replacement": "the replacement decision",
    }.get(target, "an unnamed reviewer")
