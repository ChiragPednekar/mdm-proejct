"""Training & evaluation pipeline for the failure-risk classifier.

Steps: extract -> point-in-time snapshots -> validate -> temporal split
(train | gap | validation | gap | test) -> baselines + Random Forest +
Gradient Boosting -> choose model on validation PR-AUC -> choose threshold on
validation F1 -> report held-out test metrics -> refit the chosen
configuration on all eligible snapshots for deployment -> persist + register.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ml.dataset import build_snapshots, dataset_version, load_histories, validate_dataset
from app.ml.features import CATEGORICAL_FEATURES, FEATURE_COLUMNS, FEATURE_GROUPS, NUMERIC_FEATURES
from app.models import ModelTrainingRun
from app.services import audit, settings_service

log = logging.getLogger(__name__)
RANDOM_STATE = 42

# Minimum data before anything is trained at all.
MIN_SNAPSHOTS = 300
MIN_POSITIVES = 30
# Minimum held-out evidence before a model on OPERATIONAL data is called validated.
MIN_TEST_POSITIVES = 25
# Validation PR-AUC margin Gradient Boosting needs to replace Random Forest.
SELECTION_MARGIN = 0.01


class InsufficientDataError(Exception):
    pass


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------
def make_preprocessor() -> ColumnTransformer:
    numeric = SimpleImputer(strategy="median", add_indicator=True)
    categorical = Pipeline([
        ("impute", SimpleImputer(strategy="constant", fill_value="None")),
        ("onehot", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=5, sparse_output=False)),
    ])
    return ColumnTransformer([("num", numeric, NUMERIC_FEATURES), ("cat", categorical, CATEGORICAL_FEATURES)])


def make_candidates() -> dict[str, Pipeline]:
    return {
        "random_forest": Pipeline([
            ("prep", make_preprocessor()),
            ("clf", RandomForestClassifier(
                # No class re-weighting: we want probabilities that stay close to
                # observed frequencies because risk bands are defined on them.
                n_estimators=400, min_samples_leaf=15, max_features="sqrt",
                random_state=RANDOM_STATE, n_jobs=-1,
            )),
        ]),
        "gradient_boosting": Pipeline([
            ("prep", make_preprocessor()),
            ("clf", GradientBoostingClassifier(
                n_estimators=150, max_depth=2, learning_rate=0.05, subsample=0.8, min_samples_leaf=20,
                random_state=RANDOM_STATE,
            )),
        ]),
    }


class PriorRateBaseline:
    """Predicts the training positive rate for everyone."""

    def fit(self, X: pd.DataFrame, y: pd.Series):
        self.rate_ = float(np.mean(y))
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        p = np.full(len(X), self.rate_)
        return np.column_stack([1 - p, p])


class RecentFailureBaseline:
    """Rule of thumb: empirical failure rate for units with vs. without a
    failure in the previous 90 days."""

    def fit(self, X: pd.DataFrame, y: pd.Series):
        recent = X["failures_90d"].fillna(0) > 0
        overall = float(np.mean(y))
        self.rate_recent_ = float(y[recent].mean()) if recent.any() else overall
        self.rate_other_ = float(y[~recent].mean()) if (~recent).any() else overall
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        p = np.where(X["failures_90d"].fillna(0) > 0, self.rate_recent_, self.rate_other_)
        return np.column_stack([1 - p, p])


def classification_metrics(y: np.ndarray, p: np.ndarray, threshold: float) -> dict:
    y = np.asarray(y).astype(int)
    pred = (p >= threshold).astype(int)
    both = len(np.unique(y)) == 2
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {
        "n": int(len(y)),
        "positives": int(y.sum()),
        "prevalence": round(float(y.mean()), 4) if len(y) else None,
        "threshold": round(float(threshold), 4),
        "precision": round(float(precision_score(y, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y, pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y, pred, zero_division=0)), 4),
        "accuracy": round(float(accuracy_score(y, pred)), 4),
        # ROC-AUC / PR-AUC are undefined when only one class is present.
        "roc_auc": round(float(roc_auc_score(y, p)), 4) if both else None,
        "pr_auc": round(float(average_precision_score(y, p)), 4) if both else None,
        "brier": round(float(brier_score_loss(y, p)), 4),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def choose_threshold(y: np.ndarray, p: np.ndarray) -> float:
    """Threshold maximising F1 on validation data (ties -> lower threshold,
    i.e. higher recall, which suits proactive inspection)."""
    candidates = np.unique(np.round(p, 4))
    if len(candidates) > 200:
        candidates = np.unique(np.quantile(p, np.linspace(0.01, 0.99, 199)).round(4))
    best_t, best_f1 = 0.5, -1.0
    for t in sorted(candidates):
        f1 = f1_score(y, (p >= t).astype(int), zero_division=0)
        if f1 > best_f1 + 1e-9:
            best_t, best_f1 = float(t), f1
    return best_t


def calibration_table(y: np.ndarray, p: np.ndarray, bins: int = 8) -> list[dict]:
    df = pd.DataFrame({"y": y, "p": p})
    try:
        df["bin"] = pd.qcut(df["p"], q=bins, duplicates="drop")
    except ValueError:
        return []
    out = []
    for _, g in df.groupby("bin", observed=True):
        out.append({"mean_predicted": round(float(g["p"].mean()), 4),
                    "observed_rate": round(float(g["y"].mean()), 4), "count": int(len(g))})
    return out


def grouped_permutation_importance(model, X: pd.DataFrame, y: np.ndarray, groups: dict[str, list[str]],
                                   n_repeats: int = 10) -> list[dict]:
    """PR-AUC drop when a whole family of correlated features is shuffled
    jointly (one shared row permutation per repeat)."""
    rng = np.random.default_rng(RANDOM_STATE)
    base = average_precision_score(y, model.predict_proba(X)[:, 1])
    out = []
    for name, cols in groups.items():
        drops = []
        for _ in range(n_repeats):
            Xp = X.copy()
            idx = rng.permutation(len(X))
            Xp[cols] = X[cols].to_numpy()[idx]
            drops.append(base - average_precision_score(y, model.predict_proba(Xp)[:, 1]))
        out.append({"group": name, "features": cols, "importance": round(float(np.mean(drops)), 5),
                    "std": round(float(np.std(drops)), 5)})
    return sorted(out, key=lambda d: d["importance"], reverse=True)


def temporal_split(df: pd.DataFrame, horizon_days: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """Chronological split on cutoff dates with a horizon-length gap.

    A training snapshot's label looks ``horizon`` days into the future, so
    training snapshots whose label window overlaps the validation period are
    dropped (likewise validation vs. test). Without this gap the training labels
    would contain information from the evaluation period.
    """
    cutoffs = sorted(df["cutoff"].unique())
    n = len(cutoffs)
    if n < 6:
        raise InsufficientDataError(f"Need at least 6 monthly cutoffs for a temporal split (have {n}).")
    n_test = max(2, round(n * 0.2))
    n_val = max(2, round(n * 0.2))
    test_start = cutoffs[n - n_test]
    val_start = cutoffs[n - n_test - n_val]
    gap = pd.Timedelta(days=horizon_days)
    train = df[df["cutoff"] + gap <= val_start]
    val = df[(df["cutoff"] >= val_start) & (df["cutoff"] + gap <= test_start)]
    test = df[df["cutoff"] >= test_start]
    info = {
        "strategy": "temporal (train < validation < test by cutoff date) with a horizon-length gap",
        "train_cutoffs": [str(pd.Timestamp(train["cutoff"].min()).date()), str(pd.Timestamp(train["cutoff"].max()).date())],
        "validation_cutoffs": [str(pd.Timestamp(val["cutoff"].min()).date()), str(pd.Timestamp(val["cutoff"].max()).date())],
        "test_cutoffs": [str(pd.Timestamp(test["cutoff"].min()).date()), str(pd.Timestamp(test["cutoff"].max()).date())],
        "dropped_for_gap": int(len(df) - len(train) - len(val) - len(test)),
        "sizes": {"train": int(len(train)), "validation": int(len(val)), "test": int(len(test))},
        "positives": {"train": int(train["label"].sum()), "validation": int(val["label"].sum()),
                      "test": int(test["label"].sum())},
    }
    return train, val, test, info


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def train_model(db: Session, user_id: int | None = None, horizon_days: int | None = None,
                observation_end: datetime | None = None) -> ModelTrainingRun:
    horizon = int(horizon_days or settings_service.get_setting(db, "prediction_horizon_days"))
    provenance = str(settings_service.get_setting(db, "dataset_provenance"))
    started = datetime.now(timezone.utc)
    observation_end = observation_end or started
    version = f"rf-gb-{started:%Y%m%d-%H%M%S}"
    run = ModelTrainingRun(
        model_name="failure_risk_classifier", model_version=version, training_started_at=started,
        prediction_horizon_days=horizon, training_status="Running", model_classification="not_applicable",
        triggered_by=user_id,
    )
    db.add(run)
    db.commit()

    try:
        histories = load_histories(db)
        df = build_snapshots(histories, observation_end, horizon)
        quality = validate_dataset(df)
        run.training_dataset_version = dataset_version(provenance, histories, observation_end)
        run.training_sample_count = quality["rows"]
        if quality["rows"] < MIN_SNAPSHOTS or quality.get("positives", 0) < MIN_POSITIVES:
            raise InsufficientDataError(
                f"Only {quality['rows']} eligible snapshots with {quality.get('positives', 0)} failures; "
                f"need at least {MIN_SNAPSHOTS} snapshots and {MIN_POSITIVES} failures."
            )
        train, val, test, split = temporal_split(df, horizon)
        for name, part in (("train", train), ("validation", val), ("test", test)):
            if part["label"].nunique() < 2:
                raise InsufficientDataError(f"The {name} period contains only one class; cannot evaluate.")

        Xtr, ytr = train[FEATURE_COLUMNS], train["label"].to_numpy()
        Xva, yva = val[FEATURE_COLUMNS], val["label"].to_numpy()
        Xte, yte = test[FEATURE_COLUMNS], test["label"].to_numpy()

        models: dict[str, object] = {"baseline_prior_rate": PriorRateBaseline(),
                                     "baseline_recent_failure_rule": RecentFailureBaseline(), **make_candidates()}
        results: dict[str, dict] = {}
        for name, model in models.items():
            model.fit(Xtr, ytr)
            p_val = model.predict_proba(Xva)[:, 1]
            thr = choose_threshold(yva, p_val)
            p_test = model.predict_proba(Xte)[:, 1]
            results[name] = {
                "validation": classification_metrics(yva, p_val, thr),
                "test": classification_metrics(yte, p_test, thr),
            }

        # Random Forest is the primary model; Gradient Boosting is a comparison
        # that replaces it only with a clear validation advantage.
        rf_val = results["random_forest"]["validation"]["pr_auc"] or 0
        gb_val = results["gradient_boosting"]["validation"]["pr_auc"] or 0
        chosen = "gradient_boosting" if gb_val > rf_val + SELECTION_MARGIN else "random_forest"
        chosen_model = models[chosen]
        threshold = results[chosen]["validation"]["threshold"]
        p_test = chosen_model.predict_proba(Xte)[:, 1]

        # Importance is measured on all held-out snapshots (validation + test):
        # no selection decision uses it, and the larger sample is more stable.
        X_hold = pd.concat([Xva, Xte])
        y_hold = np.concatenate([yva, yte])
        perm = permutation_importance(chosen_model, X_hold, y_hold, scoring="average_precision",
                                      n_repeats=10, random_state=RANDOM_STATE, n_jobs=1)
        importance = sorted(
            ({"feature": f, "importance": round(float(m), 5), "std": round(float(s), 5)}
             for f, m, s in zip(FEATURE_COLUMNS, perm.importances_mean, perm.importances_std)),
            key=lambda d: d["importance"], reverse=True,
        )

        group_importance = grouped_permutation_importance(chosen_model, X_hold, y_hold, FEATURE_GROUPS)

        best_baseline_pr = max(results[b]["test"]["pr_auc"] or 0 for b in ("baseline_prior_rate", "baseline_recent_failure_rule"))
        beats_baseline = (results[chosen]["test"]["pr_auc"] or 0) > best_baseline_pr

        # Classification of the resulting model (see README "Model status").
        if provenance == "synthetic_demo":
            classification, deploy = "demonstration", True
            note = ("Trained on the SYNTHETIC demonstration dataset. Metrics are illustrative only and "
                    "are not evidence of real-world performance.")
        elif split["positives"]["test"] >= MIN_TEST_POSITIVES and beats_baseline:
            classification, deploy = "validated", True
            note = "Trained on operational data; held-out temporal test set meets the minimum evidence threshold."
        else:
            classification, deploy = "not_applicable", False
            note = (f"Operational data did not provide adequate evaluation evidence (test failures "
                    f"{split['positives']['test']} < {MIN_TEST_POSITIVES} or no improvement over baseline). "
                    "Model NOT deployed.")

        # Deployment refit: the chosen configuration on every eligible snapshot,
        # so live predictions use the most recent history. Reported metrics come
        # from the train-only fit above.
        final = make_candidates()[chosen]
        final.fit(df[FEATURE_COLUMNS], df["label"].to_numpy())

        reference = {c: float(df[c].median()) for c in NUMERIC_FEATURES if df[c].notna().any()}
        reference.update({c: str(df[c].mode().iloc[0]) for c in CATEGORICAL_FEATURES})

        artifact_dir = get_settings().artifact_path
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_name = f"{version}.joblib"
        if deploy:
            joblib.dump({
                "pipeline": final, "algorithm": chosen, "model_version": version,
                "feature_columns": FEATURE_COLUMNS, "numeric_features": NUMERIC_FEATURES,
                "categorical_features": CATEGORICAL_FEATURES, "reference_values": reference,
                "decision_threshold": threshold, "horizon_days": horizon, "classification": classification,
                "trained_at": started.isoformat(), "dataset_version": run.training_dataset_version,
            }, artifact_dir / artifact_name)

        run.evaluation_metrics = {
            "chosen_algorithm": chosen,
            "selection_rule": f"Random Forest unless Gradient Boosting exceeds its validation PR-AUC by > {SELECTION_MARGIN}",
            "decision_threshold": threshold,
            "threshold_rule": "maximises F1 on the validation period",
            "beats_best_baseline_on_test_pr_auc": beats_baseline,
            "models": results,
            "chosen_test": results[chosen]["test"],
            "calibration_test": calibration_table(yte, p_test),
            "feature_importance": importance,
            "group_importance": group_importance,
            "feature_importance_method": "permutation importance: PR-AUC drop on held-out (validation + test) snapshots; associative, not causal",
            "split": split,
            "data_quality": quality,
            "target_definition": (f"label = 1 if a failure-category service request is reported within {horizon} days "
                                  "after the cutoff; snapshots whose horizon is not fully observed are excluded."),
            "deployment_fit": "chosen configuration refit on all eligible snapshots after evaluation",
        }
        run.parameters = {"horizon_days": horizon, "random_state": RANDOM_STATE,
                          "random_forest": models["random_forest"].named_steps["clf"].get_params(),
                          "gradient_boosting": {k: v for k, v in models["gradient_boosting"].named_steps["clf"].get_params().items()
                                                if isinstance(v, (int, float, str, bool, type(None)))}}
        run.parameters["random_forest"] = {k: v for k, v in run.parameters["random_forest"].items()
                                           if isinstance(v, (int, float, str, bool, type(None)))}
        run.model_artifact_reference = artifact_name if deploy else None
        run.model_classification = classification
        run.training_status = "Completed"
        run.notes = note
        run.training_completed_at = datetime.now(timezone.utc)
        if deploy:
            db.execute(update(ModelTrainingRun).where(ModelTrainingRun.is_active).values(is_active=False))
            db.flush()
            run.is_active = True
        audit.log(db, "model_trained", "model_training_run", run.training_run_id, user_id,
                  {"version": version, "classification": classification, "deployed": deploy,
                   "test_pr_auc": results[chosen]["test"]["pr_auc"]})
        db.commit()
    except InsufficientDataError as exc:
        db.rollback()
        run.training_status = "Insufficient Data"
        run.notes = str(exc)
        run.training_completed_at = datetime.now(timezone.utc)
        audit.log(db, "model_training_insufficient_data", "model_training_run", run.training_run_id, user_id,
                  {"reason": str(exc)})
        db.commit()
    except Exception as exc:  # recorded, then re-raised for the caller to report
        db.rollback()
        log.exception("Training failed")
        run.training_status = "Failed"
        run.notes = f"{type(exc).__name__}: {exc}"
        run.training_completed_at = datetime.now(timezone.utc)
        db.commit()
        raise
    return run


def artifact_path(reference: str) -> Path:
    return get_settings().artifact_path / reference


_ = timedelta  # re-exported for type checkers in tests
