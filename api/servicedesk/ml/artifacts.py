"""Saving and loading a model artifact, with the card and metrics beside it.

An artifact is a directory: ``models/<name>/<version>/`` holding
``model.joblib``, ``metrics.json`` and ``model_card.md``. The joblib payload is
a dict rather than a bare estimator, because a fitted estimator alone cannot
answer "which data, which schema, which split?" — and the API has to refuse a
model whose feature schema no longer matches the request it is scoring.
"""
import json
import os
from datetime import datetime, timezone

import joblib

MODELS_DIR = "models"


def artifact_dir(name: str, version: str) -> str:
    return os.path.join(MODELS_DIR, name, version)


def save_artifact(name, version, estimator, metadata, metrics, model_card):
    """Write the three files that make a model usable and auditable."""
    target = artifact_dir(name, version)
    os.makedirs(target, exist_ok=True)

    payload = dict(metadata)
    payload["estimator"] = estimator
    payload["saved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    joblib.dump(payload, os.path.join(target, "model.joblib"))

    with open(os.path.join(target, "metrics.json"), "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=2, sort_keys=True)
    with open(os.path.join(target, "model_card.md"), "w", encoding="utf-8") as fh:
        fh.write(model_card)
    return target


def load_artifact(name, version):
    """Load one artifact. Missing files fail here, not at scoring time."""
    target = artifact_dir(name, version)
    payload = joblib.load(os.path.join(target, "model.joblib"))
    with open(os.path.join(target, "metrics.json"), encoding="utf-8") as fh:
        payload["metrics"] = json.load(fh)
    return payload


def latest_version(name):
    """The newest version directory by name, or None when nothing is trained.

    Versions are dated and suffixed (``uci-risk-2026-09-10-a1``), so lexical
    order is chronological order — until an eleventh same-day retrain, where
    ``a10`` would sort before ``a2``. Pass an explicit version if that day ever
    arrives.
    """
    root = os.path.join(MODELS_DIR, name)
    if not os.path.isdir(root):
        return None
    versions = sorted(
        d for d in os.listdir(root)
        if os.path.isfile(os.path.join(root, d, "model.joblib"))
    )
    return versions[-1] if versions else None
