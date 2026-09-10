# Offline demo script

The viva runs on this. It needs **no internet, no Docker, no PostgreSQL, no UCI
download, no retraining and no background worker**. Everything it uses is
either committed to the repository or built by the three commands in step 1.

If any step below asks for the network, the demo is not ready.

## What is on screen, and what it is not

The seeded database is illustrative. The tickets are named `INC-DEMO-*`, the
resolvers are named `Resolver NN (demo)`, and the SLA policy rows carry a note
saying they must be replaced with an organisation's own policy. Nothing in this
database is a measured result, and the interface says so in a banner on every
screen.

The measured results live elsewhere and are read, not demonstrated live:
`docs/results/replay-2026-09-10-a1.md` for the policy comparison,
`models/sla_risk/uci-risk-2026-09-10-a1/model_card.md` for the risk model.

## 1 · Build the demo database (about 20 seconds)

`data/` is not tracked, so the database is reproduced rather than committed.
The seed command refuses to run on a database that already has users, which is
why the first line deletes the file instead of seeding on top of it.

```bash
cd Project
rm -f data/demo/sla_desk.sqlite3            # Windows: del data\demo\sla_desk.sqlite3
python -m alembic upgrade head
python -m api.app_v2.cli.seed_demo
```

Expected output: 2 users, 4 policies, 4 agents, 14 tickets, and the line
`sign in as dispatcher.demo or manager.demo with password local-demo-password`.

The fourteen tickets are chosen so one batch reaches every outcome the
application can produce: ten need the `network` skill against nine network
slots, so at least one comes back **queued**; `INC-DEMO-0012` needs a
`mainframe` skill nobody holds, which is **no eligible agent**; `INC-DEMO-0007`
and `INC-DEMO-0008` are already **overdue** when they are seeded.

## 2 · Start the two processes

```bash
# terminal 1 — the version-2 API
python -m uvicorn api.app_v2.main:app --port 8001

# terminal 2 — the client
cd client && npm run dev
```

Open `http://localhost:5173/`. Since the phase 5 cutover this redirects to
`/v2`, which is the version-2 application.

The legacy Operations Research demo moved to `http://localhost:5173/legacy` and
still works exactly as before; every one of its old paths (`/assignment`,
`/staffing`, and the rest) redirects there rather than breaking. Start its API
with `python -m uvicorn api.main:app --port 8000` if it is going to be shown -
without it the legacy pages show their own error states.

The cutover is reversible until after the presentation:

```bash
cd client && VITE_DEFAULT_APP=legacy npm run dev   # `/` serves the OR demo again
```

Confirm the build before signing in:

```bash
curl http://localhost:8001/api/v2/health
```

`models_available: true` and a `risk_model_version` mean the committed
artifacts loaded. If they are false, the client shows a
**"Model unavailable — manual dispatch"** banner and blocks recommendation,
which is the honest behaviour rather than a hidden fallback.

## 3 · The walk-through

Times are shown in the browser's zone and stored in UTC; the header names the
zone.

1. **Sign in** as `dispatcher.demo` / `local-demo-password`.
   Point out the *Offline demo data* banner: it is driven by the API reporting a
   SQLite dialect, not by a build flag, so a screenshot cannot claim otherwise.

2. **Queue.** Fourteen tickets, soonest deadline first. Each row carries the SLA
   clock as text, the risk as a **band with the model version under it**, and
   the assignee. Say why it is a band: three fields the model was trained on
   (`impact`, `urgency`, `u_symptom`) do not exist in this application, so a
   bare percentage would be more precise than the input deserves.

3. **Create a ticket** with *New ticket* — P2, skill `network`. The deadline is
   not typed in: it comes from the SLA policy for that priority. The ticket is
   scored in the same transaction that creates it.

4. **Select several tickets and press "Generate recommendations."**
   The wording matters and there is deliberately no "assign all": this writes
   one immutable decision per ticket and assigns nobody. Expect a mix of
   `recommended`, `queued` and `no_eligible_agent` — no ticket is dropped.

5. **Open a recommended ticket.** Walk the page in this order:
   - the **stored reason**, read verbatim from the decision. The client never
     regenerates it, so what is on screen is what the audit trail holds;
   - the projections and the candidate cost, with the model and policy version
     that produced them;
   - the **alternatives** table — the rest of that ticket's own matrix row,
     cheapest first, with the note saying the batch optimum may still differ.

6. **Accept** the recommendation. The ticket becomes `assigned`, and the
   resolver's projected availability moves forward by the predicted service
   time.

7. **Open a second ticket and override it.** The button stays disabled until a
   reason is typed. After submitting, show the history: the decision still names
   the resolver it originally recommended, and `ASSIGNMENT_OVERRIDDEN` records
   who chose otherwise and why. The recommendation was not edited.

8. **Risk Radar.** Four separate lists — already overdue (recovery), P1 waiting,
   high model risk, normal queue. The split is the argument: a breached ticket
   still needs a person whatever the score says. Use *Acknowledge* on an overdue
   ticket with a note; it appends one event and changes no status, no assignee
   and no deadline, and it routes nothing to a vendor.

9. **Administration**, signed in as `manager.demo`. Show that a dispatcher sees
   the same numbers with every control disabled. Edit an SLA rate and point at
   the warning: stored deadlines do not move and decisions already written keep
   the rates they were priced under. Then press **Rescore open tickets** and
   read the result honestly — a large `unchanged` count is expected, because
   every field the artifact reads is fixed when a ticket is created. A score
   moves when a ticket is edited, when it was never scored, or when a different
   artifact is installed.

10. **The audit trail is the database's rule, not the application's.** With the
    API still running:

    ```bash
    python -c "import sqlite3;c=sqlite3.connect('data/demo/sla_desk.sqlite3');c.execute('DELETE FROM ticket_events')"
    ```

    It fails on the trigger from migration `0002`. The same trigger exists in
    the PostgreSQL path, where the application role additionally holds only
    SELECT and INSERT on that table.

11. **Restart the API** and reload the page. Tickets, decisions, assignments and
    events are all still there: version 2 keeps state in a database, not in
    process memory.

## 4 · The command line, if the browser is not wanted

```bash
python -m api.app_v2.cli.rescore_open_tickets     # the same rescore, no UI
python -m api.app_v2.cli.export_openapi           # regenerate docs/openapi_v2.json
```

There is no scheduler and no worker process in this build, so nothing in the
demo depends on a timer firing.

## 5 · Reset between runs

```bash
rm -f data/demo/sla_desk.sqlite3
python -m alembic upgrade head
python -m api.app_v2.cli.seed_demo
```

## Credentials

`dispatcher.demo` and `manager.demo`, both `local-demo-password`. They exist
only in the seeded offline database and are created by the seed command; there
is no default account in a fresh migration.
