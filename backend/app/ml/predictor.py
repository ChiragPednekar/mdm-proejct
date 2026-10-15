"""Load the active model and generate stored, explained predictions."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import joblib
import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.errors import ModelUnavailableError, NotFoundError
from app.ml.dataset import load_histories
from app.ml.features import FEATURE_LABELS, compute_features, unit_replaced_before
from app.ml.training import artifact_path
from app.models import FailurePrediction, ModelTrainingRun
from app.services import audit, settings_service

_cache: dict[str, tuple[float, dict]] = {}


def active_run(db: Session) -> ModelTrainingRun | None:
    return db.scalar(select(ModelTrainingRun).where(ModelTrainingRun.is_active))


def load_active_model(db: Session) -> tuple[ModelTrainingRun, dict]:
    """Return the deployed run and artifact, or raise ModelUnavailableError.

    There is deliberately NO fallback: without a compatible trained model the
    API reports the model as unavailable instead of inventing probabilities.
    """
    run = active_run(db)
    if run is None or not run.model_artifact_reference:
        raise ModelUnavailableError(
            "No trained failure-risk model is deployed. Train a model from the Model Performance page "
            "(or `python -m scripts.train_model`) once enough history exists."
        )
    path = artifact_path(run.model_artifact_reference)
    if not path.exists():
        raise ModelUnavailableError(f"Model artifact '{run.model_artifact_reference}' is missing; retrain the model.")
    mtime = path.stat().st_mtime
    cached = _cache.get(str(path))
    if cached is None or cached[0] != mtime:
        artifact = joblib.load(path)
        if artifact.get("model_version") != run.model_version:
            raise ModelUnavailableError("Model artifact does not match the registered model version.")
        _cache[str(path)] = (mtime, artifact)
    return run, _cache[str(path)][1]


def _proba(artifact: dict, rows: list[dict]) -> list[float]:
    X = pd.DataFrame(rows, columns=artifact["feature_columns"])
    return [float(p) for p in artifact["pipeline"].predict_proba(X)[:, 1]]


def explain(artifact: dict, features: dict, probability: float, top_k: int = 4) -> tuple[str, list[dict]]:
    """Local occlusion explanation: how much the probability changes when one
    feature is replaced by its typical (median / most common) value.

    These are associations learned by the model, not causal effects.
    """
    reference = artifact["reference_values"]
    names = [f for f in artifact["feature_columns"] if f in reference]
    variants = []
    for f in names:
        row = dict(features)
        row[f] = reference[f]
        variants.append(row)
    probs = _proba(artifact, variants)
    contribs = []
    for f, p_ref in zip(names, probs):
        delta = probability - p_ref
        if abs(delta) >= 0.005:
            contribs.append({"feature": f, "label": FEATURE_LABELS.get(f, f), "value": features.get(f),
                             "typical_value": reference[f], "contribution": round(delta, 4)})
    contribs.sort(key=lambda c: abs(c["contribution"]), reverse=True)
    top = contribs[:top_k]
    up = [c for c in top if c["contribution"] > 0]
    down = [c for c in top if c["contribution"] < 0]

    def fmt(c: dict) -> str:
        v = c["value"]
        v = "n/a" if v is None else (f"{v:,.0f}" if isinstance(v, float) else v)
        return f"{c['label']} = {v} ({c['contribution'] * 100:+.1f} pp)"

    parts = []
    if up:
        parts.append("Raising the estimate: " + "; ".join(fmt(c) for c in up) + ".")
    if down:
        parts.append("Lowering the estimate: " + "; ".join(fmt(c) for c in down) + ".")
    if not parts:
        parts.append("No single factor moves the estimate noticeably; the unit looks typical for the fleet.")
    parts.append("Contributions are model associations, not proof of cause.")
    return " ".join(parts), top


def predict_products(db: Session, product_ids: list[int], user_id: int | None = None) -> list[FailurePrediction]:
    run, artifact = load_active_model(db)
    histories = load_histories(db, product_ids)
    missing = set(product_ids) - set(histories)
    if missing:
        raise NotFoundError(f"Product(s) not found: {sorted(missing)}")
    now = datetime.now(timezone.utc)
    horizon = int(artifact["horizon_days"])
    ids = [pid for pid in product_ids if not unit_replaced_before(histories[pid], now)]
    if not ids:
        return []
    feats = [compute_features(histories[pid], now) for pid in ids]
    probs = _proba(artifact, feats)
    out = []
    for pid, f, p in zip(ids, feats, probs):
        if not 0.0 <= p <= 1.0:  # defensive: never store an invalid probability
            raise ValueError(f"Model returned an invalid probability {p}")
        text, details = explain(artifact, f, p)
        db.execute(
            update(FailurePrediction)
            .where(FailurePrediction.product_id == pid, FailurePrediction.prediction_horizon_days == horizon,
                   FailurePrediction.prediction_status == "Current")
            .values(prediction_status="Superseded")
        )
        pred = FailurePrediction(
            product_id=pid, training_run_id=run.training_run_id, prediction_date=now,
            prediction_horizon_days=horizon, failure_probability=Decimal(str(round(p, 5))),
            risk_level=settings_service.risk_level(db, p), model_version=run.model_version,
            model_classification=run.model_classification, feature_snapshot=f, explanation=text,
            explanation_details=details, prediction_status="Current", created_by=user_id,
        )
        db.add(pred)
        out.append(pred)
    db.flush()
    audit.log(db, "predictions_generated", "failure_prediction", None, user_id,
              {"products": ids, "model_version": run.model_version})
    return out
