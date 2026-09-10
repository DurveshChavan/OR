"""The machine register and its replacement advice.

Route handlers only. Every number returned here is either a figure an operator
typed into the register or a value the Operations Research replacement method
computed from those figures; nothing is recomputed in this module and nothing
is predicted.

Reads are open to any signed-in user, because a dispatcher looking at a ticket
should be able to see whether its machine is overdue for replacement. Writes are
manager-only: the register is business configuration, like the SLA policy rows.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as DbSession

from api.servicedesk import deps
from api.servicedesk.db import models
from api.servicedesk.db.session import get_db
from api.servicedesk.db.types import utcnow
from api.servicedesk.domain import schemas
from api.servicedesk.services import hardware

router = APIRouter(tags=["hardware"])


def _machine_out(machine: models.Machine, linked: int) -> schemas.MachineOut:
    scrap = machine.scrap_value_by_year_json
    if isinstance(scrap, (int, float)):
        scrap = [float(scrap)]
    return schemas.MachineOut(
        id=machine.id,
        asset_tag=machine.asset_tag,
        location=machine.location,
        machine_type=machine.machine_type,
        age_months=machine.age_months,
        age_recorded_at=machine.age_recorded_at,
        current_age_months=round(hardware.current_age_months(machine), 1),
        purchase_cost=machine.purchase_cost,
        scrap_value_by_year=[float(value) for value in scrap],
        running_cost_by_year=[float(v) for v in machine.running_cost_by_year_json],
        is_active=machine.is_active,
        source_note=machine.source_note,
        linked_tickets=linked,
    )


def _advice_out(db: DbSession, machine: models.Machine) -> schemas.ReplacementAdviceOut:
    advice = hardware.replacement_advice(machine)
    evidence = hardware.evidence_for(db, machine)
    return schemas.ReplacementAdviceOut(
        machine_id=machine.id,
        asset_tag=advice["asset_tag"],
        age_months=advice["age_months"],
        optimal_replacement_year=advice["optimal_replacement_year"],
        optimal_average_cost=advice["optimal_average_cost"],
        months_until_due=advice["months_until_due"],
        verdict=advice["verdict"],
        table=[schemas.ReplacementTableRow(**row) for row in advice["table"]],
        evidence=schemas.MachineEvidenceOut(
            linked_tickets=evidence.linked_tickets,
            open_linked_tickets=evidence.open_linked_tickets,
            mean_risk_probability=(
                round(evidence.mean_risk_probability, 4)
                if evidence.mean_risk_probability is not None
                else None
            ),
        ),
        reason=hardware.explain(advice, evidence),
        source_note=advice["source_note"],
    )


@router.get("/machines", response_model=schemas.MachineListResponse)
def list_machines(
    db: DbSession = Depends(get_db),
    actor=Depends(deps.current_user),
    request_id: str = Depends(deps.request_id),
    active_only: bool = Query(default=False),
):
    machines = hardware.list_machines(db, active_only=active_only)
    counts = hardware.linked_ticket_counts(db)
    return schemas.MachineListResponse(
        machines=[_machine_out(m, counts.get(m.id, 0)) for m in machines],
        request_id=request_id,
    )


@router.post("/machines", response_model=schemas.MachineResponse, status_code=201)
def create_machine(
    payload: schemas.MachineCreate,
    db: DbSession = Depends(get_db),
    manager=Depends(deps.current_manager),
    request_id: str = Depends(deps.request_id),
):
    machine = models.Machine(
        asset_tag=payload.asset_tag.strip(),
        location=payload.location,
        machine_type=payload.machine_type,
        age_months=payload.age_months,
        age_recorded_at=utcnow(),
        purchase_cost=payload.purchase_cost,
        scrap_value_by_year_json=list(payload.scrap_value_by_year),
        running_cost_by_year_json=list(payload.running_cost_by_year),
        is_active=payload.is_active,
        source_note=payload.source_note,
    )
    db.add(machine)
    db.commit()
    db.refresh(machine)
    return schemas.MachineResponse(
        machine=_machine_out(machine, 0), request_id=request_id
    )


@router.patch("/machines/{machine_id}", response_model=schemas.MachineResponse)
def patch_machine(
    machine_id: str,
    payload: schemas.MachinePatch,
    db: DbSession = Depends(get_db),
    manager=Depends(deps.current_manager),
    request_id: str = Depends(deps.request_id),
):
    """Edit register figures.

    Re-recording the age also re-stamps ``age_recorded_at``, so the advisor ages
    the new figure forward from today rather than from whenever the row was
    first written.
    """
    machine = hardware.get_machine(db, machine_id)
    data = payload.model_dump(exclude_unset=True)
    if "age_months" in data:
        machine.age_months = data.pop("age_months")
        machine.age_recorded_at = utcnow()
    if "scrap_value_by_year" in data:
        machine.scrap_value_by_year_json = list(data.pop("scrap_value_by_year"))
    if "running_cost_by_year" in data:
        machine.running_cost_by_year_json = list(data.pop("running_cost_by_year"))
    for field, value in data.items():
        setattr(machine, field, value)
    db.commit()
    db.refresh(machine)
    counts = hardware.linked_ticket_counts(db)
    return schemas.MachineResponse(
        machine=_machine_out(machine, counts.get(machine.id, 0)),
        request_id=request_id,
    )


@router.get(
    "/machines/{machine_id}/replacement-advice",
    response_model=schemas.ReplacementAdviceResponse,
)
def machine_advice(
    machine_id: str,
    db: DbSession = Depends(get_db),
    actor=Depends(deps.current_user),
    request_id: str = Depends(deps.request_id),
):
    machine = hardware.get_machine(db, machine_id)
    return schemas.ReplacementAdviceResponse(
        advice=_advice_out(db, machine), request_id=request_id
    )


@router.get("/replacement-advice", response_model=schemas.ReplacementAdviceListResponse)
def fleet_advice(
    db: DbSession = Depends(get_db),
    actor=Depends(deps.current_user),
    request_id: str = Depends(deps.request_id),
    active_only: bool = Query(default=True),
):
    """Advice for the whole register, most overdue first.

    The ordering is by how far past its optimal replacement year a machine is,
    which is a number in the response rather than a judgement made here.
    """
    machines = hardware.list_machines(db, active_only=active_only)
    rows = []
    for machine in machines:
        try:
            rows.append(_advice_out(db, machine))
        except Exception as failure:  # noqa: BLE001 - re-raised below unless skippable
            # A machine with unusable cost figures must not hide the rest of the
            # register; it is skipped here and its own endpoint reports why.
            if getattr(failure, "code", "") in (
                "MACHINE_COSTS_MISSING",
                "MACHINE_COSTS_MISALIGNED",
            ):
                continue
            raise
    rows.sort(key=lambda row: (row.months_until_due, row.asset_tag))
    return schemas.ReplacementAdviceListResponse(
        advice=rows, as_of=utcnow(), request_id=request_id
    )


@router.post("/replacement-advice/group", response_model=schemas.GroupReplacementResponse)
def group_advice(
    payload: schemas.GroupReplacementRequest,
    db: DbSession = Depends(get_db),
    actor=Depends(deps.current_user),
    request_id: str = Depends(deps.request_id),
):
    """Group replacement against replace-on-failure for a fleet of like items."""
    analysis = hardware.fleet_group_advice(
        n_items=payload.n_items,
        failure_prob_by_period=payload.failure_prob_by_period,
        unit_replace_cost=payload.unit_replace_cost,
        group_replace_cost=payload.group_replace_cost,
    )
    return schemas.GroupReplacementResponse(
        n_items=analysis["n_items"],
        individual_average_cost=analysis["individual_average_cost"],
        optimal_group_interval=analysis["optimal_group_interval"],
        optimal_group_average_cost=analysis["optimal_group_average_cost"],
        cheaper_policy=analysis["cheaper_policy"],
        group_table=[schemas.GroupTableRow(**row) for row in analysis["group_table"]],
        request_id=request_id,
    )
