"""The four dispatch policies under comparison.

A policy sees a list of :class:`JobView` and a list of free :class:`Slot`, and
returns one pair or nothing. It has no access to the simulator, to elapsed
outcomes, or to a job's true service demand — that is what makes the comparison
worth running.

Ties are broken by a bounded deterministic epsilon derived from sorted
identifiers, so two runs with the same inputs make the same choices. The epsilon
is many orders of magnitude below the smallest declared cost rate, and a test
holds it there.
"""
import hashlib
from dataclasses import dataclass
from typing import FrozenSet, List, Optional, Tuple

from api.app_v2.eval.emulation import SLA_POLICY
from api.app_v2.eval.jobs import JobView

#: Tie-break scale. The smallest declared cost rate is 0.1 per minute, so an
#: epsilon of 1e-9 can only decide a comparison that is otherwise exactly equal.
TIE_EPSILON = 1e-9


@dataclass(frozen=True)
class Slot:
    """One unit of an agent's WIP limit, free right now."""

    agent_id: str
    slot_index: int
    speed_multiplier: float
    skills: FrozenSet[str]

    def can_take(self, job: JobView) -> bool:
        return job.required_skill in self.skills

    @property
    def key(self):
        return (self.agent_id, self.slot_index)


def eligible_slots(job: JobView, slots: List[Slot]) -> List[Slot]:
    return [slot for slot in sorted(slots, key=lambda s: s.key) if slot.can_take(job)]


def _tie_break(job: JobView, slot: Optional[Slot] = None) -> float:
    """A stable, negligible nudge from identifiers, never from data.

    ``hash()`` on a string is salted per process, so it would make runs
    irreproducible across sessions. A digest keeps the nudge fixed for a given
    pair of identifiers forever.
    """
    text = job.incident_id + ("|" + slot.agent_id + str(slot.slot_index) if slot else "")
    digest = hashlib.sha256(text.encode()).digest()
    return TIE_EPSILON * int.from_bytes(digest[:4], "big") / float(1 << 32)


class Policy:
    """Choose one waiting job and one free slot, or decline to dispatch."""

    name = "policy"

    def choose(self, waiting: List[JobView], slots: List[Slot],
               now: float) -> Optional[Tuple[JobView, Slot]]:
        raise NotImplementedError

    def _first_placeable(self, ordered_jobs, slots):
        """Walk the policy's own ordering and take the first job that fits."""
        for job in ordered_jobs:
            candidates = eligible_slots(job, slots)
            if candidates:
                return job, candidates[0]
        return None


class Fifo(Policy):
    """Earliest arrival first. The minimal operational baseline."""

    name = "fifo"

    def choose(self, waiting, slots, now):
        ordered = sorted(waiting, key=lambda j: (j.arrival_minute, j.incident_id))
        return self._first_placeable(ordered, slots)


class PriorityOnly(Policy):
    """P1 before P4, then arrival. Conventional severity triage."""

    name = "priority_only"

    def choose(self, waiting, slots, now):
        ordered = sorted(
            waiting, key=lambda j: (j.priority, j.arrival_minute, j.incident_id)
        )
        return self._first_placeable(ordered, slots)


class DurationFirst(Policy):
    """Shortest predicted job first — speed and makespan oriented.

    This policy is allowed to read the duration model: it is precisely the
    speed-oriented comparator, and the exogenous demand it actually receives is
    unchanged either way.
    """

    name = "duration_first"

    def choose(self, waiting, slots, now):
        ordered = sorted(waiting, key=lambda j: (
            j.predicted_duration_minutes + _tie_break(j), j.incident_id
        ))
        return self._first_placeable(ordered, slots)


class SlaRiskAware(Policy):
    """Tiered by priority, ranked by money per minute, placed by candidate cost.

    Two costs, never mixed: a ticket still inside its window is ranked by what
    delay is expected to cost given its breach risk; a ticket already past its
    deadline is ranked by a recovery rate that grows with how late it is, so it
    cannot be starved by a stream of fresher work.

    The three switches exist for the ablations the plan requires. Turning one off
    removes exactly one term, so a difference in the results table can be
    attributed to that term and not to a rewritten policy.
    """

    name = "sla_risk_aware"

    def __init__(self, use_risk=True, use_lateness=True, use_agent_choice=True,
                 name=None):
        self.use_risk = use_risk
        self.use_lateness = use_lateness
        self.use_agent_choice = use_agent_choice
        if name:
            self.name = name

    def urgency(self, job: JobView, now: float) -> float:
        policy = SLA_POLICY[job.priority]
        overdue_minutes = now - job.sla_due_minute
        if overdue_minutes >= 0:
            grace = policy["grace_minutes"]
            return policy["overdue_recovery_penalty_per_minute"] * (
                1.0 + overdue_minutes / grace
            )
        remaining = max(1.0, -overdue_minutes)  # never divide by zero
        risk = job.risk_probability if self.use_risk else 1.0
        return policy["breach_penalty_per_minute"] * risk / remaining

    def candidate_cost(self, job: JobView, slot: Slot, now: float) -> float:
        policy = SLA_POLICY[job.priority]
        speed = slot.speed_multiplier if self.use_agent_choice else 1.0
        service = job.predicted_duration_minutes * speed
        projected_finish = now + service
        lateness = max(0.0, projected_finish - job.sla_due_minute)
        waited = max(0.0, now - job.arrival_minute)
        cost = self.urgency(job, now) * waited
        if self.use_lateness:
            cost += policy["late_penalty_per_minute"] * lateness
        cost += policy["holding_cost_per_minute"] * service
        return cost + _tie_break(job, slot)

    def choose(self, waiting, slots, now):
        for tier in (1, 2, 3, 4):
            in_tier = [job for job in waiting if job.priority == tier]
            if not in_tier:
                continue
            ranked = sorted(in_tier, key=lambda j: (
                -(self.urgency(j, now) + _tie_break(j)), j.incident_id
            ))
            for job in ranked:
                candidates = eligible_slots(job, slots)
                if not candidates:
                    continue
                if not self.use_agent_choice:
                    # Ablation: take the first eligible slot, the same rule the
                    # ordering-only baselines use.
                    return job, candidates[0]
                best = min(candidates,
                           key=lambda s: (self.candidate_cost(job, s, now), s.key))
                return job, best
        return None


def all_policies() -> Tuple[Policy, ...]:
    """The four policies under comparison, in the order the plan lists them."""
    return (Fifo(), PriorityOnly(), DurationFirst(), SlaRiskAware())


def ablations() -> Tuple[Policy, ...]:
    """One term removed at a time, so each column of the table means something.

    The baselines pick the first eligible slot by agent id, while the proposed
    policy picks the cheapest candidate. `no_agent_choice` is what separates
    "the ordering helped" from "picking a faster agent helped".
    """
    return (
        SlaRiskAware(use_risk=False, name="ablation_no_risk"),
        SlaRiskAware(use_lateness=False, name="ablation_no_lateness_cost"),
        SlaRiskAware(use_agent_choice=False, name="ablation_no_agent_choice"),
    )
