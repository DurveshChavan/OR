# Assumption register

Every quantity the system uses that the data does not supply. Each entry states
what is assumed, why the data cannot supply it, and where to change it.

Rule: no value may be described as "derived from UCI-498" unless it actually is.

## Confirmed by audit — these are NOT assumptions

| Quantity | Value | Evidence |
|---|---|---|
| Breach label | `made_sla == False` on final ordered record | latching flag, 0 un-breaches |
| Breach prevalence | 38.28% over 23,323 valid incidents | `data/reports/uci498_audit.md` |
| Service duration | `resolved_at - opened_at` | `closed_at` rejected: ~5-day auto-close timer |
| Feature snapshot | first ordered record only | ordering rule fixed in audit |
| `assignment_group` | excluded | populated on 96.4% of first records |

## Assumptions — the data cannot supply these

| # | Assumption | Why the data cannot supply it | Where to change it |
|---|---|---|---|
| A1 | SLA target minutes per priority | UCI-498 records the breach *outcome*, never the deadline that produced it | `sla_policies.target_minutes` |
| A2 | Breach penalty per minute per priority | No monetary field exists in the dataset | `sla_policies`, `source_note` marks it demo configuration |
| A3 | Overdue recovery penalty per minute | Policy choice preventing starvation of already-breached work | `sla_policies` |
| A4 | Holding cost per minute | Queue/load cost; an organisational input | `sla_policies` |
| A5 | Agent WIP limits | No concurrency field in the log | `agents.wip_limit` |
| A6 | Agent skill map | Not recorded; derived from training-period category-to-resolver association with a minimum support threshold | replay config; production uses manager administration |
| A7 | Agent speed multiplier | Residualised from training-period outcomes, shrunk toward 1.0; low-volume resolvers shrink hardest | replay manifest records per-resolver sample size |
| A8 | Shift coverage / availability | Not recorded | replay assumes agents initially available |
| A9 | Initial queue state | Not recorded | replay starts empty; warm-up excluded from metrics |
| A10 | Preemption behaviour | Not recorded | non-preemptive service assumed |
| A11 | Service-demand proxy | Held-out empirical resolved-duration | secondary residual-bootstrap sensitivity |
| A12 | Required skill per ticket | Derived from training-period category mapping only | recorded in replay fixtures |

## Known contamination in A11

The empirical duration includes whatever queueing the ticket historically
suffered, so it is an upper bound on pure handling time. A replay that treats it
as pure service time overstates service and understates the benefit of *any*
scheduling policy — including the proposed one.

It therefore biases **against** the proposed policy, which makes it the
conservative choice rather than a flattering one. Stated in `limitations.md` and
required in the report.

## Engine pipeline only — not used by the service desk

Hardware ageing alpha, workstation ages, degradation threshold, purchase/scrap
economics, capacity cost per agent, routing overhead matrix, support-centre
capacities. All were invented. None supply any number in the application.
