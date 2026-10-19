# AI-Driven SLA Optimization

**Predictive Ticket Allocation, Escalation and Hardware Replacement in IT Service Desks**

An IT service desk decision-support system built for MDM40233 (Operations Research). Eight
OR techniques -- LP capacity sizing, the transportation problem, Hungarian assignment,
Johnson's sequencing rule, decision/game theory, CPM/PERT, and replacement theory -- are
implemented from first principles in `api/engine/` and wired into one causal chain:
staffing funds who's available, assignment gives tickets to those agents, sequencing
orders each agent's work, escalation reviews at-risk tickets and changes their routing,
hardware ageing warps assignment cost, and replacement resets it -- see
`api/engine/pipeline.py`'s module docstring for the full story.

## Architecture

```
client/ (React + Vite)  -->  api/main.py (FastAPI)  -->  api/engine/ (OR logic)
```

`api/engine/` has no dependency on FastAPI, Streamlit, or React -- it's pure functions
over pandas/numpy DataFrames and dicts. `api/main.py` is route handlers and pydantic
schemas only (zero OR logic); every number the client shows traces back to an
`api/engine` call. `client/` is a plain Vite + React + Tailwind + React Query + recharts
app talking to that API over HTTP -- nothing in it recomputes an OR result client-side.

## Project layout

```
api/
  engine/            OR logic, one module per technique, no framework imports
    data_layer.py       M0 -- loads/cleans the UCI-498 log, derives empirical rates
    capacity.py         M1 -- LP staffing/headcount sizing
    transport.py         M2 -- transportation problem (regional ticket distribution)
    assignment.py        M3 -- Hungarian assignment (ticket -> agent cost matrix)
    sequencing.py        M4 -- Johnson's two-machine sequencing rule
    decision.py          M5/M6 -- escalation decision theory, EMV, game-theoretic routing
    cpm_pert.py           -- CPM/PERT network for major-incident timelines
    replacement.py       M7 -- deteriorating-hardware replacement + M7->M3 feedback
    pipeline.py          wires M0-M7 into one run; CONFIG dict holds every
                          non-derivable business assumption, each commented with why
  main.py              FastAPI app; every route calls straight into api.engine.pipeline
  requirements.txt
client/
  src/
    pages/             one page per pipeline stage (StaffingPlanner, TicketAssignment,
                        HardwareHealth, EscalationAdvisor, WorkQueue, RegionalLoad,
                        MajorIncident, Overview)
    components/        shared UI (Card, Heatmap, StatTile, EditableNumberField, ...)
    hooks/              React Query hooks wrapping the API client
    lib/                API client, formatting helpers
  vite.config.js        dev-time proxy of /api/* -> localhost:8000
tests/
  test_m0.py .. test_m7.py   one test file per engine module above
  test_pipeline.py           full M0-M7 chain, asserts the feedback loop actually feeds back
  test_api.py                FastAPI routes via fastapi.testclient
data/                  gitignored; holds the cached UCI-498 CSV after first run
```

If you're adding a ninth OR technique or reworking an existing one, the engine module is
the only place its math should live -- `pipeline.py` should only ever call into it,
`main.py` should only ever call into `pipeline.py`, and the corresponding `tests/test_mN.py`
should assert the module's output directly (not through the API).

## Prerequisites

- **Python 3.11+**
- **Node 18+**

## Setup

### 1. Install Python dependencies

```bash
pip install -r api/requirements.txt
```

### 2. Install client dependencies

```bash
cd client
npm install
```

### 3. Initialise the database

The service-desk application stores tickets, agents and the audit trail in a
database. By default it uses an SQLite file at `data/demo/sla_desk.sqlite3`
(see `DATABASE_URL` in `api/servicedesk/db/session.py`). Run the Alembic
migrations to create the schema:

```bash
python -m alembic upgrade head
```

### 4. Seed the demo data (first time only)

```bash
python -m api.servicedesk.cli.seed_demo
```

This downloads the UCI-498 incident event log (cached to `data/`), creates
four demo SLA tiers, the resolver roster, and fourteen held-out test tickets.
The command is idempotent — it refuses to seed a database that already has
users. Pass `--force` only on a throwaway demo database.

Deadlines are measured against the real clock, so a demo database left for a
day opens with every ticket overdue. Re-anchor the seeded tickets (an event on
each records the shift) with:

```bash
python -m api.servicedesk.cli.refresh_demo_window
```

## Data

The OR engine runs on UCI dataset 498 (Incident management process enriched
event log). `api/engine/data_layer.py`'s `load_incident_log` looks for
`data/incident_event_log.csv` first; if it's not there (first run, or a fresh
clone — `data/` is gitignored), it tries `ucimlrepo`, then falls back to
downloading the zip directly from the UCI archive, and caches the result to
`data/incident_event_log.csv` so every later run is offline. If a run needs to
work with no network access at all, see `make_synthetic` in the same file —
`pipeline.py` falls back to it when no cached CSV and no network are available.

Every number that *is* in the dataset comes from a `derive_*` function in
`data_layer.py`. Every number that *isn't* (costs, budgets, SLA deadlines,
hardware-ageing alpha, …) lives in the `CONFIG` dict at the top of
`pipeline.py`, each entry commented with why it can't be derived — that's the
first place to look when changing a business assumption, and the CLI run below
prints a `source:` line under each stage so you can tell which numbers came
from which place.

## Run

### Engine only (CLI)

```bash
python -m api.engine.pipeline
```

Prints the story in order — capacity funding, regional distribution, the
sequenced work queue, the M6-gated escalation routing, and the three-stage
(baseline / aged / replaced) cost table — with a `source:` line under each
stage naming exactly where its numbers came from (real UCI-498 log vs. a
documented CONFIG assumption).

### Full application (three terminals)

Two separate FastAPI processes serve the project, and they are separate on
purpose:

| Server | Command | Port | Purpose |
|--------|---------|------|---------|
| OR engine | `uvicorn api.main:app --port 8000 --reload` | 8000 | Operations Research methods (LP, transport, assignment, sequencing, decision/game theory, CPM/PERT, replacement) |
| Service desk | `uvicorn api.servicedesk.main:app --port 8001 --reload` | 8001 | The product: tickets, agents, SLA policies, audit trail, risk scoring, recommendations |
| Client | `cd client && npm run dev` | 5173 | React + Vite frontend |

```bash
# terminal 1 — OR engine
uvicorn api.main:app --port 8000 --reload

# terminal 2 — service desk API
uvicorn api.servicedesk.main:app --port 8001 --reload

# terminal 3 — client
cd client
npm run dev
```

Open **http://localhost:5173** (or the port Vite assigns, e.g., `5174`).
Log in with username **`dispatcher.demo`** or **`manager.demo`** and the default password **`local-demo-password`**.

The Vite dev server proxies two prefixes (see `client/vite.config.js`):

- `/or-api/*` → `http://localhost:8000` (prefix stripped before forwarding)
- `/api/*` → `http://localhost:8001` (prefix kept)

No environment variables are needed for local development. Set
`VITE_OR_API_BASE_URL` (e.g. in `client/.env.local`) only if the OR engine is
served from a different origin in production.

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | `sqlite:///./data/demo/sla_desk.sqlite3` | Database for the service desk (PostgreSQL or SQLite) |
| `VITE_OR_API_BASE_URL` | `/or-api` | Override the OR engine base URL on the client |

## Tests

```bash
pytest -q
```

Each `tests/test_mN.py` targets one engine module in isolation;
`test_pipeline.py` runs the full M0-M7 chain and checks the M7→M3 feedback
loop actually changes assignment cost; `test_api.py` exercises the FastAPI app
in-process via `fastapi.testclient`, so it catches route/schema regressions
without needing a running server or the client.

Run the relevant `test_mN.py` (or add one) when changing an engine module, and
`test_pipeline.py` when changing how modules feed into each other. If a change
adds or renames a route in `api/main.py`, extend `test_api.py` rather than
relying on manual browser checks alone.

## Manual verification checklist

Run the full app (above) and confirm, in the browser:

The shell has two destinations for a dispatcher and four for a manager, which
is the whole product surface; the Operations Research worksheets sit behind the
research-appendix link in the footer. Sign in with the password **`local-demo-password`**. Use username `dispatcher.demo` for the first
three checks and `manager.demo` for the rest.

- [ ] **Queue** (`/`): active tickets load ordered by deadline, each with its
      title; the search box matches a reference or a title; select one or more
      and `Preview assignments` lists a suggested resolver per ticket with its
      reason; `Assign to <resolver>` commits one; the ticket page records it.
- [ ] **New ticket**: a title is required; set impact *2 - Medium* and urgency
      *1 - High* and the priority field disappears — the ticket is created as
      P2 by the ITIL matrix and its creation event says so.
- [ ] **Ticket lifecycle**: on a ticket, `Resolve` with a note shows *SLA met*
      or *breached*; `Close`, then `Reopen` sends it back to the queue
      unassigned with the same deadline; the activity list names all three.
- [ ] **At risk** (`/at-risk`): one ranked list, not four. Each row offers a
      single next action. `Start escalation review` asks who the review is with
      before it will open.
- [ ] **Escalation round trip**: open a review on an overdue ticket, confirm the
      at-risk row now reads *in review with …* and offers `Close review`, then
      close it with an outcome and confirm the ticket returns to the queue and
      the timeline names both ends of the review.
- [ ] **Ticket → machine → replacement**: on a ticket, link an affected machine
      under *Affected machine*; its replacement verdict appears beside the
      control; the review target `Replacement decision` becomes available, and
      closing as *a hardware replacement was raised* stores the verdict in the
      event history.
- [ ] **Asset planning** (`/hardware`, manager): the register loads with a
      per-machine verdict; opening one shows the full year-by-year average-cost
      table a reader can check with a calculator.
- [ ] **Operations** (`/operations`, manager): SLA target and escalation
      threshold are editable in front; the four per-minute cost weights are
      behind *Cost weights the solver prices with*.
- [ ] **Methods → Staffing Planner** (`/methods/staffing`): edit the budget
      field and re-solve — funded headcount per skill changes.
- [ ] **Methods → Ticket Assignment** (`/methods/assignment`): toggle
      "Show hardware impact" — the aged total appears alongside baseline and
      moved tickets are highlighted.
- [ ] **Methods → Replacement** (`/methods/replacement`): click "Age +N months"
      then "Replace recommended" — cost rises then falls.

## Ticket text: tested, not used

Tickets carry a title and description, and no model reads them. Whether public
ticket text could suggest urgency was measured, not assumed:
`python -m api.servicedesk.eval.text_urgency` writes
`docs/results/text-urgency-2026-10-15.md`. On 357 real tickets the text model
reaches ROC-AUC 0.665 with each client held out and leans on greetings; a model
trained on 16,338 synthetic tickets scores 0.451 on the real ones. The urgency
that reaches the risk model is the one a person sets.

## Screenshots and UI evidence

`docs/ui-evidence/` holds the screenshots and measurements from the last
interface review: every screen at 360, 768, 1024 and 1440 CSS pixels and at
200% zoom, the escalation round trip driven end to end, and `findings.json` —
axe-core violations, keyboard traversal with focus visibility, and contrast
ratios measured from rendered pixels rather than from the token values. The
review itself is `docs/UI_UX_CRITIQUE.md` in the SCE folder above this one.
