from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import MANAGERS, get_current_user, require_roles
from app.core.errors import ModelUnavailableError, NotFoundError
from app.ml import predictor
from app.ml.training import train_model
from app.models import ModelTrainingRun, User
from app.schemas.common import TrainIn
from app.services import settings_service

router = APIRouter(prefix="/models", tags=["models"])

_DESCRIPTIONS = {
    "validated": "Trained on operational data with adequate held-out temporal evaluation.",
    "demonstration": "Trained on the synthetic demonstration dataset. Metrics and predictions are illustrative only.",
    "unavailable": "No deployable model. Predictions are disabled until a model is trained on sufficient data.",
}


def _run_summary(run: ModelTrainingRun) -> dict:
    return {
        "training_run_id": run.training_run_id, "model_name": run.model_name, "model_version": run.model_version,
        "training_status": run.training_status, "model_classification": run.model_classification,
        "is_active": run.is_active, "training_started_at": run.training_started_at,
        "training_completed_at": run.training_completed_at, "training_dataset_version": run.training_dataset_version,
        "training_sample_count": run.training_sample_count, "prediction_horizon_days": run.prediction_horizon_days,
        "notes": run.notes,
        "chosen_algorithm": (run.evaluation_metrics or {}).get("chosen_algorithm"),
        "test_pr_auc": ((run.evaluation_metrics or {}).get("chosen_test") or {}).get("pr_auc"),
    }


@router.get("/status")
def model_status(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    run = predictor.active_run(db)
    provenance = settings_service.get_setting(db, "dataset_provenance")
    available, reason = False, None
    if run is not None:
        try:
            predictor.load_active_model(db)
            available = True
        except ModelUnavailableError as exc:
            reason = exc.message
    else:
        reason = _DESCRIPTIONS["unavailable"]
    state = run.model_classification if (available and run) else "unavailable"
    last = db.scalar(select(ModelTrainingRun).order_by(ModelTrainingRun.training_started_at.desc()).limit(1))
    return {
        "state": state, "description": _DESCRIPTIONS.get(state), "available": available, "reason": reason,
        "dataset_provenance": provenance, "active_run": _run_summary(run) if run else None,
        "latest_run": _run_summary(last) if last else None,
        "risk_bands": {"medium_min": float(settings_service.get_setting(db, "risk_band_medium_min")),
                       "high_min": float(settings_service.get_setting(db, "risk_band_high_min"))},
        "decision_threshold": (run.evaluation_metrics or {}).get("decision_threshold") if run else None,
        "training_restricted_to": ["admin"] if get_settings().is_production else ["admin", "service_manager"],
    }


@router.get("/metrics")
def model_metrics(training_run_id: int | None = None, db: Session = Depends(get_db),
                  _: User = Depends(get_current_user)):
    run = db.get(ModelTrainingRun, training_run_id) if training_run_id else predictor.active_run(db)
    if run is None:
        raise NotFoundError("No training run found." if training_run_id else "No active model.")
    return _run_summary(run) | {"evaluation_metrics": run.evaluation_metrics, "parameters": run.parameters}


@router.get("/runs")
def runs(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.scalars(select(ModelTrainingRun).order_by(ModelTrainingRun.training_started_at.desc()).limit(50))
    return [_run_summary(r) for r in rows]


def _trainer_roles():
    return ("admin",) if get_settings().is_production else MANAGERS


@router.post("/train")
def train(body: TrainIn | None = None, db: Session = Depends(get_db),
          user: User = Depends(require_roles(*_trainer_roles()))):
    run = train_model(db, user.user_id, horizon_days=body.horizon_days if body else None)
    return _run_summary(run)
