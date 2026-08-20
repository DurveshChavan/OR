"""FastAPI app exposing api.engine over HTTP.

This file is route handlers and pydantic schemas only -- zero OR logic.
Every handler calls straight into api.engine.pipeline (or the module it
re-exports from), which owns every computation, every CONFIG default, and
every "source" string. This file's only job is: parse the request, call
the engine, shape the response, cast numpy/pandas scalars to plain
Python types (pydantic v2 validates strictly and rejects e.g. numpy.int64).

State: one in-memory scenario (module-level `_state`), seeded with a
default at import time so every GET works even before a client calls
POST /api/scenario. POST /api/scenario replaces it outright. Downstream
per-stage results (staffing, distribution, schedule, escalations,
hardware) are cached lazily and invalidated where a re-solve would make
them stale (re-solving staffing changes the funded agent pool, so it
invalidates schedule/escalations/degradation state; distribution is
independent of the ticket chain and never invalidates anything).

/api/comparison is scoped to the M3/M7 hardware-ageing story specifically
(baseline / aged / replaced assignment cost against the CURRENT funded
agent pool) -- it does not reproduce the CLI pipeline's full
funding-and-escalation-adjusted three-stage table (see
api.engine.pipeline.run_pipeline for that). That table needs the whole
M1->M6 chain run as one batch; this API is built for incremental,
per-stage interaction from a frontend instead.
"""
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api.engine.pipeline import (
    CONFIG,
    _load_cleaned_log, derive_all, load_or_synthesize_data,
    size_capacity, select_funded_agents, _assert_no_unfunded_agent,
    distribute_regions, assignment_stage, _triage_share, sequence_tickets,
    _incident_forces_escalation, route_escalations, split_by_escalation,
    choose_replacements, plan_major_incident,
)
from api.engine.replacement import workstation_factors, ALPHA_BY_TYPE
from api.engine.assignment import INFEASIBLE
from api.engine.decision import escalation_game

app = FastAPI(title="SLA Ticket Allocation API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str


class ScenarioRequest(BaseModel):
    n_tickets: int = 50
    n_agents: int = 150
    n_workstations: int = 20
    seed: int = 42


class ScenarioResponse(BaseModel):
    n_tickets: int
    n_agents: int
    n_workstations: int
    seed: int
    data_source: str
    derived_sources: Dict[str, str]


class StaffingResponse(BaseModel):
    status: str
    agents_per_skill: Dict[str, int]
    total_cost: Optional[float]
    demand_by_skill: Dict[str, int]
    cost_by_skill: Dict[str, float]
    budget: float
    min_per_skill: Dict[str, int]
    source: str


class StaffingOverrideRequest(BaseModel):
    budget: Optional[float] = None
    cost_by_skill: Optional[Dict[str, float]] = None


class DistributionResponse(BaseModel):
    allocation: List[List[float]]
    total_cost: float
    supply: List[float]
    demand: List[float]
    cost: List[List[float]]
    source: str


class DistributionOverrideRequest(BaseModel):
    capacities: Optional[List[float]] = None
    cost_matrix: Optional[List[List[float]]] = None


class AssignmentPair(BaseModel):
    ticket_id: str
    agent_id: str
    cost: float


class AssignmentResponse(BaseModel):
    aged: bool
    ticket_ids: List[str]
    agent_ids: List[str]
    matrix: List[List[Optional[float]]]
    pairs: List[AssignmentPair]
    total_cost: float
    n_tickets_served: int


class ScheduleEntry(BaseModel):
    ticket_id: str
    triage_start: float
    triage_end: float
    fix_start: float
    fix_end: float
    completion_minutes: float


class ScheduleResponse(BaseModel):
    sequence: List[str]
    makespan: float
    entries: List[ScheduleEntry]


class EscalationRow(BaseModel):
    ticket_id: str
    priority: int
    act: str
    time_to_breach_hours: Optional[float]
    forced_by_incident_risk: bool
    acts: List[str]
    payoff: List[List[float]]
    p_breach: List[float]
    values: List[float]


class EscalationsResponse(BaseModel):
    rows: List[EscalationRow]
    counts: Dict[str, int]
    vendor_cost: float


class SaddlePoint(BaseModel):
    exists: bool
    value: Optional[float]
    position: Optional[List[int]]


class Dominance(BaseModel):
    matrix: List[List[float]]
    rows_kept: List[int]
    cols_kept: List[int]


class Graphical(BaseModel):
    p: float
    value: float
    mixing_player: str


class MixedStrategyLp(BaseModel):
    value: float
    row_strategy: List[float]
    col_strategy: List[float]


class EscalationGameResponse(BaseModel):
    acts: List[str]
    priorities: List[int]
    matrix: List[List[float]]
    saddle_point: SaddlePoint
    dominance: Dominance
    graphical: Graphical
    mixed_strategy_lp: MixedStrategyLp


class IncidentNode(BaseModel):
    activity: str
    es: float
    ef: float
    ls: float
    lf: float
    slack: float
    critical: bool


class IncidentResponse(BaseModel):
    nodes: List[IncidentNode]
    edges: List[List[str]]
    critical_path: List[str]
    project_duration: float
    probability: float
    z: float
    forces_escalation: bool


class HardwareFactor(BaseModel):
    workstation_id: str
    age_months: float
    type: str
    factor: float


class SensitivityRow(BaseModel):
    alpha: float
    replace_age_months: float
    n_flagged: int


class HardwareResponse(BaseModel):
    factors: List[HardwareFactor]
    to_replace: List[str]
    stable_core: List[str]
    disputed: List[str]
    deteriorating_optimal_year: int
    group_cheaper_policy: str
    sensitivity: List[SensitivityRow]
    source: str


class AgeRequest(BaseModel):
    months: float


class ReplaceRequest(BaseModel):
    workstation_ids: List[str]


class HardwareAgeResponse(BaseModel):
    factors: List[HardwareFactor]
    baseline_cost: float
    aged_cost: float
    delta: float


class HardwareReplaceResponse(BaseModel):
    factors: List[HardwareFactor]
    aged_cost: float
    replaced_cost: float
    delta: float


class ComparisonResponse(BaseModel):
    baseline: Optional[float]
    aged: Optional[float]
    replaced: Optional[float]


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def _build_scenario(n_tickets, n_agents, n_workstations, seed):
    cleaned = _load_cleaned_log()
    derived = derive_all(cleaned)
    data = load_or_synthesize_data(
        seed=seed, n_tickets=n_tickets, n_agents=n_agents,
        n_workstations=n_workstations, cleaned=cleaned,
    )
    workstations = data["workstations"].copy()
    workstations["age_months"] = workstations["age_months"].astype(float)

    return {
        "cleaned": cleaned, "derived": derived,
        "tickets": data["tickets"], "agents": data["agents"], "workstations": workstations,
        "n_tickets": n_tickets, "n_agents": n_agents, "n_workstations": n_workstations, "seed": seed,
        "staffing": None, "funded_agents": None,
        "distribution": None,
        "degradation_factors": None,
        "schedule": None, "assigned_tickets": None,
        "incident": None,
        "baseline_cost": None, "aged_cost": None, "replaced_cost": None,
    }


_state: Dict[str, Any] = _build_scenario(50, 150, 20, 42)


def _invalidate_downstream_of_staffing():
    _state["schedule"] = None
    _state["assigned_tickets"] = None
    _state["degradation_factors"] = None
    _state["baseline_cost"] = None
    _state["aged_cost"] = None
    _state["replaced_cost"] = None


def _ensure_staffing():
    if _state["staffing"] is None:
        result = size_capacity(_state["agents"], _state["derived"]["categories"])
        _state["staffing"] = result
        _state["funded_agents"] = select_funded_agents(
            _state["agents"], result["agents_per_skill"]
        ).reset_index(drop=True)
    return _state["staffing"]


def _ensure_schedule():
    _ensure_staffing()
    if _state["schedule"] is None:
        baseline = assignment_stage(_state["tickets"], _state["funded_agents"], degradation=None)
        assigned_ids = {_state["tickets"].iloc[r]["id"] for r, _c in baseline["pairs"]}
        assigned_tickets = _state["tickets"][_state["tickets"]["id"].isin(assigned_ids)].reset_index(drop=True)
        _state["assigned_tickets"] = assigned_tickets
        triage_share = _triage_share(_state["derived"]["durations"])
        _state["schedule"] = sequence_tickets(assigned_tickets, triage_share)
    return _state["schedule"]


def _ensure_incident():
    if _state["incident"] is None:
        _state["incident"] = plan_major_incident(_state["derived"]["durations"])
    return _state["incident"]


def _hardware_factors():
    return workstation_factors(_state["workstations"], alphas_by_type=ALPHA_BY_TYPE)


def _factor_rows(factors):
    return [
        HardwareFactor(
            workstation_id=str(row.id), age_months=float(row.age_months),
            type=str(row.type), factor=float(factors.get(row.id, 1.0)),
        )
        for row in _state["workstations"].itertuples()
    ]


def _staffing_response(result):
    return StaffingResponse(
        status=result["status"],
        agents_per_skill={k: int(v) for k, v in (result["agents_per_skill"] or {}).items()},
        total_cost=(float(result["total_cost"]) if result["total_cost"] is not None else None),
        demand_by_skill={k: int(v) for k, v in result["demand_by_skill"].items()},
        cost_by_skill={k: float(v) for k, v in result["cost_by_skill"].items()},
        budget=float(result["budget"]),
        min_per_skill={k: int(v) for k, v in result["min_per_skill"].items()},
        source=result["source"],
    )


def _distribution_response(result):
    return DistributionResponse(
        allocation=[[float(v) for v in row] for row in result["allocation"]],
        total_cost=float(result["total_cost"]),
        supply=[float(v) for v in result["supply"]],
        demand=[float(v) for v in result["demand"]],
        cost=[[float(v) for v in row] for row in result["cost"]],
        source=result["source"],
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok")


@app.post("/api/scenario", response_model=ScenarioResponse)
def post_scenario(req: ScenarioRequest):
    global _state
    _state = _build_scenario(req.n_tickets, req.n_agents, req.n_workstations, req.seed)

    cleaned = _state["cleaned"]
    data_source = (
        f"real UCI-498 log, {len(cleaned)} cleaned tickets" if cleaned is not None
        else "no cached UCI-498 log; CONFIG-documented fallback distributions used"
    )
    derived_sources = {name: result["source"] for name, result in _state["derived"].items()}

    return ScenarioResponse(
        n_tickets=req.n_tickets, n_agents=req.n_agents, n_workstations=req.n_workstations,
        seed=req.seed, data_source=data_source, derived_sources=derived_sources,
    )


@app.get("/api/staffing", response_model=StaffingResponse)
def get_staffing():
    return _staffing_response(_ensure_staffing())


@app.post("/api/staffing", response_model=StaffingResponse)
def post_staffing(body: StaffingOverrideRequest):
    result = size_capacity(
        _state["agents"], _state["derived"]["categories"],
        cost_by_skill=body.cost_by_skill, budget=body.budget,
    )
    _state["staffing"] = result
    _state["funded_agents"] = select_funded_agents(
        _state["agents"], result["agents_per_skill"] or {}
    ).reset_index(drop=True)
    _invalidate_downstream_of_staffing()
    return _staffing_response(result)


@app.get("/api/distribution", response_model=DistributionResponse)
def get_distribution():
    if _state["distribution"] is None:
        _state["distribution"] = distribute_regions(_state["derived"]["regions"])
    return _distribution_response(_state["distribution"])


@app.post("/api/distribution", response_model=DistributionResponse)
def post_distribution(body: DistributionOverrideRequest):
    result = distribute_regions(
        _state["derived"]["regions"], capacities=body.capacities, cost=body.cost_matrix,
    )
    _state["distribution"] = result
    return _distribution_response(result)


@app.get("/api/assignment", response_model=AssignmentResponse)
def get_assignment(aged: bool = False):
    _ensure_staffing()
    funded_agents, tickets = _state["funded_agents"], _state["tickets"]
    degradation = _state["degradation_factors"] if aged else None

    result = assignment_stage(tickets, funded_agents, degradation=degradation)
    _assert_no_unfunded_agent(
        result["pairs"], funded_agents, _state["agents"], _state["staffing"]["agents_per_skill"]
    )

    pairs = [
        AssignmentPair(
            ticket_id=str(tickets.iloc[r]["id"]),
            agent_id=str(funded_agents.iloc[c]["id"]),
            cost=float(result["matrix"][r][c]),
        )
        for r, c in result["pairs"]
    ]
    if not aged:
        _state["baseline_cost"] = float(result["total_cost"])

    ticket_ids = [str(v) for v in tickets["id"]]
    agent_ids = [str(v) for v in funded_agents["id"]]
    matrix = [
        [None if v >= INFEASIBLE else float(v) for v in row]
        for row in result["matrix"]
    ]

    return AssignmentResponse(
        aged=aged, ticket_ids=ticket_ids, agent_ids=agent_ids, matrix=matrix,
        pairs=pairs, total_cost=float(result["total_cost"]), n_tickets_served=len(pairs),
    )


@app.get("/api/schedule", response_model=ScheduleResponse)
def get_schedule():
    result = _ensure_schedule()
    entries = [
        ScheduleEntry(
            ticket_id=row["job"],
            triage_start=float(row["m1_start"]), triage_end=float(row["m1_end"]),
            fix_start=float(row["m2_start"]), fix_end=float(row["m2_end"]),
            completion_minutes=float(row["m2_end"]),
        )
        for row in result["schedule"]
    ]
    return ScheduleResponse(sequence=result["sequence"], makespan=float(result["makespan"]), entries=entries)


@app.get("/api/escalations", response_model=EscalationsResponse)
def get_escalations():
    schedule = _ensure_schedule()
    incident = _ensure_incident()
    force = _incident_forces_escalation(
        incident["probability"], CONFIG["major_incident_probability_threshold"]
    )
    rows = route_escalations(
        _state["assigned_tickets"], _state["derived"]["breach"],
        schedule["completion_minutes"], force_priority1=force,
    )
    counts = split_by_escalation(_state["assigned_tickets"], rows)["counts"]
    vendor_cost = counts["escalate-vendor"] * CONFIG["escalation_labour_cost"]["escalate-vendor"]

    return EscalationsResponse(
        rows=[
            EscalationRow(
                ticket_id=r["ticket_id"], priority=int(r["priority"]), act=r["act"],
                time_to_breach_hours=(
                    float(r["time_to_breach_hours"]) if r["time_to_breach_hours"] is not None else None
                ),
                forced_by_incident_risk=bool(r["forced_by_incident_risk"]),
                acts=r["decision"]["acts"],
                payoff=[[float(v) for v in row] for row in r["decision"]["payoff"]],
                p_breach=[float(v) for v in r["decision"]["p_breach"]],
                values=[float(v) for v in r["decision"]["values"]],
            )
            for r in rows
        ],
        counts=counts, vendor_cost=float(vendor_cost),
    )


@app.get("/api/escalations/game", response_model=EscalationGameResponse)
def get_escalations_game():
    """Desk-vs-workload zero-sum game -- see
    api.engine.decision.escalation_game's docstring for how the payoff
    matrix is built from the current scenario's derived breach rates."""
    result = escalation_game(
        _state["derived"]["breach"]["rates"],
        CONFIG["sla_penalty_by_priority"],
        CONFIG["escalation_labour_cost"],
        breach_reduction=CONFIG["escalation_breach_reduction"],
    )
    saddle = result["saddle_point"]
    dominance_result = result["dominance"]
    graphical = result["graphical"]
    mixed = result["mixed_strategy_lp"]

    return EscalationGameResponse(
        acts=result["acts"],
        priorities=[int(p) for p in result["priorities"]],
        matrix=[[float(v) for v in row] for row in result["matrix"]],
        saddle_point=SaddlePoint(
            exists=bool(saddle["exists"]),
            value=(float(saddle["value"]) if saddle["value"] is not None else None),
            position=(list(saddle["position"]) if saddle["position"] is not None else None),
        ),
        dominance=Dominance(
            matrix=[[float(v) for v in row] for row in dominance_result["matrix"]],
            rows_kept=[int(r) for r in dominance_result["rows_kept"]],
            cols_kept=[int(c) for c in dominance_result["cols_kept"]],
        ),
        graphical=Graphical(
            p=float(graphical["p"]), value=float(graphical["value"]),
            mixing_player=graphical["mixing_player"],
        ),
        mixed_strategy_lp=MixedStrategyLp(
            value=float(mixed["value"]),
            row_strategy=[float(v) for v in mixed["row_strategy"]],
            col_strategy=[float(v) for v in mixed["col_strategy"]],
        ),
    )


@app.get("/api/incident", response_model=IncidentResponse)
def get_incident(deadline_hours: Optional[float] = None):
    # a caller-supplied deadline recomputes fresh and is never cached --
    # the M6->M5 gate (see /api/escalations) must keep using the CONFIG
    # default, not whatever the UI's deadline input is currently set to.
    result = (
        plan_major_incident(_state["derived"]["durations"], deadline_hours=deadline_hours)
        if deadline_hours is not None
        else _ensure_incident()
    )
    schedule = result["schedule"]
    critical = set(schedule["critical_path"])

    nodes = [
        IncidentNode(
            activity=act, es=float(schedule["ES"][act]), ef=float(schedule["EF"][act]),
            ls=float(schedule["LS"][act]), lf=float(schedule["LF"][act]),
            slack=float(schedule["slack"][act]), critical=act in critical,
        )
        for act in schedule["ES"]
    ]
    return IncidentResponse(
        nodes=nodes,
        edges=[list(e) for e in result["edges"]],
        critical_path=schedule["critical_path"],
        project_duration=float(schedule["project_duration"]),
        probability=float(result["probability"]["probability"]),
        z=float(result["probability"]["z"]),
        forces_escalation=_incident_forces_escalation(
            result["probability"], CONFIG["major_incident_probability_threshold"]
        ),
    )


@app.get("/api/hardware", response_model=HardwareResponse)
def get_hardware():
    factors = _hardware_factors()
    _state["degradation_factors"] = factors
    replacement = choose_replacements(_state["workstations"])

    return HardwareResponse(
        factors=_factor_rows(factors),
        to_replace=replacement["to_replace"],
        stable_core=replacement["sensitivity"]["stable_core"],
        disputed=replacement["sensitivity"]["disputed"],
        deteriorating_optimal_year=int(replacement["deteriorating"]["optimal_year"]),
        group_cheaper_policy=replacement["group"]["cheaper_policy"],
        sensitivity=[
            SensitivityRow(
                alpha=float(row["alpha"]), replace_age_months=float(row["replace_age_months"]),
                n_flagged=int(row["n_flagged"]),
            )
            for row in replacement["sensitivity"]["results"]
        ],
        source=replacement["source"],
    )


@app.post("/api/hardware/age", response_model=HardwareAgeResponse)
def post_hardware_age(body: AgeRequest):
    _ensure_staffing()
    baseline_cost = float(
        assignment_stage(_state["tickets"], _state["funded_agents"], degradation=None)["total_cost"]
    )

    _state["workstations"]["age_months"] = _state["workstations"]["age_months"] + body.months
    factors = _hardware_factors()
    _state["degradation_factors"] = factors

    aged_cost = float(
        assignment_stage(_state["tickets"], _state["funded_agents"], degradation=factors)["total_cost"]
    )
    _state["baseline_cost"] = baseline_cost
    _state["aged_cost"] = aged_cost

    return HardwareAgeResponse(
        factors=_factor_rows(factors), baseline_cost=baseline_cost, aged_cost=aged_cost,
        delta=aged_cost - baseline_cost,
    )


@app.post("/api/hardware/replace", response_model=HardwareReplaceResponse)
def post_hardware_replace(body: ReplaceRequest):
    _ensure_staffing()
    # order matters: read the CURRENT (pre-reset) factors/cost before
    # mutating anything, else "aged" and "replaced" collapse to the same
    # number and the improvement this endpoint reports is fabricated.
    pre_factors = _state["degradation_factors"] or _hardware_factors()
    aged_cost = float(
        assignment_stage(_state["tickets"], _state["funded_agents"], degradation=pre_factors)["total_cost"]
    )

    mask = _state["workstations"]["id"].isin(body.workstation_ids)
    _state["workstations"].loc[mask, "age_months"] = 0.0
    factors = _hardware_factors()
    _state["degradation_factors"] = factors

    replaced_cost = float(
        assignment_stage(_state["tickets"], _state["funded_agents"], degradation=factors)["total_cost"]
    )
    _state["aged_cost"] = aged_cost
    _state["replaced_cost"] = replaced_cost

    return HardwareReplaceResponse(
        factors=_factor_rows(factors), aged_cost=aged_cost, replaced_cost=replaced_cost,
        delta=replaced_cost - aged_cost,
    )


@app.get("/api/comparison", response_model=ComparisonResponse)
def get_comparison():
    return ComparisonResponse(
        baseline=_state["baseline_cost"], aged=_state["aged_cost"], replaced=_state["replaced_cost"],
    )
