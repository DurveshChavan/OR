# Offline demo script

The viva runs on this. It needs **no internet, no Docker, no PostgreSQL, no UCI
download, no retraining and no background worker**. Everything it uses is
either committed to the repository or built by the three commands in step 1.

If any step below asks for the network, the demo is not ready.

## What is on screen, and what it is not

The tickets are real. Each one is an incident from the held-out split of
UCI-498, carrying the record's own incident number, priority, category,
subcategory, location and contact type. Held-out matters: those are the 3,499
records the risk and duration models never saw while being fitted, so a risk
figure on screen is a prediction rather than a memory. The one thing that is not
the record's own is the opening time - the incidents are from 2016 and a
deadline is measured against the clock, so each ticket is opened at a stated
offset inside the demo window, and the offset is written into the ticket's
creation event.

Everything that is not a ticket is illustrative and says so in its own source
note: the four resolvers, the SLA policy rows and the machine register, because
UCI-498 carries no roster, no SLA policy and no asset table. The footer of every
screen states all of this in one line.

No number in the report comes from this database.

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
python -m api.servicedesk.cli.seed_demo
```

Expected output: 2 users, 4 policies, 4 agents, 14 tickets, 4 machines, and the
line
`sign in as dispatcher.demo or manager.demo with password local-demo-password`.

The fourteen incidents are chosen, not sampled - 3,333 of the 3,499 held-out
records are priority 3, so a random draw would show one tier and one outcome.
`scripts/select_demo_incidents.py` is the selection, and it is kept in the
repository so the choice can be checked. It picks them so one batch reaches
every outcome the application can produce: ten are Category 42 against nine
Category 42 slots, so at least one comes back **queued**; `INC0031021` is
Category 23, which no resolver holds, and is **no eligible agent**; `INC0030987`
and `INC0032909` are already **overdue** when they are seeded.

The categories read as `Category 42`, not `Network`, because that is how they
are in the source - UCI-498 anonymises them. Renaming them to something more
readable would mean inventing the one field the dispatcher routes on.

## 2 · Start the processes

```bash
# terminal 1 — the service desk API
python -m uvicorn api.servicedesk.main:app --port 8001

# terminal 2 — the Operations Research engine, which the Methods screens read
python -m uvicorn api.main:app --port 8000

# terminal 3 — the client
cd client && npm run dev
```

Open `http://localhost:5173/`. That is the whole application: Queue, Risk Radar,
Hardware, Methods and Administration.

The engine on port 8000 is only needed for the Methods screens; every other
screen works without it, and each Methods page shows its own error state when it
is not running.

Confirm the build before signing in:

```bash
curl http://localhost:8001/api/health
```

`models_available: true` and a `risk_model_version` mean the committed
artifacts loaded. If they are false, the client shows a
**"Model unavailable — manual dispatch"** banner and blocks recommendation,
which is the honest behaviour rather than a hidden fallback.

## 3 · The walk-through

Times are shown in the browser's zone and stored in UTC; the header names the
zone.

1. **Sign in** as `dispatcher.demo` / `local-demo-password`.
   Point out the provenance line in the footer. It is driven by the API
   reporting a SQLite dialect, not by a build flag, so a screenshot cannot claim
   otherwise. Read it out: the tickets are real held-out UCI-498 incidents, the
   roster and policy are illustrative, and the opening times are placed in the
   demo window because the records are from 2016.

2. **Queue.** Fourteen tickets, soonest deadline first. Each row carries the SLA
   clock as text, the risk as a **band with the model version under it**, and
   the assignee. Say why it is a band: `u_symptom` does not exist in this
   application at all, and `impact` and `urgency` exist only when a person sets
   them, so a bare percentage would be more precise than the input deserves.

3. **Create a ticket** with *New ticket* — P2, skill `Category 42`. The deadline is
   not typed in: it comes from the SLA policy for that priority. The ticket is
   scored in the same transaction that creates it.

4. **Select several tickets and press "Preview assignments."**
   The wording matters and there is deliberately no "assign all": this writes
   one immutable decision per ticket and assigns nobody. Each suggestion then
   appears with its own *Assign to <resolver>* button, so a batch review still
   ends in explicit per-ticket confirmations. Expect a mix of
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

8. **At risk.** One ranked list — overdue work and unowned P1 tickets first,
   because a breached ticket needs a person whatever the score says. Every row
   offers exactly one next action. On an overdue ticket, choose *Start
   escalation review*, pick who it goes to, and type why. The status changes to
   `escalation review`, the row now reads *in review with …*, and the same row
   offers *Close review*. Close it with an outcome and the ticket returns to the
   queue with both ends of the review in its history.

   If somebody asks whether that is a real escalation: try to close it as *a
   different resolver now owns it* without reassigning it first. The server
   refuses. The outcomes are claims about the ticket, not free text.

9. **From the ticket to the machine.** Before leaving a ticket, link its
   affected machine. The replacement verdict for that machine appears beside the
   control, and *Replacement decision* becomes available as a review target.
   This is the join the title's three terms meet at, and it is a person's
   statement: UCI-498 has no ticket-to-asset key and nothing here guesses one.

10. **Asset planning** (sign in as `manager.demo`). The title's third term, and
   the screen that answers "where did this number come from" fastest. WS-1004 is 57 months old and its own cost
   figures put the lowest average annual cost at year 3, so the advice is
   *replace now*, 21 months late. Open the verdict: the full year-by-year table
   appears with the minimum marked — 36,000 / 25,500 / 23,333.33 / 24,000 /
   26,400 — and a professor can check it with a calculator. Say plainly that
   every figure was typed in by an operator, that two tickets were linked to that
   machine by a person, and that linking them changed no recommendation: the
   register is decision support and dispatch never reads it. Then run the
   group-versus-individual comparison below it with the default figures; the
   renewal table 700 / 560 / 600.67 / 703.55 against 666.67 says a group swap
   every 2 periods is cheaper.

11. **Methods.** Eight pages, one per Operations Research technique, with the
    syllabus unit named on each. The assignment page is worth opening: within a
    row every permitted cell holds the same number, which is exactly the defect
    the dispatch cost model in the Queue screen fixes.

12. **Operations**, signed in as `manager.demo`. The route is manager-only now:
   a dispatcher's shell has two entries and this is not one of them, because a
   page whose every control is disabled exists only to tell somebody they may
   not use it. Note that the SLA target and the escalation threshold are in
   front, while the four per-minute cost weights sit behind a disclosure —
   policy is a sentence a manager can say; the weights are how the solver
   prices a choice. Edit an SLA rate and point at
   the warning: stored deadlines do not move and decisions already written keep
   the rates they were priced under. Then press **Rescore open tickets** and
   read the result honestly — a large `unchanged` count is expected, because
   every field the artifact reads is fixed when a ticket is created. A score
   moves when a ticket is edited, when it was never scored, or when a different
   artifact is installed.

13. **The audit trail is the database's rule, not the application's.** With the
    API still running:

    ```bash
    python -c "import sqlite3;c=sqlite3.connect('data/demo/sla_desk.sqlite3');c.execute('DELETE FROM ticket_events')"
    ```

    It fails on the trigger from migration `0002`. The same trigger exists in
    the PostgreSQL path, where the application role additionally holds only
    SELECT and INSERT on that table.

14. **Restart the API** and reload the page. Tickets, decisions, assignments and
    events are all still there: the service desk keeps state in a database, not in
    process memory.

## 4 · The command line, if the browser is not wanted

```bash
python -m api.servicedesk.cli.rescore_open_tickets     # the same rescore, no UI
python -m api.servicedesk.cli.export_openapi           # regenerate docs/openapi.json
```

There is no scheduler and no worker process in this build, so nothing in the
demo depends on a timer firing.

## 5 · Reset between runs

```bash
rm -f data/demo/sla_desk.sqlite3
python -m alembic upgrade head
python -m api.servicedesk.cli.seed_demo
```

## Credentials

`dispatcher.demo` and `manager.demo`, both `local-demo-password`. They exist
only in the seeded offline database and are created by the seed command; there
is no default account in a fresh migration.
