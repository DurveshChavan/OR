"""Re-anchor the seeded demo tickets to the current clock.

    python -m api.servicedesk.cli.refresh_demo_window

The seed places each held-out incident a stated number of minutes before the
moment it runs, so a fresh demo opens with a deliberate mix: two tickets already
past their deadline, a few close to it, and the rest with time in hand. That mix
is a property of *when the seed ran*, and the application measures deadlines
against the real clock. Leave the database alone for a day and every ticket in
it is overdue, which is not a demo of an SLA desk. It is a demo of a desk that
lost.

This command shifts every ``seed_demo`` ticket forward by the same amount, so
the intended spread comes back without reseeding and without touching the audit
trail's meaning. Three things it deliberately does not do:

* it does not move the tickets a person created by hand, only seeded ones;
* it does not touch a ticket's risk score, assignee or status, because a shift
  in the demo window is not a claim that anything was re-decided;
* it does not silently rewrite history. Each shifted ticket gets an event
  recording how far it moved and why, so a reader of the timeline can see that
  the deadline they are looking at was re-anchored rather than met.

The shift is taken from the oldest seeded ticket: the offset that keeps the
earliest ticket exactly where the seed put it relative to now.
"""
import argparse
import sys

from sqlalchemy import select

from api.servicedesk.db import models
from api.servicedesk.db.session import session_scope, database_url
from api.servicedesk.db.types import utcnow
from api.servicedesk.services import events


def seeded_tickets(db):
    return list(
        db.scalars(
            select(models.Ticket)
            .where(models.Ticket.source == "seed_demo")
            .order_by(models.Ticket.opened_at.asc())
        ).all()
    )


def refresh(dry_run: bool = False) -> dict:
    db = session_scope()
    try:
        tickets = seeded_tickets(db)
        if not tickets:
            return {"tickets": 0, "shift_minutes": 0.0, "note": "no seeded tickets"}

        # The seed's own spread is preserved by moving every ticket by one
        # constant. That constant is whatever puts the most recently opened
        # ticket back where it was relative to "now" when the seed ran, which is
        # the elapsed time since the newest seeded ticket was created.
        newest = max(tickets, key=lambda row: row.created_at)
        shift = utcnow() - newest.created_at
        shift_minutes = shift.total_seconds() / 60.0
        if shift_minutes < 1.0:
            return {
                "tickets": len(tickets),
                "shift_minutes": round(shift_minutes, 1),
                "note": "already current; nothing moved",
            }
        if dry_run:
            return {
                "tickets": len(tickets),
                "shift_minutes": round(shift_minutes, 1),
                "note": "dry run; nothing written",
            }

        actor = db.scalars(
            select(models.User).where(models.User.role == "manager")
        ).first()
        for ticket in tickets:
            ticket.opened_at = ticket.opened_at + shift
            ticket.sla_due_at = ticket.sla_due_at + shift
            ticket.created_at = ticket.created_at + shift
            events.record(
                db,
                ticket.id,
                "TICKET_UPDATED",
                actor_user_id=actor.id if actor else None,
                payload={
                    "action": "demo_window_refreshed",
                    "shift_minutes": round(shift_minutes, 1),
                    "opened_at": ticket.opened_at.isoformat(),
                    "sla_due_at": ticket.sla_due_at.isoformat(),
                    "note": (
                        "seeded demo ticket re-anchored to the current clock; the "
                        "incident, its priority and its category are unchanged and "
                        "no decision was re-made"
                    ),
                },
            )
        db.commit()
        return {
            "tickets": len(tickets),
            "shift_minutes": round(shift_minutes, 1),
            "note": "re-anchored",
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Move the seeded demo tickets forward to the current clock."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report the shift that would be applied and write nothing",
    )
    args = parser.parse_args(argv)
    result = refresh(dry_run=args.dry_run)
    print("database: %s" % database_url())
    print(
        "%d seeded ticket(s), shift %.1f minutes: %s"
        % (result["tickets"], result["shift_minutes"], result["note"])
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
