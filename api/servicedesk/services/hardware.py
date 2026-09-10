"""Replacement advice for the machines an operator registered.

**Where the numbers come from, because that is the whole question.** Nothing in
this module is predicted, mined or inferred. The incident log this project
models has no hardware telemetry and no ticket-to-asset key, so a machine's age,
purchase cost, resale value and yearly running cost are typed in by a manager
from their own records, and every response repeats that. What the module adds is
the arithmetic: the textbook deteriorating-item average-cost method and the
group-versus-individual comparison, applied to those figures.

The arithmetic itself is not reimplemented here. It lives in
``api/engine/replacement.py``, is covered by tests that check it against worked
examples, and is the same code the oral examination is prepared against. This
module reads a row, hands plain numbers to those functions, and turns what comes
back into a decision a dispatcher can read.

**What this does not do.** It does not change any recommendation, any deadline,
any assignment or any risk score. A machine flagged for replacement changes what
a manager is told; it changes nothing the dispatch policy computes. The earlier
build multiplied a whole cost-matrix row by an ageing factor, which cannot alter
which resolver is chosen - only the total. That loop is not wired into this
application, and the report says so plainly rather than implying a feedback
effect the data cannot support.
"""
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from api.servicedesk.db import models
from api.servicedesk.db.types import utcnow
from api.servicedesk.errors import ApiError

# The one import of the Operations Research engine. It is a pure-arithmetic
# module - no database, no ORM, no model artifact - and reimplementing the
# average-cost method here would create a second definition of the number the
# viva checks by hand. The engine stays free of this application's dependencies;
# the dependency runs one way only.
from api.engine import replacement as or_replacement

#: Average days per month, used only to age a recorded figure forward. A month
#: is not a fixed unit and this is stated rather than hidden in a constant name.
DAYS_PER_MONTH = 30.4375


@dataclass(frozen=True)
class MachineEvidence:
    """What the ticket history says about a machine, counted, never inferred.

    Every ticket counted here was linked to this machine by a person. The link
    is an operator's statement; no column in the source data could have produced
    it, and nothing in this project guesses it.
    """

    linked_tickets: int
    open_linked_tickets: int
    mean_risk_probability: Optional[float]


def current_age_months(machine: models.Machine, as_of=None) -> float:
    """The recorded age, carried forward to today.

    A manager types an age once. Reading that number months later as if it were
    current would quietly understate every machine in the register, so the row
    also stores when it was recorded and the age is aged forward from there.
    """
    as_of = as_of or utcnow()
    elapsed_days = max(0.0, (as_of - machine.age_recorded_at).total_seconds() / 86400.0)
    return machine.age_months + elapsed_days / DAYS_PER_MONTH


def _cost_series(machine: models.Machine):
    """The two operator-supplied series, validated together.

    They must align: year *n* of running cost is the same year as year *n* of
    resale value. A single resale figure is accepted and read as constant, which
    is the textbook's own simplification.
    """
    running = list(machine.running_cost_by_year_json or [])
    scrap = machine.scrap_value_by_year_json
    if not running:
        raise ApiError(
            "MACHINE_COSTS_MISSING",
            "Machine %s has no yearly running-cost figures, so no replacement "
            "age can be computed for it." % machine.asset_tag,
            status_code=422,
            details={"asset_tag": machine.asset_tag},
        )
    if isinstance(scrap, (int, float)):
        scrap_series = float(scrap)
    else:
        scrap = list(scrap or [])
        if len(scrap) == 1:
            scrap_series = float(scrap[0])
        elif len(scrap) != len(running):
            raise ApiError(
                "MACHINE_COSTS_MISALIGNED",
                "Machine %s lists %d running-cost years and %d resale years; "
                "they must describe the same years."
                % (machine.asset_tag, len(running), len(scrap)),
                status_code=422,
                details={"running_years": len(running), "scrap_years": len(scrap)},
            )
        else:
            scrap_series = [float(value) for value in scrap]
    return [float(value) for value in running], scrap_series


def replacement_advice(machine: models.Machine, as_of=None) -> dict:
    """When this machine should be replaced, and whether that moment has passed.

    The method is the syllabus one: for replacement at the end of year *n*,

        total(n)   = purchase - resale(n) + running cost accumulated to n
        average(n) = total(n) / n

    and the optimal year is the one minimising ``average(n)``. The year-by-year
    table is returned in full, because a number a professor cannot recompute on
    paper is not an answer.
    """
    running, scrap = _cost_series(machine)
    analysis = or_replacement.deteriorating_replacement(
        purchase=float(machine.purchase_cost),
        scrap=scrap,
        running_cost_by_year=running,
    )
    age_months = current_age_months(machine, as_of)
    age_years = age_months / 12.0
    optimal_year = analysis["optimal_year"]
    months_until_due = optimal_year * 12.0 - age_months

    if age_years >= optimal_year:
        verdict = "replace_now"
    elif months_until_due <= 6.0:
        verdict = "replace_soon"
    else:
        verdict = "keep"

    return {
        "asset_tag": machine.asset_tag,
        "machine_id": machine.id,
        "age_months": round(age_months, 1),
        "optimal_replacement_year": optimal_year,
        "optimal_average_cost": round(analysis["optimal_average_cost"], 2),
        "months_until_due": round(months_until_due, 1),
        "verdict": verdict,
        "table": [
            {
                "year": row["year"],
                "cumulative_running_cost": round(row["cumulative_running_cost"], 2),
                "total_cost": round(row["total_cost"], 2),
                "average_cost": round(row["average_cost"], 2),
            }
            for row in analysis["table"]
        ],
        "source_note": machine.source_note,
    }


def explain(advice: dict, evidence: MachineEvidence) -> str:
    """One sentence a manager reads, built only from the numbers beside it.

    Same rule as a dispatch recommendation's reason: the text is generated from
    the computed figures and cannot describe a calculation that did not happen.
    """
    verdicts = {
        "replace_now": (
            "Replace now: %s is %.0f months old and its average annual cost is "
            "lowest at year %d, which passed %.0f months ago."
        ),
        "replace_soon": (
            "Replace soon: %s is %.0f months old and reaches its lowest average "
            "annual cost at year %d, in %.0f months."
        ),
        "keep": (
            "Keep: %s is %.0f months old and its average annual cost is lowest "
            "at year %d, still %.0f months away."
        ),
    }
    template = verdicts[advice["verdict"]]
    sentence = template % (
        advice["asset_tag"],
        advice["age_months"],
        advice["optimal_replacement_year"],
        abs(advice["months_until_due"]),
    )
    sentence += _degradation_clause(advice["table"])
    if evidence.linked_tickets:
        sentence += (
            " %d ticket(s) have been linked to it by hand, %d still open."
            % (evidence.linked_tickets, evidence.open_linked_tickets)
        )
    else:
        sentence += " No ticket has been linked to it, so the register figures stand alone."
    return sentence + " Figures supplied by the operator: %s." % advice["source_note"]


def _degradation_clause(table: list) -> str:
    """Name what a rising running cost means, in the operator's own figures.

    A machine that costs more to keep running each year is a machine getting
    worse - slower, more often broken, more hands on it. That is the whole
    premise of the deteriorating-item method, and it is the only degradation
    signal this project has, because no dataset available to it carries hardware
    telemetry. So it is stated from the entered series rather than inferred from
    anything: first year against last, and nothing at all when the series is
    flat or falling.
    """
    per_year = []
    previous = 0.0
    for year in table:
        per_year.append(year["cumulative_running_cost"] - previous)
        previous = year["cumulative_running_cost"]
    if len(per_year) < 2 or per_year[-1] <= per_year[0]:
        return ""
    return (
        " Its recorded running cost rises from %.0f in year 1 to %.0f in year %d,"
        " which is the operator's own measure of the machine degrading."
        % (per_year[0], per_year[-1], table[-1]["year"])
    )


def evidence_for(db: DbSession, machine: models.Machine) -> MachineEvidence:
    """Count the tickets a human attached to this machine. Counting only."""
    rows = db.scalars(
        select(models.Ticket).where(models.Ticket.machine_id == machine.id)
    ).all()
    open_rows = [
        row for row in rows if row.status not in models.TERMINAL_TICKET_STATUSES
    ]
    # There used to be a third count here: how many of the linked tickets were
    # filed under a hardware category. It matched the literal string "hardware",
    # which worked only while the categories were invented. UCI-498 anonymises
    # them - "Category 42", not "Network" - so no category in real data means
    # hardware, and the count could only ever read zero. A figure that is always
    # zero by construction is worse than no figure, so it was removed rather
    # than left on screen looking like evidence of absence.
    scored = [row.risk_probability for row in rows if row.risk_probability is not None]
    return MachineEvidence(
        linked_tickets=len(rows),
        open_linked_tickets=len(open_rows),
        mean_risk_probability=(sum(scored) / len(scored)) if scored else None,
    )


def fleet_group_advice(n_items: int, failure_prob_by_period, unit_replace_cost,
                       group_replace_cost) -> dict:
    """Group replacement against replace-on-failure, for a fleet of like items.

    The second syllabus method, and the one that answers "should we swap the
    whole batch on a schedule instead of one at a time". The failure
    probabilities are an operator input like everything else here: they describe
    the organisation's own fleet, and the response says so.
    """
    if n_items < 1:
        raise ApiError(
            "FLEET_EMPTY",
            "Group replacement needs at least one machine in the fleet.",
            status_code=422,
        )
    probabilities = [float(value) for value in failure_prob_by_period]
    total = sum(probabilities)
    if not probabilities or abs(total - 1.0) > 0.01:
        raise ApiError(
            "FAILURE_PROBABILITIES_INVALID",
            "The per-period failure probabilities must cover the whole life of "
            "an item and sum to 1.0; these sum to %.3f." % total,
            status_code=422,
            details={"sum": round(total, 4)},
        )
    analysis = or_replacement.group_vs_individual(
        failure_prob_by_period=probabilities,
        unit_replace_cost=float(unit_replace_cost),
        group_replace_cost=float(group_replace_cost),
        n_items=int(n_items),
    )
    return {
        "n_items": int(n_items),
        "individual_average_cost": round(analysis["individual_average_cost"], 2),
        "optimal_group_interval": analysis["optimal_group_interval"],
        "optimal_group_average_cost": round(analysis["optimal_group_average_cost"], 2),
        "cheaper_policy": analysis["cheaper_policy"],
        "group_table": [
            {"interval": row["interval"], "average_cost": round(row["average_cost"], 2)}
            for row in analysis["group_table"]
        ],
    }


def list_machines(db: DbSession, active_only: bool = False) -> List[models.Machine]:
    query = select(models.Machine)
    if active_only:
        query = query.where(models.Machine.is_active.is_(True))
    return list(db.scalars(query.order_by(models.Machine.asset_tag.asc())).all())


def get_machine(db: DbSession, machine_id: str) -> models.Machine:
    machine = db.get(models.Machine, machine_id)
    if machine is None:
        raise ApiError(
            "MACHINE_NOT_FOUND",
            "No machine exists with that id.",
            status_code=404,
            details={"machine_id": machine_id},
        )
    return machine


def linked_ticket_counts(db: DbSession) -> dict:
    """Linked-ticket totals for the whole register, in one query."""
    rows = db.execute(
        select(models.Ticket.machine_id, func.count())
        .where(models.Ticket.machine_id.is_not(None))
        .group_by(models.Ticket.machine_id)
    ).all()
    return {machine_id: count for machine_id, count in rows}
