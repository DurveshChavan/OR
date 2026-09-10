"""Who may take a ticket, and how much room they have left.

Eligibility is three separate questions and this module keeps them separate,
because a dispatcher who is told "not eligible" needs to know which one failed:

* is the agent active,
* does the agent hold the required skill as an explicit ``agent_skills`` row,
* does the agent have a free WIP slot after current open work is counted.

A skill is never inferred. A cross-skill pairing exists only where a row says
so, and that row's ``efficiency_multiplier`` is what makes the pairing slower or
faster than the reference resolver. There is no default multiplier for a skill
an agent does not have.

WIP is counted from live ticket rows, not from a cached counter, so a ticket
assigned by an override a second ago is already occupying its slot.
"""
from dataclasses import dataclass
from typing import Dict, List, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from api.app_v2.db import models
from api.app_v2.errors import ApiError

#: Statuses that hold a slot. A resolved or closed ticket releases capacity;
#: an escalation under review has not left the resolver's desk.
OCCUPYING_STATUSES = ("assigned", "escalation_review")


@dataclass(frozen=True)
class AgentCapacity:
    """One agent as dispatch sees them: skills, speed, and free slots."""

    agent_id: str
    display_name: str
    wip_limit: int
    open_count: int
    next_available_at: object
    #: skill -> efficiency multiplier, from explicit rows only.
    skills: Dict[str, float]

    @property
    def free_slots(self) -> int:
        return max(0, self.wip_limit - self.open_count)

    def holds(self, skill) -> bool:
        """A ticket with no required skill can go to any active agent."""
        return skill is None or skill in self.skills

    def multiplier_for(self, skill) -> float:
        if skill is None:
            return 1.0
        return self.skills[skill]


def load_capacities(db: DbSession, agent_ids: Sequence[str] = None) -> List[AgentCapacity]:
    """Active agents with their skills and current load, ordered by agent id.

    Ordered here rather than at the call site: the dispatch matrix has to be
    built from a fixed column order for the same inputs to give the same answer.
    """
    query = select(models.Agent).where(models.Agent.is_active.is_(True))
    if agent_ids is not None:
        query = query.where(models.Agent.id.in_(list(agent_ids)))
    agents = db.scalars(query.order_by(models.Agent.id.asc())).all()
    if not agents:
        return []

    ids = [agent.id for agent in agents]
    skills = _skills_by_agent(db, ids)
    loads = _open_counts(db, ids)
    return [
        AgentCapacity(
            agent_id=agent.id,
            display_name=agent.display_name,
            wip_limit=agent.wip_limit,
            open_count=loads.get(agent.id, 0),
            next_available_at=agent.next_available_at,
            skills=skills.get(agent.id, {}),
        )
        for agent in agents
    ]


def _skills_by_agent(db: DbSession, agent_ids) -> Dict[str, Dict[str, float]]:
    rows = db.execute(
        select(
            models.AgentSkill.agent_id,
            models.AgentSkill.skill,
            models.AgentSkill.efficiency_multiplier,
        ).where(models.AgentSkill.agent_id.in_(agent_ids))
    ).all()
    by_agent: Dict[str, Dict[str, float]] = {}
    for agent_id, skill, multiplier in rows:
        by_agent.setdefault(agent_id, {})[skill] = float(multiplier)
    return by_agent


def _open_counts(db: DbSession, agent_ids) -> Dict[str, int]:
    rows = db.execute(
        select(models.Ticket.current_assignee_id, func.count())
        .where(models.Ticket.current_assignee_id.in_(agent_ids))
        .where(models.Ticket.status.in_(OCCUPYING_STATUSES))
        .group_by(models.Ticket.current_assignee_id)
    ).all()
    return {agent_id: int(count) for agent_id, count in rows}


def eligible_for(ticket, capacities: Sequence[AgentCapacity]) -> List[AgentCapacity]:
    """Agents holding the ticket's skill, whether or not they have a free slot.

    Capacity is deliberately not filtered here. An agent with the exact skill and
    no free slot is a queue candidate the dispatcher should see, not a silently
    dropped one (spec F.3).
    """
    return [capacity for capacity in capacities if capacity.holds(ticket.required_skill)]


def check_assignable(ticket, capacity: AgentCapacity, is_active: bool = True) -> None:
    """Raise the specific reason an override target cannot take this ticket.

    Used by the override path, where a dispatcher named an agent and is entitled
    to a sentence explaining the refusal rather than a generic validation error.
    """
    if not is_active:
        raise ApiError(
            "AGENT_NOT_ELIGIBLE",
            "%s is not an active resolver." % capacity.display_name,
            status_code=409,
            details={"ticket_id": ticket.id, "agent_id": capacity.agent_id},
        )
    if not capacity.holds(ticket.required_skill):
        raise ApiError(
            "AGENT_NOT_ELIGIBLE",
            "%s does not hold the required %s skill."
            % (capacity.display_name, ticket.required_skill),
            status_code=409,
            details={
                "ticket_id": ticket.id,
                "agent_id": capacity.agent_id,
                "required_skill": ticket.required_skill,
            },
        )
    if capacity.free_slots <= 0:
        raise ApiError(
            "AGENT_AT_WIP_LIMIT",
            "%s is already holding %d of %d open tickets."
            % (capacity.display_name, capacity.open_count, capacity.wip_limit),
            status_code=409,
            details={
                "ticket_id": ticket.id,
                "agent_id": capacity.agent_id,
                "wip_limit": capacity.wip_limit,
                "open_count": capacity.open_count,
            },
        )


def capacity_for(db: DbSession, agent_id: str):
    """One agent's capacity and whether they are active, or a 404 naming the id.

    Active status is returned beside the capacity rather than filtered out,
    because :func:`check_assignable` has to be able to say "not an active
    resolver" instead of "no such agent".
    """
    agent = db.get(models.Agent, agent_id)
    if agent is None:
        raise ApiError(
            "AGENT_NOT_FOUND",
            "No agent exists with that id.",
            status_code=404,
            details={"agent_id": agent_id},
        )
    skills = _skills_by_agent(db, [agent_id]).get(agent_id, {})
    loads = _open_counts(db, [agent_id])
    capacity = AgentCapacity(
        agent_id=agent.id,
        display_name=agent.display_name,
        wip_limit=agent.wip_limit,
        open_count=loads.get(agent.id, 0),
        next_available_at=agent.next_available_at,
        skills=skills,
    )
    return capacity, bool(agent.is_active)
