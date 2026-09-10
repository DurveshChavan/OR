# Viva question bank

Answers are short and specific, with the file or number to point at. Where an
answer is "we could not show that", it says so — a defended overclaim loses more
marks than an admitted limit.

---

## A · Operations Research, the syllabus half

**A1. Which OR technique does the production system actually use?**
Assignment — the Hungarian method, `scipy.optimize.linear_sum_assignment`, run
once per priority tier in `api/servicedesk/services/dispatch.py`. Rows are tickets,
columns are individual free WIP slots. It is the same technique as
`api/engine/assignment.py`; what changed is what is in the cells.

**A2. Why does the Hungarian method earn its place? A greedy loop is simpler.**
Because greedy can take a locally cheap cell and strand a later ticket on a
prohibited one. `test_hungarian_beats_greedy_when_the_greedy_pick_is_locally_cheap`
builds a 2×2 instance, worked by hand in its docstring, where greedy costs more
than the optimum. Show that test.

**A3. What is in a cell of your cost matrix?**
Currency, not minutes:
`urgency_rate × wait + late_rate × lateness + holding_rate × service`. Each term
is a rate per minute times a number of minutes, so all three are currency and
adding them is legitimate. The rates are the SLA policy row for that priority,
which a manager can edit on screen.

**A4. Your earlier version had a defect in that matrix. What was it?**
It put the ticket's own predicted resolution time in every qualified agent's
column, so the row was constant. A constant row carries no information: the
solver could not prefer one resolver over another, so the assignment step was
decoration. You can see it on `/legacy/assignment` — within a row, every
permitted cell holds the same number.
`test_the_cost_row_is_not_constant_across_agents` fails if that returns.

**A5. How do you make the matrix square? Textbook assignment needs it.**
Columns are padded with visible queue columns, one per ticket that could not get
a real slot. A queue column is priced one material quantum above the most
expensive permitted real candidate in the tier, plus the ticket's own urgency
rate for one review cycle. So a real resolver is always preferred to the queue,
but when capacity forces someone to wait, the ticket with the cheapest minutes
waits. The result is a `queued` decision, which is why no ticket is ever
silently dropped.

**A6. How do you handle a resolver who cannot do the work?**
A prohibited cell, priced at `PROHIBITED_COST = 1e12` — the textbook M. Large
enough that it is never chosen while a permitted cell is free, finite so the
matrix stays solvable. The candidate survives into the stored payload marked
ineligible, so a refusal is recorded rather than disappearing.

**A7. What if two candidates cost exactly the same?**
A deterministic epsilon from sorted identifier ranks, `TIE_EPSILON = 1e-9`,
which is eight orders of magnitude below the declared material quantum of 0.01.
It can only decide a comparison that is otherwise exactly equal, it is the same
on every machine, and the tie-break policy version is stored in each decision.

**A8. Show that you can still do the hand methods.**
`legacy/viva_methods.ipynb` — VAM and MODI on a small transportation instance
cross-checked against the PuLP optimum, a hand-solved Hungarian 3×3, Johnson's
rule on a small job set, EMV and minimax regret on a payoff table, a CPM forward
and backward pass with ES/EF/LS/LF and slack, and the deteriorating-item
replacement table. Each cell states the expected answer before it runs the code.

**A9. Where is the LP?**
`api/engine/capacity.py`, PuLP with CBC — the staffing/capacity allocation
problem, Unit I. It funds an agent headcount, which the legacy pipeline then
feeds to the assignment step.

**A10. Explain the M7 → M3 feedback loop, your original contribution.**
`replacement.py` exposes `workstation_factors()`; each factor is ≥ 1.0, rises
with workstation age and equals exactly 1.0 at age zero. `assignment.py`
multiplies each expected-resolution-time entry by the factor for the workstation
that ticket runs on. Ageing hardware raises cost; recommending a replacement
resets the factor to 1.0 and the solve re-runs. `pipeline.py` prints baseline /
aged / post-replacement and a test asserts cost rises then falls.

**A11. Does that loop change who gets the ticket?**
No, and this is the important part of the answer. The factor multiplies a whole
*row*, and a row scaled by a positive constant has the same ordering it had.
The loop moves total cost, not the assignment. The service desk's candidate-specific
cost is the fix: it prices a pair — when that resolver can start, how fast they
are on that skill, how late that combination finishes — so the row is no longer
constant. Explaining that transition is the honest answer.

---

## A-bis · Hardware replacement — expect this, it is in the title

**H1. Where does the machine data come from?**
A manager types it in, from their own asset register: age, purchase cost, resale
value by year, running cost by year, and a required note saying where the figures
came from. UCI-498 has no hardware telemetry and no ticket-to-asset key, so
nothing here could honestly be mined. The screen says that above the table.

**H2. Then what is the contribution, if the data is typed in?**
The decision. Given an organisation's own economics, the system says when each
machine should be replaced and whether a fleet is cheaper swapped on a schedule
than repaired on failure — and it shows the whole table so the answer can be
checked with a calculator. That is decision support, and it is the same thing an
LP or a transportation model does with numbers a planner supplies.

**H3. Show me the arithmetic.**
For replacement at the end of year *n*: total = purchase − resale(n) + running
cost accumulated to n; average = total / n; the optimal year minimises the
average. On the seeded register: purchase 62,000, resale 30,000 / 22,000 /
15,000 / 9,000 / 5,000, running 4,000 / 7,000 / 12,000 / 20,000 / 32,000 gives
averages 36,000 / 25,500 / 23,333.33 / 24,000 / 26,400, so year 3. WS-1004 is 57
months old, which is 21 months past that, so the verdict is replace now.

**H4. And the fleet method?**
The renewal recursion: B₁ = N·p₁, and B_i = N·p_i + Σ_j B_j·p_(i−j), because an
item replaced on failure is new again and can fail again. Group cost for
interval T is (N·group_cost + unit_cost·ΣB_i)/T; replace-on-failure costs
N·unit_cost / mean life. The test instance — N = 100, p = 0.1/0.2/0.3/0.4, unit
20, group 5 — gives 700 / 560 / 600.67 / 703.55 against 666.67, so a group swap
every 2 periods wins. That table is in the test docstring.

**H5. Does a failing machine change who gets the ticket?**
No, and a test enforces it. The same ticket recommended before and after being
linked to a machine 21 months overdue gets the identical resolver, risk and
stored reason. Saying otherwise would require a causal claim the data cannot
support.

**H6. Then why link tickets to machines at all?**
So a manager can see the operational context beside the economics: how many
tickets a person has attached to that machine, how many are still open, how many
are hardware-category. It is counted, never inferred — the link is set by a
signed-in user through one endpoint and the history records who set it — and it
is not an input to the replacement arithmetic.

**H7. Why not predict hardware failure from a real dataset?**
Because the only candidates — disk-failure datasets, for instance — cannot be
joined to this ticket log, so a model trained on one could not be shown to
affect anything in the other. A separately evaluated failure-risk appendix was
considered and rejected as answering a question this project did not register.

---

## B · Data and labels

**B1. What is the dataset, exactly?**
UCI-498, "Incident management process enriched event log": an anonymised
ServiceNow log from one IT company, 141,712 events over 24,918 incidents,
March 2016 to February 2017. Provenance, SHA-256 and commands are in
`docs/data_provenance.md`.

**B2. How did you decide the breach label was trustworthy?**
`made_sla` latches. Across all 24,918 incidents it is `T` throughout, `F`
throughout, or exactly one `T→F` transition — zero un-breaches. The naive
reading is that it changes during 36.6% of incidents and is therefore unstable;
that change *is* the breach event. The label is the final ordered record.
Prepared set: 23,323 incidents, 38.28% prevalence.

**B3. Why not use `closed_at` for duration? The dataset documentation does.**
Because `closed_at − resolved_at` has an IQR of about 120.2–120.8 hours — a
fixed five-day auto-close timer, with 25.4% of incidents in a single one-hour
band. It measures a timer, not work. Duration is `resolved_at − opened_at`, and
the divergence from the dataset's own documentation is deliberate and recorded.

**B4. What did you exclude, and why?**
`assignment_group` — populated on 96.4% of first records, so it encodes a
routing action a human already took, which is the decision being evaluated.
`assigned_to`, `resolved_by`, close code and resolution timestamps as outcome
leakage. Reassignment, reopen and update counts, because they develop after the
opening decision. `made_sla` is a label and never a feature; a test fails if a
forbidden column reaches the model.

**B5. Your training breach rate is 44% and your test rate is 24%. Is that a bug?**
It was checked before any model was trained. Right-censoring is ruled out
(`resolved_at` missing 0.0% in every week from November onward; only the final
week spikes). Left-truncation is ruled out (0.0% of incidents are breached on
their first record). It is a genuine front-loaded regime: weekly rates run 57.6,
96.1, 67.6, 44.2, 33.6 percent over the first five weeks and settle at 18–27%.
A sensitivity dropping the first three weeks was declared *before* the test
period was touched.

**B6. Why is there no NLP in a ticket project?**
UCI-498 has no free-text column — no `description`, no `short_description`. All
eight papers in the literature review classify ticket text; none of that is
possible here. The pivot to the decision layer is forced by the data.

---

## C · Models

**C1. Give me the headline model numbers.**
Locked test, base rate 24.4%, n = 3,499. Shipped model: ROC-AUC 0.7383,
PR-AUC 0.4707, Brier 0.1608, ECE 0.0406. Priority-only baseline: 0.5505 /
0.3020 / 0.2142 / 0.1974.

**C2. Your baseline scores 0.55. Isn't that suspiciously weak?**
It is weak, and it is a finding rather than a convenience. Priority separates
17.3% from 97.1% breach across the whole log, but priority 3 is 95% of the data,
so *inside the test period* priority is barely a ranker. Both numbers are
reported.

**C3. Why does calibration matter more than AUC here?**
Because the base rate moved. Uncalibrated, the model predicts a mean of 0.411
against an observed 0.244 — it learned the 44% training world. Isotonic
recalibration on the validation period brings the mean to 0.280 and ECE from
0.1664 to 0.0406. Calibrating inside the training period instead fixes nothing
(ECE 0.1692). A probability shown to a dispatcher has to mean what it says.

**C4. Is the calibration number in-sample anywhere?**
Yes, and the model card says so on the line under the table: the shipped map is
fitted on the validation period, so its validation ECE of 0.0000 is in-sample.
The test row is the real number.

**C5. Your duration model is wrong by roughly a day. Why ship it?**
Median absolute error 979 minutes against the baseline's 1,581, on a target
whose test-period median is 201 minutes and which spans minutes to months. It is
used only for ordering projected finishes, and the card states that logged
elapsed time contains historical queue waiting. It is not presented as an
accurate ETA.

**C6. Tell me about a bug you found.**
The application stores priority as `2`; the model was fitted on `"2 - High"`.
Every API-shaped payload scored 0.5556 regardless of priority, because
`OneHotEncoder(handle_unknown="ignore")` answers an unrecognised level with an
all-zero block and no error. The most predictive field was silently gone and the
number still looked reasonable. `normalise_priority` now maps both forms and
raises otherwise, with five tests scoring request-shaped payloads.

**C7. Why does a manually created P2 ticket score 0.999?**
Because `impact`, `urgency` and `u_symptom` are UCI fields with no equivalent in
this application, so they reach the artifact as missing and its imputer fills
them; priority 2 breaches 97.1% of the time in the log and nothing counters it.
Every `RISK_SCORED` payload lists them under `unavailable_features`, and the
interface shows the score as a band with its model version rather than as a bare
percentage.

---

## D · The evaluation — expect the hardest questions here

**D1. Did your policy reduce SLA breaches?**
In a simulation, under declared assumptions, the simulated breach rate is lower
at three of four capacity levels — 0.3287 against FIFO's 0.3590 at full
capacity. It is not evidence that a live service desk would improve. The metric
is the *simulated* SLA breach rate; establishing a real effect needs a shadow
deployment or an A/B test and this project performs neither.

**D2. What is doing the work, then?**
Candidate selection, not risk ranking. At full capacity queue waits are zero, so
ordering cannot be the mechanism, and the `no_agent_choice` ablation — same
tiering, same urgency, first eligible slot — lands at 0.3607, back at FIFO. What
moves the number is routing to a faster resolver.

**D3. So what did the risk model contribute to throughput?**
Nothing measurable in this replay. Replacing every calibrated probability with
1.0 gives exactly the same 0.3287, and removing the projected-lateness term does
too. Both are reported as null results, and the contribution sentence ends with
"reported with its null results" because of them. The risk score stays in the
product as Risk Radar ordering and as the stored explanation — a review aid.

**D4. Is there a case where your policy loses?**
Yes. At capacity multiplier 0.10, duration-first simulates 0.5384 against the
proposed policy's 0.7791. That is classic shortest-job-first behaviour under
overload, the proposed policy's own difference from FIFO there includes zero,
and nothing was retuned after seeing it.

**D5. How do you know the replay is not validating itself?**
The exogenous job list — arrival, required skill, SLA target, service demand,
seed — is built before any policy runs. The simulated outcome is computed only
as `finish > due`, never sampled from the risk model. Invariant tests prove
predictions cannot alter stored service demand, that replacing risk scores
leaves FIFO unchanged, and that no policy can read `made_sla`, `resolved_at`,
`closed_at`, the actual resolver or any future row.

**D6. Where did the agents come from? The log has no roster.**
Emulated from the training period only: 104 resolvers, WIP limits from the p90
concurrently-open incidents per resolver, speed multipliers from training
residuals shrunk toward 1.0 for low-volume resolvers. No test-period outcome,
resolver or assignment establishes agent performance. The full list of what is
assumed is `docs/assumptions.md` — twelve entries.

**D7. Where did the SLA targets come from?**
They are declared: 4 h / 8 h / 24 h / 48 h. UCI-498 records the breach outcome
but never the deadline that produced it. Deriving targets from the same
durations that generate the service demand would compare a number against
itself.

**D8. Why does P1 breach 90% under every policy?**
Because the declared 240-minute P1 target sits far below typical handling time
in this log. It is a property of the declared table meeting this data, not a
policy result, and it is reported that way.

**D9. Your service-demand proxy includes waiting time. Doesn't that flatter you?**
The opposite. `resolved_at − opened_at` overstates pure handling time, which
inflates service for *every* policy and understates the benefit of any
scheduling at all, including the proposed one. It is the conservative choice.

**D10. Did the replay evaluate the code you shipped?**
Not exactly, and this is stated in the report. The replay's urgency term is
`breach × risk / remaining`, which is currency per minute squared; the shipped
product uses the dimensionless slack ratio `target / remaining` so the three
cost terms share units. Ticket ordering inside a tier is identical either way,
because the target is constant within a tier; the balance between the wait term
and the other two is not. Both terms involved were already reported as null
results.

**D11. Why bootstrap only some days?**
Over the whole test period the median arrival day holds two tickets and the
busiest holds 358. Resampling all 132 days would measure which near-empty day
was drawn rather than the ticket mix, so blocks are the 16 comparable days in
the dense window.

---

## E · The application

**E1. What stops someone editing the audit trail?**
The database. `ticket_events` carries `BEFORE UPDATE OR DELETE` triggers in
PostgreSQL and `RAISE(ABORT, …)` in SQLite. Run
`DELETE FROM ticket_events` in a plain `sqlite3` connection and it answers
`ticket_events is append-only`. In PostgreSQL deployment the application role
holds only SELECT and INSERT on that table.

**E2. What happens when a dispatcher disagrees with a recommendation?**
They override, with a reason the form will not submit without. The
recommendation row is never edited — an `ASSIGNMENT_OVERRIDDEN` event is
appended naming the recommended resolver, the chosen resolver, the actor and the
stated reason. The ticket page shows both side by side.

**E3. Does the system ever assign anyone automatically?**
No. Generating recommendations writes decisions and assigns nobody; there is
deliberately no "assign all" button. Only accept and override set an assignee,
and both re-verify eligibility at that moment, because an earlier accept in the
same batch may have taken the last slot.

**E4. What does escalation do?**
Records. `ESCALATION_RECOMMENDED` when calibrated risk crosses the priority's
manager-editable threshold, `ESCALATION_ACKNOWLEDGED` when a human answers it
with a note. Nothing is routed to L2 or to a vendor, and the acknowledgement
changes no status, no assignee and no deadline.

**E5. Why can a recommendation become un-acceptable?**
Because the policy version or the model version behind it moved, in which case
accepting it would put a number in the audit trail that the current
configuration would not produce. The server refuses with `DECISION_STALE`; the
interface names which of four things changed — policy, model, the ticket itself,
or the recommended resolver's availability — rather than saying "stale".

**E6. Your rescore reports 14 considered, 0 rescored. Is it broken?**
No, and the module docstring says so. Every field the artifact reads — priority,
category, subcategory, location, contact type, opening timestamp — is fixed when
the ticket is created, and nothing in the feature row reads the clock. A rescore
earns its place in exactly three cases: an unscored ticket, a dispatcher
patching a field the model reads, or a different artifact being installed. A
time-varying score would need a feature the model was never fitted on.

**E7. Why no scheduler or background worker?**
Because a demo must not depend on a timer firing. Rescore is a protected
endpoint and a CLI command, `python -m api.servicedesk.cli.rescore_open_tickets`. A
real deployment can schedule that command externally.

**E8. Why synchronous FastAPI and synchronous sessions?**
A single machine serving one dispatch team. Async would add failure modes a
40-mark oral cannot inspect and buys nothing at this scale. It is a stated
simplification, not a missing feature.

---

## F · Honesty and scope

**F1. What is new here?**
An implementation and evaluation, not an algorithm. Prior work already predicts
SLA outcomes and completion times on this exact log, and the audit says so with
its search date and queries. What the search did not find is a dispatch replay
on it with disclosed baselines and a per-decision audit record — and that
absence comes from a web-only search, so it is reported as weak evidence.

**F2. What would you do differently?**
Two things. Fix the priority-encoding mismatch by giving the feature contract
one representation from the start rather than discovering it through a
suspiciously constant 0.5556. And declare the cost-model units before writing
the replay, so the replay and the product would be evaluating identical
functions rather than the same family.

**F3. What is not finished?**
Three items, all in the report's section 11. PostgreSQL is unverified — no
server exists on the development machine, so 91 dialect-parametrised tests skip
their PostgreSQL case and migration `0002`'s PostgreSQL trigger path has never
executed. The trigger rejection is therefore proven in SQLite only. And nobody
other than the author has followed the demo script on a clean machine.

**F4. Is any part of this project synthetic?**
The demo database, and it is labelled on screen as offline demo data — tickets
named `INC-DEMO-*`, resolvers named `Resolver NN (demo)`, SLA rows carrying a
note saying they must be replaced with a real policy. No result in the report
comes from it. The earlier synthetic ticket/agent/workstation universe was
removed from the production build entirely.

**F5. How does the project justify the "Hardware Replacement" in its title?**
With the machine register and its replacement advice, which is a screen a
professor can use, not an appendix. What it does not do is claim a hardware
effect on routing: no dataset joins a ticket to an asset, so the honest feature
is decision support over an operator's own economics. The earlier design
multiplied a cost-matrix row by an ageing factor and called that a feedback
loop; a row scaled by a constant keeps its ordering, so it moved total cost and
not the assignment. This build says so and replaces it rather than defending it.
