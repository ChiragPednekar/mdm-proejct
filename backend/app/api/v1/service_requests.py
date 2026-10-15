from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.api.v1._util import Paging, page_body, paginate
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.errors import ForbiddenError
from app.models import (
    PRIORITIES,
    REQUEST_STATUSES,
    Component,
    Customer,
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
from app.schemas.common import CompleteIn, RepairIn, ServiceRequestIn, ServiceRequestUpdate
from app.services import service_requests as svc
from app.services.inventory import PartLine
from app.services.warranty import effective_status

router = APIRouter(prefix="/service-requests", tags=["service requests"])


def _repair_input(body: RepairIn) -> svc.RepairInput:
    return svc.RepairInput(
        technician_id=body.technician_id, diagnosis=body.diagnosis, repair_action=body.repair_action,
        outcome=body.outcome, labor_cost=body.labor_cost, root_cause=body.root_cause,
        component_id=body.component_id, parts=[PartLine(p.part_id, p.quantity) for p in body.parts],
        idempotency_key=body.idempotency_key,
    )


def _check_technician_scope(user: User, sr: ServiceRequest, technician_id: int | None = None) -> None:
    """Technicians may only work on their own assignments / record their own repairs."""
    if user.role != "technician":
        return
    if sr.assigned_technician_id not in (None, user.technician_id) or (
        technician_id is not None and technician_id != user.technician_id
    ):
        raise ForbiddenError("Technicians can only update requests assigned to them.")


@router.get("")
def list_requests(
    q: str | None = Query(None, max_length=100, description="Serial, customer, or complaint text"),
    status_: list[str] | None = Query(None, alias="status"),
    priority: str | None = None,
    severity: str | None = None,
    technician_id: int | None = None,
    product_id: int | None = None,
    fault_category_id: int | None = None,
    category: str | None = None,
    warranty_covered: bool | None = None,
    reported_from: date | None = None,
    reported_to: date | None = None,
    sort: str = Query("-reported_at", pattern="^-?(reported_at|priority|status)$"),
    paging: Paging = Depends(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = (
        select(ServiceRequest.service_request_id, ServiceRequest.product_id, Product.serial_number,
               ProductModel.model_name, ProductModel.product_category, Customer.full_name.label("customer_name"),
               FaultCategory.name.label("fault_category"), ServiceRequest.complaint_description,
               ServiceRequest.priority, ServiceRequest.failure_severity, ServiceRequest.request_status,
               ServiceRequest.reported_at, ServiceRequest.resolution_date, ServiceRequest.warranty_covered,
               Technician.full_name.label("technician_name"), ServiceRequest.assigned_technician_id)
        .join(Product, Product.product_id == ServiceRequest.product_id)
        .join(ProductModel, ProductModel.product_model_id == Product.product_model_id)
        .join(Customer, Customer.customer_id == Product.customer_id)
        .join(FaultCategory, FaultCategory.fault_category_id == ServiceRequest.fault_category_id)
        .outerjoin(Technician, Technician.technician_id == ServiceRequest.assigned_technician_id)
    )
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Product.serial_number).like(like), func.lower(Customer.full_name).like(like),
                              func.lower(ServiceRequest.complaint_description).like(like)))
    if status_:
        stmt = stmt.where(ServiceRequest.request_status.in_(status_))
    if priority:
        stmt = stmt.where(ServiceRequest.priority == priority)
    if severity:
        stmt = stmt.where(ServiceRequest.failure_severity == severity)
    if technician_id:
        stmt = stmt.where(ServiceRequest.assigned_technician_id == technician_id)
    if product_id:
        stmt = stmt.where(ServiceRequest.product_id == product_id)
    if fault_category_id:
        stmt = stmt.where(ServiceRequest.fault_category_id == fault_category_id)
    if category:
        stmt = stmt.where(ProductModel.product_category == category)
    if warranty_covered is not None:
        stmt = stmt.where(ServiceRequest.warranty_covered == warranty_covered)
    if reported_from:
        stmt = stmt.where(ServiceRequest.reported_at >= reported_from)
    if reported_to:
        stmt = stmt.where(func.date(ServiceRequest.reported_at) <= reported_to)
    key = sort.lstrip("-")
    col = {
        "reported_at": ServiceRequest.reported_at,
        "priority": case({v: i for i, v in enumerate(PRIORITIES)}, value=ServiceRequest.priority),
        "status": case({v: i for i, v in enumerate(REQUEST_STATUSES)}, value=ServiceRequest.request_status),
    }[key]
    stmt = stmt.order_by(col.desc() if sort.startswith("-") else col, ServiceRequest.service_request_id.desc())
    rows, total = paginate(db, stmt, paging)
    return page_body([dict(r._mapping) for r in rows], total, paging)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_request(body: ServiceRequestIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sr = svc.create_request(db, user_id=user.user_id, **body.model_dump())
    db.commit()
    return request_detail(sr.service_request_id, db, user)


@router.get("/{request_id}")
def request_detail(request_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    sr = svc.get_request(db, request_id)
    p: Product = sr.product
    w: Warranty | None = db.get(Warranty, sr.warranty_id) if sr.warranty_id else None
    repairs = db.execute(
        select(RepairHistory, Technician.full_name, Component.component_name)
        .join(Technician, Technician.technician_id == RepairHistory.technician_id)
        .outerjoin(Component, Component.component_id == RepairHistory.component_id)
        .where(RepairHistory.service_request_id == request_id).order_by(RepairHistory.attempt_number)
    ).all()
    lines = db.execute(
        select(RepairPart, Part.part_number, Part.part_name).join(Part, Part.part_id == RepairPart.part_id)
        .where(RepairPart.repair_id.in_([r[0].repair_id for r in repairs] or [-1]))
    ).all()
    parts_by: dict[int, list] = {}
    for rp, pn, name in lines:
        parts_by.setdefault(rp.repair_id, []).append({
            "part_id": rp.part_id, "part_number": pn, "part_name": name, "quantity_used": rp.quantity_used,
            "unit_cost_at_repair": float(rp.unit_cost_at_repair),
            "line_total": float(rp.unit_cost_at_repair * rp.quantity_used)})
    repair_list = []
    labor = parts = 0.0
    for r, tech, comp in repairs:
        labor += float(r.labor_cost)
        parts += float(r.parts_cost)
        repair_list.append({
            "repair_id": r.repair_id, "attempt_number": r.attempt_number, "technician_id": r.technician_id,
            "technician_name": tech, "component_id": r.component_id, "component_name": comp,
            "diagnosis": r.diagnosis, "root_cause": r.root_cause, "repair_action": r.repair_action,
            "labor_cost": float(r.labor_cost), "parts_cost": float(r.parts_cost),
            "total_cost": float(r.labor_cost + r.parts_cost), "repair_date": r.repair_date, "outcome": r.outcome,
            "repeat_failure": r.repeat_failure, "parts": parts_by.get(r.repair_id, [])})
    warranty_cost = 0.0
    if sr.warranty_covered and w is not None:
        warranty_cost = (labor if w.covers_labor else 0) + (parts if w.covers_parts else 0)
    allowed = svc.ALLOWED_TRANSITIONS.get(sr.request_status, set()) - {"Resolved"}
    if repair_list:  # mirrors the rule enforced in services.service_requests.transition
        allowed = allowed - {"Cancelled"}
    allowed = sorted(allowed)
    return {
        "service_request_id": sr.service_request_id, "request_status": sr.request_status,
        "complaint_description": sr.complaint_description, "priority": sr.priority,
        "failure_severity": sr.failure_severity, "reported_at": sr.reported_at,
        "resolution_date": sr.resolution_date, "resolution_summary": sr.resolution_summary,
        "fault_category": {"fault_category_id": sr.fault_category.fault_category_id, "name": sr.fault_category.name,
                           "is_customer_induced": sr.fault_category.is_customer_induced,
                           "is_wear_and_tear": sr.fault_category.is_wear_and_tear,
                           "counts_as_failure": sr.fault_category.counts_as_failure},
        "technician": ({"technician_id": sr.technician.technician_id, "full_name": sr.technician.full_name,
                        "specialization": sr.technician.specialization} if sr.technician else None),
        "product": {"product_id": p.product_id, "serial_number": p.serial_number,
                    "model_name": p.product_model.model_name, "manufacturer": p.product_model.manufacturer,
                    "product_category": p.product_model.product_category, "product_status": p.product_status,
                    "customer_name": p.customer.full_name, "customer_phone": p.customer.phone},
        "warranty": ({"warranty_id": w.warranty_id, "warranty_type": w.warranty_type, "start_date": w.start_date,
                      "end_date": w.end_date, "covers_parts": w.covers_parts, "covers_labor": w.covers_labor,
                      "effective_status": effective_status(w)} if w else None),
        "warranty_covered": sr.warranty_covered, "coverage_notes": sr.coverage_notes,
        "repairs": repair_list,
        "costs": {"labor": round(labor, 2), "parts": round(parts, 2), "total": round(labor + parts, 2),
                  "warranty": round(warranty_cost, 2), "customer": round(labor + parts - warranty_cost, 2)},
        "allowed_transitions": allowed,
        "can_record_repair": sr.request_status in ("Assigned", "In Progress"),
        "can_complete": sr.request_status in ("Assigned", "In Progress"),
    }


@router.patch("/{request_id}")
def update_request(request_id: int, body: ServiceRequestUpdate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    sr = svc.get_request(db, request_id, lock=True)
    _check_technician_scope(user, sr, body.assigned_technician_id)
    svc.update_request(db, sr, body.model_dump(exclude_unset=True), user.user_id)
    db.commit()
    return request_detail(request_id, db, user)


@router.post("/{request_id}/repairs", status_code=status.HTTP_201_CREATED)
def add_repair(request_id: int, body: RepairIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sr = svc.get_request(db, request_id, lock=True)  # serialises concurrent submissions
    _check_technician_scope(user, sr, body.technician_id)
    repair = svc.add_repair(db, sr, _repair_input(body), user.user_id)
    db.commit()
    return {"repair_id": repair.repair_id, "request": request_detail(request_id, db, user)}


@router.post("/{request_id}/complete")
def complete(request_id: int, body: CompleteIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sr = svc.get_request(db, request_id, lock=True)
    _check_technician_scope(user, sr, body.final_repair.technician_id if body.final_repair else None)
    svc.complete_request(db, sr, body.resolution_summary,
                         _repair_input(body.final_repair) if body.final_repair else None, user.user_id)
    db.commit()
    return request_detail(request_id, db, user)
