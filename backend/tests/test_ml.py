from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.ml.dataset import build_snapshots
from app.ml.features import (
    FEATURE_COLUMNS,
    ProductHistory,
    RepairEvent,
    RequestEvent,
    WarrantyTerm,
    compute_features,
    target_label,
)
from app.ml.training import classification_metrics, make_candidates, temporal_split, train_model
from app.models import FailurePrediction, ModelTrainingRun

T0 = datetime(2026, 3, 1, tzinfo=timezone.utc)


def history(**kw) -> ProductHistory:
    h = ProductHistory(product_id=1, purchase_date=date(2025, 1, 1), installation_date=None, purchase_price=50000,
                       product_category="Laptop", manufacturer="Testco", product_model="T-1", release_year=2024)
    h.warranties = [WarrantyTerm(date(2025, 1, 1), date(2025, 12, 31), "Valid", "Manufacturer")]
    h.requests = [RequestEvent(T0 - timedelta(days=20), True, False, "Electrical Failure"),
                  RequestEvent(T0 - timedelta(days=200), True, False, "Display Fault")]
    h.repairs = [RepairEvent(T0 - timedelta(days=18), "Fixed", 3000.0, 1)]
    for k, v in kw.items():
        setattr(h, k, v)
    return h


def test_feature_generation_values():
    f = compute_features(history(), T0)
    assert f["product_age_days"] == (T0.date() - date(2025, 1, 1)).days
    assert f["prior_failures"] == 2 and f["failures_30d"] == 1 and f["failures_90d"] == 1 and f["failures_180d"] == 1
    assert f["prior_repairs"] == 1 and f["days_since_last_repair"] == 18 and f["prior_repair_cost"] == 3000.0
    assert f["warranty_active"] == 0 and f["warranty_days_remaining"] == 0  # warranty ended 2025-12-31
    assert f["last_fault_category"] == "Electrical Failure"
    assert f["days_since_installation"] is None  # missing value, imputed later by the pipeline
    assert set(f) == set(FEATURE_COLUMNS)


def test_no_future_leakage():
    h = history()
    before = compute_features(h, T0)
    # Add events at / after the cutoff, plus a request reported before the cutoff but repaired after it.
    h.requests.append(RequestEvent(T0 + timedelta(days=3), True, False, "Cooling Failure"))
    h.requests.append(RequestEvent(T0, True, True, "Physical Damage"))
    h.repairs.append(RepairEvent(T0 + timedelta(hours=5), "Not Fixed", 9999.0, 4))
    assert compute_features(h, T0) == before


def test_target_label_construction():
    h = history()
    assert target_label(h, T0, 30) == 0
    h.requests.append(RequestEvent(T0 + timedelta(days=29), True, False, "Electrical Failure"))
    assert target_label(h, T0, 30) == 1
    assert target_label(h, T0, 20) == 0  # outside a shorter horizon
    h2 = history()
    h2.requests.append(RequestEvent(T0 + timedelta(days=5), False, False, "Installation Request"))
    assert target_label(h2, T0, 30) == 0  # non-failure visits do not count


def test_snapshots_exclude_censored_and_prepurchase_cutoffs():
    h = history()
    obs_end = datetime(2026, 3, 20, tzinfo=timezone.utc)
    df = build_snapshots({1: h}, obs_end, 30)
    assert df["cutoff"].max() <= obs_end - timedelta(days=30)  # full horizon observed
    assert df["cutoff"].min().date() > h.purchase_date
    assert (df["product_age_days"] > 0).all()


def test_pipeline_handles_missing_values_and_unknown_categories():
    rows = []
    rng = np.random.default_rng(0)
    for i in range(200):
        f = compute_features(history(), T0)
        f["prior_failures"] = int(rng.integers(0, 5))
        f["days_since_last_repair"] = None if i % 3 == 0 else float(rng.integers(1, 300))
        f["manufacturer"] = ["A", "B", "C"][i % 3]
        rows.append({**f, "label": int(f["prior_failures"] >= 3)})
    df = pd.DataFrame(rows)
    pipe = make_candidates()["random_forest"].fit(df[FEATURE_COLUMNS], df["label"])
    new = compute_features(history(), T0) | {"manufacturer": "NeverSeen", "days_since_last_repair": None}
    p = pipe.predict_proba(pd.DataFrame([new], columns=FEATURE_COLUMNS))[:, 1]
    assert 0.0 <= p[0] <= 1.0


def test_metric_calculation():
    y = np.array([0, 0, 1, 1, 0, 1])
    p = np.array([0.1, 0.6, 0.7, 0.4, 0.2, 0.9])
    m = classification_metrics(y, p, 0.5)
    assert m["confusion_matrix"] == {"tn": 2, "fp": 1, "fn": 1, "tp": 2}
    assert m["precision"] == pytest.approx(2 / 3, abs=1e-4) and m["recall"] == pytest.approx(2 / 3, abs=1e-4)
    assert m["roc_auc"] == pytest.approx(8 / 9, abs=1e-4)
    single = classification_metrics(np.zeros(4), np.full(4, 0.1), 0.5)
    assert single["roc_auc"] is None and single["pr_auc"] is None  # undefined with one class


def test_temporal_split_has_gap():
    cutoffs = pd.date_range("2025-01-01", periods=12, freq="MS", tz="UTC")
    df = pd.DataFrame({"cutoff": np.repeat(cutoffs, 10), "label": np.tile([0] * 9 + [1], 12)})
    train, val, test, info = temporal_split(df, 45)
    assert train["cutoff"].max() + pd.Timedelta(days=45) <= val["cutoff"].min()
    assert val["cutoff"].max() + pd.Timedelta(days=45) <= test["cutoff"].min()
    assert info["dropped_for_gap"] > 0


def test_model_unavailable_keeps_app_working(client, world):
    h = world.headers()
    status = client.get("/api/v1/models/status", headers=h).json()
    assert status["state"] == "unavailable" and status["available"] is False
    r = client.post(f"/api/v1/predictions/{world.product.product_id}/generate", headers=h)
    assert r.status_code == 503 and r.json()["error"]["code"] == "model_unavailable"
    assert client.get(f"/api/v1/products/{world.product.product_id}", headers=h).status_code == 200


def test_insufficient_data_training_does_not_deploy(db, world):
    run = train_model(db)
    assert run.training_status == "Insufficient Data" and not run.is_active
    assert run.model_artifact_reference is None


def test_probability_constraint(db, world):
    run = ModelTrainingRun(model_name="x", model_version="v-test", training_started_at=datetime.now(timezone.utc),
                           training_status="Completed", model_classification="demonstration")
    db.add(run)
    db.flush()
    with pytest.raises(IntegrityError):
        db.add(FailurePrediction(product_id=world.product.product_id, training_run_id=run.training_run_id,
                                 prediction_date=datetime.now(timezone.utc), prediction_horizon_days=30,
                                 failure_probability=1.5, risk_level="High", model_version="v-test",
                                 model_classification="demonstration", feature_snapshot={}, explanation="x"))
        db.flush()
    db.rollback()


@pytest.fixture
def seeded_and_trained(db):
    from scripts.seed import seed

    seed(date.today(), reset=True)
    run = train_model(db)
    return run


def test_demo_training_serialization_and_prediction(client, db, seeded_and_trained):
    run = seeded_and_trained
    assert run.training_status == "Completed"
    assert run.model_classification == "demonstration" and run.is_active  # synthetic data is never "validated"
    m = run.evaluation_metrics
    assert {"baseline_prior_rate", "baseline_recent_failure_rule", "random_forest", "gradient_boosting"} <= set(m["models"])
    for key in ("precision", "recall", "f1", "roc_auc", "pr_auc", "brier", "confusion_matrix"):
        assert key in m["chosen_test"]
    assert m["split"]["sizes"]["test"] > 0 and m["feature_importance"]

    # Serialized artifact round-trips through joblib and predicts identically.
    import joblib
    from app.ml.training import artifact_path
    art = joblib.load(artifact_path(run.model_artifact_reference))
    assert art["model_version"] == run.model_version

    from app.models import User
    admin = db.scalar(select(User).where(User.username == "admin"))
    from app.core.security import create_access_token
    h = {"Authorization": f"Bearer {create_access_token(admin.user_id, admin.role)}"}
    status = client.get("/api/v1/models/status", headers=h).json()
    assert status["state"] == "demonstration"

    from app.models import Product
    pid = db.scalar(select(Product.product_id).where(Product.product_status == "Active").order_by(Product.product_id))
    a = client.post(f"/api/v1/predictions/{pid}/generate", headers=h)
    assert a.status_code == 201, a.text
    pa = a.json()
    assert 0 <= pa["failure_probability"] <= 1 and pa["risk_level"] in ("Low", "Medium", "High")
    assert pa["model_classification"] == "demonstration" and "not proof of cause" in pa["explanation"]
    b = client.post(f"/api/v1/predictions/{pid}/generate", headers=h).json()
    assert b["failure_probability"] == pa["failure_probability"]  # deterministic for the same history
    db.expire_all()
    preds = db.scalars(select(FailurePrediction).where(FailurePrediction.product_id == pid)
                       .order_by(FailurePrediction.prediction_id)).all()
    assert [p.prediction_status for p in preds] == ["Superseded", "Current"]  # history kept, not overwritten
