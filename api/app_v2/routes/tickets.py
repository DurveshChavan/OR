"""Ticket CRUD and event history (spec D.2, D.6).

There is no recommendation endpoint here yet. Dispatch arrives in phase 3, and
until then the queue shows tickets and their deadlines and nothing that pretends
to be a model output.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from api.app_v2 import deps
from api.app_v2.db import models
from api.app_v2.db.session import get_db
from api.app_v2.domain import schemas
from api.app_v2.services import tickets as ticket_service

router = APIRouter(prefix="/tickets", tags=["tickets"])

#: A page size a dispatcher can actually read, and a cap that keeps one request
#: from pulling a whole replay into the browser.
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def _ticket_out(ticket: models.Ticket) -> schemas.TicketOut:
    return schemas.TicketOut(
        id=ticket.id,
        external_reference=ticket.external_reference,
        source=ticket.source,
        status=ticket.status,
        priority=ticket.priority,
        category=ticket.category,
        subcategory=ticket.subcategory,
        location=ticket.location,
        contact_type=ticket.contact_type,
        required_skill=ticket.required_skill,
        opened_at=ticket.opened_at,
        sla_due_at=ticket.sla_due_at,
        current_assignee_id=ticket.current_assignee_id,
        risk_probability=ticket.risk_probability,
        risk_model_version=ticket.risk_model_version,
        last_scored_at=ticket.last_scored_at,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


@router.post("", response_model=schemas.TicketResponse, status_code=201)
def create_ticket(
    payload: schemas.TicketCreate,
    db: DbSession = Depends(get_db),
    actor=Depends(deps.current_user),
    request_id: str = Depends(deps.request_id),
):
    ticket = ticket_service.create_ticket(db, actor, payload)
    return schemas.TicketResponse(ticket=_ticket_out(ticket), request_id=request_id)


@router.get("", response_model=schemas.TicketListResponse)
def list_tickets(
    db: DbSession = Depends(get_db),
    actor=Depends(deps.current_user),
    request_id: str = Depends(deps.request_id),
    status: Optional[str] = Query(default=None),
    priority: Optional[int] = Query(default=None, ge=1, le=4),
    assignee_id: Optional[str] = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
):
    query = select(models.Ticket)
    count_query = select(func.count()).select_from(models.Ticket)
    for condition in _filters(status, priority, assignee_id):
        query = query.where(condition)
        count_query = count_query.where(condition)
    # Soonest deadline first, then id, so two tickets due at the same moment
    # always come back in the same order.
    query = query.order_by(models.Ticket.sla_due_at.asc(), models.Ticket.id.asc())
    rows = db.scalars(query.limit(limit).offset(offset)).all()
    return schemas.TicketListResponse(
        tickets=[_ticket_out(row) for row in rows],
        total=db.scalar(count_query),
        request_id=request_id,
    )


def _filters(status, priority, assignee_id):
    if status:
        yield models.Ticket.status == status
    if priority:
        yield models.Ticket.priority == priority
    if assignee_id:
        yield models.Ticket.current_assignee_id == assignee_id


@router.get("/{ticket_id}", response_model=schemas.TicketResponse)
def get_ticket(
    ticket_id: str,
    db: DbSession = Depends(get_db),
    actor=Depends(deps.current_user),
    request_id: str = Depends(deps.request_id),
):
    ticket = ticket_service.get_ticket(db, ticket_id)
    return schemas.TicketResponse(ticket=_ticket_out(ticket), request_id=request_id)


@router.patch("/{ticket_id}", response_model=schemas.TicketResponse)
def patch_ticket(
    ticket_id: str,
    payload: schemas.TicketPatch,
    db: DbSession = Depends(get_db),
    actor=Depends(deps.current_user),
    request_id: str = Depends(deps.request_id),
):
    ticket = ticket_service.get_ticket(db, ticket_id)
    ticket, _changes = ticket_service.patch_ticket(db, actor, ticket, payload)
    return schemas.TicketResponse(ticket=_ticket_out(ticket), request_id=request_id)


@router.get("/{ticket_id}/events", response_model=schemas.EventListResponse)
def list_events(
    ticket_id: str,
    db: DbSession = Depends(get_db),
    actor=Depends(deps.current_user),
    request_id: str = Depends(deps.request_id),
):
    """History ascending by occurrence time, then event id (spec D.6)."""
    ticket_service.get_ticket(db, ticket_id)
    rows = db.scalars(
        select(models.TicketEvent)
        .where(models.TicketEvent.ticket_id == ticket_id)
        .order_by(models.TicketEvent.occurred_at.asc(), models.TicketEvent.id.asc())
    ).all()
    return schemas.EventListResponse(
        events=[
            schemas.EventOut(
                id=row.id,
                ticket_id=row.ticket_id,
                decision_id=row.decision_id,
                actor_user_id=row.actor_user_id,
                event_type=row.event_type,
                payload=row.payload_json,
                occurred_at=row.occurred_at,
            )
            for row in rows
        ],
        request_id=request_id,
    )
