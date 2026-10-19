"""Ticket CRUD, search, event history, the lifecycle, and escalation review.

Spec D.2 and D.6 for the ticket and history routes. Status changes only through
the named actions here (resolve, close, reopen, escalation review) and through
assignment in ``routes/decisions``; nothing here assigns anybody.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as DbSession

from api.servicedesk import deps
from api.servicedesk.db import models
from api.servicedesk.db.session import get_db
from api.servicedesk.domain import schemas
from api.servicedesk.services import escalation as escalation_service
from api.servicedesk.services import events, hardware
from api.servicedesk.services import tickets as ticket_service

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
        title=ticket.title,
        description=ticket.description,
        status=ticket.status,
        priority=ticket.priority,
        impact=ticket.impact,
        urgency=ticket.urgency,
        category=ticket.category,
        subcategory=ticket.subcategory,
        location=ticket.location,
        contact_type=ticket.contact_type,
        required_skill=ticket.required_skill,
        opened_at=ticket.opened_at,
        sla_due_at=ticket.sla_due_at,
        current_assignee_id=ticket.current_assignee_id,
        machine_id=ticket.machine_id,
        escalation_target=ticket.escalation_target,
        escalation_opened_at=ticket.escalation_opened_at,
        resolved_at=ticket.resolved_at,
        sla_met=ticket.resolved_at <= ticket.sla_due_at if ticket.resolved_at else None,
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
    q: Optional[str] = Query(default=None, max_length=100,
                             description="Matches the reference or the title, any case."),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
):
    query = select(models.Ticket)
    count_query = select(func.count()).select_from(models.Ticket)
    for condition in _filters(status, priority, assignee_id, q):
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


def _filters(status, priority, assignee_id, q):
    if status:
        yield models.Ticket.status == status
    if priority:
        yield models.Ticket.priority == priority
    if assignee_id:
        yield models.Ticket.current_assignee_id == assignee_id
    if q and q.strip():
        # Substring match on a few hundred rows; an index cannot serve a
        # leading wildcard anyway. shortcut: no full-text search, add one if
        # the desk grows past what a LIKE scan answers quickly.
        pattern = "%" + q.strip().lower().replace("%", "").replace("_", "") + "%"
        yield or_(func.lower(models.Ticket.external_reference).like(pattern),
                  func.lower(models.Ticket.title).like(pattern))


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


@router.put("/{ticket_id}/machine", response_model=schemas.TicketResponse)
def link_machine(
    ticket_id: str,
    payload: schemas.TicketMachineLink,
    db: DbSession = Depends(get_db),
    actor=Depends(deps.current_user),
    request_id: str = Depends(deps.request_id),
):
    """State which machine this ticket is about, or clear that statement.

    This is the only way a ticket and a machine are ever connected. No column in
    the source event log links an incident to an asset, so the link is a
    person's assertion and the history records who made it. Nothing in scoring
    or dispatch reads the field: linking a machine changes what the replacement
    advisor counts, and nothing else.
    """
    ticket = ticket_service.get_ticket(db, ticket_id)
    previous = ticket.machine_id
    if payload.machine_id is not None:
        machine = hardware.get_machine(db, payload.machine_id)
        ticket.machine_id = machine.id
        asset_tag = machine.asset_tag
    else:
        ticket.machine_id = None
        asset_tag = None
    db.flush()
    events.record(
        db,
        ticket.id,
        "TICKET_UPDATED",
        actor_user_id=actor.id,
        payload={
            "field": "machine_id",
            "previous_machine_id": previous,
            "machine_id": ticket.machine_id,
            "asset_tag": asset_tag,
            "note": "operator-stated link; nothing infers it and dispatch does not read it",
        },
    )
    db.commit()
    db.refresh(ticket)
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


@router.post(
    "/{ticket_id}/escalation-review",
    response_model=schemas.EscalationReviewResponse,
    status_code=201,
)
def start_escalation_review(
    ticket_id: str,
    payload: schemas.EscalationReviewRequest,
    db: DbSession = Depends(get_db),
    actor=Depends(deps.current_user),
    request_id: str = Depends(deps.request_id),
):
    """Open an internal review with a stated reason and a named target."""
    ticket = ticket_service.get_ticket(db, ticket_id)
    event = escalation_service.start_review(
        db, actor, ticket, payload.note, payload.target
    )
    return _review_response(ticket, event, request_id)


@router.post(
    "/{ticket_id}/escalation-review/close",
    response_model=schemas.EscalationReviewResponse,
    status_code=201,
)
def close_escalation_review(
    ticket_id: str,
    payload: schemas.EscalationReviewCloseRequest,
    db: DbSession = Depends(get_db),
    actor=Depends(deps.current_user),
    request_id: str = Depends(deps.request_id),
):
    """End a live review with a stated outcome and return the ticket to work."""
    ticket = ticket_service.get_ticket(db, ticket_id)
    event = escalation_service.close_review(
        db, actor, ticket, payload.note, payload.outcome
    )
    return _review_response(ticket, event, request_id)


@router.post("/{ticket_id}/resolve", response_model=schemas.TicketResponse, status_code=201)
def resolve_ticket(
    ticket_id: str,
    payload: schemas.TicketTransitionRequest,
    db: DbSession = Depends(get_db),
    actor=Depends(deps.current_user),
    request_id: str = Depends(deps.request_id),
):
    """Mark the work done; the response carries the SLA outcome."""
    return _transition(db, actor, ticket_id, payload.note, ticket_service.resolve_ticket, request_id)


@router.post("/{ticket_id}/close", response_model=schemas.TicketResponse, status_code=201)
def close_ticket(
    ticket_id: str,
    payload: schemas.TicketTransitionRequest,
    db: DbSession = Depends(get_db),
    actor=Depends(deps.current_user),
    request_id: str = Depends(deps.request_id),
):
    """Confirm a resolved ticket and end it."""
    return _transition(db, actor, ticket_id, payload.note, ticket_service.close_ticket, request_id)


@router.post("/{ticket_id}/reopen", response_model=schemas.TicketResponse, status_code=201)
def reopen_ticket(
    ticket_id: str,
    payload: schemas.TicketTransitionRequest,
    db: DbSession = Depends(get_db),
    actor=Depends(deps.current_user),
    request_id: str = Depends(deps.request_id),
):
    """Send a resolved or closed ticket back to the dispatch queue, unassigned."""
    return _transition(db, actor, ticket_id, payload.note, ticket_service.reopen_ticket, request_id)


def _transition(db, actor, ticket_id, note, action, request_id) -> schemas.TicketResponse:
    ticket = ticket_service.get_ticket(db, ticket_id)
    action(db, actor, ticket, note)
    return schemas.TicketResponse(ticket=_ticket_out(ticket), request_id=request_id)


def _review_response(ticket, event, request_id) -> schemas.EscalationReviewResponse:
    return schemas.EscalationReviewResponse(
        ticket_id=ticket.id,
        event=schemas.EventOut(
            id=event.id,
            ticket_id=event.ticket_id,
            decision_id=event.decision_id,
            actor_user_id=event.actor_user_id,
            event_type=event.event_type,
            payload=event.payload_json,
            occurred_at=event.occurred_at,
        ),
        ticket_status=ticket.status,
        escalation_target=ticket.escalation_target,
        request_id=request_id,
    )
