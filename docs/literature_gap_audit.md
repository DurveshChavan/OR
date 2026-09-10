# Literature gap audit

Purpose: decide what this project may honestly claim. A negative novelty finding
is an acceptable outcome and is better than a false claim.

**Status: COMPLETE (search run 2026-09-10).** The structural finding below was
already settled. The reproducible search for prior UCI-498 routing and SLA work
has now been run, is recorded in full below with its own limits stated, and
decision rule 1 applies: the contribution is positioned as an implementation
and evaluation gap.

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

## Required action: rewrite the comparison document's conclusion — DONE 2026-09-10

`docs/papers/literature_review_comparison.md` currently closes by recommending
transformers, macro-F1 and active learning — a project that was not built and
that this dataset cannot support. Read top to bottom, the literature review
argues against its own project.

Its "Cross-paper takeaways" section must be replaced with an explicit gap
statement plus a *this project vs. prior work* row. This is a documentation
defect with direct marks attached, not a stylistic preference.

## The reproducible search for prior UCI-498 work

**Run 2026-09-10.** Tool: web search only. This is the honest limit of it: no
paywalled bibliographic database (Scopus, Web of Science, ACM DL, IEEE Xplore)
was queried, and no citation graph was walked. A closer work behind a paywall
would not have been seen. The queries and what came back are below so the
search can be repeated and corrected.

### Queries run

```
"incident management process enriched event log" UCI SLA prediction machine learning
ServiceNow incident event log remaining time prediction predictive process monitoring UCI 498
SLA-aware ticket dispatch policy simulation replay evaluation incident routing baselines FIFO priority
Amaral "incident management process" event log SLA violation prediction paper 2018 2020
"incident_event_log" UCI dataset "made_sla" prediction classification github kaggle
agent assignment optimization IT service desk event log counterfactual simulation Hungarian algorithm SLA breach ticket allocation research
```

### What the search found

| Date | Source | Work | Task | Label / split treatment | Routing or replay policy | Baselines and metrics | Overlap with this project |
|---|---|---|---|---|---|---|---|
| 2026-09-10 | UCI ML Repository | Amaral, Fantinato & Peres — the dataset itself (DOI 10.24432/C57S4H) | dataset publication; documented as supporting completion-time prediction, `closed_at` named as the dependent variable for it | dataset documentation only | none | none | **Dataset overlap, and one methodological disagreement.** The documentation points completion-time work at `closed_at`; this project's audit rejects `closed_at` as a ~5-day auto-close artefact and uses `resolved_at - opened_at`. That divergence is recorded in `data_provenance.md`. |
| 2026-09-10 | AITM / ISM 2018–2019 | Amaral et al., *Enhancing Completion Time Prediction Through Attribute Selection*; *Attribute Selection with Filter and Wrapper* | completion-time prediction, attribute selection | not inspected in full text | none | attribute-selection comparison | **Prediction on the same log already exists.** Nothing here claims otherwise. No dispatch policy is evaluated. |
| 2026-09-10 | GitHub / Medium | `apratimnath/incident-analysis`, `san-git/ML-Incident-Management`, several write-ups | priority prediction, close-code prediction, volume forecasting, `made_sla` classification | notebook-level, splits not disclosed | none | accuracy / F1, e.g. SVM ~95% accuracy, RF F1 ~0.75 reported | **`made_sla` classification on this log already exists in public code.** Not peer-reviewed and not leakage-controlled, but sufficient to make "predicting SLA outcomes on UCI-498 is new" an untenable claim. |
| 2026-09-10 | arXiv | Verenich et al., *Survey and cross-benchmark comparison of remaining time prediction methods* (1805.02896), and related predictive-process-monitoring work | remaining-time prediction across benchmark logs | chronological protocols standard in that literature | none | regression error metrics | **Method overlap on the prediction half.** The replay half has no counterpart there. |
| 2026-09-10 | Journal / industry | SLA-aware scheduling work outside ITSM, e.g. DRL edge-cloud task scheduling against FIFO / round-robin / EDF | task scheduling | synthetic and trace-driven clusters | yes, but in a different domain | SLA violation, latency, energy | **Policy-comparison shape is not new in general.** It is not this dataset, not a service desk, and not an auditable per-decision record. |
| 2026-09-10 | Vendor material | ITSM vendor pages on SLA-breach prediction and smart routing | product descriptions | undisclosed | proprietary | undisclosed | **No reproducible baseline.** Cited only to show the industrial framing exists; nothing is comparable. |

### What was not found

No work was found that replays UCI-498 as a dispatch problem: no exogenous job
list built from that log, no comparison of FIFO, priority-only, duration-first
and an SLA-risk-aware policy on it, and no per-decision audit record. Absence in
a web-only search is weak evidence, and it is reported as weak evidence.

### Decision, under the rules below

Rule 1 applies. Prior work predicts on this log and does not evaluate an
auditable dispatch policy on it, so the contribution is an **implementation and
evaluation** contribution. Two claims are therefore forbidden and are not made
anywhere in this project:

1. that using UCI-498 is new;
2. that predicting SLA outcomes on it is new.

### Final contribution statement

> A leakage-controlled, reproducible evaluation of an auditable SLA-risk-aware
> dispatch policy against disclosed routing baselines on a public ServiceNow
> event log, reported with its null results.

The last four words are load-bearing and were added after the replay ran. The
evaluation found that the risk score contributed nothing measurable to simulated
breach rate, and that under severe scarcity the proposed policy loses to
shortest-job-first. A contribution sentence that omitted them would describe a
different project.

### Decision rules

- Prior work predicts SLA but does not evaluate an auditable dispatch policy →
  position as an implementation/evaluation gap. **(This is the outcome.)**
- Prior work already runs comparable SLA-aware dispatch replays on UCI-498 → do
  not claim a novel benchmark; limit the contribution to a transparent
  implementation and its documented results.
- A close work contains the same policy and evaluation → change the research
  claim before the viva.

## Banned language

Do not write, in the report, the paper, or the product: `novel`,
`state-of-the-art`, `patentable`, `guaranteed SLA reduction`, `proven causal
improvement`, `AI chooses the best employee`, `optimal enterprise outcome`.
