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
    """Expected Monetary Value: for each act, sum_j probs[j] * payoff[act][j].

    Hand method: multiply each act's row by the state-probability row,
    sum across states, pick the act with the largest total.

    Data source: caller-supplied; syllabus demonstration, exercised in
    tests only (tests/test_m5.py) -- the product's own EMV-shaped
    computation is escalation_decision, which needs a per-act probability
    rather than a single shared state distribution, so it computes its
    values directly instead of calling this function.
    """
    payoff = _as_matrix(payoff)
    probs = np.array(probs, dtype=float)
    values = (payoff * probs).sum(axis=1)
    best = int(np.argmax(values))
    return {"values": values.tolist(), "best_index": best, "best_value": float(values[best])}


def maximax(payoff):
    """Optimist's rule: best of each act's best-case payoff.

    Hand method: take each row's max, then pick the largest of those.

    Data source: caller-supplied; syllabus demonstration, exercised in
    tests only (tests/test_m5.py).
    """
    payoff = _as_matrix(payoff)
    values = payoff.max(axis=1)
    best = int(np.argmax(values))
    return {"values": values.tolist(), "best_index": best, "best_value": float(values[best])}


def maximin(payoff):
    """Pessimist's rule: best of each act's worst-case payoff.

    Hand method: take each row's min, then pick the largest of those.

    Data source: caller-supplied; syllabus demonstration, exercised in
    tests only (tests/test_m5.py).
    """
    payoff = _as_matrix(payoff)
    values = payoff.min(axis=1)
    best = int(np.argmax(values))
    return {"values": values.tolist(), "best_index": best, "best_value": float(values[best])}


def laplace(payoff):
    """Equal-likelihood rule: average payoff per act (states equiprobable).

    Hand method: average each row, pick the act with the largest average.

    Data source: caller-supplied; syllabus demonstration, exercised in
    tests only (tests/test_m5.py).
    """
    payoff = _as_matrix(payoff)
    values = payoff.mean(axis=1)
    best = int(np.argmax(values))
    return {"values": values.tolist(), "best_index": best, "best_value": float(values[best])}


def hurwicz(payoff, alpha):
    """Hurwicz criterion: alpha * best-case + (1-alpha) * worst-case per act.

    Hand method: for each row, take alpha*max + (1-alpha)*min, pick the
    largest result.

    Data source: caller-supplied; syllabus demonstration, exercised in
    tests only (tests/test_m5.py).
    """
    payoff = _as_matrix(payoff)
    values = alpha * payoff.max(axis=1) + (1 - alpha) * payoff.min(axis=1)
    best = int(np.argmax(values))
    return {"values": values.tolist(), "best_index": best, "best_value": float(values[best])}


def minimax_regret(payoff):
    """Savage regret: regret[i][j] = (best payoff in state j) - payoff[i][j];
    pick the act minimising its worst-case (max) regret.

    Hand method: for each state (column), find the best payoff and
    subtract every entry in that column from it to get the regret table;
    take each row's max regret, pick the act with the smallest.

    Data source: caller-supplied; syllabus demonstration, exercised in
    tests only (tests/test_m5.py).
    """
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


def escalation_decision(ticket_row, breach_rates, sla_penalties, labour_cost,
                         breach_reduction=None, reassignment_bump=0.15,
                         time_to_breach_hours=None):
    """Build one ticket's escalation expected-cost table from real data.

    Base P(breach) comes from `breach_rates` (derive_breach_rates'
    empirical P(made_sla==False)) for this ticket's priority, bumped up
    by `reassignment_bump` per reassignment already on the ticket
    (documented heuristic: a ticket that's already been reassigned is
    judged more likely to breach). If `time_to_breach_hours` is given and
    <= 0, the SCHEDULE (M4's Johnson-rule completion time vs the ticket's
    SLA deadline) already shows this ticket missing its deadline -- that
    scheduled fact overrides the statistical prior, forcing P(breach)=1.0
    before anything else is applied.

    Acts = {resolve-in-place, escalate-L2, escalate-vendor}. Each act's
    OWN breach probability is base P(breach) * breach_reduction[act]
    (default 1.0, i.e. no effect, if `breach_reduction` is omitted):
    escalation is modelled as buying specialist attention that lowers the
    chance of actually breaching, not just adding labour cost -- without
    this, escalating only ever costs more in this model and would never
    be the EMV-optimal act. This is a documented policy assumption (no
    UCI-498 equivalent -- the dataset records the historical outcome, not
    what escalating would have changed).

    Expected cost per act = p_breach(act)*(penalty+labour) +
    (1-p_breach(act))*labour, penalty = sla_penalties[priority] (SLA
    penalty, since UCI-498 carries no monetary breach cost). Payoff is
    -(expected cost); the recommended act maximises payoff (standard EMV
    rule), computed directly rather than via emv() because here each act
    carries its own probability, not a single shared state distribution.

    Hand method: for each of the three acts, compute its own p_breach
    (base rate times that act's breach_reduction), then
    p*(penalty+labour) + (1-p)*labour; negate for payoff; pick the act
    with the largest payoff -- the same table a grader would fill in by
    hand per ticket.

    Data source: `breach_rates` is derived["breach"]["rates"]
    (derive_breach_rates, empirical or CONFIG fallback); `sla_penalties`,
    `labour_cost`, `breach_reduction`, `reassignment_bump` are
    CONFIG["sla_penalty_by_priority"], CONFIG["escalation_labour_cost"],
    CONFIG["escalation_breach_reduction"], CONFIG["reassignment_breach_bump"];
    `ticket_row` and `time_to_breach_hours` come from the current
    scenario's assigned tickets and M4 schedule (route_escalations).
    """
    priority = int(ticket_row["priority"])
    p_breach = breach_rates[priority]
    reassignments = int(ticket_row.get("reassignment_count", 0))
    if reassignments > 0:
        p_breach = min(1.0, p_breach * (1.0 + reassignment_bump * reassignments))
    if time_to_breach_hours is not None and time_to_breach_hours <= 0:
        p_breach = 1.0

    acts = ["resolve-in-place", "escalate-L2", "escalate-vendor"]
    reduction = breach_reduction or {}
    penalty = sla_penalties[priority]

    payoff, act_p_breach, values = [], [], []
    for act in acts:
        p = min(1.0, p_breach * reduction.get(act, 1.0))
        breach_cost = penalty + labour_cost[act]
        no_breach_cost = labour_cost[act]
        payoff.append([-breach_cost, -no_breach_cost])  # cols: breach, no-breach
        act_p_breach.append(p)
        values.append(-(p * breach_cost + (1.0 - p) * no_breach_cost))

    best = int(np.argmax(values))
    return {
        "acts": acts, "payoff": payoff, "p_breach": act_p_breach,
        "values": values, "best_index": best, "best_value": values[best],
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

    Hand method: draw the tree, fold from the leaves inward -- a chance
    node's value is its branches' probability-weighted average, a
    decision node's value is its best child's value -- until one value
    remains at the root.

    Data source: caller-supplied; syllabus demonstration, exercised in
    tests only (tests/test_m5.py).
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
    minimax (best worst-case column); that common value is the game value.

    Hand method: write each row's minimum and each column's maximum
    alongside the matrix, take the largest row-minimum (maximin) and the
    smallest column-maximum (minimax); if they're equal, that cell is a
    saddle point and the game's value.

    Data source: `matrix` is caller-supplied -- escalation_game builds
    one from derived["breach"]["rates"] for /api/escalations/game;
    otherwise caller-supplied directly (tests/test_m5.py).
    """
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
    prefers it) and dominated columns (symmetric, minimizer prefers smaller).

    Hand method: scan rows pairwise for one that's never better than
    another in any column, cross it out; scan columns pairwise for one
    that's never better (smaller) than another in any row, cross it out;
    repeat on the shrinking matrix until no more crossings apply.

    Data source: `matrix` is caller-supplied -- escalation_game builds
    one from derived["breach"]["rates"] for /api/escalations/game;
    otherwise caller-supplied directly (tests/test_m5.py).
    """
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

    Hand method: draw one line per column j on axes p (row 0's mixing
    probability, x-axis) vs expected payoff (y-axis), from
    payoff[0][j] at p=1 to payoff[1][j] at p=0; the row player's
    guaranteed value at any p is the LOWEST line there (the column player
    picks it); the best p is where that lower envelope peaks -- always at
    an intersection of two lines (or at p=0 or p=1), which is exactly
    what the intersection-candidate scan below computes instead of
    reading it off a hand-drawn graph.

    Data source: `matrix` is caller-supplied -- escalation_game builds
    one from derived["breach"]["rates"] for /api/escalations/game;
    otherwise caller-supplied directly (tests/test_m5.py).
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
    minimax theorem guarantees v == w at the optimum.

    Hand method: set up the row player's LP exactly as described (maximize
    v subject to each column's expected payoff >= v, probabilities summing
    to 1) and solve by simplex -- the same LP a grader would write out by
    hand from the payoff table, here solved by PuLP's bundled CBC instead
    of hand simplex.

    Data source: `matrix` is caller-supplied -- escalation_game builds
    one from derived["breach"]["rates"] for /api/escalations/game;
    otherwise caller-supplied directly (tests/test_m5.py).
    """
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


def escalation_game(breach_rates, sla_penalties, labour_cost, breach_reduction=None):
    """Model desk-vs-workload as a zero-sum game (the /api/escalations/game
    endpoint's backing computation).

    Construction: rows are the desk's two pure dispatch strategies,
    "resolve-in-place" and "escalate-L2" (vendor escalation is left out so
    the matrix is 2xN and the graphical method applies honestly, not
    forced onto a 3xN table it wasn't built for). Columns are the
    priority classes present in `breach_rates`. Cell (act, priority) is
    the SAME expected-cost formula escalation_decision uses per ticket --
    p = min(1, breach_rates[priority] * breach_reduction.get(act, 1.0));
    cost = p*(sla_penalties[priority] + labour_cost[act])
           + (1-p)*labour_cost[act]
    -- negated into a payoff (higher is better, this module's sign
    convention).

    Reading "workload" as a column player choosing which priority class
    dominates the desk's incoming stream is the standard decision-theory-
    as-a-game device for a distribution-free worst-case guarantee (nature
    modelled as an adversary; not a claim that ticket volume literally
    strategizes against the desk). It complements, rather than replaces,
    the EMV-based per-ticket recommendation escalation_decision already
    gives -- EMV needs a probability over priorities, this needs none.

    Runs all four game-theory techniques on the one matrix: saddle_point
    first (a pure-strategy equilibrium, if one exists, is the simplest
    honest answer), dominance (any act or priority class that's never the
    right call regardless of the other player), graphical_2xn for the
    mixed-strategy value, and mixed_strategy_lp as an independent LP
    cross-check of that same value (the minimax theorem guarantees they
    agree).

    Hand method: build the 2xN payoff table by hand from the formula
    above; check maximin row / minimax column for a saddle point; if
    none, plot each column j's line p*payoff[0][j] + (1-p)*payoff[1][j]
    against p in [0,1], and read the game value off the highest point of
    the lower envelope of those lines.

    Data source: `breach_rates` is derived["breach"]["rates"] (empirical
    UCI-498 P(breach) per priority, or the CONFIG fallback -- see
    derive_breach_rates); `sla_penalties`, `labour_cost`, and
    `breach_reduction` are CONFIG["sla_penalty_by_priority"],
    CONFIG["escalation_labour_cost"], CONFIG["escalation_breach_reduction"]
    -- the same runtime inputs route_escalations already feeds to
    escalation_decision, just aggregated across priorities instead of
    applied per ticket.
    """
    acts = ["resolve-in-place", "escalate-L2"]
    priorities = sorted(breach_rates.keys())
    reduction = breach_reduction or {}

    matrix = []
    for act in acts:
        row = []
        for priority in priorities:
            p = min(1.0, breach_rates[priority] * reduction.get(act, 1.0))
            breach_cost = sla_penalties[priority] + labour_cost[act]
            no_breach_cost = labour_cost[act]
            row.append(-(p * breach_cost + (1.0 - p) * no_breach_cost))
        matrix.append(row)

    return {
        "acts": acts,
        "priorities": priorities,
        "matrix": matrix,
        "saddle_point": saddle_point(matrix),
        "dominance": dominance(matrix),
        "graphical": graphical_2xn(matrix),
        "mixed_strategy_lp": mixed_strategy_lp(matrix),
    }
