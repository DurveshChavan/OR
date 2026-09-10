# The Operations Research demo — archive notes

This directory is an archive **pointer**, not a copy.

## Why the code was not duplicated here

`tests/test_m0.py` through `tests/test_m7.py`, `tests/test_pipeline.py` and
`tests/test_api.py` import `api.engine` and `api.main` by their real paths. 95
of the repository's tests are legacy tests. Moving the modules would break all
of them; copying them would create two definitions of the same eight OR modules,
and the copy would quietly drift from the one the tests actually exercise.

So the legacy application stays exactly where it always was, still runnable,
still tested on every commit:

| What | Where |
|---|---|
| OR engine, one module per technique | `api/engine/` |
| Legacy FastAPI routes (no OR logic) | `api/main.py` |
| Legacy React pages | `client/src/pages/`, `client/src/components/`, `client/src/hooks/` |
| Legacy tests | `tests/test_m*.py`, `tests/test_pipeline.py`, `tests/test_api.py` |
| Worked examples for the oral exam | `legacy/viva_methods.ipynb` |
| Pre-cutover state | git tag `legacy-or-final` (local, at `b82a7cc`) |

## Running it after the cutover

Version 2 now serves `/`. The legacy demo moved to `/legacy` and every one of
its old paths redirects there, so nothing that was rehearsed against
`/assignment` or `/staffing` breaks.

```bash
python -m uvicorn api.main:app --port 8000     # the legacy API
cd client && npm run dev                       # then open /legacy
```

To put the legacy demo back on `/` — the switch is kept until after the
presentation:

```bash
cd client && VITE_DEFAULT_APP=legacy npm run dev
```

Check it is alive with `curl http://localhost:8000/api/health`. Without that
process the legacy pages render their own error states rather than blank.

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

## What version 2 takes from this, and what it does not

Nothing. `api/app_v2/` imports no module from `api/engine/`, and no number in a
version-2 screen, decision or result comes from the legacy pipeline. The two
applications share a repository, a client build and a test run, and nothing
else.

## The M7 → M3 loop, described accurately

The legacy contribution is the degradation feedback loop: `replacement.py`
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
the ticket. The `/legacy/assignment` screen shows this plainly: within a row,
every permitted cell holds the same number.

Version 2's dispatch is the fix, and explaining that transition is a stronger
answer than defending the original loop. `api/app_v2/services/dispatch.py`
prices a *pair*: when that agent can start, how long that agent takes on that
skill, and how late that combination finishes. The row is no longer constant, so
the assignment step has something to choose between —
`test_the_cost_row_is_not_constant_across_agents` watches for the old shape
coming back.
