"""M3 — agent-to-ticket assignment (Unit III: Hungarian method).

build_cost_matrix is the hook M7 uses to close the feedback loop: a
workstation's degradation factor multiplies every cost-matrix entry for
tickets running on it, so ageing hardware makes the Hungarian optimum
route work elsewhere.

Reading chosen where the brief was silent: resolution time depends on the
ticket (its base_resolution_minutes) whenever the agent's skill matches,
not on which specific agent of that skill handles it. M0's agent table
does carry a `capacity` field (this project's per-agent speed proxy,
used by M1's throughput and by pipeline.py's funded-agent ranking and
"senior" flag) -- it is deliberately not folded into this cost formula,
since the tested Hungarian instances (test_m3.py) are pinned to the
skill-match-only cost; which agent handles a matched ticket is decided
upstream, by which agents pipeline.py hands this function in the first
place, not by a per-agent cost term here.
"""
import numpy as np
from scipy.optimize import linear_sum_assignment

INFEASIBLE = 1e6


def build_cost_matrix(tickets, agents, degradation=None):
    """Rows = tickets, columns = agents. Entry = expected resolution
    minutes if agent.skill == ticket.skill, else INFEASIBLE. When given,
    `degradation` maps workstation_id -> factor (>=1.0) and multiplies
    every entry for tickets running on that workstation.

    Hand method: build the same matrix on paper by listing tickets as rows,
    agents as columns, writing each ticket's base_resolution_minutes into
    every cell whose column agent shares its skill (INFEASIBLE elsewhere),
    then scaling each row by its ticket's workstation degradation factor
    (1.0 if the workstation isn't in the `degradation` table).

    Data source: `tickets` and `agents` are whatever DataFrames the caller
    (pipeline.py's assignment_stage, or api/main.py's /api/assignment) has
    already derived; `degradation` is M7's per-workstation factor table
    when hardware ageing is being modelled, else None.
    """
    skill_match = tickets["skill"].to_numpy()[:, None] == agents["skill"].to_numpy()[None, :]
    base = tickets["base_resolution_minutes"].to_numpy(dtype=float)[:, None]

    factor = np.ones(len(tickets))
    if degradation is not None:
        factor = tickets["workstation_id"].map(degradation).fillna(1.0).to_numpy(dtype=float)

    return np.where(skill_match, base * factor[:, None], INFEASIBLE)


def pad_to_square(matrix, fill=INFEASIBLE):
    """Pad a rectangular cost matrix to square with `fill`, so the
    assignment can be taught/verified by hand as a classic square
    Hungarian tableau (scipy itself does not require this).

    Hand method: add dummy rows or columns of `fill` cost until the
    tableau is square, exactly as the textbook Hungarian method requires
    before row/column reduction.

    Data source: `matrix` is whatever cost matrix the caller already has
    (typically build_cost_matrix's output); this function has no data
    dependency of its own.
    """
    matrix = np.asarray(matrix, dtype=float)
    m, n = matrix.shape
    size = max(m, n)
    padded = np.full((size, size), fill)
    padded[:m, :n] = matrix
    return padded


def assign(cost_matrix):
    """Hungarian assignment via scipy.optimize.linear_sum_assignment
    (handles rectangular matrices directly). Pairs landing on an
    INFEASIBLE (or padded-dummy) cell are dropped from the result.

    Hand method: row-reduce (subtract each row's min), column-reduce
    (subtract each column's min), cover all zeros with the minimum number
    of lines; if that number equals the matrix size, an optimal zero-cost
    assignment exists among the covered zeros -- otherwise adjust
    (subtract the smallest uncovered value from all uncovered cells, add
    it to cells covered twice) and repeat.

    Data source: `cost_matrix` is whatever the caller already built --
    typically build_cost_matrix's output, optionally pad_to_square'd.
    """
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
