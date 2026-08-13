# CLAUDE.md

## Build/test commands
- Install: `pip install "pulp>=3.0,<4.0" pandas numpy scipy networkx matplotlib streamlit pytest ucimlrepo`
- Run tests: `pytest -q`
- Run pipeline demo: `python -m src.pipeline`
- Run dashboard: `streamlit run app.py`

## Non-negotiable rules
- Do ONE module per prompt. Stop after each module. Do not scaffold future modules early.
- Every module gets pytest tests in the same prompt. Tests must pass before moving on.
- No machine learning. No database. No new dependencies beyond the stack in CONTEXT.md.
- PuLP must be pinned <4.0 so the bundled CBC solver works with `prob.solve()` (no solver arg).
- Do not call `st.cache` (deprecated). Use `st.cache_data`.
- Keep functions small and readable. This is a student OR project, not production. Prefer clarity over cleverness.
- Every OR method must be traceable to its hand-method equivalent (a grader will check the math).

## Architecture
- Pure functions where possible: inputs are numpy arrays / pandas DataFrames, outputs are dataclasses or dicts.
- Each module m*.py exposes one main entry function and its helpers. pipeline.py imports them.
- Costs and results are plain numbers; no hidden global state.
- Random synthetic data uses a fixed seed (numpy default_rng(42)) so tests are deterministic.

## Anti-over-engineering
- If a task can be done in 40 lines, do not write 200.
- No config framework, no plugin system, no abstract base classes unless a test needs one.
- If you are about to add a dependency, stop and ask.

## When unsure
- Prefer the simplest correct OR formulation from a standard textbook (Taha / Hillier-Lieberman).
- If data is missing, generate deterministic synthetic data rather than failing.
