"""Build a workforce to replay against, from training-period rows only.

UCI-498 has no agent roster, no skill matrix, no shift calendar and no WIP
limit. §G.2 says what to do about that: derive what the training period can
support, declare the rest, and sweep the quantity that is least knowable
(capacity). Everything this module returns is either counted from training
incidents or listed in the assumption register it carries.

Two things here read fields the risk model may never see — ``resolved_by`` and
``assignment_group``. That is deliberate and bounded: they describe *who was
working and on what*, not what the model predicts, and they are read only from
training rows. :func:`build_training_profile` refuses a frame containing any
non-training row rather than trusting a caller to have filtered it.
"""
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Tuple

import numpy as np
import pandas as pd

#: A resolver needs this many training incidents before it becomes an agent.
#: Below it, a speed multiplier is noise and a skill set is an accident.
MIN_RESOLVER_INCIDENTS = 20
#: A resolver holds a skill if they closed this many training incidents in it.
MIN_SKILL_INCIDENTS = 5
#: A category maps to a skill only with this much training support.
MIN_CATEGORY_SUPPORT = 30
#: Shrinkage constant for the speed multiplier: a resolver with `k` incidents is
#: pulled halfway back to 1.0. Small samples do not get to claim they are fast.
SPEED_SHRINKAGE_K = 20
#: Multipliers are clipped here; a resolver twice or half the pace of the
#: baseline is at the edge of what a residual on this data can support.
SPEED_BOUNDS = (0.5, 2.0)
#: WIP is the p90 of a resolver's concurrently-open training incidents. Named
#: because p50 and p90 give very different systems and the choice must be
#: visible, not implied by a call to `quantile`.
WIP_ESTIMATOR = "p90 concurrently open incidents per resolver, training period"
WIP_QUANTILE = 0.90

#: Declared SLA policy — illustrative, not derived from UCI-498. The log is
#: anonymised and carries no SLA target, so deriving one from the same durations
#: that generate the replay's service demand would compare a number against
#: itself. These are round business numbers a manager could edit, exactly as
#: §C.2 describes, and the simulated breach rate is reported as their
#: consequence whatever it turns out to be.
SLA_POLICY = {
    1: {"target_minutes": 240, "breach_penalty_per_minute": 40.0,
        "late_penalty_per_minute": 40.0, "overdue_recovery_penalty_per_minute": 60.0,
        "holding_cost_per_minute": 1.0, "grace_minutes": 120},
    2: {"target_minutes": 480, "breach_penalty_per_minute": 20.0,
        "late_penalty_per_minute": 20.0, "overdue_recovery_penalty_per_minute": 30.0,
        "holding_cost_per_minute": 0.6, "grace_minutes": 240},
    3: {"target_minutes": 1440, "breach_penalty_per_minute": 5.0,
        "late_penalty_per_minute": 5.0, "overdue_recovery_penalty_per_minute": 7.5,
        "holding_cost_per_minute": 0.2, "grace_minutes": 720},
    4: {"target_minutes": 2880, "breach_penalty_per_minute": 2.0,
        "late_penalty_per_minute": 2.0, "overdue_recovery_penalty_per_minute": 3.0,
        "holding_cost_per_minute": 0.1, "grace_minutes": 1440},
}
SLA_POLICY_SOURCE_NOTE = (
    "illustrative demo policy; replace with organisational SLA policy. Not "
    "derived from UCI-498, which carries no SLA target."
)

#: Predeclared capacity sweep. At 1.0 the emulated workforce holds roughly 2,411
#: concurrent slots against about 258 arrivals a day, so capacity is not binding
#: and every policy starts every job on arrival. The constrained multipliers are
#: where dispatch order can matter at all.
CAPACITY_MULTIPLIERS = (0.10, 0.25, 0.50, 1.00)


class NotTrainingData(ValueError):
    """A frame handed to the profile builder contained non-training rows."""


@dataclass(frozen=True)
class Agent:
    agent_id: str
    skills: FrozenSet[str]
    wip_limit: int
    speed_multiplier: float
    training_incidents: int

    def scaled(self, multiplier: float) -> "Agent":
        """Capacity sweep: only the WIP limit moves, never skills or speed."""
        return Agent(
            agent_id=self.agent_id,
            skills=self.skills,
            wip_limit=max(1, int(round(self.wip_limit * multiplier))),
            speed_multiplier=self.speed_multiplier,
            training_incidents=self.training_incidents,
        )


@dataclass(frozen=True)
class TrainingProfile:
    agents: Tuple[Agent, ...]
    skill_map: Dict[str, str]
    fallback_skill: str
    assumptions: Dict = field(default_factory=dict)

    def required_skill(self, category) -> str:
        """Test jobs get their skill from this map, built on training rows."""
        return self.skill_map.get(str(category), self.fallback_skill)

    def with_capacity(self, multiplier: float) -> Tuple[Agent, ...]:
        return tuple(agent.scaled(multiplier) for agent in self.agents)


def _guard_training_only(frame):
    if "split" not in frame.columns:
        raise NotTrainingData("frame carries no split column; refusing to guess")
    other = sorted(set(frame["split"]) - {"train"})
    if other:
        raise NotTrainingData(
            "profile may only be built from training rows; frame also holds "
            + ", ".join(other)
        )


def build_skill_map(train, min_support=MIN_CATEGORY_SUPPORT):
    """Category to the group that handled it most often in training.

    Purity is poor on this log (median about 0.5), which is a real property of
    an anonymised dataset where one category spreads across several groups. It
    is measured and recorded rather than smoothed over.
    """
    mapping, purity = {}, {}
    for category, part in train.groupby("category"):
        groups = part["assignment_group"].dropna()
        if len(groups) < min_support:
            continue
        counts = groups.value_counts()
        mapping[str(category)] = str(counts.index[0])
        purity[str(category)] = float(counts.iloc[0] / len(groups))
    fallback = str(train["assignment_group"].dropna().value_counts().index[0])
    return mapping, purity, fallback


def _speed_multipliers(train):
    """Resolver pace, from training residuals against a priority×category median.

    Resolver identity never enters the duration model. This is the separate,
    training-period residual the plan allows: predict a base duration from
    ticket attributes, take each resolver's log-ratio against it, and shrink
    small samples toward 1.0.
    """
    base = train.groupby(["priority", "category"])["duration_minutes"].transform("median")
    ratio = np.log(train["duration_minutes"] / base.replace(0, np.nan))
    frame = pd.DataFrame({"resolver": train["resolved_by"], "log_ratio": ratio}).dropna()
    out = {}
    for resolver, part in frame.groupby("resolver"):
        n = len(part)
        shrunk = (n / (n + SPEED_SHRINKAGE_K)) * float(part["log_ratio"].mean())
        out[str(resolver)] = float(np.clip(np.exp(shrunk), *SPEED_BOUNDS))
    return out


def _wip_limits(train, quantile=WIP_QUANTILE):
    """p90 of concurrently open incidents, per resolver, over the training period."""
    limits = {}
    for resolver, part in train.dropna(subset=["resolved_at"]).groupby("resolved_by"):
        starts = part["opened_at"].to_numpy()
        ends = part["resolved_at"].to_numpy()
        events = np.concatenate([starts, ends])
        deltas = np.concatenate([np.ones(len(part)), -np.ones(len(part))])
        order = np.argsort(events, kind="mergesort")
        concurrent = np.cumsum(deltas[order])
        limits[str(resolver)] = max(1, int(np.quantile(concurrent, quantile)))
    return limits


def build_training_profile(train, min_incidents=MIN_RESOLVER_INCIDENTS):
    """The workforce, its skills, its pace and its capacity — training only."""
    _guard_training_only(train)
    skill_map, purity, fallback = build_skill_map(train)
    speeds = _speed_multipliers(train)
    wip = _wip_limits(train)

    counts = train["resolved_by"].value_counts()
    agents = []
    for resolver, total in counts.items():
        if total < min_incidents:
            continue
        handled = train[train["resolved_by"] == resolver]["assignment_group"].dropna()
        skills = frozenset(
            str(group) for group, n in handled.value_counts().items()
            if n >= MIN_SKILL_INCIDENTS
        )
        if not skills:
            continue
        agents.append(Agent(
            agent_id=str(resolver),
            skills=skills,
            wip_limit=wip.get(str(resolver), 1),
            speed_multiplier=speeds.get(str(resolver), 1.0),
            training_incidents=int(total),
        ))
    agents.sort(key=lambda a: a.agent_id)

    assumptions = {
        "source": "training-period incidents only",
        "training_incidents": int(len(train)),
        "agents": len(agents),
        "resolvers_seen": int(counts.size),
        "min_resolver_incidents": min_incidents,
        "min_skill_incidents": MIN_SKILL_INCIDENTS,
        "min_category_support": MIN_CATEGORY_SUPPORT,
        "skill_source": "assignment_group, training rows only (never a model feature)",
        "skill_map_categories": len(skill_map),
        "skill_map_purity_median": float(np.median(list(purity.values()))) if purity else None,
        "skill_map_purity_p25": float(np.quantile(list(purity.values()), 0.25)) if purity else None,
        "fallback_skill": fallback,
        "wip_estimator": WIP_ESTIMATOR,
        "wip_total_slots": int(sum(a.wip_limit for a in agents)),
        "speed_shrinkage_k": SPEED_SHRINKAGE_K,
        "speed_bounds": list(SPEED_BOUNDS),
        "speed_multiplier_median": float(np.median([a.speed_multiplier for a in agents])) if agents else None,
        "sla_policy": {str(k): v for k, v in SLA_POLICY.items()},
        "sla_policy_source_note": SLA_POLICY_SOURCE_NOTE,
        "unavailable_and_assumed": [
            "shift coverage: agents are available for the whole simulated period",
            "initial queue state: the system starts empty",
            "preemption: none; a started job runs to completion",
            "WIP definition: concurrently open incidents, not concurrent effort",
            "handling-time proxy: logged elapsed time, which contains waiting",
            "SLA policy: declared, not derived from the log",
        ],
    }
    return TrainingProfile(tuple(agents), skill_map, fallback, assumptions)


def load_emulation_records(prepared, raw_path=None, split="train"):
    """Join the workforce columns back onto prepared incidents, for one split.

    ``resolved_by``, ``assignment_group`` and ``resolved_at`` are not in the
    prepared parquet — `FeatureSpec` forbids them, and that ban is what keeps
    them out of the model. The replay needs them to emulate a workforce, so they
    are read here from the raw log under the same ordering rule, and the frame is
    filtered to one split before it leaves this function.
    """
    from api.servicedesk.ingest.uci498 import RAW_PATH, load_raw
    from api.servicedesk.ml.feature_spec import ORDER_RULE

    raw = load_raw(raw_path or RAW_PATH)
    ordered = raw.sort_values(list(ORDER_RULE), kind="mergesort")
    grouped = ordered.groupby("number", sort=False)
    first = grouped.head(1).set_index("number")
    final = grouped.tail(1).set_index("number")

    wanted = prepared[prepared["split"] == split].copy()
    index = wanted["incident_id"]
    wanted["assignment_group"] = first["assignment_group"].reindex(index).to_numpy()
    wanted["resolved_by"] = final["resolved_by"].reindex(index).to_numpy()
    wanted["resolved_at"] = final["resolved_at"].reindex(index).to_numpy()
    return wanted
