"""Exogenous jobs: built once, before any policy exists, identical for all.

The failure this guards against is a replay that validates itself. If a policy
could influence how long a ticket takes, or could read what actually happened to
it, the comparison would measure the model's opinion rather than the policy's
behaviour. So the service demand and the SLA deadline are fixed here, and a
policy is handed a :class:`JobView` that has no route back to them.

``JobView`` deliberately holds no reference to its :class:`Job`. A view that
kept one would pass an attribute check and still leak the answer through
``view._job``.
"""
from dataclasses import dataclass
from typing import Tuple

import numpy as np
import pandas as pd

from api.servicedesk.eval.emulation import SLA_POLICY, TrainingProfile

#: Columns a policy must never be able to reach, listed so the invariant test
#: can assert against the same names the audit forbade.
HIDDEN_OUTCOME_FIELDS = (
    "made_sla", "label_breach", "resolved_at", "closed_at", "resolved_by",
    "assignment_group", "service_minutes", "duration_minutes",
)


def priority_number(value) -> int:
    """UCI writes "3 - Moderate"; the SLA policy is keyed by the integer."""
    return int(str(value).strip().split(" ")[0])


@dataclass(frozen=True)
class JobView:
    """Everything a policy is allowed to see about a waiting ticket."""

    incident_id: str
    arrival_minute: float
    priority: int
    required_skill: str
    sla_due_minute: float
    predicted_duration_minutes: float
    risk_probability: float


@dataclass(frozen=True)
class Job:
    """A view plus the exogenous truth the simulator alone consumes."""

    view: JobView
    service_minutes: float

    @property
    def incident_id(self):
        return self.view.incident_id

    @property
    def arrival_minute(self):
        return self.view.arrival_minute


def build_exogenous_jobs(test_rows, profile: TrainingProfile, risk, duration,
                         seed: int) -> Tuple[Job, ...]:
    """One job per held-out incident, in arrival order.

    ``risk`` and ``duration`` are arrays already scored by the frozen artifacts.
    They are predictions and policies may use them. ``service_minutes`` is the
    held-out empirical duration and no policy sees it: it is the imperfect
    demand proxy the plan names, imperfect because logged elapsed time contains
    historical waiting.
    """
    ordered = test_rows.sort_values(["opened_at", "incident_id"], kind="mergesort")
    risk = np.asarray(risk, dtype=float)
    duration = np.asarray(duration, dtype=float)
    if len(risk) != len(ordered) or len(duration) != len(ordered):
        raise ValueError("prediction arrays do not line up with the test rows")

    origin = ordered["opened_at"].iloc[0]
    jobs = []
    for position, (_, row) in enumerate(ordered.iterrows()):
        priority = priority_number(row["priority"])
        arrival = float((row["opened_at"] - origin).total_seconds() / 60.0)
        target = SLA_POLICY[priority]["target_minutes"]
        view = JobView(
            incident_id=str(row["incident_id"]),
            arrival_minute=arrival,
            priority=priority,
            required_skill=profile.required_skill(row["category"]),
            sla_due_minute=arrival + target,
            predicted_duration_minutes=float(duration[position]),
            risk_probability=float(risk[position]),
        )
        jobs.append(Job(view=view, service_minutes=float(row["duration_minutes"])))
    # Seed is threaded for the sake of any later stochastic variant; the default
    # demand proxy is empirical and therefore already deterministic.
    _ = np.random.default_rng(seed)
    return tuple(jobs)


def jobs_fingerprint(jobs) -> str:
    """A stable digest of the exogenous inputs, so two runs can be compared.

    The invariant test uses it to prove that every policy in a scenario received
    the same fixtures rather than a re-derived approximation of them.
    """
    import hashlib

    digest = hashlib.sha256()
    for job in jobs:
        view = job.view
        digest.update(
            f"{view.incident_id}|{view.arrival_minute:.4f}|{view.priority}|"
            f"{view.required_skill}|{view.sla_due_minute:.4f}|"
            f"{view.predicted_duration_minutes:.6f}|{view.risk_probability:.6f}|"
            f"{job.service_minutes:.6f}".encode()
        )
    return digest.hexdigest()


def build_test_frame(prepared, split="test"):
    """The held-out rows, in a shape both the scorer and the job builder accept."""
    rows = prepared[prepared["split"] == split].copy()
    return rows.sort_values(["opened_at", "incident_id"], kind="mergesort")


def to_dataframe(jobs) -> pd.DataFrame:
    """Jobs as a frame, for manifests and fixtures. Includes service minutes,
    which is why it is written by the runner and never handed to a policy."""
    return pd.DataFrame([{
        "incident_id": job.view.incident_id,
        "arrival_minute": job.view.arrival_minute,
        "priority": job.view.priority,
        "required_skill": job.view.required_skill,
        "sla_due_minute": job.view.sla_due_minute,
        "predicted_duration_minutes": job.view.predicted_duration_minutes,
        "risk_probability": job.view.risk_probability,
        "service_minutes": job.service_minutes,
    } for job in jobs])
