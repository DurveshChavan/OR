# Limitations

Read this before quoting any number from this project.

## The replay is a simulation, not a trial

The counterfactual replay asks: under the disclosed queue, agent, SLA and
service-demand assumptions, how do policy outcomes differ? It **cannot** observe
what would have happened to a historical ticket under a different resolver.

The reported metric is the **simulated SLA breach rate**. It is never "SLA
breach reduction", and never evidence that a live service desk will improve.
Establishing that needs a shadow deployment or an A/B test; this project
performs neither.

## Assumption load

Agent capacity, skills, WIP limits, shift coverage, initial queue state and SLA
policy values are all absent from UCI-498. They are assumptions (see
`assumptions.md`). Results are reported across a predeclared sweep of capacity
multipliers rather than at one invented staffing level.

## Service-demand proxy contains queue waiting

`resolved_at - opened_at` includes historical waiting, so it overstates pure
handling time. This biases against every scheduling policy including the
proposed one — conservative, not flattering.

## Dataset scope

One organisation, one platform (ServiceNow), one anonymised window from 2016.
Category, location and group labels carry no semantic meaning.

Priority 3 is 95% of the data, so any aggregate metric is effectively a
priority-3 metric. The priority-1 and priority-2 subsets are small (185 and 311
incidents). The priority-2 breach rate (97.11%) **exceeds** priority-1 (80.54%);
this inversion is unexplained and is reported rather than smoothed over.

## No ticket text

UCI-498 contains no free-text field, so this project cannot perform — and does
not claim — the text classification the reviewed literature performs.

## Model limitations

The risk score is a **ticket-level urgency signal**. It is not agent-specific
and does not estimate any individual agent's probability of success. Agent
selection comes from eligibility, projected availability, workload and a
residualised duration estimate, never from the risk model.

Calibration is reported even when poor. Discrimination metrics are never shown
alone.

## Hardware

Absent. No claim about hardware replacement, asset ageing or a hardware feedback
loop appears in any v2 result.
