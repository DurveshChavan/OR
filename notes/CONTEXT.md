# Project: SLA-Driven Ticket Allocation, Escalation and Hardware Replacement in IT Service Desks
Course: MDM40233 Multidisciplinary Minor-V (Operations Research), 2 credits. Final-year B.Tech IT.
Goal: A Python decision-support pipeline that demonstrates OR techniques on real IT service-desk data,
with one original contribution: hardware ageing changes ticket assignment through a closed feedback loop.

## What this is
A command-line + Streamlit decision-support tool. NOT machine learning. NOT a web service. NOT a database app.
Every module maps to one OR syllabus unit and must be independently runnable and testable.

## Modules
- M0 Data layer: load UCI dataset 498; fit a synthetic generator to it; emit tidy tables.
- M1 Capacity allocation: LPP via Simplex (PuLP + CBC). Decide agents/shift per skill group under budget.
- M2 Regional distribution: transportation problem (PuLP) + hand methods NWCR, Least Cost, VAM, MODI.
- M3 Agent-to-ticket assignment: Hungarian method (scipy linear_sum_assignment). Cost=1e6 for infeasible pairs; pad-to-square helper.
- M4 Sequencing: Johnson's rule (2 machines) + two-jobs-m-machines graphical method.
- M5 Escalation decision: decision theory (EMV, maximax, maximin, Laplace, Hurwicz, minimax regret, decision tree) + game theory (saddle point, dominance, 2xn graphical, mixed-strategy LP).
- M6 Major-incident planner: CPM/PERT (networkx DiGraph, hand-coded forward/backward pass, te=(a+4m+b)/6, Z-score probability of finishing by deadline).
- M7 Hardware replacement: deteriorating-item average-cost minimisation; group vs individual replacement for sudden failure.

## The novelty spine (must work end to end)
M7 emits a per-workstation degradation factor d_w >= 1.0. This factor MULTIPLIES the resolution-time
cost entries in M3's cost matrix for tickets handled on that workstation. Older hardware => higher cost =>
Hungarian assignment shifts work away from it. When M7 recommends replacing a workstation, d_w resets to 1.0
and M3 is re-run. The pipeline must show a before/after comparison: total resolution cost and assignment
changes when workstations age, and again after replacement.

## Stack (fixed — do not add anything)
Python 3.11+, pandas, numpy, scipy, PuLP (>=3.0,<4.0), networkx, matplotlib, streamlit, pytest, ucimlrepo.
No ML libraries. No database. No ORM. No async. No web framework beyond streamlit.

## Deliverables
- src/ package with modules m0..m7 and a pipeline.py that wires the feedback loop.
- tests/ with pytest for each module (must be green).
- app.py Streamlit dashboard with an "age workstation" toggle.
- report.md, viva_bank.md, demo_script.md, papers_notes.md, prior_art_notes.md.
