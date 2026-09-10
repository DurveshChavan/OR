# Model card — handling duration `uci-duration-2026-09-10-a1`

Predicts elapsed minutes from `opened_at` to `resolved_at` for a ticket described only by what is known when it is created. The dispatch policy uses it for projected finish times.

## Data

- source: SHA-256 `f41dba115f5bae26…`, feature schema `incident-features-v1`
- incidents: train 16,326 | validation 3,498 | locked test 3,499
- target: `duration_minutes` = `resolved_at - opened_at`. `closed_at` is rejected: its gap from `resolved_at` is a fixed ~5-day auto-close timer, so a `closed_at` target would be largely constant.

## Method

- estimator: ridge regression on `log1p(minutes)`, `alpha=3.0`, `min_frequency=10`
- inverse transform: `max(0, expm1(prediction))`, with a test proving a negative minute cannot escape
- selection: median_absolute_error_minutes on validation only, over 12 candidates
- baseline: median duration by (priority, category), training period only, falling back to the priority median and then the overall median

## Results — minutes

### Validation period

| Model | Median abs. error | Mean abs. error | p90 abs. error | Median predicted |
|---|---:|---:|---:|---:|
| baseline (priority x category median) | 1,584.5 | 8,769.2 | 18,646.1 | 1,593.5 |
| ridge on log1p(minutes) | 879.8 | 8,403.4 | 18,061.6 | 655.8 |

Median actual duration in this period: 216.5 minutes.

### Test period

| Model | Median abs. error | Mean abs. error | p90 abs. error | Median predicted |
|---|---:|---:|---:|---:|
| baseline (priority x category median) | 1,581.5 | 8,198.0 | 17,840.4 | 1,593.5 |
| ridge on log1p(minutes) | 979.0 | 7,984.0 | 17,747.4 | 756.2 |

Median actual duration in this period: 201.0 minutes.

## Known limitations

- Logged elapsed time contains historical queue waiting. This is a handling-time proxy, not pure service time, and the replay inherits that limitation.
- The p90 absolute error is large in absolute terms because the target spans minutes to months. No per-ticket confidence interval is exposed, because none has been estimated.
- The model reads creation-time fields only. It cannot see that a ticket was reassigned four times, which is most of what makes a long incident long.
- No resolver identity is used. Agent speed multipliers are a separate, training-period residual calculation in the replay.
