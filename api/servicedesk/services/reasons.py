"""The sentence a dispatcher reads, generated from the decision's own payload.

Two rules govern this module and both exist to stop the same failure. First, the
text is built from the stored candidate payload and from nothing else, so it can
never describe a calculation the decision did not record. Second, the client
displays it verbatim and never recomputes it, so what a dispatcher read in the
demo is what the audit trail holds a year later.

The vocabulary follows spec B.3. The model produces a "calibrated SLA-risk
estimate" and a "predicted completion estimate"; the output is a
"recommendation". Nothing here says the system chose the best employee, and
nothing claims an outcome.
"""
from typing import Optional

#: How a recommendation names its own arithmetic. Kept as one template so the
#: wording cannot drift between the reason and the payload it cites.
RECOMMENDED_TEMPLATE = (
    "Recommendation: {agent}. Calibrated SLA-risk estimate {risk}, predicted "
    "completion estimate {duration} minutes at this resolver's {multiplier} "
    "speed factor. Projected start in {wait} minutes, finishing {finish}. "
    "Candidate cost {cost} against {alternatives} other eligible {slot_word}."
)


def _minutes(value: float) -> str:
    return "%.0f" % round(float(value))


def _probability(value: Optional[float]) -> str:
    if value is None:
        return "unavailable"
    return "%.2f" % float(value)


def _finish_phrase(candidate: dict, due_in_minutes: float) -> str:
    """Says whether the projection lands inside the deadline, in plain minutes."""
    lateness = float(candidate.get("projected_lateness_minutes", 0.0))
    if lateness > 0:
        return "%s minutes past the SLA deadline" % _minutes(lateness)
    finish = float(candidate.get("projected_finish_in_minutes", 0.0))
    return "%s minutes inside the deadline" % _minutes(due_in_minutes - finish)


def recommended_reason(candidate: dict, risk_probability, due_in_minutes: float,
                       eligible_count: int) -> str:
    """One recommendation, described using only the numbers stored with it."""
    alternatives = max(0, eligible_count - 1)
    return RECOMMENDED_TEMPLATE.format(
        agent=candidate.get("display_name", "the recommended resolver"),
        risk=_probability(risk_probability),
        duration=_minutes(candidate.get("projected_service_minutes", 0.0)),
        multiplier="%.2f" % float(candidate.get("speed_multiplier", 1.0)),
        wait=_minutes(candidate.get("projected_wait_minutes", 0.0)),
        finish=_finish_phrase(candidate, due_in_minutes),
        cost="%.2f" % float(candidate.get("total_cost", 0.0)),
        alternatives=alternatives,
        slot_word="slot" if alternatives == 1 else "slots",
    )


def queued_reason(required_skill, eligible_count: int, free_slots: int) -> str:
    """No free slot right now, so the ticket is visibly parked, not dropped."""
    return (
        "Queued for capacity: %d resolver(s) hold the required %s skill and %d "
        "of their slots are free at this moment. No assignment was made; the "
        "ticket stays in the queue until capacity frees or a dispatcher "
        "overrides." % (eligible_count, required_skill or "general", free_slots)
    )


def no_eligible_agent_reason(required_skill) -> str:
    """No active agent holds the skill at all. This is a triage prompt."""
    return (
        "No eligible resolver: no active agent holds the required %s skill, so "
        "no recommendation can be made. Route this ticket for triage or add the "
        "skill to a resolver." % (required_skill or "general")
    )


def override_reason(recommended_name: Optional[str], chosen_name: str,
                    typed_reason: str) -> str:
    """What the history records when a human disagrees with the recommendation."""
    recommended = recommended_name or "no resolver (the recommendation was not an assignment)"
    return (
        "Human override: recommendation was %s, dispatcher chose %s. Stated "
        "reason: %s" % (recommended, chosen_name, typed_reason.strip())
    )
