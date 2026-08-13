---
name: or-project
description: Rules for building the SLA-Driven Ticket Allocation, Escalation and Hardware Replacement operations-research project. Load this for ANY work on this repository — writing or editing modules m0 through m7, pipeline.py, app.py, tests, or the report and viva documents. Enforces the fixed tech stack, the hand-verifiable-math requirement, the M7-to-M3 degradation feedback loop, and the ban on machine learning, databases, and speculative abstraction.
---

# OR Project Rules

This is a 2-credit undergraduate Operations Research course project (MDM40233). A human professor will read the code and examine the student orally for 40 marks. Optimise for **explainability by hand**, not for production engineering.

## Hard constraints

Fixed stack. Nothing else may be added without asking first:

```
python>=3.11  pandas  numpy  scipy  "pulp>=3.0,<4.0"  networkx  matplotlib  streamlit  pytest  ucimlrepo
```

Banned outright: any ML library (sklearn, torch, tensorflow, xgboost), any database or ORM, any async, any web framework other than streamlit, any config framework (hydra, pydantic-settings, dynaconf), any logging framework beyond the stdlib.

`pulp` must stay below 4.0. The 4.x line drops the bundled CBC binary and `prob.solve()` then raises `PulpError: No solver available`.

Never call `st.cache`. It has been deprecated since Streamlit 1.18. Use `st.cache_data`.

## Module map

One file per module. One OR technique per module. Do not merge them.

| File | Technique | Syllabus unit |
|---|---|---|
| `src/m0_data.py` | UCI 498 loader + seeded synthetic generator | — |
| `src/m1_capacity.py` | LPP / Simplex (PuLP + CBC) | I |
| `src/m2_transport.py` | Transportation: NWCR, Least Cost, VAM, MODI | III |
| `src/m3_assignment.py` | Hungarian (`scipy.optimize.linear_sum_assignment`) | III |
| `src/m4_sequencing.py` | Johnson's rule, two-jobs-m-machines graphical | III |
| `src/m5_decision.py` | EMV, maximax, maximin, Laplace, Hurwicz, minimax regret, decision tree; saddle point, dominance, 2xn graphical, mixed-strategy LP | II |
| `src/m6_cpm_pert.py` | CPM forward/backward pass, PERT te and variance, Z-score | IV |
| `src/m7_replacement.py` | Deteriorating-item average cost; group vs individual replacement | IV |
| `src/pipeline.py` | Wires M0 to M7 and closes the feedback loop | — |

## The feedback loop (the one original contribution)

M7 exposes `workstation_factors(workstations_df) -> {workstation_id: float}` where each factor is `>= 1.0`, is monotonic in workstation age, and equals exactly `1.0` at age zero.

M3's `build_cost_matrix(tickets, agents, degradation=None)` multiplies each expected-resolution-time entry by the degradation factor of the workstation that ticket runs on. Ageing hardware raises cost, so the Hungarian optimum shifts work away from it. When M7 recommends a replacement, that factor resets to `1.0` and M3 re-runs.

`pipeline.py` must print a three-stage table: baseline, aged, post-replacement, showing total cost and the count of reassigned tickets. Cost must rise at the aged stage and fall at the post-replacement stage. A test asserts this. If that test does not exist, the project has no contribution.

## Math must be hand-checkable

Every OR function needs a docstring stating the formulation it implements: objective, decision variables, constraints, or the numbered steps of the hand method. A grader will compare the code against a textbook.

Every module's tests must include at least one small instance whose answer is known independently — a worked textbook problem, not a snapshot of whatever the code happened to output first. Snapshot tests that merely freeze current behaviour are worthless here and must not be written.

Write the failing test from the known answer first, then implement until it passes. This applies especially to M3, M6 and M7.

Hand methods are not optional decoration. VAM and MODI must actually be implemented and must agree with the PuLP optimum on the test instance, because the oral exam asks the student to run them on paper.

M6's forward and backward pass must be hand-coded loops over the DiGraph. Do not substitute a NetworkX longest-path shortcut; the student has to reproduce ES, EF, LS, LF and slack on a whiteboard.

## Style

Functions under about 40 lines. Descriptive names drawn from the OR vocabulary (`supply`, `demand`, `slack`, `makespan`, `saddle_point`), not generic ones (`data`, `result`, `process`).

Plain functions taking and returning numpy arrays, pandas DataFrames, dicts or dataclasses. No hidden global state. No abstract base classes, no registries, no plugin systems, no dependency injection. If a class has one instance and one method, it should have been a function.

All randomness goes through `numpy.random.default_rng(seed)` with the seed threaded explicitly through the call chain. Tests must be deterministic.

Comments explain the OR reasoning, not the Python. `# dummy column balances supply against demand` is useful; `# loop over rows` is noise.

## Working rhythm

One module per turn. Write the module, write its tests, run `pytest -q`, stop. Do not scaffold the next module in advance and do not create placeholder files for work not yet requested.

When a module is green, say so and stop. Do not volunteer refactors of code that already passes.

If a requirement is ambiguous, implement the simplest textbook reading of it and say which reading was chosen. Do not build for both.

## Writing the report and viva documents

Cite only sources present in `papers_notes.md` and `prior_art_notes.md`. Never invent an author, year, DOI or patent number. If a claim needs a citation that does not exist in those files, drop the claim or flag it.

Describe the novelty as an identified gap in the surveyed prior art. Do not write that the work is patentable, novel in the legal sense, or state-of-the-art.

Report prose should be plain and specific. Give the actual numbers the pipeline produced. Avoid the register of a press release: no "leverages", "robust framework", "comprehensive solution", "seamlessly integrates", "underscores the significance". A sentence that would survive a professor asking "what exactly does this mean?" is the target.
