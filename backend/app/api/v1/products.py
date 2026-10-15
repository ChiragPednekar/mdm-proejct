import secrets
from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.orm import Session

from app.api.v1._util import Paging, page_body, paginate
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.errors import BusinessRuleError, NotFoundError
from app.models import (
    Component,
    Customer,
    FailurePrediction,
    FaultCategory,
    Part,
    Product,
    ProductModel,
    RepairHistory,
    RepairPart,
    ServiceRequest,
    Technician,
    User,
    Warranty,
)
from app.schemas.common import ProductIn, ProductOut, ProductUpdate, WarrantyOut
from app.services import audit, warranty as warranty_svc
from app.services.analytics import _rows

router = APIRouter(prefix="/products", tags=["products"])

CATEGORY_CODES = {"Laptop": "LT", "Refrigerator": "RF", "Washing Machine": "WM", "Air Conditioner": "AC",
                  "Television": "TV"}


def _coverage_status():
    today = func.current_date()
    valid = and_(Warranty.product_id == Product.product_id, Warranty.warranty_status == "Valid")
    active = exists().where(valid, Warranty.start_date <= today, Warranty.end_date >= today)
    pending = exists().where(valid, Warranty.start_date > today)
    anyw = exists().where(Warranty.product_id == Product.product_id)
    return case((active, "Active"), (pending, "Pending"), (anyw, "Expired"), else_="None")


def _latest(col):
    return (select(col).where(FailurePrediction.product_id == Product.product_id,
                              FailurePrediction.prediction_status == "Current")
            .order_by(FailurePrediction.prediction_date.desc()).limit(1).correlate(Product).scalar_subquery())


@router.get("")
def list_products(
    q: str | None = Query(None, max_length=100, description="Serial number or customer name"),
    category: str | None = None,
    manufacturer: str | None = None,
    product_model_id: int | None = None,
    customer_id: int | None = None,
    status_: str | None = Query(None, alias="status"),
    coverage: str | None = Query(None, pattern="^(Active|Expired|Pending|None)$"),
    risk: str | None = Query(None, pattern="^(Low|Medium|High)$"),
    sort: str = Query("newest", pattern="^(newest|oldest|serial|risk)$"),
    paging: Paging = Depends(),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    cov = _coverage_status().label("coverage_status")
    risk_level = _latest(FailurePrediction.risk_level).label("risk_level")
    prob = _latest(FailurePrediction.failure_probability).label("failure_probability")
    stmt = (
        select(Product.product_id, Product.serial_number, Product.purchase_date, Product.purchase_price,
               Product.product_status, ProductModel.product_model_id, ProductModel.manufacturer,
               ProductModel.model_name, ProductModel.product_category, Customer.customer_id,
               Customer.full_name.label("customer_name"), cov, risk_level, prob)
        .join(ProductModel, ProductModel.product_model_id == Product.product_model_id)
        .join(Customer, Customer.customer_id == Product.customer_id)
    )
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Product.serial_number).like(like), func.lower(Customer.full_name).like(like)))
    if category:
        stmt = stmt.where(ProductModel.product_category == category)
    if manufacturer:
        stmt = stmt.where(ProductModel.manufacturer == manufacturer)
    if product_model_id:
        stmt = stmt.where(Product.product_model_id == product_model_id)
    if customer_id:
        stmt = stmt.where(Product.customer_id == customer_id)
    if status_:
        stmt = stmt.where(Product.product_status == status_)
    if coverage:
        stmt = stmt.where(_coverage_status() == coverage)
    if risk:
        stmt = stmt.where(_latest(FailurePrediction.risk_level) == risk)
    order = {
        "newest": (Product.purchase_date.desc(), Product.product_id.desc()),
        "oldest": (Product.purchase_date.asc(), Product.product_id),
        "serial": (Product.serial_number,),
        "risk": (_latest(FailurePrediction.failure_probability).desc().nulls_last(), Product.product_id),
    }[sort]
    rows, total = paginate(db, stmt.order_by(*order), paging)
    items = []
    for r in rows:
        d = dict(r._mapping)
        d["purchase_price"] = float(d["purchase_price"])
        d["failure_probability"] = float(d["failure_probability"]) if d["failure_probability"] is not None else None
        items.append(d)
    return page_body(items, total, paging)


@router.get("/serial-suggestion")
def serial_suggestion(product_model_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    pm = db.get(ProductModel, product_model_id)
    if pm is None:
        raise NotFoundError(f"Product model {product_model_id} not found.")
    maker = "".join(ch for ch in pm.manufacturer.upper() if ch.isalnum())[:3]
    for _ in range(20):
        serial = f"{maker}-{CATEGORY_CODES[pm.product_category]}-{date.today():%y}-{secrets.randbelow(90000) + 10000}"
        if not db.scalar(select(exists().where(Product.serial_number == serial))):
            return {"serial_number": serial}
    raise BusinessRuleError("Could not generate a unique serial number; enter one manually.")


@router.post("", status_code=status.HTTP_201_CREATED)
def create_product(body: ProductIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    pm = db.get(ProductModel, body.product_model_id)
    if pm is None:
        raise NotFoundError(f"Product model {body.product_model_id} not found.")
    if db.get(Customer, body.customer_id) is None:
        raise NotFoundError(f"Customer {body.customer_id} not found.")
    serial = (body.serial_number or serial_suggestion(pm.product_model_id, db, user)["serial_number"]).upper()
    p = Product(serial_number=serial, product_model_id=pm.product_model_id, customer_id=body.customer_id,
                purchase_date=body.purchase_date, purchase_price=body.purchase_price,
                installation_date=body.installation_date)
    p.product_model = pm
    db.add(p)
    db.flush()  # unique serial enforced by the database
    audit.log(db, "product_registered", "product", p.product_id, user.user_id, {"serial_number": serial})
    w = None
    if body.register_manufacturer_warranty:
        w = warranty_svc.register_manufacturer_warranty(db, p, user.user_id)
    db.commit()
    return {"product": ProductOut.model_validate(p),
            "warranty": WarrantyOut.model_validate(w) if w is not None else None}


def _warranty_out(w: Warranty) -> WarrantyOut:
    return WarrantyOut.model_validate(w).model_copy(update={
        "effective_status": warranty_svc.effective_status(w), "days_remaining": (w.end_date - date.today()).days})


def _get_product(db: Session, product_id: int) -> Product:
    p = db.get(Product, product_id)
    if p is None:
        raise NotFoundError(f"Product {product_id} not found.")
    return p


@router.get("/{product_id}")
def product_profile(product_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    p = _get_product(db, product_id)
    warranties = [_warranty_out(w) for w in p.warranties]
    latest = db.scalar(select(FailurePrediction).where(
        FailurePrediction.product_id == product_id, FailurePrediction.prediction_status == "Current"
    ).order_by(FailurePrediction.prediction_date.desc()).limit(1))
    stats = _rows(db, """
        SELECT (SELECT COUNT(*) FROM service_requests WHERE product_id = :pid) AS service_requests,
               (SELECT COUNT(*) FROM service_requests WHERE product_id = :pid
                  AND request_status IN ('Open','Assigned','In Progress')) AS open_requests,
               COUNT(rc.repair_id) AS repairs,
               COALESCE(SUM(rc.total_cost), 0) AS total_repair_cost,
               COALESCE(SUM(rc.warranty_cost), 0) AS warranty_cost,
               COALESCE(SUM(rc.customer_cost), 0) AS customer_cost,
               COUNT(*) FILTER (WHERE rc.repeat_failure) AS repeat_repairs
        FROM v_repair_costs rc WHERE rc.product_id = :pid""", {"pid": product_id})[0]
    active = [w for w in warranties if w.effective_status == "Active"]
    return {
        "product": ProductOut.model_validate(p),
        "model": {"product_model_id": p.product_model.product_model_id, "manufacturer": p.product_model.manufacturer,
                  "model_name": p.product_model.model_name, "product_category": p.product_model.product_category,
                  "standard_warranty_months": p.product_model.standard_warranty_months,
                  "release_year": p.product_model.release_year},
        "customer": {"customer_id": p.customer.customer_id, "full_name": p.customer.full_name,
                     "email": p.customer.email, "phone": p.customer.phone, "address": p.customer.address,
                     "city": p.customer.city},
        "warranties": warranties,
        "coverage": {"covered_today": bool(active),
                     "covered_until": max((w.end_date for w in warranties if w.warranty_status == "Valid"), default=None),
                     "active_warranty_ids": [w.warranty_id for w in active]},
        "stats": stats,
        "latest_prediction": _prediction_dict(latest) if latest else None,
    }


def _prediction_dict(fp: FailurePrediction) -> dict:
    return {"prediction_id": fp.prediction_id, "prediction_date": fp.prediction_date,
            "prediction_horizon_days": fp.prediction_horizon_days, "failure_probability": float(fp.failure_probability),
            "risk_level": fp.risk_level, "model_version": fp.model_version,
            "model_classification": fp.model_classification, "explanation": fp.explanation,
            "explanation_details": fp.explanation_details, "feature_snapshot": fp.feature_snapshot,
            "prediction_status": fp.prediction_status}


@router.get("/{product_id}/history")
def product_history(product_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _get_product(db, product_id)
    requests = db.execute(
        select(ServiceRequest, FaultCategory.name, Technician.full_name)
        .join(FaultCategory, FaultCategory.fault_category_id == ServiceRequest.fault_category_id)
        .outerjoin(Technician, Technician.technician_id == ServiceRequest.assigned_technician_id)
        .where(ServiceRequest.product_id == product_id).order_by(ServiceRequest.reported_at.desc())
    ).all()
    repairs = db.execute(
        select(RepairHistory, Technician.full_name, Component.component_name)
        .join(ServiceRequest, ServiceRequest.service_request_id == RepairHistory.service_request_id)
        .join(Technician, Technician.technician_id == RepairHistory.technician_id)
        .outerjoin(Component, Component.component_id == RepairHistory.component_id)
        .where(ServiceRequest.product_id == product_id).order_by(RepairHistory.repair_date)
    ).all()
    lines = db.execute(
        select(RepairPart, Part.part_number, Part.part_name)
        .join(Part, Part.part_id == RepairPart.part_id)
        .where(RepairPart.repair_id.in_([r[0].repair_id for r in repairs] or [-1]))
    ).all()
    by_repair: dict[int, list] = {}
    for rp, pn, name in lines:
        by_repair.setdefault(rp.repair_id, []).append({
            "part_id": rp.part_id, "part_number": pn, "part_name": name, "quantity_used": rp.quantity_used,
            "unit_cost_at_repair": float(rp.unit_cost_at_repair),
            "line_total": float(rp.unit_cost_at_repair * rp.quantity_used)})
    repairs_by_request: dict[int, list] = {}
    for r, tech, comp in repairs:
        repairs_by_request.setdefault(r.service_request_id, []).append({
            "repair_id": r.repair_id, "attempt_number": r.attempt_number, "technician_name": tech,
            "component_name": comp, "diagnosis": r.diagnosis, "root_cause": r.root_cause,
            "repair_action": r.repair_action, "labor_cost": float(r.labor_cost), "parts_cost": float(r.parts_cost),
            "total_cost": float(r.labor_cost + r.parts_cost), "repair_date": r.repair_date, "outcome": r.outcome,
            "repeat_failure": r.repeat_failure, "parts": by_repair.get(r.repair_id, [])})
    timeline = [{
        "service_request_id": sr.service_request_id, "reported_at": sr.reported_at, "fault_category": fault,
        "complaint_description": sr.complaint_description, "priority": sr.priority,
        "failure_severity": sr.failure_severity, "request_status": sr.request_status,
        "technician_name": tech, "warranty_id": sr.warranty_id, "warranty_covered": sr.warranty_covered,
        "coverage_notes": sr.coverage_notes, "resolution_date": sr.resolution_date,
        "resolution_summary": sr.resolution_summary, "repairs": repairs_by_request.get(sr.service_request_id, []),
    } for sr, fault, tech in requests]
    components = _rows(db, """
        SELECT co.component_name, pa.part_number, pa.part_name, SUM(rp.quantity_used) AS quantity,
               SUM(rp.quantity_used * rp.unit_cost_at_repair) AS cost, MAX(r.repair_date)::date AS last_replaced
        FROM repair_parts rp JOIN repair_history r ON r.repair_id = rp.repair_id
        JOIN service_requests sr ON sr.service_request_id = r.service_request_id
        JOIN parts pa ON pa.part_id = rp.part_id LEFT JOIN components co ON co.component_id = pa.component_id
        WHERE sr.product_id = :pid
        GROUP BY co.component_name, pa.part_number, pa.part_name ORDER BY last_replaced DESC""", {"pid": product_id})
    predictions = db.scalars(select(FailurePrediction).where(FailurePrediction.product_id == product_id)
                             .order_by(FailurePrediction.prediction_date.desc()).limit(50)).all()
    return {"timeline": timeline, "components_replaced": components,
            "predictions": [_prediction_dict(fp) for fp in predictions]}


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(product_id: int, body: ProductUpdate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    p = _get_product(db, product_id)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if "customer_id" in changes and db.get(Customer, changes["customer_id"]) is None:
        raise NotFoundError(f"Customer {changes['customer_id']} not found.")
    if changes.get("product_status") in ("Active", "Retired", "Replaced") and db.scalar(
        select(func.count()).where(ServiceRequest.product_id == product_id,
                                   ServiceRequest.request_status.in_(("Open", "Assigned", "In Progress")))
    ) and changes["product_status"] != p.product_status:
        raise BusinessRuleError("Product has open service requests; resolve them before changing its status.")
    if "installation_date" in changes and changes["installation_date"] < p.purchase_date:
        raise BusinessRuleError("installation_date cannot be before purchase_date.")
    for k, v in changes.items():
        setattr(p, k, v)
    audit.log(db, "product_updated", "product", product_id, user.user_id,
              {k: str(v) for k, v in changes.items()})
    db.commit()
    return p
