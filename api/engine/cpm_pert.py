"""M6 — CPM / PERT project network (Unit IV).

Activities are nodes (AON representation); an edge predecessor -> activity
means the activity can't start until the predecessor finishes.
"""
import math

import networkx as nx


def pert_expected(a, m, b):
    """PERT expected time: te = (a + 4m + b) / 6.

    Hand method: the formula itself, applied to the (optimistic,
    most-likely, pessimistic) triple.

    Data source: `a`, `m`, `b` are caller-supplied (build_network unpacks
    them from each activity's estimate).
    """
    return (a + 4 * m + b) / 6.0


def pert_variance(a, m, b):
    """PERT variance: ((b - a) / 6) ** 2.

    Hand method: the formula itself, applied to the (optimistic,
    most-likely, pessimistic) triple.

    Data source: `a`, `m`, `b` are caller-supplied (build_network unpacks
    them from each activity's estimate).
    """
    return ((b - a) / 6.0) ** 2


def build_network(activities):
    """Build the AON DiGraph. `activities` is
    {activity_id: (duration_or_(a,m,b), [predecessor_ids])}.
    A plain number is a deterministic CPM duration (variance 0); a 3-tuple
    is PERT's (optimistic, most likely, pessimistic) estimate, reduced to
    its expected time te and variance up front so forward_backward and
    project_completion_probability don't need to know which flavor an
    activity was given.

    Hand method: draw one node per activity, one arrow per predecessor
    edge, and label each node with te = (a+4m+b)/6 (or the plain duration
    for CPM-only activities) -- this is exactly that network, built
    programmatically instead of on paper.

    Data source: `activities` is caller-assembled (pipeline.py's
    plan_major_incident) -- triage/fix durations are real per-priority-1-
    incident (a,m,b) estimates from derive_incident_durations; every other
    stage's (a,m,b) is CONFIG's cpm_stage_defaults (no UCI-498 timestamp
    exists for those stages).
    """
    G = nx.DiGraph()
    for act_id, (dur, _preds) in activities.items():
        if isinstance(dur, tuple):
            a, m, b = dur
            te, variance = pert_expected(a, m, b), pert_variance(a, m, b)
        else:
            te, variance = float(dur), 0.0
        G.add_node(act_id, te=te, variance=variance)

    for act_id, (_dur, preds) in activities.items():
        for p in preds:
            if p not in G:
                raise ValueError(f"unknown predecessor {p!r} for activity {act_id!r}")
            G.add_edge(p, act_id)

    return G


def forward_backward(G):
    """Hand-coded forward and backward pass over the activity network.

    Forward: ES(node) = max EF over predecessors (0 if none); EF = ES + te.
    Backward: LF(node) = min LS over successors (project duration if none);
    LS = LF - te. slack = LS - ES; activities with (near) zero slack form
    the critical path.

    Hand method: fill a table with one row per activity; do a forward
    pass in topological order computing ES/EF, then a backward pass in
    reverse order computing LS/LF from the project duration found on the
    forward pass; slack = LS-ES per activity, critical path = the
    zero-slack chain.

    Data source: `G` is build_network's output; no independent data of
    its own.
    """
    try:
        order = list(nx.topological_sort(G))
    except nx.NetworkXUnfeasible:
        raise ValueError("activity network contains a cycle")

    ES, EF = {}, {}
    for node in order:
        es = max((EF[p] for p in G.predecessors(node)), default=0.0)
        ES[node] = es
        EF[node] = es + G.nodes[node]["te"]

    project_duration = max(EF.values(), default=0.0)

    LF, LS = {}, {}
    for node in reversed(order):
        lf = min((LS[s] for s in G.successors(node)), default=project_duration)
        LF[node] = lf
        LS[node] = lf - G.nodes[node]["te"]

    slack = {node: LS[node] - ES[node] for node in G.nodes}
    critical_path = [node for node in order if abs(slack[node]) < 1e-9]

    return {
        "ES": ES, "EF": EF, "LS": LS, "LF": LF, "slack": slack,
        "critical_path": critical_path, "project_duration": project_duration,
    }


def project_completion_probability(G, deadline):
    """P(project finishes by `deadline`), assuming the critical path's
    total duration is approximately normal (sum of independent PERT
    activity times): mean = sum(te) and variance = sum(variance) over the
    critical path, Z = (deadline - mean) / sqrt(variance), CDF via
    math.erf (no scipy.stats dependency).

    Hand method: sum te and variance down the critical path found by
    forward_backward, compute Z = (deadline-mean)/std, then look up
    Phi(Z) in a standard normal table -- math.erf reproduces that table
    lookup in closed form.

    Data source: `G` is build_network's output; `deadline` is CONFIG's
    cpm_deadline_hours, or a caller override (api/main.py's GET
    /api/incident?deadline_hours=).
    """
    result = forward_backward(G)
    critical = result["critical_path"]

    mean = sum(G.nodes[n]["te"] for n in critical)
    variance = sum(G.nodes[n]["variance"] for n in critical)
    std = math.sqrt(variance)

    if std == 0:
        probability = 1.0 if deadline >= mean else 0.0
        z = math.inf if deadline > mean else (-math.inf if deadline < mean else 0.0)
    else:
        z = (deadline - mean) / std
        probability = 0.5 * (1 + math.erf(z / math.sqrt(2)))

    return {"z": z, "probability": probability, "mean": mean, "std": std}
