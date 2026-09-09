"""Writing the audit trail.

One helper, used by every flow that changes a ticket, so an event can never be
written with a shape that differs from the rest of the history. The event row
is only flushed here; the surrounding request commits it together with the
current-state change it explains, so the two can never separate.
"""
from sqlalchemy.orm import Session as DbSession

from api.app_v2.db import models


def record(
    db: DbSession,
    ticket_id: str,
    event_type: str,
    actor_user_id: str = None,
    decision_id: str = None,
    payload: dict = None,
) -> models.TicketEvent:
    """Append one event to a ticket's history."""
    if event_type not in models.EVENT_TYPES:
        raise ValueError("unknown event type %r" % event_type)
    event = models.TicketEvent(
        ticket_id=ticket_id,
        decision_id=decision_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        payload_json=payload or {},
    )
    db.add(event)
    db.flush()
    return event
