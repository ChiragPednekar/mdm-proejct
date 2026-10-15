"""Service-request lifecycle: registration, warranty check, assignment,
repair attempts (with transactional inventory consumption) and resolution.

State machine::

    Open ──► Assigned ──► In Progress ──► Resolved ──► Closed
     │  ◄──────┘  │            ▲              │
     └──► Cancelled ◄┘          └── (reopen) ──┘

Functions here flush but never commit: the API layer commits once per
request, so any failure rolls back the whole unit of work.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError, InvalidTransitionError, NotFoundError
from app.models import (
    FaultCategory,
    Product,
    RepairHistory,
    ServiceRequest,
    Technician,
)
from app.services import audit, inventory, settings_service, warranty

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "Open": {"Assigned", "Cancelled"},
    "Assigned": {"Open", "In Progress", "Cancelled"},
    "In Progress": {"Resolved", "Cancelled"},
    "Resolved": {"Closed", "In Progress"},
    "Closed": set(),
    "Cancelled": set(),
}
# Transitions that must go through a dedicated workflow endpoint.
_WORKFLOW_ONLY = {("In Progress", "Resolved")}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_request(db: Session, request_id: int, lock: bool = False) -> ServiceRequest:
    stmt = select(ServiceRequest).where(ServiceRequest.service_request_id == request_id)
    if lock:
        stmt = stmt.with_for_update()
    sr = db.scalar(stmt)
    if sr is None:
        raise NotFoundError(f"Service request {request_id} not found.")
    return sr


def _active_technician(db: Session, technician_id: int) -> Technician:
    tech = db.get(Technician, technician_id)
    if tech is None:
        raise NotFoundError(f"Technician {technician_id} not found.")
    if tech.employment_status != "Active":
        raise BusinessRuleError(f"Technician {tech.full_name} is {tech.employment_status.lower()}.")
    return tech


def create_request(
    db: Session,
    product_id: int,
    fault_category_id: int,
    complaint_description: str,
    priority: str = "Medium",
    failure_severity: str = "Moderate",
    reported_at: datetime | None = None,
    assigned_technician_id: int | None = None,
    user_id: int | None = None,
) -> ServiceRequest:
    product = db.get(Product, product_id)
    if product is None:
        raise NotFoundError(f"Product {product_id} not found.")
    if product.product_status in ("Retired", "Replaced"):
        raise BusinessRuleError(f"Product is {product.product_status.lower()}; new complaints cannot be registered.")
    reported_at = reported_at or utcnow()
    if reported_at > utcnow() + timedelta(minutes=5):
        raise BusinessRuleError("reported_at cannot be in the future.")
    if reported_at.date() < product.purchase_date:
        raise BusinessRuleError("A complaint cannot predate the product's purchase date.")
    open_dupe = db.scalar(
        select(ServiceRequest.service_request_id).where(
            ServiceRequest.product_id == product_id,
            ServiceRequest.fault_category_id == fault_category_id,
            ServiceRequest.request_status.in_(("Open", "Assigned", "In Progress")),
        )
    )
    if open_dupe:
        raise ConflictError(
            f"Service request #{open_dupe} for this product and fault category is still open.",
            {"service_request_id": open_dupe},
        )

    decision = warranty.check_product_coverage(db, product_id, reported_at.date(), fault_category_id)
    sr = ServiceRequest(
        product_id=product_id,
        warranty_id=decision.warranty_id,
        complaint_description=complaint_description.strip(),
        fault_category_id=fault_category_id,
        reported_at=reported_at,
        priority=priority,
        failure_severity=failure_severity,
        request_status="Open",
        warranty_covered=decision.covered,
        coverage_notes=" ".join(decision.reasons),
    )
    if assigned_technician_id is not None:
        _active_technician(db, assigned_technician_id)
        sr.assigned_technician_id = assigned_technician_id
        sr.request_status = "Assigned"
    db.add(sr)
    db.flush()
    audit.log(db, "service_request_created", "service_request", sr.service_request_id, user_id,
              {"product_id": product_id, "coverage": decision.as_dict()})
    return sr


def transition(db: Session, sr: ServiceRequest, new_status: str, user_id: int | None = None,
               *, via_workflow: bool = False) -> None:
    old = sr.request_status
    if new_status == old:
        return
    if new_status not in ALLOWED_TRANSITIONS.get(old, set()):
        raise InvalidTransitionError(f"Cannot move a request from '{old}' to '{new_status}'.",
                                     {"allowed": sorted(ALLOWED_TRANSITIONS.get(old, set()))})
    if (old, new_status) in _WORKFLOW_ONLY and not via_workflow:
        raise InvalidTransitionError("Use the complete workflow to resolve a request (it records the outcome).")
    if new_status in ("Assigned", "In Progress") and sr.assigned_technician_id is None:
        raise BusinessRuleError("Assign a technician first.")
    if new_status == "Cancelled" and sr.repairs:
        raise InvalidTransitionError("A request with recorded repairs cannot be cancelled.")
    if new_status == "Open":
        sr.assigned_technician_id = None
    if old == "Resolved" and new_status == "In Progress":  # reopened
        sr.resolution_date = None
    sr.request_status = new_status
    product = sr.product
    if new_status == "In Progress" and product.product_status == "Active":
        product.product_status = "Under Repair"
    if new_status == "Cancelled" and product.product_status == "Under Repair":
        product.product_status = "Active"
    db.flush()
    audit.log(db, "service_request_status_changed", "service_request", sr.service_request_id, user_id,
              {"from": old, "to": new_status})


def update_request(db: Session, sr: ServiceRequest, changes: dict, user_id: int | None = None) -> ServiceRequest:
    if sr.request_status in ("Closed", "Cancelled"):
        raise InvalidTransitionError(f"A {sr.request_status.lower()} request cannot be modified.")
    for key in ("priority", "failure_severity", "complaint_description"):
        if changes.get(key) is not None:
            setattr(sr, key, changes[key])
    if "assigned_technician_id" in changes and changes["assigned_technician_id"] is not None:
        _active_technician(db, changes["assigned_technician_id"])
        sr.assigned_technician_id = changes["assigned_technician_id"]
        if sr.request_status == "Open" and not changes.get("request_status"):
            transition(db, sr, "Assigned", user_id)
    if changes.get("request_status"):
        transition(db, sr, changes["request_status"], user_id)
    db.flush()
    return sr


@dataclass
class RepairInput:
    technician_id: int
    diagnosis: str
    repair_action: str
    outcome: str
    labor_cost: Decimal
    root_cause: str | None = None
    component_id: int | None = None
    parts: list[inventory.PartLine] = field(default_factory=list)
    repair_date: datetime | None = None
    idempotency_key: str | None = None


def is_repeat_failure(db: Session, sr: ServiceRequest) -> bool:
    window = int(settings_service.get_setting(db, "repeat_failure_window_days"))
    prior = db.scalar(
        select(func.count(RepairHistory.repair_id))
        .join(ServiceRequest, ServiceRequest.service_request_id == RepairHistory.service_request_id)
        .where(
            ServiceRequest.product_id == sr.product_id,
            ServiceRequest.service_request_id != sr.service_request_id,
            RepairHistory.repair_date < sr.reported_at,
            RepairHistory.repair_date >= sr.reported_at - timedelta(days=window),
        )
    )
    return bool(prior)


def add_repair(db: Session, sr: ServiceRequest, data: RepairInput, user_id: int | None = None) -> RepairHistory:
    """Record one repair attempt and consume its parts atomically."""
    if data.idempotency_key:
        existing = db.scalar(select(RepairHistory).where(RepairHistory.idempotency_key == data.idempotency_key))
        if existing is not None:
            if existing.service_request_id != sr.service_request_id:
                raise ConflictError("Idempotency key already used for a different service request.")
            return existing  # duplicate submission: no second deduction

    if sr.request_status == "Assigned":
        transition(db, sr, "In Progress", user_id)
    if sr.request_status != "In Progress":
        raise InvalidTransitionError(
            f"Repairs can only be recorded while a request is In Progress (current: {sr.request_status})."
        )
    _active_technician(db, data.technician_id)
    if data.labor_cost < 0:
        raise BusinessRuleError("Labor cost cannot be negative.")
    repair_date = data.repair_date or utcnow()
    if repair_date < sr.reported_at:
        raise BusinessRuleError("Repair date cannot be before the complaint was reported.")

    attempt = (db.scalar(
        select(func.max(RepairHistory.attempt_number)).where(RepairHistory.service_request_id == sr.service_request_id)
    ) or 0) + 1
    repair = RepairHistory(
        service_request_id=sr.service_request_id,
        technician_id=data.technician_id,
        component_id=data.component_id,
        attempt_number=attempt,
        diagnosis=data.diagnosis.strip(),
        root_cause=(data.root_cause or "").strip() or None,
        repair_action=data.repair_action.strip(),
        labor_cost=Decimal(data.labor_cost).quantize(Decimal("0.01")),
        parts_cost=Decimal("0.00"),
        repair_date=repair_date,
        outcome=data.outcome,
        repeat_failure=is_repeat_failure(db, sr),
        idempotency_key=data.idempotency_key,
    )
    db.add(repair)
    db.flush()  # assigns repair_id for the junction rows
    repair.parts_cost = inventory.consume_parts_for_repair(db, repair, data.parts, user_id)
    db.flush()
    audit.log(db, "repair_recorded", "repair", repair.repair_id, user_id, {
        "service_request_id": sr.service_request_id, "attempt": attempt, "outcome": data.outcome,
        "labor_cost": str(repair.labor_cost), "parts_cost": str(repair.parts_cost),
    })
    return repair


def complete_request(
    db: Session,
    sr: ServiceRequest,
    resolution_summary: str,
    final_repair: RepairInput | None = None,
    user_id: int | None = None,
) -> ServiceRequest:
    """Resolve a request. If ``final_repair`` is given it is recorded (with its
    inventory consumption) in the same transaction as the resolution."""
    if sr.request_status in ("Resolved", "Closed"):
        raise ConflictError(f"Service request #{sr.service_request_id} is already {sr.request_status.lower()}.")
    if sr.request_status == "Assigned":
        transition(db, sr, "In Progress", user_id)
    if sr.request_status != "In Progress":
        raise InvalidTransitionError(f"Cannot complete a request that is {sr.request_status}.")
    if final_repair is not None:
        add_repair(db, sr, final_repair, user_id)
    db.refresh(sr, ["repairs"])
    if not sr.repairs:
        raise BusinessRuleError("Record at least one repair before completing the request.")
    last = sr.repairs[-1]
    # Set the resolution fields before the status flush: the database CHECK
    # requires resolution_date for Resolved/Closed requests.
    sr.resolution_date = max(utcnow(), last.repair_date)
    sr.resolution_summary = resolution_summary.strip()
    transition(db, sr, "Resolved", user_id, via_workflow=True)
    product = sr.product
    if last.outcome == "Unit Replaced":
        product.product_status = "Replaced"
    elif product.product_status == "Under Repair":
        product.product_status = "Active"
    db.flush()
    audit.log(db, "service_request_completed", "service_request", sr.service_request_id, user_id, {
        "repairs": len(sr.repairs), "final_outcome": last.outcome,
    })
    return sr


def fault_category(db: Session, fault_category_id: int) -> FaultCategory:
    fc = db.get(FaultCategory, fault_category_id)
    if fc is None:
        raise NotFoundError(f"Fault category {fault_category_id} not found.")
    return fc
