# SLA-Driven Ticket Allocation, Escalation & Hardware Replacement

An IT service desk decision-support system built for MDM40233 (Operations Research). Eight
OR techniques -- LP capacity sizing, the transportation problem, Hungarian assignment,
Johnson's sequencing rule, decision/game theory, CPM/PERT, and replacement theory -- are
implemented from first principles in `api/engine/` and wired into one pipeline. The
project's original contribution is a feedback loop: `replacement.py` (M7) computes a
per-workstation hardware-degradation factor that ages `assignment.py`'s (M3) cost matrix,
so slower hardware measurably raises ticket-resolution cost until it's replaced.

## Architecture

```
client/ (React, placeholder)  -->  api/main.py (FastAPI, placeholder)  -->  api/engine/ (OR logic)
```

`api/engine/` has no dependency on FastAPI or Streamlit -- it's pure functions over
pandas/numpy DataFrames and dicts, so any frontend can sit on top of it.

## Setup

**API / engine**

```
pip install -r api/requirements.txt
```

**Client** -- not yet implemented (`client/` is a placeholder).

## Tests

```
pytest -q
```

## Run

```
python -m api.engine.pipeline
```

prints the three-stage cost table (baseline / aged / post-replacement) demonstrating the
M7-to-M3 feedback loop.

## Screenshots

_(placeholder -- add dashboard screenshots here once the client exists)_
