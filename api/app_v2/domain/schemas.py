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


class SlaPolicyPatch(BaseModel):
    """The business inputs a manager may edit (spec I.4).

    Priority is absent because it identifies the row, and version is absent
    because it is the system's counter: a manager who could type a version could
    make an old recommendation look current.
    """

    target_minutes: Optional[int] = Field(default=None, gt=0)
    breach_penalty_per_minute: Optional[float] = Field(default=None, ge=0)
    late_penalty_per_minute: Optional[float] = Field(default=None, ge=0)
    overdue_recovery_penalty_per_minute: Optional[float] = Field(default=None, ge=0)
    holding_cost_per_minute: Optional[float] = Field(default=None, ge=0)
    escalation_threshold: Optional[float] = Field(default=None, ge=0, le=1)
    source_note: Optional[str] = Field(default=None, min_length=1)


class SlaPolicyResponse(BaseModel):
    """One policy after an edit, with what the edit reaches.

    ``affected_ticket_ids`` are the open tickets of that priority which received
    a ``POLICY_CHANGED_REFERENCE`` event. Their stored deadlines did not move;
    the field exists so the interface can say truthfully which live work the
    next recommendation will price differently.
    """

    policy: SlaPolicyOut
    changes: dict
    affected_ticket_ids: List[str]
    request_id: str


class HealthResponse(BaseModel):
    status: str
    dialect: str
    migration_head_present: bool
    #: False when no usable artifact is installed. Automated recommendation is
    #: blocked in that state; the client shows the manual-dispatch banner.
    models_available: bool = False
    risk_model_version: Optional[str] = None
    duration_model_version: Optional[str] = None
    request_id: str


# --- dispatch (spec D.3 to D.6) --------------------------------------------


class AgentSummary(BaseModel):
    """Just enough of an agent to name them in a recommendation."""

    id: str
    display_name: str


class RecommendationRequest(BaseModel):
    """Ask for recommendations. This request never assigns anyone."""

    ticket_ids: List[str] = Field(min_length=1)
    #: ``batch`` gives every decision a shared batch id; ``single`` leaves it
    #: null, which is what a one-ticket recommendation from the ticket page is.
    mode: str = "batch"
    as_of: Optional[datetime] = None

    @field_validator("mode")
    @classmethod
    def _known_mode(cls, value):
        if value not in ("batch", "single"):
            raise ValueError("mode must be 'batch' or 'single'")
        return value

    @field_validator("as_of")
    @classmethod
    def _aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("as_of must include a timezone offset")
        return value


class DecisionOut(BaseModel):
    """A stored recommendation, exactly as it was written.

    ``reason`` is the text the decision carries. The client shows it verbatim;
    nothing recomputes it, here or in the browser.
    """

    decision_id: str
    ticket_id: str
    batch_id: Optional[str]
    state: str
    recommended_agent: Optional[AgentSummary]
    risk_probability: Optional[float]
    predicted_duration_minutes: Optional[float]
    projected_wait_minutes: Optional[float]
    projected_finish_at: Optional[datetime]
    projected_lateness_minutes: Optional[float]
    sla_due_at: datetime
    reason: str
    model_version: Optional[str]
    policy_version: int
    eligible_agent_count: int
    created_at: datetime


class DecisionListResponse(BaseModel):
    decisions: List[DecisionOut]
    request_id: str


class DecisionDetailResponse(BaseModel):
    decision: DecisionOut
    #: Every candidate the solve priced, with its cost components. This is the
    #: audit view; it is not needed to render a queue row.
    candidate_payload: dict
    request_id: str


class OverrideRequest(BaseModel):
    agent_id: str
    #: A non-empty reason is a hard requirement, not a nudge: an override with no
    #: stated reason is an unexplained change in the audit trail.
    reason: str = Field(min_length=1)


class AssignmentResponse(BaseModel):
    """What was recommended and what was actually assigned, side by side."""

    decision: DecisionOut
    assigned_agent: Optional[AgentSummary]
    ticket_status: str
    overridden: bool
    request_id: str


class RescoreRequest(BaseModel):
    only_stale: bool = True
    stale_after_minutes: int = Field(default=5, ge=0)
    as_of: Optional[datetime] = None

    @field_validator("as_of")
    @classmethod
    def _aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("as_of must include a timezone offset")
        return value


class RescoreResponse(BaseModel):
    considered: int
    rescored: int
    unchanged: int
    request_id: str


class RiskRadarRow(BaseModel):
    """One open ticket with the numbers that decided where it sits in the list."""

    ticket_id: str
    external_reference: Optional[str]
    priority: int
    status: str
    required_skill: Optional[str]
    sla_due_at: datetime
    minutes_to_due: float
    overdue: bool
    overdue_minutes: float
    risk_probability: Optional[float]
    risk_model_version: Optional[str]
    urgency_cost_per_minute: float
    current_assignee_id: Optional[str]


class RiskRadarResponse(BaseModel):
    as_of: datetime
    tickets: List[RiskRadarRow]
    request_id: str


class EscalationAcknowledgeRequest(BaseModel):
    """A human answering an escalation recommendation, or raising one."""

    #: Required for the same reason an override reason is required: an
    #: unexplained entry in the audit trail is not an audit trail.
    note: str = Field(min_length=1)


class EscalationAcknowledgeResponse(BaseModel):
    ticket_id: str
    event: EventOut
    #: True when the model had already flagged this ticket. False means the
    #: dispatcher went first, and the history says so.
    following_recommendation: bool
    #: Unchanged by this action, and returned so the client can show that.
    ticket_status: str
    request_id: str
