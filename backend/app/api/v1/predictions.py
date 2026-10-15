from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.v1._util import Paging, page_body, paginate
from app.core.database import get_db
from app.core.deps import MANAGERS, get_current_user, require_roles
from app.core.errors import NotFoundError
from app.ml import predictor
from app.models import FailurePrediction, ModelTrainingRun, Product, ProductModel, User
from app.api.v1.products import _prediction_dict

router = APIRouter(prefix="/predictions", tags=["predictions"])


@router.get("")
def list_predictions(
    risk_level: str | None = Query(None, pattern="^(Low|Medium|High)$"),
    current_only: bool = True,
    product_id: int | None = None,
    category: str | None = None,
    q: str | None = Query(None, max_length=100),
    sort: str = Query("-probability", pattern="^-?(probability|date)$"),
    paging: Paging = Depends(),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = (select(FailurePrediction, Product.serial_number, ProductModel.model_name, ProductModel.product_category,
                   ModelTrainingRun.evaluation_metrics["decision_threshold"].astext.label("threshold"))
            .join(Product, Product.product_id == FailurePrediction.product_id)
            .join(ProductModel, ProductModel.product_model_id == Product.product_model_id)
            .join(ModelTrainingRun, ModelTrainingRun.training_run_id == FailurePrediction.training_run_id))
    if current_only:
        stmt = stmt.where(FailurePrediction.prediction_status == "Current")
    if risk_level:
        stmt = stmt.where(FailurePrediction.risk_level == risk_level)
    if product_id:
        stmt = stmt.where(FailurePrediction.product_id == product_id)
    if category:
        stmt = stmt.where(ProductModel.product_category == category)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Product.serial_number).like(like), func.lower(ProductModel.model_name).like(like)))
    col = FailurePrediction.failure_probability if "probability" in sort else FailurePrediction.prediction_date
    stmt = stmt.order_by(col.desc() if sort.startswith("-") else col, FailurePrediction.prediction_id.desc())
    rows, total = paginate(db, stmt, paging)
    items = []
    for fp, serial, model, cat, thr in rows:
        d = _prediction_dict(fp)
        d.pop("feature_snapshot")
        thr = float(thr) if thr is not None else None
        d.update(product_id=fp.product_id, serial_number=serial, model_name=model, product_category=cat,
                 decision_threshold=thr,
                 above_decision_threshold=(thr is not None and float(fp.failure_probability) >= thr))
        items.append(d)
    return page_body(items, total, paging)


@router.post("/{product_id}/generate", status_code=status.HTTP_201_CREATED)
def generate(product_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if db.get(Product, product_id) is None:
        raise NotFoundError(f"Product {product_id} not found.")
    preds = predictor.predict_products(db, [product_id], user.user_id)
    db.commit()
    if not preds:
        raise NotFoundError("This unit has been replaced; predictions are no longer generated for it.")
    return _prediction_dict(preds[0])


@router.post("/generate-batch", status_code=status.HTTP_201_CREATED)
def generate_batch(db: Session = Depends(get_db), user: User = Depends(require_roles(*MANAGERS))):
    ids = list(db.scalars(select(Product.product_id).where(Product.product_status.in_(("Active", "Under Repair")))))
    preds = predictor.predict_products(db, ids, user.user_id) if ids else []
    db.commit()
    counts: dict[str, int] = {}
    for p in preds:
        counts[p.risk_level] = counts.get(p.risk_level, 0) + 1
    return {"generated": len(preds), "by_risk_level": counts}
