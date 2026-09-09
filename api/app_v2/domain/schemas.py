"""Request and response shapes for the version-2 API.

These are the contract. Routes convert ORM rows into these models and never
return an ORM object, so a column added to a table does not silently widen the
API, and a client field never depends on lazy loading.

Every response carries ``request_id`` (spec D) so a screenshot of a failure in
the demo can be traced to a specific request.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class ActorOut(BaseModel):
    """The signed-in user, with nothing about credentials in it."""

    id: str
    username: str
    role: str


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    actor: ActorOut
    request_id: str


class LogoutResponse(BaseModel):
    signed_out: bool
    request_id: str


class TicketCreate(BaseModel):
    external_reference: Optional[str] = None
    priority: int = Field(ge=1, le=4)
    category: Optional[str] = None
    subcategory: Optional[str] = None
    location: Optional[str] = None
    contact_type: Optional[str] = None
    required_skill: Optional[str] = None
    #: Defaults to now. Supplied explicitly by the replay and the seed command
    #: so a fixture reproduces the same deadlines on every run.
    opened_at: Optional[datetime] = None

    @field_validator("opened_at")
    @classmethod
    def _must_be_timezone_aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("opened_at must include a timezone offset")
        return value


class TicketPatch(BaseModel):
    """The fields a dispatcher may correct after creation.

    Priority is here and the deadline is not: changing a priority is a triage
    decision that gets recorded as an event, while ``sla_due_at`` stays fixed at
    the value the policy produced when the ticket was opened.
    """

    priority: Optional[int] = Field(default=None, ge=1, le=4)
    status: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    location: Optional[str] = None
    contact_type: Optional[str] = None
    required_skill: Optional[str] = None


class TicketOut(BaseModel):
    id: str
    external_reference: Optional[str]
    source: str
    status: str
    priority: int
    category: Optional[str]
    subcategory: Optional[str]
    location: Optional[str]
    contact_type: Optional[str]
    required_skill: Optional[str]
    opened_at: datetime
    sla_due_at: datetime
    current_assignee_id: Optional[str]
    risk_probability: Optional[float]
    risk_model_version: Optional[str]
    last_scored_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class TicketResponse(BaseModel):
    ticket: TicketOut
    request_id: str


class TicketListResponse(BaseModel):
    tickets: List[TicketOut]
    total: int
    request_id: str


class EventOut(BaseModel):
    id: str
    ticket_id: str
    decision_id: Optional[str]
    actor_user_id: Optional[str]
    event_type: str
    payload: dict
    occurred_at: datetime


class EventListResponse(BaseModel):
    events: List[EventOut]
    request_id: str


class SkillIn(BaseModel):
    skill: str
    efficiency_multiplier: float = Field(default=1.0, gt=0)
    is_primary: bool = False


class AgentCreate(BaseModel):
    display_name: str
    wip_limit: int = Field(default=1, ge=1)
    is_active: bool = True
    skills: List[SkillIn] = Field(default_factory=list)


class AgentPatch(BaseModel):
    display_name: Optional[str] = None
    wip_limit: Optional[int] = Field(default=None, ge=1)
    is_active: Optional[bool] = None


class SkillOut(BaseModel):
    skill: str
    efficiency_multiplier: float
    is_primary: bool


class AgentOut(BaseModel):
    id: str
    display_name: str
    is_active: bool
    wip_limit: int
    next_available_at: Optional[datetime]
    skills: List[SkillOut]


class AgentResponse(BaseModel):
    agent: AgentOut
    request_id: str


class AgentListResponse(BaseModel):
    agents: List[AgentOut]
    request_id: str


class SlaPolicyOut(BaseModel):
    id: str
    priority: int
    target_minutes: int
    breach_penalty_per_minute: float
    late_penalty_per_minute: float
    overdue_recovery_penalty_per_minute: float
    holding_cost_per_minute: float
    escalation_threshold: float
    version: int
    source_note: str


class SlaPolicyListResponse(BaseModel):
    policies: List[SlaPolicyOut]
    request_id: str


class HealthResponse(BaseModel):
    status: str
    dialect: str
    migration_head_present: bool
    request_id: str
