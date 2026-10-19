"""The eight service-desk tables, exactly as specified in FINAL_IMPLEMENTATION.md C.2.

Deliberately absent, and each for a stated reason:

* no ``assignments`` table - the current assignment is ``tickets.current_assignee_id``;
  how it got there is recoverable from the immutable event history;
* no ``assignment_runs`` table - a batch is identified by a UUID carried in the
  decision and event payloads;
* no ``model_versions`` table - model metadata lives in the artifact's model card
  and is copied into every decision snapshot, so a decision stays readable even
  if an artifact is later replaced.

Two tables are append-only: ``assignment_decisions`` (a recommendation is a
historical fact) and ``ticket_events`` (the audit trail). Nothing in this module
enforces that; database triggers added by the second migration do, in both
dialects, because application-level immutability is a promise and a trigger is a
control.
"""
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.servicedesk.db.base import Base, IdColumn, new_id
from api.servicedesk.db.types import CanonicalJson, UtcDateTime, utcnow

USER_ROLES = ("dispatcher", "manager")
TICKET_SOURCES = ("manual", "uci_replay", "seed_demo")
TICKET_STATUSES = ("open", "assigned", "escalation_review", "resolved", "closed")
#: Terminal statuses never appear in the Risk Radar or in a rescore batch.
TERMINAL_TICKET_STATUSES = ("resolved", "closed")
RECOMMENDATION_STATES = ("recommended", "no_eligible_agent", "queued")

#: Where an escalation review is sent. Every entry is a route this desk actually
#: has: two people who work here, and the asset-replacement decision this
#: project computes. There is no "L2 queue" or "vendor" in the list, because
#: this application operates neither and a named target it cannot reach would be
#: the acknowledgement ritual over again with a better label.
ESCALATION_TARGETS = ("senior_resolver", "duty_manager", "asset_replacement")

#: How an escalation review ends. A review that cannot be closed is a state a
#: ticket falls into and never leaves, which is why the vocabulary exists.
ESCALATION_OUTCOMES = ("reassigned", "replacement_raised", "no_action")

#: Event vocabulary. The first eleven are required by spec C.2; MODEL_UNAVAILABLE
#: is the documented manual-fallback marker described in spec C.3, recorded so a
#: ticket created without a model score is visibly not a scored ticket.
EVENT_TYPES = (
    "TICKET_CREATED",
    "TICKET_UPDATED",
    "RISK_SCORED",
    "ASSIGNMENT_RECOMMENDED",
    "ASSIGNMENT_ACCEPTED",
    "ASSIGNMENT_OVERRIDDEN",
    "NO_ELIGIBLE_AGENT",
    "QUEUED_FOR_TRIAGE",
    "ESCALATION_RECOMMENDED",
    "ESCALATION_ACKNOWLEDGED",
    "POLICY_CHANGED_REFERENCE",
    "MODEL_UNAVAILABLE",
)


def _in_set(column, allowed):
    """SQL fragment restricting a column to an allowed set, written once."""
    values = ", ".join("'%s'" % value for value in allowed)
    return "%s IN (%s)" % (column, values)


class User(Base):
    """A local sign-in. Every mutation resolves to one of these as its actor."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(IdColumn, primary_key=True, default=new_id)
    #: Stored already lower-cased; the route layer normalises before comparing,
    #: which is what makes the uniqueness case-insensitive in practice.
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[object] = mapped_column(UtcDateTime, nullable=False, default=utcnow)

    __table_args__ = (
        CheckConstraint(_in_set("role", USER_ROLES), name="ck_users_role"),
        CheckConstraint("username = lower(username)", name="ck_users_username_lowercase"),
    )


class Session(Base):
    """A server-side session. The cookie carries the id and nothing else."""

    __tablename__ = "sessions"

    #: The random token itself is never stored: this is a SHA-256 hash of the
    #: cookie value, so a database dump does not hand out live sessions.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(IdColumn, ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[object] = mapped_column(UtcDateTime, nullable=False)
    revoked_at: Mapped[object] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[object] = mapped_column(UtcDateTime, nullable=False, default=utcnow)

    __table_args__ = (Index("ix_sessions_user_id", "user_id"),)


class Agent(Base):
    """A resolver who can hold work. Capacity is the WIP limit, not a guess."""

    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(IdColumn, primary_key=True, default=new_id)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    wip_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_available_at: Mapped[object] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[object] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[object] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        CheckConstraint("wip_limit >= 1", name="ck_agents_wip_limit_positive"),
    )


class AgentSkill(Base):
    """One skill an agent may work, with the documented speed effect of that pairing."""

    __tablename__ = "agent_skills"

    id: Mapped[str] = mapped_column(IdColumn, primary_key=True, default=new_id)
    agent_id: Mapped[str] = mapped_column(IdColumn, ForeignKey("agents.id"), nullable=False)
    skill: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Below 1.0 is faster than the reference resolver, above 1.0 is slower.
    #: A cross-skill pairing exists only where an explicit row here allows it.
    efficiency_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("agent_id", "skill", name="uq_agent_skills_agent_skill"),
        CheckConstraint(
            "efficiency_multiplier > 0", name="ck_agent_skills_multiplier_positive"
        ),
    )


class SlaPolicy(Base):
    """The manager-editable business inputs for one priority.

    Every cost here is a rate per minute in one declared currency unit, so the
    dispatch cost terms can be added together and still mean something.
    """

    __tablename__ = "sla_policies"

    id: Mapped[str] = mapped_column(IdColumn, primary_key=True, default=new_id)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    target_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    breach_penalty_per_minute: Mapped[float] = mapped_column(Float, nullable=False)
    late_penalty_per_minute: Mapped[float] = mapped_column(Float, nullable=False)
    overdue_recovery_penalty_per_minute: Mapped[float] = mapped_column(Float, nullable=False)
    holding_cost_per_minute: Mapped[float] = mapped_column(Float, nullable=False)
    escalation_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    #: Incremented on every policy edit and snapshotted into each decision, so a
    #: recommendation can still be read against the numbers that produced it.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: Says where the number came from. Demo rows must say they are a demo.
    source_note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[object] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[object] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        CheckConstraint("priority BETWEEN 1 AND 4", name="ck_sla_policies_priority_range"),
        CheckConstraint("target_minutes > 0", name="ck_sla_policies_target_positive"),
        CheckConstraint(
            "breach_penalty_per_minute >= 0", name="ck_sla_policies_breach_penalty"
        ),
        CheckConstraint("late_penalty_per_minute >= 0", name="ck_sla_policies_late_penalty"),
        CheckConstraint(
            "overdue_recovery_penalty_per_minute >= 0",
            name="ck_sla_policies_overdue_penalty",
        ),
        CheckConstraint("holding_cost_per_minute >= 0", name="ck_sla_policies_holding_cost"),
        CheckConstraint(
            "escalation_threshold BETWEEN 0 AND 1", name="ck_sla_policies_threshold_range"
        ),
        CheckConstraint("version >= 1", name="ck_sla_policies_version_positive"),
        CheckConstraint("length(source_note) > 0", name="ck_sla_policies_source_note_present"),
    )


class Ticket(Base):
    """Current operational state of one piece of work. Not the audit trail."""

    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(IdColumn, primary_key=True, default=new_id)
    external_reference: Mapped[str] = mapped_column(String(64), nullable=True, unique=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    #: What the caller reported, in their words. Required by the create route;
    #: nullable here because tickets made before titles existed have none, and
    #: back-filling one would put words in a caller's mouth. Nothing in risk
    #: scoring reads either field - only the urgency a person confirmed does.
    title: Mapped[str] = mapped_column(String(200), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    #: 1 is the highest priority. The convention is stated here because both the
    #: cost model and the UCI priority field depend on reading it the same way.
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    #: ITIL impact and urgency, 1 (high) to 3 (low), as UCI-498 records them.
    #: When both are set, priority is derived from them (services/triage.py).
    #: Range-checked at the API rather than by a CHECK constraint, so a database
    #: built fresh and one migrated by revision 0005 carry the same schema.
    impact: Mapped[int] = mapped_column(Integer, nullable=True)
    urgency: Mapped[int] = mapped_column(Integer, nullable=True)
    category: Mapped[str] = mapped_column(String(64), nullable=True)
    subcategory: Mapped[str] = mapped_column(String(64), nullable=True)
    location: Mapped[str] = mapped_column(String(64), nullable=True)
    contact_type: Mapped[str] = mapped_column(String(32), nullable=True)
    required_skill: Mapped[str] = mapped_column(String(64), nullable=True)
    opened_at: Mapped[object] = mapped_column(UtcDateTime, nullable=False)
    #: Fixed at creation from the policy in force then. A later policy edit does
    #: not move an existing deadline, which is what makes a breach arguable.
    sla_due_at: Mapped[object] = mapped_column(UtcDateTime, nullable=False)
    current_assignee_id: Mapped[str] = mapped_column(
        IdColumn, ForeignKey("agents.id"), nullable=True
    )
    #: The machine this ticket is about, if a human said so. Nullable and
    #: operator-set: no column in UCI-498 links an incident to an asset, so a
    #: value here is a person's statement and never an inference. Nothing in
    #: dispatch reads it.
    machine_id: Mapped[str] = mapped_column(
        IdColumn, ForeignKey("machines.id"), nullable=True
    )
    #: Who a live escalation review is with, and when it opened. Both are NULL
    #: unless ``status == "escalation_review"``; closing the review clears them
    #: and the immutable event history keeps the record of what happened. They
    #: are columns rather than facts reconstructed from events because the queue
    #: and the at-risk list have to show them on every row, and an escalation a
    #: dispatcher has to open a ticket to see is an escalation nobody chases.
    escalation_target: Mapped[str] = mapped_column(String(32), nullable=True)
    escalation_opened_at: Mapped[object] = mapped_column(UtcDateTime, nullable=True)
    #: When the ticket was last resolved. Cleared on reopen; the event history
    #: keeps every earlier resolution. Compared against the fixed ``sla_due_at``
    #: it is the SLA outcome.
    resolved_at: Mapped[object] = mapped_column(UtcDateTime, nullable=True)
    risk_probability: Mapped[float] = mapped_column(Float, nullable=True)
    risk_model_version: Mapped[str] = mapped_column(String(64), nullable=True)
    last_scored_at: Mapped[object] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[object] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[object] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        CheckConstraint(_in_set("source", TICKET_SOURCES), name="ck_tickets_source"),
        CheckConstraint(_in_set("status", TICKET_STATUSES), name="ck_tickets_status"),
        CheckConstraint("priority BETWEEN 1 AND 4", name="ck_tickets_priority_range"),
        CheckConstraint(
            "risk_probability IS NULL OR (risk_probability >= 0 AND risk_probability <= 1)",
            name="ck_tickets_risk_probability_range",
        ),
        CheckConstraint("sla_due_at > opened_at", name="ck_tickets_due_after_opened"),
        # The queue reads by deadline, the radar reads by risk within priority,
        # and the agent view reads by assignee. One index each.
        Index("ix_tickets_status_sla_due_at", "status", "sla_due_at"),
        Index("ix_tickets_status_priority_risk", "status", "priority", "risk_probability"),
        Index("ix_tickets_current_assignee_id", "current_assignee_id"),
        Index("ix_tickets_machine_id", "machine_id"),
    )


class AssignmentDecision(Base):
    """One immutable recommendation.

    Nothing updates a row here. Acceptance, override and every later change are
    events; this row stays exactly as the policy produced it, which is what lets
    the ticket page show what was recommended next to what a human chose.
    """

    __tablename__ = "assignment_decisions"

    id: Mapped[str] = mapped_column(IdColumn, primary_key=True, default=new_id)
    ticket_id: Mapped[str] = mapped_column(IdColumn, ForeignKey("tickets.id"), nullable=False)
    #: Present for a batch solve, null for a single-ticket recommendation.
    batch_id: Mapped[str] = mapped_column(IdColumn, nullable=True)
    #: Null only when the state itself says no agent was recommended.
    recommended_agent_id: Mapped[str] = mapped_column(
        IdColumn, ForeignKey("agents.id"), nullable=True
    )
    recommendation_state: Mapped[str] = mapped_column(String(24), nullable=False)
    risk_probability: Mapped[float] = mapped_column(Float, nullable=True)
    predicted_duration_minutes: Mapped[float] = mapped_column(Float, nullable=True)
    projected_wait_minutes: Mapped[float] = mapped_column(Float, nullable=True)
    projected_finish_at: Mapped[object] = mapped_column(UtcDateTime, nullable=True)
    projected_lateness_minutes: Mapped[float] = mapped_column(Float, nullable=True)
    model_version: Mapped[str] = mapped_column(String(64), nullable=True)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Every eligible candidate with its cost components and tie-break value.
    #: The stored reason is generated from this and must agree with it.
    candidate_payload_json: Mapped[dict] = mapped_column(CanonicalJson, nullable=False)
    reason_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[object] = mapped_column(UtcDateTime, nullable=False, default=utcnow)

    __table_args__ = (
        CheckConstraint(
            _in_set("recommendation_state", RECOMMENDATION_STATES),
            name="ck_assignment_decisions_state",
        ),
        CheckConstraint(
            "(recommendation_state = 'recommended' AND recommended_agent_id IS NOT NULL)"
            " OR (recommendation_state <> 'recommended' AND recommended_agent_id IS NULL)",
            name="ck_assignment_decisions_agent_matches_state",
        ),
        CheckConstraint(
            "risk_probability IS NULL OR (risk_probability >= 0 AND risk_probability <= 1)",
            name="ck_assignment_decisions_risk_range",
        ),
        CheckConstraint(
            "length(reason_text) > 0", name="ck_assignment_decisions_reason_present"
        ),
        Index("ix_assignment_decisions_ticket_id", "ticket_id", "created_at"),
        Index("ix_assignment_decisions_batch_id", "batch_id"),
    )


class TicketEvent(Base):
    """Append-only history. This table answers "why did that happen?"."""

    __tablename__ = "ticket_events"

    id: Mapped[str] = mapped_column(IdColumn, primary_key=True, default=new_id)
    ticket_id: Mapped[str] = mapped_column(IdColumn, ForeignKey("tickets.id"), nullable=False)
    #: Set when the event refers to a specific recommendation.
    decision_id: Mapped[str] = mapped_column(
        IdColumn, ForeignKey("assignment_decisions.id"), nullable=True
    )
    #: Null only for events a system command produced with no signed-in human.
    actor_user_id: Mapped[str] = mapped_column(IdColumn, ForeignKey("users.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[dict] = mapped_column(CanonicalJson, nullable=False)
    occurred_at: Mapped[object] = mapped_column(UtcDateTime, nullable=False, default=utcnow)

    __table_args__ = (
        CheckConstraint(_in_set("event_type", EVENT_TYPES), name="ck_ticket_events_type"),
        # History is read in occurrence order, with the id breaking ties so the
        # order is stable when two events share a timestamp.
        Index("ix_ticket_events_ticket_id_occurred_at", "ticket_id", "occurred_at", "id"),
        Index("ix_ticket_events_decision_id", "decision_id"),
    )


#: Machine families the replacement model treats differently. The engine's
#: ALPHA_BY_TYPE assumes a laptop wears faster than a desktop; that is a
#: documented assumption, not a measurement, and the advisor screen says so.
MACHINE_TYPES = ("desktop", "laptop", "server", "kiosk")


class Machine(Base):
    """One workstation the service desk supports, entered by a manager.

    **Where this data comes from, stated in the schema because the answer
    decides whether the whole feature is honest.** UCI-498 has no ticket-to-asset
    join and no hardware telemetry, so nothing here is mined, inferred or
    modelled from the incident log. Every column is typed in by an operator from
    their own asset register or purchasing records. The replacement advice is
    therefore a decision-support calculation over the organisation's own numbers,
    not a prediction about hardware this project has observed.

    ``running_cost_by_year`` is the yearly maintenance-plus-downtime cost the
    operator attributes to this machine, oldest year first. It is what makes the
    deteriorating-item average-cost method applicable: the method needs a rising
    running cost and a falling resale value, and both are organisational facts.
    """

    __tablename__ = "machines"

    id: Mapped[str] = mapped_column(IdColumn, primary_key=True, default=new_id)
    asset_tag: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    location: Mapped[str] = mapped_column(String(64), nullable=True)
    machine_type: Mapped[str] = mapped_column(String(16), nullable=False, default="desktop")
    #: Age in whole months at the moment the operator recorded it, together with
    #: when that was, so the advisor can age it forward without anyone editing
    #: the row every month.
    age_months: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    age_recorded_at: Mapped[object] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    purchase_cost: Mapped[float] = mapped_column(Float, nullable=False)
    #: Resale value, oldest year first, aligned with running_cost_by_year. A
    #: single-element list means a constant resale value.
    scrap_value_by_year_json: Mapped[dict] = mapped_column(CanonicalJson, nullable=False)
    running_cost_by_year_json: Mapped[dict] = mapped_column(CanonicalJson, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: Free text: where the operator got these numbers. Required, for the same
    #: reason the SLA policy rows carry a source note.
    source_note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[object] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[object] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        CheckConstraint(_in_set("machine_type", MACHINE_TYPES), name="ck_machines_type"),
        CheckConstraint("age_months >= 0", name="ck_machines_age_non_negative"),
        CheckConstraint("purchase_cost > 0", name="ck_machines_purchase_positive"),
        Index("ix_machines_location", "location"),
    )
