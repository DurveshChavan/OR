"""Can public ticket text teach a model to suggest urgency? Measured: no.

    python -m api.servicedesk.eval.text_urgency

UCI-498 has no ticket text, so the breach-risk model cannot read a title or a
description. The one route from text into that model is ``urgency``, a field it
was fitted on: if a classifier could suggest urgency from what a caller wrote, a
dispatcher could confirm it and the confirmed value would reach the risk model
through the ITIL priority matrix. This script tests whether the public data
supports such a classifier. It writes a results page and a metrics file, and
no model: neither candidate is fit to put a suggestion in front of a dispatcher.

Data:

* **Real tickets.** Mendeley Data "Help Desk Tickets" v3 (M. Abdellatif,
  CC BY 4.0, doi:10.17632/btm76zndnt.3), the 357 issues with reporter-written
  text, via the processed mirror ``tasksource/help-desk-tickets``. One software
  company's tracker, masked by the source authors (``ph_*`` tokens).
* **Synthetic tickets.** ``Tobi-Bueck/customer-support-tickets``
  (CC BY-NC 4.0), 16,338 English LLM-generated tickets.

Label: a ticket is *high urgency* when its priority is Blocker, Highest or High
(real) or high (synthetic). Three classes are not learnable on the real set,
where Low is 9 of 357 rows.

What is measured, in order:

1. nested cross-validation on the real tickets, 5 repeats x 5 outer folds, with
   the alert threshold chosen inside each outer fold from inner out-of-fold
   predictions by a rule declared first (precision >= 0.80);
2. the same model under ``GroupKFold`` on the client project, so no client's
   tickets sit on both sides of a split;
3. the model's strongest features, because a score is only as good as what
   it reads;
4. a model trained on the synthetic tickets, scored on the real ones, and the
   real folds retrained with the synthetic rows added.
"""
import hashlib
import json
import os
import urllib.request

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score
from sklearn.model_selection import GroupKFold, StratifiedKFold
from sklearn.pipeline import Pipeline

RUN_ID = "text-urgency-2026-10-15"
SEED = 20261015
RAW_DIR = os.path.join("data", "raw", "ticket_text")
MANIFEST_PATH = os.path.join("data", "manifests", "ticket_text.json")
RESULTS_PAGE = os.path.join("docs", "results", RUN_ID + ".md")
RESULTS_JSON = os.path.join("docs", "results", RUN_ID + ".json")

#: Pinned revisions, so a dataset changing under the same name cannot move a
#: number on the results page without anyone deciding it should.
DATASETS = {
    "real": {
        "path": os.path.join(RAW_DIR, "mendeley_reporter_messages.parquet"),
        "url": "https://huggingface.co/datasets/tasksource/help-desk-tickets/resolve/"
               "d08adc88a5d39b938da00dc837ac613d9be02153/reporter_messages/train.parquet",
        "sha256": "a5fc8920beaaece20c0e7ae6da7583dfe9d91353a1b0807aa9b3a3028fbc2360",
        "citation": "M. Abdellatif, Help Desk Tickets, Mendeley Data v3, "
                    "doi:10.17632/btm76zndnt.3, CC BY 4.0",
    },
    "synthetic": {
        "path": os.path.join(RAW_DIR, "tobi_bueck_tickets.csv"),
        "url": "https://huggingface.co/datasets/Tobi-Bueck/customer-support-tickets/resolve/"
               "ddf1c81a5475992c4fa6752bf1e8b4e31f07bbeb/"
               "aa_dataset-tickets-multi-lang-5-2-50-version.csv",
        "sha256": "f187c090e59581c2bbf3aa1377c8db4dd647464ecf2ae51bf8966e42e0ed6bc0",
        "citation": "T. Bueck, customer-support-tickets (Hugging Face), synthetic, "
                    "CC BY-NC 4.0",
    },
}

HIGH_PRIORITIES = ("Blocker", "Highest", "High")
TARGET_PRECISION = 0.80
#: Not tuned: with 357 rows a grid over C would be fitted to fold noise.
REGULARISATION_C = 1.0
OUTER_FOLDS, INNER_FOLDS, REPEATS = 5, 5, 5
#: UCI-498's urgency mix over the 23,323 prepared incidents: 185 + 210 at
#: urgency 1. Used only to carry the operating point to that base rate.
UCI_URGENCY_HIGH, UCI_INCIDENTS = 395, 23323


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch():
    """Download each pinned file once, then refuse it unless its hash matches."""
    os.makedirs(RAW_DIR, exist_ok=True)
    for name, spec in DATASETS.items():
        if not os.path.exists(spec["path"]):
            print(f"downloading {name} -> {spec['path']}")
            urllib.request.urlretrieve(spec["url"], spec["path"])
        actual = sha256(spec["path"])
        if actual != spec["sha256"]:
            raise RuntimeError(f"{spec['path']} hash {actual} != pinned {spec['sha256']}")
    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as fh:
        json.dump(DATASETS, fh, indent=2, sort_keys=True)


def load_real():
    frame = pd.read_parquet(DATASETS["real"]["path"])
    return (frame["text"].fillna("").to_numpy(),
            frame["issue_priority"].isin(HIGH_PRIORITIES).to_numpy(),
            frame["issue_proj"].to_numpy())


def load_synthetic():
    frame = pd.read_csv(DATASETS["synthetic"]["path"])
    frame = frame[frame["language"] == "en"]
    text = frame["subject"].fillna("") + " . " + frame["body"].fillna("")
    return text.to_numpy(), (frame["priority"] == "high").to_numpy()


def build_estimator():
    """TF-IDF over words and word pairs, then logistic regression.

    The token pattern keeps alphabetic tokens of two or more letters and drops
    the source's ``ph_*`` masking tokens, which no live ticket would contain.
    """
    return Pipeline([
        ("tfidf", TfidfVectorizer(
            lowercase=True, token_pattern=r"(?u)\b(?!ph_)[^\W\d_]{2,}\b",
            ngram_range=(1, 2), min_df=2, sublinear_tf=True)),
        ("logistic", LogisticRegression(C=REGULARISATION_C, max_iter=3000)),
    ])


def threshold_for_precision(labels, scores, target=TARGET_PRECISION):
    """The lowest threshold whose precision reaches `target` (most recall kept).

    If none reaches it, the threshold of highest precision.
    """
    precision, _recall, thresholds = precision_recall_curve(labels, scores)
    precision = precision[:-1]  # the final point has no threshold
    meeting = np.flatnonzero(precision >= target)
    return float(thresholds[meeting[0] if len(meeting) else int(np.argmax(precision))])


def out_of_fold(texts, labels, seed):
    scores = np.zeros(len(labels))
    for train, held in StratifiedKFold(INNER_FOLDS, shuffle=True, random_state=seed).split(texts, labels):
        scores[held] = build_estimator().fit(texts[train], labels[train]).predict_proba(texts[held])[:, 1]
    return scores


def nested_cv(texts, labels):
    rows = []
    for repeat in range(REPEATS):
        outer = StratifiedKFold(OUTER_FOLDS, shuffle=True, random_state=SEED + repeat)
        for train, test in outer.split(texts, labels):
            threshold = threshold_for_precision(
                labels[train], out_of_fold(texts[train], labels[train], SEED + repeat))
            scores = build_estimator().fit(texts[train], labels[train]).predict_proba(texts[test])[:, 1]
            flagged = scores >= threshold
            hits = int((flagged & labels[test]).sum())
            rows.append({
                "roc_auc": roc_auc_score(labels[test], scores),
                "pr_auc": average_precision_score(labels[test], scores),
                "threshold": threshold,
                "precision": hits / flagged.sum() if flagged.sum() else 0.0,
                "recall": hits / labels[test].sum(),
            })
    frame = pd.DataFrame(rows)
    return {column: {"mean": float(frame[column].mean()), "sd": float(frame[column].std())}
            for column in frame.columns}


def grouped_cv(texts, labels, groups):
    """ROC-AUC with every client project held out whole."""
    scores = []
    for train, test in GroupKFold(OUTER_FOLDS).split(texts, labels, groups):
        model = build_estimator().fit(texts[train], labels[train])
        scores.append(roc_auc_score(labels[test], model.predict_proba(texts[test])[:, 1]))
    return {"folds": [float(s) for s in scores], "mean": float(np.mean(scores)),
            "projects": int(len(set(groups)))}


#: Words a reader would expect an urgency model to lean on, reported beside the
#: words it actually leans on.
EXPECTED_WORDS = ("critical", "blocked", "down", "urgent")


def strongest_features(texts, labels, count=12):
    model = build_estimator().fit(texts, labels)
    names = list(model.named_steps["tfidf"].get_feature_names_out())
    weights = model.named_steps["logistic"].coef_[0]
    order = np.argsort(weights)
    pick = lambda idx: [[str(names[i]), round(float(weights[i]), 2)] for i in idx]
    return {"toward_high": pick(order[::-1][:count]), "toward_not_high": pick(order[:count]),
            "expected_words": {w: round(float(weights[names.index(w)]), 2) if w in names else None
                               for w in EXPECTED_WORDS}}


def synthetic_transfer(real_texts, real_labels):
    syn_texts, syn_labels = load_synthetic()
    held = np.random.default_rng(SEED).random(len(syn_labels)) < 0.2
    model = build_estimator().fit(syn_texts[~held], syn_labels[~held])
    mixed = []
    for train, test in StratifiedKFold(OUTER_FOLDS, shuffle=True, random_state=SEED).split(real_texts, real_labels):
        both = build_estimator().fit(np.concatenate([real_texts[train], syn_texts]),
                                     np.concatenate([real_labels[train], syn_labels]))
        mixed.append(roc_auc_score(real_labels[test], both.predict_proba(real_texts[test])[:, 1]))
    return {
        "synthetic_rows": int(len(syn_labels)),
        "synthetic_held_out_roc_auc": roc_auc_score(syn_labels[held], model.predict_proba(syn_texts[held])[:, 1]),
        "real_roc_auc_trained_on_synthetic": roc_auc_score(real_labels, model.predict_proba(real_texts)[:, 1]),
        "real_roc_auc_real_plus_synthetic": float(np.mean(mixed)),
    }


def at_prevalence(precision, recall, source_rate, target_rate):
    """Carry an operating point to another base rate.

    The false-positive rate does not move with prevalence:
    FPR = recall x pi/(1 - pi) x (1 - precision)/precision at the source rate pi.
    At a new rate q, precision = recall x q / (recall x q + FPR x (1 - q)).
    """
    fpr = recall * source_rate / (1 - source_rate) * (1 - precision) / precision
    true_flags, false_flags = recall * target_rate, fpr * (1 - target_rate)
    return {"precision": true_flags / (true_flags + false_flags),
            "flagged_share": true_flags + false_flags}


def write_page(results):
    nested, grouped, transfer = results["nested_cv"], results["grouped_cv"], results["synthetic_transfer"]
    carried, features = results["uci_carryover"], results["strongest_features"]
    cell = lambda name: f"{nested[name]['mean']:.3f} ± {nested[name]['sd']:.3f}"
    words = lambda pairs: ", ".join(f"`{w}`" for w, _ in pairs)
    return f"""# Text urgency from public ticket data — `{RUN_ID}`

Reproduce with `python -m api.servicedesk.eval.text_urgency`. Metrics: `{RESULTS_JSON}`.

**Question.** UCI-498 has no ticket text, so the breach-risk model reads none. The one
route from a caller's words into that model is `urgency`, a field it was fitted on. Can a
classifier trained on public ticket text suggest urgency well enough for a dispatcher to
be shown the suggestion?

**Answer: no, on the data that exists publicly.** No text model ships, the new-ticket form
asks a person for impact and urgency, and priority is derived from them.

## Data

- real: {DATASETS['real']['citation']}. 357 issues with reporter-written text,
  {results['base_rate']:.1%} high urgency (Blocker, Highest or High). Low is 9 rows, so the label is binary.
- synthetic: {DATASETS['synthetic']['citation']}. {transfer['synthetic_rows']:,} English tickets.
- both pinned by revision and SHA-256 (`{MANIFEST_PATH}`); neither is committed.

## 1. Real tickets, cross-validated

TF-IDF over words and word pairs → logistic regression (`C={REGULARISATION_C}`, not tuned).
{REPEATS} repeats × {OUTER_FOLDS} outer folds; the alert threshold is chosen inside each outer fold
from {INNER_FOLDS}-fold out-of-fold predictions on its training part, by the rule declared first:
the lowest threshold with precision ≥ {TARGET_PRECISION:.2f}.

| ROC-AUC | PR-AUC | Precision at threshold | Recall at threshold |
|---:|---:|---:|---:|
| {cell('roc_auc')} | {cell('pr_auc')} | {cell('precision')} | {cell('recall')} |

## 2. Holding each client out whole

The 357 issues come from {grouped['projects']} client projects, and clients differ in how often they file
high-priority work. With `GroupKFold` on the project, so no client is on both sides of a split,
ROC-AUC falls to **{grouped['mean']:.3f}** (folds: {', '.join(f'{s:.3f}' for s in grouped['folds'])}). Part of the
number above was the model recognising clients.

## 3. What it reads

Strongest words toward high urgency: {words(features['toward_high'])}.

Strongest toward not-high: {words(features['toward_not_high'])}.

Several are salutations and phrasing habits — how a particular reporter writes — and the
content words among them name this one company's product (transactions, mobile numbers)
rather than how badly anything is broken. A model reading them suggests urgency partly by
who is writing, which section 2 measures, and a different desk's tickets give it little to
recognise. Words a reader would expect to matter carry these weights:
{', '.join(f"`{w}` {v:+.2f}" if v is not None else f"`{w}` (not in vocabulary)" for w, v in features['expected_words'].items())},
against {features['toward_high'][0][1]:+.2f} for the strongest word above.

## 4. Synthetic tickets do not transfer

| Check | ROC-AUC |
|---|---:|
| trained on synthetic, scored on held-out synthetic | {transfer['synthetic_held_out_roc_auc']:.3f} |
| trained on synthetic, scored on the 357 real tickets | {transfer['real_roc_auc_trained_on_synthetic']:.3f} |
| real training folds + all synthetic rows, real test folds | {transfer['real_roc_auc_real_plus_synthetic']:.3f} |

0.5 is chance. The synthetic model learns its generator's idea of urgency, which real
tickets do not share, and adding synthetic rows to real training data makes the real-data
score worse.

## 5. Even the best number would not survive the desk's base rate

The section-1 operating point was measured where {results['base_rate']:.0%} of tickets are high urgency. In
UCI-498 urgency 1 is {UCI_URGENCY_HIGH} of {UCI_INCIDENTS:,} incidents ({UCI_URGENCY_HIGH / UCI_INCIDENTS:.1%}). The false-positive rate does not
move with prevalence, so there the same model would flag {carried['flagged_share']:.1%} of tickets at a precision
of about {carried['precision']:.1%}, and every wrong flag would raise an impact-2 ticket to priority 2.

## What this decides

- Title and description are stored and shown; no model reads them.
- Impact and urgency are entered by a person, priority is derived by the ITIL matrix
  `priority = min(4, impact + urgency − 1)`, and all three reach the risk model.
- What would change the answer: labelled text from a real IT desk — titles or descriptions
  with the urgency an agent assigned. This script runs unchanged on such a file once it is
  loaded in place of the real set above.
- Nothing here claims ticket-text classification is new: every paper in the project's
  literature review does it. The finding is that public data does not support it for this desk.
"""


def main():
    fetch()
    texts, labels, groups = load_real()
    results = {
        "base_rate": float(labels.mean()),
        "nested_cv": nested_cv(texts, labels),
        "grouped_cv": grouped_cv(texts, labels, groups),
        "strongest_features": strongest_features(texts, labels),
        "synthetic_transfer": synthetic_transfer(texts, labels),
    }
    results["uci_carryover"] = at_prevalence(
        results["nested_cv"]["precision"]["mean"], results["nested_cv"]["recall"]["mean"],
        results["base_rate"], UCI_URGENCY_HIGH / UCI_INCIDENTS)
    with open(RESULTS_JSON, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, sort_keys=True)
    with open(RESULTS_PAGE, "w", encoding="utf-8") as fh:
        fh.write(write_page(results))
    print(f"wrote {RESULTS_PAGE}")
    print(f"  nested auc={results['nested_cv']['roc_auc']['mean']:.3f} "
          f"grouped auc={results['grouped_cv']['mean']:.3f} "
          f"synthetic->real auc={results['synthetic_transfer']['real_roc_auc_trained_on_synthetic']:.3f}")
    return results


if __name__ == "__main__":
    main()
