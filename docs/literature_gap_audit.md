# Literature gap audit

Purpose: decide what this project may honestly claim. A negative novelty finding
is an acceptable outcome and is better than a false claim.

**Status: IN PROGRESS.** The structural finding below is settled. The
reproducible search for prior UCI-498 routing/SLA work is not yet done and
gates the final contribution sentence.

## Settled finding: UCI-498 cannot support the task the reviewed papers perform

All eight papers in `docs/papers/literature_review_papers/` perform **ticket text
classification**:

| Paper | Method | Input |
|---|---|---|
| Fuchs 2022 | review; RF and SVM best-performing | ticket text |
| Schmidt 2022 | hybrid-intelligence requirements | ticket text workflows |
| Ahmed 2023 | systematic review, 563 studies | ticket text |
| Crosley 2023 | IndoBERT + Random Forest | ticket text |
| Liu 2023 (Ticket-BERT) | fine-tuned BERT + active learning | title/description/updates |
| Ferreira 2025 | CROSS recommender + AutoML | procedure text |
| Islam 2025 | R preprocessing, stopwords/stemming | ticket text |
| Razma 2026 | TF-IDF + LR, mBERT, XLM-R | multilingual ticket text |

**UCI-498 has no ticket text column.** No `description`, no
`short_description` — structured fields, identifiers and timestamps only
(verified in `data/reports/uci498_audit.md`).

This is the important framing point. The pivot away from text classification is
**forced by the data**, not chosen for convenience. It converts "this project
does not contain a transformer" from an apparent weakness into a dataset-level
constraint, and it is the cleanest justification for positioning the
contribution downstream of prediction rather than inside it.

## The gap this project targets

Every reviewed paper stops at *predict the label*. None evaluate what is done
with the prediction. The comparison document's own takeaway #4 already names the
gap:

> "Treat routing as a separate constrained decision: combine predicted
> category/priority with team skill, workload, availability and SLA time
> remaining."

None of the eight evaluate an auditable dispatch policy against disclosed
routing baselines. None address hardware or asset lifecycle economics.

Provisional contribution statement, to be finalised after the search below:

> A leakage-controlled, reproducible evaluation of an auditable SLA-risk-aware
> dispatch policy against disclosed routing baselines on a public ServiceNow
> event log.

Positioned as an **implementation and evaluation** contribution, not an
algorithmic novelty claim.

## Required action: rewrite the comparison document's conclusion

`docs/papers/literature_review_comparison.md` currently closes by recommending
transformers, macro-F1 and active learning — a project that was not built and
that this dataset cannot support. Read top to bottom, the literature review
argues against its own project.

Its "Cross-paper takeaways" section must be replaced with an explicit gap
statement plus a *this project vs. prior work* row. This is a documentation
defect with direct marks attached, not a stylistic preference.

## Outstanding: reproducible search for prior UCI-498 work

Initial web results already show UCI-498 used for SLA and remaining-time
prediction. **Do not claim that using this dataset, predicting SLA outcomes, or
publishing a benchmark is inherently new.**

Record each candidate in the table below.

| Search date | Database | Query | Paper / DOI | Split & label treatment | Task | Routing or replay policy | Baselines & metrics | Overlap with this project |
|---|---|---|---|---|---|---|---|---|
| _(to complete)_ | | | | | | | | |

Suggested queries: `"incident management process enriched event log"`,
`UCI 498 incident SLA prediction`, `ServiceNow event log remaining time
prediction`, `SLA-aware ticket dispatch simulation`, `predictive process
monitoring incident routing`.

### Decision rules

- Prior work predicts SLA but does not evaluate an auditable dispatch policy →
  position as an implementation/evaluation gap. **(Expected outcome.)**
- Prior work already runs comparable SLA-aware dispatch replays on UCI-498 → do
  not claim a novel benchmark; limit the contribution to a transparent
  implementation and its documented results.
- A close work contains the same policy and evaluation → change the research
  claim before the viva.

## Banned language

Do not write, in the report, the paper, or the product: `novel`,
`state-of-the-art`, `patentable`, `guaranteed SLA reduction`, `proven causal
improvement`, `AI chooses the best employee`, `optimal enterprise outcome`.
