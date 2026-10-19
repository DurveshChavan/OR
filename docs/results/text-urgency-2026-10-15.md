# Text urgency from public ticket data — `text-urgency-2026-10-15`

Reproduce with `python -m api.servicedesk.eval.text_urgency`. Metrics: `docs\results\text-urgency-2026-10-15.json`.

**Question.** UCI-498 has no ticket text, so the breach-risk model reads none. The one
route from a caller's words into that model is `urgency`, a field it was fitted on. Can a
classifier trained on public ticket text suggest urgency well enough for a dispatcher to
be shown the suggestion?

**Answer: no, on the data that exists publicly.** No text model ships, the new-ticket form
asks a person for impact and urgency, and priority is derived from them.

## Data

- real: M. Abdellatif, Help Desk Tickets, Mendeley Data v3, doi:10.17632/btm76zndnt.3, CC BY 4.0. 357 issues with reporter-written text,
  54.3% high urgency (Blocker, Highest or High). Low is 9 rows, so the label is binary.
- synthetic: T. Bueck, customer-support-tickets (Hugging Face), synthetic, CC BY-NC 4.0. 16,338 English tickets.
- both pinned by revision and SHA-256 (`data\manifests\ticket_text.json`); neither is committed.

## 1. Real tickets, cross-validated

TF-IDF over words and word pairs → logistic regression (`C=1.0`, not tuned).
5 repeats × 5 outer folds; the alert threshold is chosen inside each outer fold
from 5-fold out-of-fold predictions on its training part, by the rule declared first:
the lowest threshold with precision ≥ 0.80.

| ROC-AUC | PR-AUC | Precision at threshold | Recall at threshold |
|---:|---:|---:|---:|
| 0.725 ± 0.045 | 0.776 ± 0.035 | 0.818 ± 0.078 | 0.399 ± 0.092 |

## 2. Holding each client out whole

The 357 issues come from 119 client projects, and clients differ in how often they file
high-priority work. With `GroupKFold` on the project, so no client is on both sides of a split,
ROC-AUC falls to **0.665** (folds: 0.640, 0.704, 0.573, 0.689, 0.719). Part of the
number above was the model recognising clients.

## 3. What it reads

Strongest words toward high urgency: `dears`, `transaction`, `note`, `mobile`, `dears kindly`, `kindly note`, `that`, `note that`, `default`, `mobile number`, `customer`, `set`.

Strongest toward not-high: `to be`, `greetings kindly`, `in`, `greetings`, `for`, `time`, `password`, `behalf`, `team`, `issues`, `on behalf`, `users`.

Several are salutations and phrasing habits — how a particular reporter writes — and the
content words among them name this one company's product (transactions, mobile numbers)
rather than how badly anything is broken. A model reading them suggests urgency partly by
who is writing, which section 2 measures, and a different desk's tickets give it little to
recognise. Words a reader would expect to matter carry these weights:
`critical` -0.00, `blocked` +0.00, `down` +0.06, `urgent` +0.32,
against +0.98 for the strongest word above.

## 4. Synthetic tickets do not transfer

| Check | ROC-AUC |
|---|---:|
| trained on synthetic, scored on held-out synthetic | 0.790 |
| trained on synthetic, scored on the 357 real tickets | 0.451 |
| real training folds + all synthetic rows, real test folds | 0.675 |

0.5 is chance. The synthetic model learns its generator's idea of urgency, which real
tickets do not share, and adding synthetic rows to real training data makes the real-data
score worse.

## 5. Even the best number would not survive the desk's base rate

The section-1 operating point was measured where 54% of tickets are high urgency. In
UCI-498 urgency 1 is 395 of 23,323 incidents (1.7%). The false-positive rate does not
move with prevalence, so there the same model would flag 11.1% of tickets at a precision
of about 6.1%, and every wrong flag would raise an impact-2 ticket to priority 2.

## What this decides

- Title and description are stored and shown; no model reads them.
- Impact and urgency are entered by a person, priority is derived by the ITIL matrix
  `priority = min(4, impact + urgency − 1)`, and all three reach the risk model.
- What would change the answer: labelled text from a real IT desk — titles or descriptions
  with the urgency an agent assigned. This script runs unchanged on such a file once it is
  loaded in place of the real set above.
- Nothing here claims ticket-text classification is new: every paper in the project's
  literature review does it. The finding is that public data does not support it for this desk.
