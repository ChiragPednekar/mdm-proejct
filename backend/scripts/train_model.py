"""Train, evaluate and register the failure-risk model.

Usage (from backend/):
    python -m scripts.train_model                 # uses horizon from settings (30 days)
    python -m scripts.train_model --horizon 60
    python -m scripts.train_model --predict-all   # also score every active product
"""
import argparse
import json

from app.core.database import SessionLocal
from app.ml.predictor import predict_products
from app.ml.training import train_model
from app.models import Product


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=None)
    ap.add_argument("--predict-all", action="store_true")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        run = train_model(db, horizon_days=args.horizon)
        print(f"run #{run.training_run_id} {run.model_version}: {run.training_status} "
              f"[{run.model_classification}] active={run.is_active}")
        print(run.notes)
        if run.evaluation_metrics:
            m = run.evaluation_metrics
            print("chosen:", m["chosen_algorithm"], "threshold:", m["decision_threshold"])
            print("split:", json.dumps(m["split"]["sizes"]), "positives:", json.dumps(m["split"]["positives"]))
            for name, r in m["models"].items():
                t, v = r["test"], r["validation"]
                print(f"  {name:32s} val PR-AUC={v['pr_auc']} | test PR-AUC={t['pr_auc']} ROC-AUC={t['roc_auc']} "
                      f"P={t['precision']} R={t['recall']} F1={t['f1']} Brier={t['brier']}")
        if args.predict_all and run.is_active:
            ids = [p.product_id for p in db.query(Product).filter(Product.product_status.in_(("Active", "Under Repair")))]
            preds = predict_products(db, ids)
            db.commit()
            from collections import Counter
            print("predictions:", len(preds), dict(Counter(p.risk_level for p in preds)))
    finally:
        db.close()


if __name__ == "__main__":
    main()
