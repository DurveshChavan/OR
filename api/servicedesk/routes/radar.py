"""Risk Radar (spec D.6): open work, ordered so nothing quietly rots.

The ordering is fixed by the specification and is applied here in Python rather
than in SQL, because the second and third keys are computed from the same
dispatch cost model the recommendation uses. Reimplementing them as a SQL
expression would be a second definition of urgency, and the two would drift.

    P1 first
    then overdue recovery priority
    then urgency cost per minute, descending
    then SLA due time, ascending
    then ticket id, ascending

The list carries the numbers that produced the order - risk, urgency rate,
overdue minutes - so the client can render the reason for a row's position as
text, not as a colour (spec I.5).
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from api.servicedesk import deps
from api.servicedesk.db import models
from api.servicedesk.db.session import get_db
from api.servicedesk.db.types import utcnow
from api.servicedesk.domain import schemas
from api.servicedesk.services import dispatch

router = APIRouter(tags=["radar"])

#: Bands the client filters by. The boundaries are display conventions, not
#: model outputs, and they are named here so a filter cannot mean two things.
RISK_BANDS = {"high": (0.66, 1.01), "medium": (0.33, 0.66), "low": (0.0, 0.33)}


@router.get("/risk-radar", response_model=schemas.RiskRadarResponse)
def risk_radar(
    db: DbSession = Depends(get_db),
    actor=Depends(deps.current_user),
    request_id: str = Depends(deps.request_id),
    priority: Optional[int] = Query(default=None, ge=1, le=4),
    overdue_only: bool = Query(default=False),
    assignee_id: Optional[str] = Query(default=None),
    risk_band: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    as_of = utcnow()
    query = select(models.Ticket).where(
        models.Ticket.status.notin_(models.TERMINAL_TICKET_STATUSES)
    )
    if priority:
        query = query.where(models.Ticket.priority == priority)
    if assignee_id:
        query = query.where(models.Ticket.current_assignee_id == assignee_id)
    tickets = db.scalars(query).all()

    policies = {
        row.priority: dispatch.PolicyRates.from_row(row)
        for row in db.scalars(select(models.SlaPolicy)).all()
    }
    rows = [
        _radar_row(ticket, policies, as_of)
        for ticket in tickets
        if ticket.priority in policies
    ]
    rows = [row for row in rows if _passes(row, overdue_only, risk_band)]
    rows.sort(key=_ordering)
    return schemas.RiskRadarResponse(
        as_of=as_of, tickets=rows[:limit], request_id=request_id
    )


def _radar_row(ticket, policies, as_of) -> schemas.RiskRadarRow:
    policy = policies[ticket.priority]
    due_in = dispatch.minutes_between(ticket.sla_due_at, as_of)
    view = dispatch.TicketView(
        ticket_id=ticket.id,
        priority=ticket.priority,
        required_skill=ticket.required_skill,
        due_in_minutes=due_in,
        # An unscored ticket is ranked as if the breach were certain rather than
        # dropped from the radar. Being unable to score a ticket is not a reason
        # to stop showing it, and the row says the score is unavailable.
        risk_probability=ticket.risk_probability if ticket.risk_probability is not None else 1.0,
        predicted_duration_minutes=0.0,
    )
    return schemas.RiskRadarRow(
        ticket_id=ticket.id,
        external_reference=ticket.external_reference,
        priority=ticket.priority,
        status=ticket.status,
        required_skill=ticket.required_skill,
        sla_due_at=ticket.sla_due_at,
        minutes_to_due=round(due_in, 1),
        overdue=dispatch.is_overdue(due_in),
        overdue_minutes=round(max(0.0, -due_in), 1),
        risk_probability=ticket.risk_probability,
        risk_model_version=ticket.risk_model_version,
        urgency_cost_per_minute=round(
            dispatch.urgency_cost_per_minute(view, policy), 4
        ),
        current_assignee_id=ticket.current_assignee_id,
        escalation_target=ticket.escalation_target,
    )


def _passes(row: schemas.RiskRadarRow, overdue_only: bool, risk_band) -> bool:
    if overdue_only and not row.overdue:
        return False
    if risk_band:
        low, high = RISK_BANDS.get(risk_band.lower(), (0.0, 1.01))
        if row.risk_probability is None or not low <= row.risk_probability < high:
            return False
    return True


def _ordering(row: schemas.RiskRadarRow):
    """The spec's stable ordering, written as one key so it cannot be partly applied."""
    return (
        0 if row.priority == 1 else 1,
        0 if row.overdue else 1,
        -row.urgency_cost_per_minute,
        row.sla_due_at,
        row.ticket_id,
    )
