# Literature Review: AI-Powered Support Ticket Management

Search scope: Google Scholar and Google, filtered to 2022-2026. The eight PDFs in `literature_review_papers/` were opened and title-page checked before inclusion.

| Title & year | Authors | ML model used | Key features relevant to the project | Accuracy / performance | Limitations / research gaps |
|---|---|---|---|---|---|
| *Improving Support Ticket Systems Using Machine Learning: A Literature Review* (2022) | Simon Fuchs; Clemens Drieschner; Holger Wittges | Review of ML approaches; Random Forest and SVM are identified as the most frequently best-performing classifiers | Covers incident management, escalation, sentiment prediction, classification and ticket-system automation | Qualitative synthesis; no common benchmark or single accuracy value | Fragmented evidence and heterogeneous datasets/metrics; little standardised evaluation across ticket systems |
| *Requirements for an IT Support System Based on Hybrid Intelligence* (2022) | Simon L. Schmidt; Mahei Manhai Li; Christoph Peters | Hybrid intelligence architecture (human + AI); no single trained classifier evaluated | Derives design requirements for classification, routing, chatbots, solution recommendations and human hand-off | 24 consolidated requirements from 17 literature-based and 21 interview-based requirements | Requirements/design research, not a deployed-model evaluation; classification and routing quality remain to be validated in production |
| *A Systematic Review of AI and Machine Learning-Driven IT Support Systems: Enhancing Efficiency and Automation in Technical Service Management* (2023) | Shahan Ahmed; Anisur Rahman; Md. Ashrafuzzaman | Systematic review of ML, NLP, predictive maintenance, sentiment analysis and virtual assistants | Reviews intelligent ticketing, prioritisation, routing and SLA-oriented service management across 563 studies | Reports aggregated claims: 50-60% improvement in ticket-classification accuracy and 30-40% fewer misclassifications | Review-level claims rather than a reproducible ticket benchmark; reported percentages should be treated as secondary evidence |
| *Improving IT Support Efficiency Using AI-Driven Ticket Random Forest Classification Technique* (2023) | Nathaniel Crosley; Ito Wasito | IndoBERT-assisted text understanding + Random Forest (100 trees) | GLPI ticket data (>1,000 tickets); text plus urgency, impact and expertise features; 3x3 priority matrix | Uses confusion matrices, accuracy, precision, recall and F1; no single consolidated score is reported | Single-company dataset; class imbalance and coarse 3x3 matrix; authors recommend more data, continuous training and a more granular 5x5 priority scheme |
| *Ticket-BERT: Labeling Incident Management Tickets with Language Models* (2023) | Zhexiong Liu; Cris Benge; Siduo Jiang | Fine-tuned Ticket-BERT with active learning; compared against Naive Bayes, Logistic Regression and Microsoft Language Studio | Large Azure incident-ticket datasets; multi-class label prediction from ticket title/description/updates; deployable active-learning loop | Macro F1: 85.90% (human-written), 98.19% (machine-written), 98.24% (mixed); about 90% accuracy on hard-to-identify tickets | Dependent on Azure IcM data and labels; active-learning improvements were ongoing rather than fully reported; domain transfer needs validation |
| *Intelligent Ticket Management Assistant for Helpdesk Operations* (2025) | Leonardo Silva Ferreira | Context-aware recommender system (CROSS), synthetic-data generator (SNOOKER), FEDOT AutoML forecasting | Recommends fastest analyst-procedure pair, supports prioritisation/scheduling, forecasting and workforce planning while protecting sensitive data | Recommendation time remains below 0.656 s in the largest reported configuration; evaluates forecast error with MAE/RMSE/MAPE | Cybersecurity-helpdesk setting; artificial data is necessary because detailed real resolution data is restricted; AutoML reproducibility and production integration remain open issues |
| *Automated Data Classification and Pre-Processing of IT Service Tickets for Future Machine Learning Predictions* (2025) | Faraz Islam; Tasneem Ahmed | R-based data preprocessing and feature preparation; no final classifier comparison | Cleans ServiceDesk Plus / SQL ticket exports: language filtering, deduplication, stopword removal, stemming and phrase-pattern analysis | Data-readiness study; no end-to-end classification accuracy is reported | Does not test downstream classifiers or routing/SLA outcomes; needs a labelled benchmark and a direct ablation of preprocessing choices |
| *AI-Based Classification of IT Support Requests in Enterprise Service Management Systems* (2026) | Audrius Razma; Robertas Jurkus | TF-IDF + Logistic Regression, multilingual BERT and XLM-RoBERTa; random oversampling | Real enterprise ITSM data; multilingual tickets, class imbalance, request-type/team classification and deployment-cost comparison | On a naturally imbalanced test set: transformer macro F1 0.49-0.51 vs. LR 0.39; accuracy approximately 0.82-0.84. Oversampling lifts mBERT macro F1 from about 0.49 to 0.51 without raising overall accuracy | Still based on one enterprise setting; transformers increase compute/memory cost; oversampling helps rare classes but should not be mistaken for a deployment-time accuracy gain |

## What these eight papers have in common, and what this project does instead

Every paper above stops at **predict the label**. Seven of the eight take ticket
text as their input; the eighth is a preprocessing study for the same task. None
of them evaluates what is done with the prediction once it exists: no dispatch
policy, no comparison against disclosed routing baselines, no per-decision
record a reviewer could audit afterwards.

**This project cannot perform the task these papers perform, and the reason is
the dataset, not a preference.** UCI-498 - the public ServiceNow event log this
project uses - has no free-text column. No `description`, no
`short_description`: structured fields, identifiers and timestamps only,
verified in `Project/data/reports/uci498_audit.md`. A transformer has nothing to
read here. The pivot away from text classification is forced by the data.

So the work sits downstream of the prediction the literature already does well.

| | These eight papers | This project |
|---|---|---|
| Input | ticket free text | structured fields available at ticket creation |
| Task | classify category, priority, team, or label | estimate SLA-breach risk, then decide who gets the ticket |
| Output evaluated | classifier metrics (accuracy, macro F1) | calibration and discrimination **plus** simulated dispatch outcomes |
| Decision layer | absent, or recommended as future work | tiered dispatch with Hungarian assignment over eligible WIP slots |
| Baselines | other classifiers | FIFO, priority-only, duration-first, and three ablations |
| Auditability | not addressed | immutable recommendation, append-only events, actor attribution |
| Honest limits | rarely reported as null results | null results reported: the risk score changed nothing measurable in the replay |

Ferreira (2025) is the closest of the eight, because CROSS recommends an
analyst-procedure pair rather than only a label. It is still not comparable
here: it runs on synthetic helpdesk data generated because real resolution data
was restricted, and it does not compare its recommendation against disclosed
routing baselines on a public log.

## The gap this project targets

None of the eight evaluates an auditable dispatch policy against disclosed
routing baselines on a public event log. That is the gap, and it is an
**implementation and evaluation** gap rather than an algorithmic one. The
contribution statement is fixed accordingly in
`Project/docs/literature_gap_audit.md`:

> A leakage-controlled, reproducible evaluation of an auditable SLA-risk-aware
> dispatch policy against disclosed routing baselines on a public ServiceNow
> event log, reported with its null results.

Two things this review must not be read as claiming, because a separate search
recorded in that audit found prior work doing both: using UCI-498 is not new,
and predicting SLA outcomes on it is not new.

## What was previously written here, and why it was removed

This section used to recommend a transformer classifier, macro-F1 reporting and
an active-learning label loop - a project that was never built and that this
dataset cannot support. Read top to bottom, the review argued against its own
project. The one recommendation that survived is the one this project acted on:

> "Treat routing as a separate constrained decision: combine predicted
> category/priority with team skill, workload, availability and SLA time
> remaining."
