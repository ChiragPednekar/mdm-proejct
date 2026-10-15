from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1._util import Paging, page_body, paginate
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import (
    Component,
    FaultCategory,
    Product,
    ProductModel,
    RepairHistory,
    ServiceRequest,
    Technician,
    User,
)
from app.services import analytics

router = APIRouter(tags=["repair history"])


@router.get("/repairs")
def list_repairs(
    start_date: date | None = None,
    end_date: date | None = None,
    category: str | None = None,
    manufacturer: str | None = None,
    product_model_id: int | None = None,
    component_id: int | None = None,
    severity: str | None = None,
    outcome: str | None = None,
    technician_id: int | None = None,
    repeat_only: bool = False,
    q: str | None = Query(None, max_length=100),
    paging: Paging = Depends(),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = (
        select(RepairHistory.repair_id, RepairHistory.service_request_id, RepairHistory.attempt_number,
               RepairHistory.repair_date, RepairHistory.diagnosis, RepairHistory.root_cause,
               RepairHistory.repair_action, RepairHistory.outcome, RepairHistory.repeat_failure,
               RepairHistory.labor_cost, RepairHistory.parts_cost,
               (RepairHistory.labor_cost + RepairHistory.parts_cost).label("total_cost"),
               Product.product_id, Product.serial_number, ProductModel.manufacturer, ProductModel.model_name,
               ProductModel.product_category, Component.component_name, Technician.full_name.label("technician_name"),
               FaultCategory.name.label("fault_category"), ServiceRequest.failure_severity,
               ServiceRequest.warranty_covered)
        .join(ServiceRequest, ServiceRequest.service_request_id == RepairHistory.service_request_id)
        .join(Product, Product.product_id == ServiceRequest.product_id)
        .join(ProductModel, ProductModel.product_model_id == Product.product_model_id)
        .join(FaultCategory, FaultCategory.fault_category_id == ServiceRequest.fault_category_id)
        .join(Technician, Technician.technician_id == RepairHistory.technician_id)
        .outerjoin(Component, Component.component_id == RepairHistory.component_id)
    )
    if start_date:
        stmt = stmt.where(RepairHistory.repair_date >= start_date)
    if end_date:
        stmt = stmt.where(func.date(RepairHistory.repair_date) <= end_date)
    if category:
        stmt = stmt.where(ProductModel.product_category == category)
    if manufacturer:
        stmt = stmt.where(ProductModel.manufacturer == manufacturer)
    if product_model_id:
        stmt = stmt.where(ProductModel.product_model_id == product_model_id)
    if component_id:
        stmt = stmt.where(RepairHistory.component_id == component_id)
    if severity:
        stmt = stmt.where(ServiceRequest.failure_severity == severity)
    if outcome:
        stmt = stmt.where(RepairHistory.outcome == outcome)
    if technician_id:
        stmt = stmt.where(RepairHistory.technician_id == technician_id)
    if repeat_only:
        stmt = stmt.where(RepairHistory.repeat_failure)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(func.lower(Product.serial_number).like(like) | func.lower(RepairHistory.diagnosis).like(like))
    rows, total = paginate(db, stmt.order_by(RepairHistory.repair_date.desc()), paging)
    items = []
    for r in rows:
        d = dict(r._mapping)
        for k in ("labor_cost", "parts_cost", "total_cost"):
            d[k] = float(d[k])
        items.append(d)
    return page_body(items, total, paging)


@router.get("/analytics/defects")
def defects(
    start_date: date | None = None,
    end_date: date | None = None,
    category: str | None = None,
    manufacturer: str | None = None,
    product_model_id: int | None = None,
    component_id: int | None = None,
    severity: str | None = None,
    window_days: int | None = Query(None, ge=1, le=365),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return analytics.defect_analytics(db, {
        "start_date": start_date, "end_date": end_date, "category": category, "manufacturer": manufacturer,
        "product_model_id": product_model_id, "component_id": component_id, "severity": severity,
        "window_days": window_days})
