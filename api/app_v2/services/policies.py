"""Editing the SLA policy inputs (spec I.4, B.1 manager story 3).

A policy edit is the one administrative change that reaches backwards into work
already in flight, so three properties are enforced here rather than described
in the interface:

1. **A stored deadline never moves.** ``tickets.sla_due_at`` was written from
   the policy in force when the ticket opened (spec C.2). Nothing in this module
   touches it. A manager who shortens the priority-2 target changes what the
   next ticket gets, not what a team has already been working against.
2. **The version always advances.** ``version`` is snapshotted into every
   decision, and ``decisions.check_not_stale`` compares against it. If an edit
   did not bump it, a recommendation priced under the old numbers would stay
   acceptable and the audit trail would hold a cost the current configuration
   cannot reproduce.
3. **The tickets affected say so in their own history.** Each non-terminal
   ticket of that priority receives a ``POLICY_CHANGED_REFERENCE`` event naming
   the old and new version. That is the audit link between a manager's edit and
   the ``DECISION_STALE`` refusal a dispatcher meets a minute later.

Property 3 writes one event per open ticket in the priority. That is deliberate
and its cost is proportional to open work in one tier, not to the table.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from api.app_v2.db import models
from api.app_v2.errors import ApiError
from api.app_v2.services import events

#: The business inputs a manager may edit. ``priority`` and ``version`` are not
#: here: a policy row is identified by its priority, and the version is the
#: system's counter, not a field to be typed in.
EDITABLE_FIELDS = (
    "target_minutes",
    "breach_penalty_per_minute",
    "late_penalty_per_minute",
    "overdue_recovery_penalty_per_minute",
    "holding_cost_per_minute",
    "escalation_threshold",
    "source_note",
)


def get_policy(db: DbSession, policy_id: str) -> models.SlaPolicy:
    policy = db.get(models.SlaPolicy, policy_id)
    if policy is None:
        raise ApiError(
            "SLA_POLICY_NOT_FOUND",
            "No SLA policy exists with that id.",
            status_code=404,
            details={"policy_id": policy_id},
        )
    return policy


def patch_policy(db: DbSession, manager: models.User, policy: models.SlaPolicy, patch):
    """Apply an edit, bump the version, and mark the open tickets it will affect.

    Returns ``(policy, changes, referenced_ticket_ids)``. An edit that changes
    nothing is a no-op: the version does not move and no event is written, so
    re-saving an unchanged form cannot invalidate every live recommendation.
    """
    changes = {}
    for field in EDITABLE_FIELDS:
        new_value = getattr(patch, field, None)
        if new_value is None:
            continue
        old_value = getattr(policy, field)
        if new_value == old_value:
            continue
        setattr(policy, field, new_value)
        changes[field] = {"from": old_value, "to": new_value}

    if not changes:
        return policy, {}, []

    previous_version = policy.version
    policy.version = previous_version + 1
    db.flush()

    affected = db.scalars(
        select(models.Ticket)
        .where(models.Ticket.priority == policy.priority)
        .where(models.Ticket.status.notin_(models.TERMINAL_TICKET_STATUSES))
        .order_by(models.Ticket.id.asc())
    ).all()
    for ticket in affected:
        events.record(
            db,
            ticket.id,
            "POLICY_CHANGED_REFERENCE",
            actor_user_id=manager.id,
            payload={
                "sla_policy_id": policy.id,
                "priority": policy.priority,
                "from_version": previous_version,
                "to_version": policy.version,
                "changes": changes,
                "note": (
                    "future recommendations only; this ticket's stored SLA "
                    "deadline is unchanged"
                ),
            },
        )
    return policy, changes, [ticket.id for ticket in affected]
