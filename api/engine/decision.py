"""M5 — decision theory + theory of games (Unit II).

Sign convention: every payoff table here holds PAYOFFS (higher is better
for the row/decision-maker). To use a cost table instead, negate it
before calling any of these functions (max-of-costs becomes min-of-costs
automatically once negated).
"""
import numpy as np
import pulp

# ---------------------------------------------------------------------------
# Decision theory
# ---------------------------------------------------------------------------


def _as_matrix(payoff):
    return np.array(payoff, dtype=float)


def emv(payoff, probs):
    """Expected Monetary Value: for each act, sum_j probs[j] * payoff[act][j]."""
    payoff = _as_matrix(payoff)
    probs = np.array(probs, dtype=float)
    values = (payoff * probs).sum(axis=1)
    best = int(np.argmax(values))
    return {"values": values.tolist(), "best_index": best, "best_value": float(values[best])}


def maximax(payoff):
    """Optimist's rule: best of each act's best-case payoff."""
    payoff = _as_matrix(payoff)
    values = payoff.max(axis=1)
    best = int(np.argmax(values))
    return {"values": values.tolist(), "best_index": best, "best_value": float(values[best])}


def maximin(payoff):
    """Pessimist's rule: best of each act's worst-case payoff."""
    payoff = _as_matrix(payoff)
    values = payoff.min(axis=1)
    best = int(np.argmax(values))
    return {"values": values.tolist(), "best_index": best, "best_value": float(values[best])}


def laplace(payoff):
    """Equal-likelihood rule: average payoff per act (states equiprobable)."""
    payoff = _as_matrix(payoff)
    values = payoff.mean(axis=1)
    best = int(np.argmax(values))
    return {"values": values.tolist(), "best_index": best, "best_value": float(values[best])}


def hurwicz(payoff, alpha):
    """Hurwicz criterion: alpha * best-case + (1-alpha) * worst-case per act."""
    payoff = _as_matrix(payoff)
    values = alpha * payoff.max(axis=1) + (1 - alpha) * payoff.min(axis=1)
    best = int(np.argmax(values))
    return {"values": values.tolist(), "best_index": best, "best_value": float(values[best])}


def minimax_regret(payoff):
    """Savage regret: regret[i][j] = (best payoff in state j) - payoff[i][j];
    pick the act minimising its worst-case (max) regret."""
    payoff = _as_matrix(payoff)
    best_per_state = payoff.max(axis=0)
    regret = best_per_state - payoff
    worst_regret = regret.max(axis=1)
    best = int(np.argmin(worst_regret))
    return {
        "regret_matrix": regret.tolist(),
        "values": worst_regret.tolist(),
        "best_index": best,
        "best_value": float(worst_regret[best]),
    }


def decision_tree(root):
    """Fold expected values back through a decision tree.

    A node is one of:
      - a plain number (a leaf payoff),
      - {"type": "chance", "branches": [(prob, subnode), ...]},
      - {"type": "decision", "children": {action_name: subnode, ...}}.
    Chance nodes fold to their probability-weighted average; decision
    nodes fold to the best child's value (max, matching the payoff sign
    convention above).
    """

    def rollback(node):
        if isinstance(node, (int, float)):
            return float(node)
        if node["type"] == "chance":
            return sum(p * rollback(sub) for p, sub in node["branches"])
        if node["type"] == "decision":
            return max(rollback(sub) for sub in node["children"].values())
        raise ValueError(f"unknown node type: {node.get('type')}")

    if isinstance(root, dict) and root.get("type") == "decision":
        action_values = {action: rollback(sub) for action, sub in root["children"].items()}
        best_action = max(action_values, key=action_values.get)
        return {
            "expected_value": action_values[best_action],
            "best_action": best_action,
            "action_values": action_values,
        }
    return {"expected_value": rollback(root)}


# ---------------------------------------------------------------------------
# Theory of games (zero-sum, row player maximizes, column player minimizes)
# ---------------------------------------------------------------------------


def saddle_point(matrix):
    """Pure-strategy solution: exists iff maximin (best worst-case row) equals
    minimax (best worst-case column); that common value is the game value."""
    matrix = _as_matrix(matrix)
    row_mins = matrix.min(axis=1)
    col_maxs = matrix.max(axis=0)
    maximin_value = row_mins.max()
    minimax_value = col_maxs.min()

    if maximin_value != minimax_value:
        return {"exists": False, "value": None, "position": None}

    row = int(np.argmax(row_mins))
    col = int(np.argmin(col_maxs))
    return {"exists": True, "value": float(maximin_value), "position": (row, col)}


def dominance(matrix):
    """Iteratively drop dominated rows (a row is dominated if some other row
    is >= it in every column, > in at least one -- the row player never
    prefers it) and dominated columns (symmetric, minimizer prefers smaller)."""
    matrix = _as_matrix(matrix)
    rows = list(range(matrix.shape[0]))
    cols = list(range(matrix.shape[1]))

    changed = True
    while changed:
        changed = False
        for i in list(rows):
            if any(
                k != i
                and all(matrix[k, j] >= matrix[i, j] for j in cols)
                and any(matrix[k, j] > matrix[i, j] for j in cols)
                for k in rows
            ):
                rows.remove(i)
                changed = True
        for j in list(cols):
            if any(
                l != j
                and all(matrix[i, l] <= matrix[i, j] for i in rows)
                and any(matrix[i, l] < matrix[i, j] for i in rows)
                for l in cols
            ):
                cols.remove(j)
                changed = True

    reduced = matrix[np.ix_(rows, cols)]
    return {"matrix": reduced.tolist(), "rows_kept": rows, "cols_kept": cols}


def graphical_2xn(matrix):
    """Graphical method for a 2xN or Nx2 game with no saddle point.

    For 2xN: plot, for each of the N pure column strategies, the row
    player's expected payoff as a line in p (prob. of row 0). The row
    player's best guaranteed value is the highest point of the LOWER
    envelope of those lines (column player always picks the worst line
    for whatever p the row player chose). For Nx2 the roles mirror: solve
    the transposed, negated matrix as the 2xN case (column player becomes
    the maximizer of the negated game), then flip the sign back.
    """
    matrix = _as_matrix(matrix)
    m, n = matrix.shape

    if m == 2:
        lines = [(matrix[0, j], matrix[1, j]) for j in range(n)]
        sign = 1.0
        mixing_player = "row"
    elif n == 2:
        t = -matrix.T
        lines = [(t[0, i], t[1, i]) for i in range(t.shape[1])]
        sign = -1.0
        mixing_player = "col"
    else:
        raise ValueError("graphical_2xn requires a 2xN or Nx2 matrix")

    def line_value(coef, p):
        top, bottom = coef
        return p * top + (1 - p) * bottom

    candidates = {0.0, 1.0}
    for a in range(len(lines)):
        for b in range(a + 1, len(lines)):
            top_a, bot_a = lines[a]
            top_b, bot_b = lines[b]
            denom = (top_a - bot_a) - (top_b - bot_b)
            if abs(denom) > 1e-12:
                p = (bot_b - bot_a) / denom
                if 0.0 <= p <= 1.0:
                    candidates.add(p)

    best_p, best_val = None, -float("inf")
    for p in candidates:
        val = min(line_value(c, p) for c in lines)
        if val > best_val:
            best_val = val
            best_p = p

    return {"p": best_p, "value": sign * best_val, "mixing_player": mixing_player}


def mixed_strategy_lp(matrix):
    """Solve the zero-sum game's mixed-strategy value with two PuLP LPs:
    the row player maximizes the guaranteed value v subject to every
    column's expected payoff being >= v; the column player symmetrically
    minimizes w subject to every row's expected payoff being <= w. The
    minimax theorem guarantees v == w at the optimum."""
    matrix = _as_matrix(matrix)
    m, n = matrix.shape

    row_prob = pulp.LpProblem("row_player", pulp.LpMaximize)
    p = [pulp.LpVariable(f"p_{i}", lowBound=0) for i in range(m)]
    v = pulp.LpVariable("v")
    row_prob += v
    for j in range(n):
        row_prob += pulp.lpSum(p[i] * matrix[i, j] for i in range(m)) >= v
    row_prob += pulp.lpSum(p) == 1
    row_prob.solve()

    col_prob = pulp.LpProblem("col_player", pulp.LpMinimize)
    q = [pulp.LpVariable(f"q_{j}", lowBound=0) for j in range(n)]
    w = pulp.LpVariable("w")
    col_prob += w
    for i in range(m):
        col_prob += pulp.lpSum(q[j] * matrix[i, j] for j in range(n)) <= w
    col_prob += pulp.lpSum(q) == 1
    col_prob.solve()

    return {
        "value": v.value(),
        "row_strategy": [pi.value() for pi in p],
        "col_strategy": [qj.value() for qj in q],
    }
