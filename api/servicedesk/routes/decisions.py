"""Recommendation, acceptance and override (spec D.3, D.4).

Route handlers only. Every number in a response comes from a service call and
from the immutable row that call wrote; nothing is recomputed here, and the
reason string is read back from the decision rather than rebuilt for display.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from api.servicedesk import deps
from api.servicedesk.db import models
from api.servicedesk.db.session import get_db
from api.servicedesk.domain import schemas
from api.servicedesk.services import decisions as decision_service

router = APIRouter(prefix="/assignment-decisions", tags=["decisions"])


def _agent_summary(db: DbSession, agent_id):
    if not agent_id:
        return None
    agent = db.get(models.Agent, agent_id)
    if agent is None:
        return None
    return schemas.AgentSummary(id=agent.id, display_name=agent.display_name)


def decision_out(db: DbSession, decision: models.AssignmentDecision,
                 ticket: models.Ticket) -> schemas.DecisionOut:
    """One stored decision, rendered without recomputing any of it."""
    payload = decision.candidate_payload_json or {}
    return schemas.DecisionOut(
        decision_id=decision.id,
        ticket_id=decision.ticket_id,
        batch_id=decision.batch_id,
        state=decision.recommendation_state,
        recommended_agent=_agent_summary(db, decision.recommended_agent_id),
        risk_probability=decision.risk_probability,
        predicted_duration_minutes=decision.predicted_duration_minutes,
        projected_wait_minutes=decision.projected_wait_minutes,
        projected_finish_at=decision.projected_finish_at,
        projected_lateness_minutes=decision.projected_lateness_minutes,
        sla_due_at=ticket.sla_due_at,
        reason=decision.reason_text,
        model_version=decision.model_version,
        policy_version=decision.policy_version,
        eligible_agent_count=payload.get("eligible_agent_count", 0),
        created_at=decision.created_at,
    )


@router.post("", response_model=schemas.DecisionListResponse, status_code=201)
def create_recommendations(
    payload: schemas.RecommendationRequest,
    db: DbSession = Depends(get_db),
    actor=Depends(deps.current_user),
    request_id: str = Depends(deps.request_id),
):
    """Recommend, and only recommend. This endpoint assigns nobody (spec D.3)."""
    rows = decision_service.recommend(
        db, actor, payload.ticket_ids, as_of=payload.as_of, mode=payload.mode
    )
    tickets = {row.ticket_id: db.get(models.Ticket, row.ticket_id) for row in rows}
    response = schemas.DecisionListResponse(
        decisions=[decision_out(db, row, tickets[row.ticket_id]) for row in rows],
        request_id=request_id,
    )
    return response


@router.post("/{decision_id}/accept", response_model=schemas.AssignmentResponse)
def accept_recommendation(
    decision_id: str,
    db: DbSession = Depends(get_db),
    actor=Depends(deps.current_user),
    request_id: str = Depends(deps.request_id),
):
    ticket, decision = decision_service.accept(db, actor, decision_id)
    response = schemas.AssignmentResponse(
        decision=decision_out(db, decision, ticket),
        assigned_agent=_agent_summary(db, ticket.current_assignee_id),
        ticket_status=ticket.status,
        overridden=False,
        request_id=request_id,
    )
    return response


@router.post("/{decision_id}/override", response_model=schemas.AssignmentResponse)
def override_recommendation(
    decision_id: str,
    payload: schemas.OverrideRequest,
    db: DbSession = Depends(get_db),
    actor=Depends(deps.current_user),
    request_id: str = Depends(deps.request_id),
):
    """Both the recommendation and the human's choice come back, so the client
    can show the difference honestly rather than only the outcome."""
    ticket, decision = decision_service.override(
        db, actor, decision_id, payload.agent_id, payload.reason
    )
    response = schemas.AssignmentResponse(
        decision=decision_out(db, decision, ticket),
        assigned_agent=_agent_summary(db, ticket.current_assignee_id),
        ticket_status=ticket.status,
        overridden=True,
        request_id=request_id,
    )
    return response


@router.get("/{decision_id}", response_model=schemas.DecisionDetailResponse)
def read_decision(
    decision_id: str,
    db: DbSession = Depends(get_db),
    actor=Depends(deps.current_user),
    request_id: str = Depends(deps.request_id),
):
    """The decision with its full candidate payload, for the audit view."""
    decision = decision_service.get_decision(db, decision_id)
    ticket = db.get(models.Ticket, decision.ticket_id)
    return schemas.DecisionDetailResponse(
        decision=decision_out(db, decision, ticket),
        candidate_payload=decision.candidate_payload_json,
        request_id=request_id,
    )
