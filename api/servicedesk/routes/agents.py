"""Agent, skill and SLA policy administration.

Managers own this surface. A dispatcher can read the roster, because the queue
needs names, but cannot change who exists or what a breach is worth.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from api.servicedesk import deps
from api.servicedesk.db import models
from api.servicedesk.db.session import get_db
from api.servicedesk.domain import schemas
from api.servicedesk.errors import ApiError
from api.servicedesk.services import policies as policy_service

router = APIRouter(tags=["administration"])


def _agent_out(agent: models.Agent, skills) -> schemas.AgentOut:
    return schemas.AgentOut(
        id=agent.id,
        display_name=agent.display_name,
        is_active=agent.is_active,
        wip_limit=agent.wip_limit,
        next_available_at=agent.next_available_at,
        skills=[
            schemas.SkillOut(
                skill=skill.skill,
                efficiency_multiplier=skill.efficiency_multiplier,
                is_primary=skill.is_primary,
            )
            for skill in skills
        ],
    )


def _skills_for(db: DbSession, agent_id: str):
    return db.scalars(
        select(models.AgentSkill)
        .where(models.AgentSkill.agent_id == agent_id)
        .order_by(models.AgentSkill.skill.asc())
    ).all()


@router.get("/agents", response_model=schemas.AgentListResponse)
def list_agents(
    db: DbSession = Depends(get_db),
    actor=Depends(deps.current_user),
    request_id: str = Depends(deps.request_id),
):
    agents = db.scalars(select(models.Agent).order_by(models.Agent.display_name.asc())).all()
    return schemas.AgentListResponse(
        agents=[_agent_out(agent, _skills_for(db, agent.id)) for agent in agents],
        request_id=request_id,
    )


@router.post("/agents", response_model=schemas.AgentResponse, status_code=201)
def create_agent(
    payload: schemas.AgentCreate,
    db: DbSession = Depends(get_db),
    manager=Depends(deps.current_manager),
    request_id: str = Depends(deps.request_id),
):
    agent = models.Agent(
        display_name=payload.display_name,
        wip_limit=payload.wip_limit,
        is_active=payload.is_active,
    )
    db.add(agent)
    db.flush()
    _replace_skills(db, agent.id, payload.skills)
    return schemas.AgentResponse(
        agent=_agent_out(agent, _skills_for(db, agent.id)), request_id=request_id
    )


@router.patch("/agents/{agent_id}", response_model=schemas.AgentResponse)
def patch_agent(
    agent_id: str,
    payload: schemas.AgentPatch,
    db: DbSession = Depends(get_db),
    manager=Depends(deps.current_manager),
    request_id: str = Depends(deps.request_id),
):
    agent = _get_agent(db, agent_id)
    for field in ("display_name", "wip_limit", "is_active"):
        value = getattr(payload, field)
        if value is not None:
            setattr(agent, field, value)
    db.flush()
    return schemas.AgentResponse(
        agent=_agent_out(agent, _skills_for(db, agent.id)), request_id=request_id
    )


@router.put("/agents/{agent_id}/skills", response_model=schemas.AgentResponse)
def replace_skills(
    agent_id: str,
    payload: list[schemas.SkillIn],
    db: DbSession = Depends(get_db),
    manager=Depends(deps.current_manager),
    request_id: str = Depends(deps.request_id),
):
    """Set an agent's skills to exactly this list.

    Replacement rather than merge: eligibility is decided by these rows, and a
    skill that was removed has to actually disappear or the dispatcher would
    keep seeing an agent proposed for work they no longer do.
    """
    agent = _get_agent(db, agent_id)
    _replace_skills(db, agent.id, payload)
    return schemas.AgentResponse(
        agent=_agent_out(agent, _skills_for(db, agent.id)), request_id=request_id
    )


def _replace_skills(db: DbSession, agent_id: str, skills) -> None:
    seen = set()
    for skill in skills:
        if skill.skill in seen:
            raise ApiError(
                "SKILL_DUPLICATED",
                "The skill %s is listed twice for this agent." % skill.skill,
                status_code=422,
                details={"skill": skill.skill},
            )
        seen.add(skill.skill)
    for existing in _skills_for(db, agent_id):
        db.delete(existing)
    db.flush()
    for skill in skills:
        db.add(
            models.AgentSkill(
                agent_id=agent_id,
                skill=skill.skill,
                efficiency_multiplier=skill.efficiency_multiplier,
                is_primary=skill.is_primary,
            )
        )
    db.flush()


def _get_agent(db: DbSession, agent_id: str) -> models.Agent:
    agent = db.get(models.Agent, agent_id)
    if agent is None:
        raise ApiError(
            "AGENT_NOT_FOUND",
            "No agent exists with that id.",
            status_code=404,
            details={"agent_id": agent_id},
        )
    return agent


@router.get("/sla-policies", response_model=schemas.SlaPolicyListResponse)
def list_policies(
    db: DbSession = Depends(get_db),
    actor=Depends(deps.current_user),
    request_id: str = Depends(deps.request_id),
):
    policies = db.scalars(
        select(models.SlaPolicy).order_by(models.SlaPolicy.priority.asc())
    ).all()
    return schemas.SlaPolicyListResponse(
        policies=[_policy_out(policy) for policy in policies],
        request_id=request_id,
    )


def _policy_out(policy: models.SlaPolicy) -> schemas.SlaPolicyOut:
    return schemas.SlaPolicyOut(
        id=policy.id,
        priority=policy.priority,
        target_minutes=policy.target_minutes,
        breach_penalty_per_minute=policy.breach_penalty_per_minute,
        late_penalty_per_minute=policy.late_penalty_per_minute,
        overdue_recovery_penalty_per_minute=policy.overdue_recovery_penalty_per_minute,
        holding_cost_per_minute=policy.holding_cost_per_minute,
        escalation_threshold=policy.escalation_threshold,
        version=policy.version,
        source_note=policy.source_note,
    )


@router.patch("/sla-policies/{policy_id}", response_model=schemas.SlaPolicyResponse)
def patch_policy(
    policy_id: str,
    payload: schemas.SlaPolicyPatch,
    db: DbSession = Depends(get_db),
    manager=Depends(deps.current_manager),
    request_id: str = Depends(deps.request_id),
):
    """Edit the business inputs for one priority (spec I.4).

    The edit bumps ``version``, so every recommendation priced under the old
    numbers becomes stale and must be rescored before it can be accepted. No
    ticket's stored ``sla_due_at`` is touched, which is what the interface's
    "affects future recommendations only" warning actually means.
    """
    policy = policy_service.get_policy(db, policy_id)
    policy, changes, affected = policy_service.patch_policy(db, manager, policy, payload)
    return schemas.SlaPolicyResponse(
        policy=_policy_out(policy),
        changes=changes,
        affected_ticket_ids=affected,
        request_id=request_id,
    )
