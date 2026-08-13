# PLAN.md — SLA-Driven Ticket Allocation, Escalation and Hardware Replacement

Course: MDM40233 Operations Research. 2 credits, final-year B.Tech. Human-gradeable, hand-verifiable OR pipeline. No ML, no DB, no async, no config framework. Stack pinned per CLAUDE.md.

## 1. Repo layout

```
src/
  __init__.py
  m0_data.py
  m1_capacity.py
  m2_transport.py
  m3_assignment.py
  m4_sequencing.py
  m5_decision.py
  m6_cpm_pert.py
  m7_replacement.py
  pipeline.py
tests/
  test_m0_data.py
  test_m1_capacity.py
  test_m2_transport.py
  test_m3_assignment.py
  test_m4_sequencing.py
  test_m5_decision.py
  test_m6_cpm_pert.py
  test_m7_replacement.py
  test_pipeline.py
app.py
report.md
viva_bank.md
demo_script.md
papers_notes.md
prior_art_notes.md
```

## 2. Modules M0–M7

### M0 — `src/m0_data.py` (data layer, no syllabus unit)
- `load_tickets(seed=42) -> dict[str, pd.DataFrame]` — fetches UCI dataset id=498 via `ucimlrepo.fetch_ucirepo`; falls back to a `default_rng(seed)` synthetic generator fitted to its shape if fetch fails/offline. Returns tidy tables: `tickets`, `agents`, `workstations`.
- Tests: returned dict has exactly `{tickets, agents, workstations}` keys; each is a non-empty DataFrame with expected columns; same seed → identical output (determinism); synthetic fallback path runs without network.

### M1 — `src/m1_capacity.py` (LPP/Simplex, Unit I)
- `solve_capacity(skill_groups: pd.DataFrame, budget: float) -> dict` — PuLP LP: decision vars = agents per shift per skill group, maximize tickets covered s.t. budget and headcount constraints; `prob.solve()` with bundled CBC.
- Tests: small 2-skill-group hand-solved instance (known optimum from simplex by hand) matches PuLP result within tolerance; infeasible budget raises/returns explicit infeasible status, not a silent wrong answer.

### M2 — `src/m2_transport.py` (Transportation, Unit III)
- `northwest_corner(supply, demand) -> np.ndarray`
- `least_cost(costs, supply, demand) -> np.ndarray`
- `vogel_approximation(costs, supply, demand) -> np.ndarray`
- `modi_optimize(costs, initial_solution, supply, demand) -> np.ndarray`
- `solve_transport_lp(costs, supply, demand) -> dict` — PuLP reference optimum.
- Tests: one textbook transportation problem (Taha/Hillier-Lieberman, known total cost) run through NWCR→MODI, Least Cost→MODI, VAM→MODI; all three converge to the same optimal cost as the PuLP LP; unbalanced supply/demand handled via dummy row/column.

### M3 — `src/m3_assignment.py` (Hungarian, Unit III)
- `build_cost_matrix(tickets: pd.DataFrame, agents: pd.DataFrame, degradation: dict[str, float] | None = None) -> np.ndarray` — pads to square with cost `1e6` for infeasible pairs; multiplies each entry by `degradation[workstation_id]` when given (default factor 1.0).
- `assign_tickets(cost_matrix: np.ndarray) -> dict` — wraps `scipy.optimize.linear_sum_assignment`; returns assignment pairs + total cost.
- Tests: known 3x3/4x4 textbook Hungarian instance matches hand-solved optimal assignment and cost; non-square matrix pads correctly and never assigns an infeasible (`1e6`) pair when a feasible one exists; passing a `degradation` dict >1.0 strictly increases total cost vs `degradation=None` on the same instance.

### M4 — `src/m4_sequencing.py` (Sequencing, Unit III)
- `johnsons_rule(processing_times: pd.DataFrame) -> dict` — 2-machine job sequencing; returns optimal order, makespan, idle time.
- `two_jobs_m_machines(job1_times, job2_times) -> dict` — graphical method; returns elapsed time per job and total.
- Tests: classic Johnson's-rule textbook instance (known sequence + makespan) matches exactly; two-jobs-m-machines graphical case matches known elapsed time.

### M5 — `src/m5_decision.py` (Decision theory + game theory, Unit II)
- `decision_criteria(payoff: np.ndarray, probs=None, alpha=None) -> dict` — EMV, maximax, maximin, Laplace, Hurwicz, minimax regret; all from one payoff matrix.
- `decision_tree_evaluate(tree: dict) -> dict` — expected value at each node via rollback.
- `game_value(payoff: np.ndarray) -> dict` — saddle point check, dominance reduction, 2×n graphical solution, mixed-strategy LP (PuLP) fallback.
- Tests: textbook payoff matrix with known EMV/maximin/minimax-regret values; a saddle-point game and a no-saddle-point game (dominance/mixed-strategy) each matched against known game value.

### M6 — `src/m6_cpm_pert.py` (CPM/PERT, Unit IV)
- `build_network(activities: pd.DataFrame) -> nx.DiGraph` — nodes/edges from activity list.
- `cpm_forward_backward(graph: nx.DiGraph) -> dict` — hand-coded loops (no `nx.dag_longest_path`) computing ES, EF, LS, LF, slack per activity; critical path.
- `pert_probability(graph, a, m, b, deadline) -> dict` — `te=(a+4m+b)/6`, variance `((b-a)/6)**2`, Z-score, P(finish ≤ deadline).
- Tests: known CPM textbook network (fixed critical path + project duration) matches exactly; PERT Z-score/probability matches hand-calculated value for a known a/m/b/deadline instance.

### M7 — `src/m7_replacement.py` (Replacement analysis, Unit IV)
- `deteriorating_item_cost(purchase_price, maintenance_costs: list, resale_values: list, discount_rate=0.0) -> dict` — average annual cost per replacement age; recommended replacement year = age minimizing average cost.
- `group_replacement_policy(failure_pmf, item_count, individual_cost, group_cost) -> dict` — sudden-failure group vs individual policy comparison.
- `workstation_factors(workstations_df: pd.DataFrame) -> dict[str, float]` — degradation factor per workstation, monotonic non-decreasing in age, `== 1.0` at age zero, `>= 1.0` always; factor resets to `1.0` for any workstation flagged as replaced this period.
- Tests: known deteriorating-item textbook table reproduces same optimal replacement age and minimum average cost; group-replacement instance matches known break-even; `workstation_factors` returns `1.0` for age-0 rows, strictly increasing values for increasing age, and exactly `1.0` after a replacement flag.

### `pipeline.py`
- `run_pipeline(seed=42) -> dict` — calls M0→M7 in order, wires M7→M3 feedback, prints/returns the three-stage table (baseline, aged, post-replacement): total cost + reassigned-ticket count per stage.
- Tests: cost strictly rises baseline→aged and strictly falls aged→post-replacement on the seeded run; this is the test that proves the project's one original contribution and must not be skipped.

## 3. M7 → M3 data contract (the feedback loop)

`m7_replacement.workstation_factors(workstations_df)` returns `{workstation_id: factor}` where every `factor >= 1.0`, equal to exactly `1.0` for a fresh/replaced workstation and rising monotonically with hardware age. `pipeline.py` passes this dict straight into `m3_assignment.build_cost_matrix(tickets, agents, degradation=factors)`, where each cost-matrix entry — the expected resolution time for a ticket on a given agent/workstation pair — is multiplied by the factor of the workstation that ticket would run on (`cost[i][j] *= degradation[workstation_id_of(j)]`), never anywhere else in the pipeline. Because Hungarian assignment (M3) minimizes total cost, inflating one workstation's entries makes assignments route away from it; when M7 flags that workstation for replacement, its factor resets to `1.0`, M3 re-runs on the reset cost matrix, and the pipeline reports the resulting cost drop and any reassignments — this before/aged/after comparison is the project's sole original contribution and is asserted directly by `test_pipeline.py`.

## 4. Dependency pins (confirmed from CLAUDE.md / SKILL.md)

```
python>=3.11
pandas
numpy
scipy
pulp>=3.0,<4.0      # must stay <4.0: 4.x drops bundled CBC, prob.solve() raises PulpError
networkx
matplotlib
streamlit           # st.cache_data only, never st.cache
pytest
ucimlrepo
```
No other dependency added without asking first. No ML library, no database/ORM, no async, no web framework beyond streamlit, no config framework, no logging framework beyond stdlib.

---
Waiting for approval before writing any module code.
