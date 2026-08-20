"""M2 — transportation problem (Unit III).

Balances supply/demand with a zero-cost dummy row/column when unequal, then
offers the three hand starting-solution methods (NWCR, Least Cost, VAM), the
MODI optimality test that improves any of them to the optimum, and a PuLP LP
used only as an independent check that MODI actually reached that optimum.
"""
import warnings

import numpy as np
import pulp

MODI_MAX_ITERATIONS = 500


def _balance(supply, demand, cost=None):
    supply = list(supply)
    demand = list(demand)
    total_supply, total_demand = sum(supply), sum(demand)

    if cost is not None:
        cost = [list(row) for row in cost]

    if total_supply == total_demand:
        return supply, demand, cost

    if total_supply < total_demand:
        supply = supply + [total_demand - total_supply]
        if cost is not None:
            cost.append([0] * len(demand))
    else:
        demand = demand + [total_supply - total_demand]
        if cost is not None:
            for row in cost:
                row.append(0)

    return supply, demand, cost


def transport_cost(alloc, cost):
    """Total cost of an allocation: sum(alloc * cost) cell-by-cell.

    Hand method: multiply each cell's allocation by its cost, sum the
    products -- the same total a grader reads off a hand-worked tableau.

    Data source: caller-supplied allocation (nwcr/least_cost/vam/modi's
    output) and the same cost table passed to whichever of those built it.
    """
    alloc = np.array(alloc, dtype=float)
    cost = np.array(cost, dtype=float)
    return float((alloc * cost).sum())


def nwcr(supply, demand):
    """North-West Corner Rule: ignores cost, just satisfies supply/demand
    from the top-left cell outward. Gives a feasible starting solution.

    Hand method: starting at the top-left cell, allocate min(remaining
    supply, remaining demand); cross out whichever row or column is
    exhausted (or both, on the final cell); move right if the column
    exhausted, down if the row exhausted, and repeat.

    Data source: `supply`/`demand` are the caller's region/centre
    capacities, e.g. pipeline.py's distribute_regions.
    """
    supply, demand, _ = _balance(supply, demand)
    m, n = len(supply), len(demand)
    supply, demand = supply[:], demand[:]
    alloc = np.zeros((m, n))

    i = j = 0
    while i < m and j < n:
        qty = min(supply[i], demand[j])
        alloc[i][j] = qty
        supply[i] -= qty
        demand[j] -= qty
        if supply[i] == 0 and demand[j] == 0:
            if i == m - 1:
                j += 1
            else:
                i += 1
        elif supply[i] == 0:
            i += 1
        else:
            j += 1
    return alloc


def least_cost(supply, demand, cost):
    """Least Cost Method: repeatedly fill the cheapest still-active cell.

    Hand method: scan the whole active (uncrossed-out) sub-tableau for its
    single cheapest cell, allocate min(remaining supply, remaining demand)
    there, cross out the exhausted row and/or column, repeat until every
    row and column is exhausted.

    Data source: `supply`/`demand`/`cost` are the caller's capacities and
    routing-cost table, e.g. pipeline.py's distribute_regions.
    """
    supply, demand, cost = _balance(supply, demand, cost)
    m, n = len(supply), len(demand)
    supply, demand = supply[:], demand[:]
    alloc = [[0] * n for _ in range(m)]
    rows_active, cols_active = set(range(m)), set(range(n))

    while rows_active and cols_active:
        i, j = min(
            ((r, c) for r in rows_active for c in cols_active),
            key=lambda rc: (cost[rc[0]][rc[1]], rc[0], rc[1]),
        )
        qty = min(supply[i], demand[j])
        alloc[i][j] = qty
        supply[i] -= qty
        demand[j] -= qty
        if supply[i] == 0:
            rows_active.discard(i)
        if demand[j] == 0:
            cols_active.discard(j)
    return np.array(alloc, dtype=float)


def vam(supply, demand, cost):
    """Vogel's Approximation Method: at each step allocate to the min-cost
    cell of the row/column with the largest penalty (difference between its
    two cheapest active cells). Penalty ties broken by the cheapest cell
    among the tied rows/columns.

    Hand method: for every active row and column compute its penalty
    (difference between its two cheapest active cells; inf if only one
    remains), pick the row/column with the largest penalty, allocate to
    its cheapest active cell, cross out the exhausted row/column, and
    recompute penalties from scratch each round.

    Data source: `supply`/`demand`/`cost` are the caller's capacities and
    routing-cost table, e.g. pipeline.py's distribute_regions.
    """
    supply, demand, cost = _balance(supply, demand, cost)
    m, n = len(supply), len(demand)
    supply, demand = supply[:], demand[:]
    alloc = [[0] * n for _ in range(m)]
    rows_active, cols_active = set(range(m)), set(range(n))

    while rows_active and cols_active:
        row_penalty = {}
        for i in rows_active:
            costs = sorted(cost[i][j] for j in cols_active)
            row_penalty[i] = costs[1] - costs[0] if len(costs) >= 2 else float("inf")
        col_penalty = {}
        for j in cols_active:
            costs = sorted(cost[i][j] for i in rows_active)
            col_penalty[j] = costs[1] - costs[0] if len(costs) >= 2 else float("inf")

        candidates = []
        for i, p in row_penalty.items():
            j = min(cols_active, key=lambda c: (cost[i][c], c))
            candidates.append((p, cost[i][j], i, j))
        for j, p in col_penalty.items():
            i = min(rows_active, key=lambda r: (cost[r][j], r))
            candidates.append((p, cost[i][j], i, j))

        candidates.sort(key=lambda t: (-t[0], t[1], t[2], t[3]))
        _, _, i, j = candidates[0]

        qty = min(supply[i], demand[j])
        alloc[i][j] = qty
        supply[i] -= qty
        demand[j] -= qty
        if supply[i] == 0:
            rows_active.discard(i)
        if demand[j] == 0:
            cols_active.discard(j)
    return np.array(alloc, dtype=float)


def _augment_basics(basics, m, n, needed):
    """Add zero-allocation basic cells (degeneracy fix) until there are
    exactly m+n-1. Rows and columns are nodes of a bipartite graph and each
    basic cell is an edge; a solvable u/v potential system needs those
    edges to form a spanning tree (m+n nodes, m+n-1 edges, no cycles), so
    cells are added via a Kruskal-style union-find rather than a per-cell
    row/column-coverage heuristic, which misses degenerate cases where
    every row and column is already touched but a cycle-free cell is still
    needed to reach m+n-1 edges."""
    parent = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return False
        parent[ra] = rb
        return True

    for i in range(m):
        parent[("r", i)] = ("r", i)
    for j in range(n):
        parent[("c", j)] = ("c", j)

    kept = set()
    for (i, j) in basics:
        if union(("r", i), ("c", j)):
            kept.add((i, j))

    for i in range(m):
        for j in range(n):
            if len(kept) >= needed:
                return kept
            if (i, j) in kept:
                continue
            if union(("r", i), ("c", j)):
                kept.add((i, j))
    return kept


def _find_loop(start, basics):
    basics = set(basics)
    nodes = basics | {start}

    def search(path, visited, horizontal):
        last = path[-1]
        candidates = (
            [c for c in nodes if c[0] == last[0] and c != last]
            if horizontal
            else [c for c in nodes if c[1] == last[1] and c != last]
        )
        for nxt in candidates:
            if nxt == start and len(path) >= 3:
                return path
            if nxt in visited:
                continue
            result = search(path + [nxt], visited | {nxt}, not horizontal)
            if result:
                return result
        return None

    result = search([start], {start}, True)
    if result is None:
        result = search([start], {start}, False)
    if result is None:
        raise ValueError("no closed loop found for MODI step; tableau is not connected")
    return result


def modi(alloc, cost):
    """MODI (u-v) optimality test: improve a starting basic feasible
    solution until every non-basic cell has opportunity cost >= 0.

    The basis (the m+n-1 cells treated as basic) is tracked explicitly and
    updated one cell at a time on each pivot -- recomputing it from
    `alloc > 0` each round would drop degenerate basic cells that pivoted
    to exactly zero, corrupting the u/v potentials on the next pass.

    Hand method: compute row potentials u_i and column potentials v_j from
    cost[i][j] = u_i + v_j on every basic cell (fix u_0 = 0), then the
    opportunity cost of each non-basic cell is cost[i][j] - (u_i + v_j).
    If any is negative, that cell enters the basis; trace its closed
    loop of basic cells, shift theta = min allocation on the loop's minus
    corners, and repeat until every opportunity cost is >= 0.

    Returns a dict: {"allocation", "total_cost", "converged"}.
    `converged` is False only if the pivot loop above ran
    MODI_MAX_ITERATIONS times without reaching a non-negative opportunity
    cost everywhere -- this should not happen on any bounded balanced
    transportation instance, so hitting it signals a degenerate cycling
    case and is surfaced with a warning rather than returned silently.

    Data source: `alloc` is a starting basic feasible solution from nwcr,
    least_cost, or vam (run by the caller); `cost` is the same cost table
    those were given, or the CONFIG/derived per-route cost matrix that
    pipeline.py's distribute_regions builds.
    """
    alloc = np.array(alloc, dtype=float)
    cost = np.array(cost, dtype=float)
    m, n = alloc.shape
    if cost.shape != (m, n):
        # alloc may come from nwcr/least_cost/vam after internal balancing
        # (a zero-cost dummy row/column appended); pad cost to match so the
        # caller can pass either the original or the balanced cost matrix.
        padded = np.zeros((m, n))
        padded[: cost.shape[0], : cost.shape[1]] = cost
        cost = padded
    needed = m + n - 1

    basics = {(i, j) for i in range(m) for j in range(n) if alloc[i][j] > 0}
    if len(basics) < needed:
        basics = _augment_basics(basics, m, n, needed)

    converged = False
    for _ in range(MODI_MAX_ITERATIONS):
        u = [None] * m
        v = [None] * n
        u[0] = 0
        changed = True
        while changed:
            changed = False
            for (i, j) in basics:
                if u[i] is not None and v[j] is None:
                    v[j] = cost[i][j] - u[i]
                    changed = True
                elif v[j] is not None and u[i] is None:
                    u[i] = cost[i][j] - v[j]
                    changed = True

        opp = {}
        for i in range(m):
            for j in range(n):
                if (i, j) in basics or u[i] is None or v[j] is None:
                    continue
                opp[(i, j)] = cost[i][j] - (u[i] + v[j])

        if not opp or min(opp.values()) >= -1e-9:
            converged = True
            break

        entering = min(opp, key=opp.get)
        loop = _find_loop(entering, basics)
        minus_cells = loop[1::2]
        theta = min(alloc[i][j] for (i, j) in minus_cells)
        leaving = min(
            (c for c in minus_cells if abs(alloc[c[0]][c[1]] - theta) < 1e-9),
            key=lambda c: (c[0], c[1]),
        )
        for idx, (i, j) in enumerate(loop):
            alloc[i][j] += theta if idx % 2 == 0 else -theta

        basics.discard(leaving)
        basics.add(entering)

    if not converged:
        warnings.warn(
            f"MODI did not converge within {MODI_MAX_ITERATIONS} iterations; "
            "returned allocation may not be optimal.",
            stacklevel=2,
        )

    total_cost = transport_cost(alloc, cost)
    return {"allocation": alloc, "total_cost": total_cost, "converged": converged}


def solve_transport_pulp(supply, demand, cost):
    """Independent LP formulation of the same balanced problem, used only
    to check MODI's result: minimize sum(cost*x) s.t. row sums = supply,
    column sums = demand, x >= 0.

    Hand method: this is the LP a grader would set up to check a
    hand-worked MODI solution against -- decision variables x_ij >= 0 for
    every cell, row-sum and column-sum equality constraints, objective
    sum(cost_ij * x_ij), solved by simplex (here, PuLP's bundled CBC).

    Data source: same `supply`/`demand`/`cost` as nwcr/least_cost/vam --
    the caller's capacities and routing-cost table.
    """
    supply, demand, cost = _balance(supply, demand, cost)
    m, n = len(supply), len(demand)

    prob = pulp.LpProblem("transport", pulp.LpMinimize)
    x = {
        (i, j): pulp.LpVariable(f"x_{i}_{j}", lowBound=0)
        for i in range(m) for j in range(n)
    }

    prob += pulp.lpSum(cost[i][j] * x[i, j] for i in range(m) for j in range(n))
    for i in range(m):
        prob += pulp.lpSum(x[i, j] for j in range(n)) == supply[i]
    for j in range(n):
        prob += pulp.lpSum(x[i, j] for i in range(m)) == demand[j]

    prob.solve()

    alloc = np.array([[x[i, j].value() for j in range(n)] for i in range(m)])
    return {"allocation": alloc, "total_cost": transport_cost(alloc, cost)}
