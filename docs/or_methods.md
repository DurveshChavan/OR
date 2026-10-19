# The Operations Research methods — where they live and how to run them

The eight OR modules are the `/methods` section of the application, still
runnable and tested on every commit:

| What | Where |
|---|---|
| OR engine, one module per technique | `api/engine/` |
| The engine's FastAPI routes (no OR logic) | `api/main.py` |
| The screens, now the `/methods` section | `client/src/pages/`, `client/src/components/`, `client/src/hooks/` |
| Their tests | `tests/test_m*.py`, `tests/test_pipeline.py`, `tests/test_api.py` |
| Worked examples for the oral exam | test docstrings in `tests/test_m*.py` and `tests/servicedesk/test_hardware.py` |

## Running them

The engine has its own process. The client reaches it through an `/or-api`
prefix that the dev server strips, so the two APIs never collide on `/api`.

```bash
python -m uvicorn api.main:app --port 8000     # the engine
cd client && npm run dev                       # then open /methods
```

Check it is alive with `curl http://localhost:8000/api/health`. Without that
process the Methods pages render their own error states rather than blank; every
other screen works without it.

## The eight modules and their syllabus units

| File | Technique | Unit |
|---|---|---|
| `api/engine/data_layer.py` | UCI-498 loader, seeded synthetic generator, `derive_*` | — |
| `api/engine/capacity.py` | LPP / Simplex via PuLP + CBC | I |
| `api/engine/transport.py` | Transportation: NWCR, Least Cost, VAM, MODI, PuLP cross-check | III |
| `api/engine/assignment.py` | Hungarian assignment + degradation hook | III |
| `api/engine/sequencing.py` | Johnson's rule, two-jobs-m-machines graphical | III |
| `api/engine/decision.py` | EMV, maximax, maximin, Laplace, Hurwicz, minimax regret, decision tree, saddle point, dominance, 2×n graphical, mixed-strategy LP | II |
| `api/engine/cpm_pert.py` | CPM forward/backward pass, PERT `te` and variance, Z-score | IV |
| `api/engine/replacement.py` | Deteriorating-item average cost, group vs individual replacement | IV |
| `api/engine/pipeline.py` | Wires M0–M7 and closes the M7→M3 loop | — |

## What the application takes from this

The replacement arithmetic, and only that. `services/hardware.py` calls
`api/engine/replacement.py` so the Hardware screen and the oral examination read
the same code. Nothing else is imported: dispatch, scoring and the replay share
no code with the engine, and no number in a dispatch result comes from the
engine pipeline.

## The M7 → M3 loop, described accurately

The engine's contribution is the degradation feedback loop: `replacement.py`
exposes `workstation_factors()`, and `assignment.py` multiplies each
expected-resolution-time entry by the factor of the workstation the ticket runs
on. Ageing hardware raises cost; replacing it resets the factor to `1.0` and the
Hungarian solve re-runs. `pipeline.py` prints the three-stage baseline / aged /
post-replacement table and a test asserts that total cost rises at the aged
stage and falls after replacement.

**What it cannot do, and the viva answer should say so first.** The factor
multiplies a whole cost-matrix *row* — every qualified agent's column for that
ticket by the same number. A row scaled by a constant has the same ordering it
had before, so the loop moves the total cost without changing which agent serves
the ticket. The `/methods/assignment` screen shows this plainly: within a row,
every permitted cell holds the same number.

The service desk's dispatch is the fix, and explaining that transition is a stronger
answer than defending the original loop. `api/servicedesk/services/dispatch.py`
prices a *pair*: when that agent can start, how long that agent takes on that
skill, and how late that combination finishes. The row is no longer constant, so
the assignment step has something to choose between —
`test_the_cost_row_is_not_constant_across_agents` watches for the old shape
coming back.
