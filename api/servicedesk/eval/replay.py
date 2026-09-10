"""The replay event loop, and the runner that drives every policy through it.

Discrete-event, non-preemptive, minute-level. A job starts when a policy picks
it and a slot is free; it finishes at
``clock + exogenous_service_minutes × slot.speed_multiplier``. Breach is decided
one way only:

    simulated_finish_minute > configured_sla_due_minute

It is never sampled from the risk model. The model can change which ticket goes
first; it cannot change how long that ticket takes or when its deadline falls.

What this measures is comparative policy behaviour under declared assumptions.
It is not a causal claim about a live service desk, and no number it produces
may be reported as an achieved SLA improvement.
"""
import heapq
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from api.servicedesk.eval.emulation import Agent
from api.servicedesk.eval.jobs import Job
from api.servicedesk.eval.policies import Policy, Slot


@dataclass
class Outcome:
    incident_id: str
    priority: int
    required_skill: str
    arrival_minute: float
    sla_due_minute: float
    start_minute: float
    finish_minute: float
    wait_minutes: float
    service_minutes: float
    slack_minutes: float
    breached: bool
    agent_id: str
    state: str = "completed"


def build_slots(agents: Tuple[Agent, ...]) -> List[Slot]:
    """Expand each agent into its WIP slots, in a stable order."""
    slots = []
    for agent in sorted(agents, key=lambda a: a.agent_id):
        for index in range(agent.wip_limit):
            slots.append(Slot(agent.agent_id, index, agent.speed_multiplier,
                              agent.skills))
    return slots


def _unservable(jobs, slots):
    """Jobs whose required skill no agent holds. Visible, never silently dropped."""
    covered = set()
    for slot in slots:
        covered |= set(slot.skills)
    return {job.incident_id for job in jobs
            if job.view.required_skill not in covered}


def run_policy(jobs: Tuple[Job, ...], agents: Tuple[Agent, ...],
               policy: Policy) -> pd.DataFrame:
    """Run one policy over one exogenous job list and return per-ticket rows."""
    slots = build_slots(agents)
    demand: Dict[str, float] = {job.incident_id: job.service_minutes for job in jobs}
    views = {job.incident_id: job.view for job in jobs}
    blocked = _unservable(jobs, slots)

    arrivals = sorted((job.view.arrival_minute, job.incident_id) for job in jobs)
    next_arrival = 0
    waiting: List[str] = []
    free: List[Slot] = list(slots)
    busy: List[Tuple[float, str, int, str]] = []  # finish, agent, slot index, id
    finished: List[Outcome] = []
    by_key = {slot.key: slot for slot in slots}

    clock = arrivals[0][0] if arrivals else 0.0
    while next_arrival < len(arrivals) or waiting or busy:
        while next_arrival < len(arrivals) and arrivals[next_arrival][0] <= clock:
            incident_id = arrivals[next_arrival][1]
            if incident_id not in blocked:
                waiting.append(incident_id)
            next_arrival += 1
        while busy and busy[0][0] <= clock:
            _, agent_id, slot_index, _ = heapq.heappop(busy)
            free.append(by_key[(agent_id, slot_index)])

        dispatched = True
        while dispatched and waiting and free:
            dispatched = False
            choice = policy.choose([views[i] for i in waiting], free, clock)
            if choice is None:
                break
            view, slot = choice
            waiting.remove(view.incident_id)
            free.remove(slot)
            service = demand[view.incident_id] * slot.speed_multiplier
            finish = clock + service
            heapq.heappush(busy, (finish, slot.agent_id, slot.slot_index,
                                  view.incident_id))
            finished.append(Outcome(
                incident_id=view.incident_id,
                priority=view.priority,
                required_skill=view.required_skill,
                arrival_minute=view.arrival_minute,
                sla_due_minute=view.sla_due_minute,
                start_minute=clock,
                finish_minute=finish,
                wait_minutes=clock - view.arrival_minute,
                service_minutes=service,
                slack_minutes=view.sla_due_minute - finish,
                breached=bool(finish > view.sla_due_minute),
                agent_id=slot.agent_id,
            ))
            dispatched = True

        candidates = []
        if next_arrival < len(arrivals):
            candidates.append(arrivals[next_arrival][0])
        if busy:
            candidates.append(busy[0][0])
        if not candidates:
            break
        clock = max(clock, min(candidates))

    for incident_id in sorted(blocked):
        view = views[incident_id]
        finished.append(Outcome(
            incident_id=incident_id, priority=view.priority,
            required_skill=view.required_skill,
            arrival_minute=view.arrival_minute, sla_due_minute=view.sla_due_minute,
            start_minute=float("nan"), finish_minute=float("nan"),
            wait_minutes=float("nan"), service_minutes=demand[incident_id],
            slack_minutes=float("nan"), breached=False, agent_id="",
            state="no_eligible_agent",
        ))
    return pd.DataFrame([outcome.__dict__ for outcome in finished])


def summarise(outcomes: pd.DataFrame, policy_name: str, multiplier: float,
              label="all") -> dict:
    """The reported metrics. "Simulated" is in every name that needs it."""
    served = outcomes[outcomes["state"] == "completed"]
    p1 = served[served["priority"] == 1]
    return {
        "policy": policy_name,
        "capacity_multiplier": multiplier,
        "window": label,
        "tickets": int(len(outcomes)),
        "served": int(len(served)),
        "visible_unassigned": int((outcomes["state"] == "no_eligible_agent").sum()),
        "simulated_breach_rate": float(served["breached"].mean()) if len(served) else float("nan"),
        "p1_simulated_breach_rate": float(p1["breached"].mean()) if len(p1) else float("nan"),
        "p90_wait_minutes": float(np.quantile(served["wait_minutes"], 0.90)) if len(served) else float("nan"),
        "median_wait_minutes": float(np.median(served["wait_minutes"])) if len(served) else float("nan"),
        "mean_slack_minutes": float(served["slack_minutes"].mean()) if len(served) else float("nan"),
        "p10_slack_minutes": float(np.quantile(served["slack_minutes"], 0.10)) if len(served) else float("nan"),
        "makespan_minutes": float(served["finish_minute"].max()) if len(served) else float("nan"),
    }
