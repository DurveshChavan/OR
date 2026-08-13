"""M3 — agent-to-ticket assignment (Unit III: Hungarian method).

build_cost_matrix is the hook M7 uses to close the feedback loop: a
workstation's degradation factor multiplies every cost-matrix entry for
tickets running on it, so ageing hardware makes the Hungarian optimum
route work elsewhere.

Reading chosen where the brief was silent: resolution time depends on the
ticket (its base_resolution_minutes) whenever the agent's skill matches,
not on which specific agent of that skill handles it -- M0's agent table
carries no per-agent speed field to differentiate on.
"""
import numpy as np
from scipy.optimize import linear_sum_assignment

INFEASIBLE = 1e6


def build_cost_matrix(tickets, agents, degradation=None):
    """Rows = tickets, columns = agents. Entry = expected resolution
    minutes if agent.skill == ticket.skill, else INFEASIBLE. When given,
    `degradation` maps workstation_id -> factor (>=1.0) and multiplies
    every entry for tickets running on that workstation."""
    n_tickets, n_agents = len(tickets), len(agents)
    matrix = np.empty((n_tickets, n_agents))

    for ti, trow in enumerate(tickets.itertuples()):
        factor = 1.0
        if degradation is not None:
            factor = degradation.get(trow.workstation_id, 1.0)
        for ai, arow in enumerate(agents.itertuples()):
            base = trow.base_resolution_minutes if trow.skill == arow.skill else INFEASIBLE
            matrix[ti, ai] = base * factor

    return matrix


def pad_to_square(matrix, fill=INFEASIBLE):
    """Pad a rectangular cost matrix to square with `fill`, so the
    assignment can be taught/verified by hand as a classic square
    Hungarian tableau (scipy itself does not require this)."""
    matrix = np.asarray(matrix, dtype=float)
    m, n = matrix.shape
    size = max(m, n)
    padded = np.full((size, size), fill)
    padded[:m, :n] = matrix
    return padded


def assign(cost_matrix):
    """Hungarian assignment via scipy.optimize.linear_sum_assignment
    (handles rectangular matrices directly). Pairs landing on an
    INFEASIBLE (or padded-dummy) cell are dropped from the result."""
    cost_matrix = np.asarray(cost_matrix, dtype=float)
    row_ind, col_ind = linear_sum_assignment(cost_matrix)

    pairs = []
    total_cost = 0.0
    for r, c in zip(row_ind, col_ind):
        cost = cost_matrix[r, c]
        if cost < INFEASIBLE:
            pairs.append((int(r), int(c)))
            total_cost += float(cost)

    return {"pairs": pairs, "total_cost": total_cost}
