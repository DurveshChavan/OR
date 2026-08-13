"""M6 — CPM / PERT project network (Unit IV).

Activities are nodes (AON representation); an edge predecessor -> activity
means the activity can't start until the predecessor finishes.
"""
import math

import networkx as nx


def pert_expected(a, m, b):
    """PERT expected time: te = (a + 4m + b) / 6."""
    return (a + 4 * m + b) / 6.0


def pert_variance(a, m, b):
    """PERT variance: ((b - a) / 6) ** 2."""
    return ((b - a) / 6.0) ** 2


def build_network(activities):
    """Build the AON DiGraph. `activities` is
    {activity_id: (duration_or_(a,m,b), [predecessor_ids])}.
    A plain number is a deterministic CPM duration (variance 0); a 3-tuple
    is PERT's (optimistic, most likely, pessimistic) estimate, reduced to
    its expected time te and variance up front so forward_backward and
    project_completion_probability don't need to know which flavor an
    activity was given."""
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
    math.erf (no scipy.stats dependency)."""
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
