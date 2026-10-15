from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.api.v1._util import Paging, page_body, paginate
from app.core.database import get_db
from app.core.deps import MANAGERS, get_current_user, require_roles
from app.core.errors import BusinessRuleError, NotFoundError
from app.models import Customer, Product, ProductModel, User, Warranty
from app.schemas.common import WarrantyExtendIn, WarrantyIn, WarrantyOut, WarrantyVoidIn
from app.services import audit, settings_service
from app.services import warranty as svc
from app.services.analytics import _rows

router = APIRouter(prefix="/warranties", tags=["warranties"])


def _effective_filter(effective: str):
    today = func.current_date()
    valid = Warranty.warranty_status == "Valid"
    return {
        "Active": and_(valid, Warranty.start_date <= today, Warranty.end_date >= today),
        "Pending": and_(valid, Warranty.start_date > today),
        "Expired": and_(valid, Warranty.end_date < today),
        "Voided": Warranty.warranty_status == "Voided",
        "Cancelled": Warranty.warranty_status == "Cancelled",
    }[effective]


@router.get("")
def list_warranties(
    q: str | None = Query(None, max_length=100, description="Serial number or customer"),
    effective_status: str | None = Query(None, pattern="^(Active|Pending|Expired|Voided|Cancelled)$"),
    warranty_type: str | None = None,
    product_id: int | None = None,
    category: str | None = None,
    expiring_within_days: int | None = Query(None, ge=1, le=730),
    sort: str = Query("end_date", pattern="^(end_date|-end_date|start_date|-start_date)$"),
    paging: Paging = Depends(),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = (select(Warranty, Product.serial_number, ProductModel.model_name, ProductModel.product_category,
                   Customer.full_name)
            .join(Product, Product.product_id == Warranty.product_id)
            .join(ProductModel, ProductModel.product_model_id == Product.product_model_id)
            .join(Customer, Customer.customer_id == Product.customer_id))
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Product.serial_number).like(like), func.lower(Customer.full_name).like(like)))
    if effective_status:
        stmt = stmt.where(_effective_filter(effective_status))
    if warranty_type:
        stmt = stmt.where(Warranty.warranty_type == warranty_type)
    if product_id:
        stmt = stmt.where(Warranty.product_id == product_id)
    if category:
        stmt = stmt.where(ProductModel.product_category == category)
    if expiring_within_days:
        stmt = stmt.where(_effective_filter("Active"),
                          Warranty.end_date <= date.today() + timedelta(days=expiring_within_days))
    col = Warranty.end_date if "end_date" in sort else Warranty.start_date
    stmt = stmt.order_by(col.desc() if sort.startswith("-") else col, Warranty.warranty_id)
    rows, total = paginate(db, stmt, paging)
    items = []
    for w, serial, model, cat, customer in rows:
        d = WarrantyOut.model_validate(w).model_dump()
        d.update(effective_status=svc.effective_status(w), days_remaining=(w.end_date - date.today()).days,
                 serial_number=serial, model_name=model, product_category=cat, customer_name=customer)
        items.append(d)
    return page_body(items, total, paging)


@router.get("/expiring")
def expiring(days: int | None = Query(None, ge=1, le=730), db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    days = days or int(settings_service.get_setting(db, "expiring_soon_days"))
    rows = _rows(db, """
        SELECT w.warranty_id, w.product_id, p.serial_number, pm.model_name, c.full_name AS customer_name,
               c.phone, c.email, w.warranty_type, w.end_date, w.days_remaining,
               EXISTS (SELECT 1 FROM warranties nxt WHERE nxt.product_id = w.product_id
                       AND nxt.warranty_status = 'Valid' AND nxt.start_date > w.end_date) AS has_follow_on
        FROM v_warranty_effective_status w
        JOIN products p ON p.product_id = w.product_id
        JOIN product_models pm ON pm.product_model_id = p.product_model_id
        JOIN customers c ON c.customer_id = p.customer_id
        WHERE w.effective_status = 'Active' AND w.days_remaining <= :days
        ORDER BY w.end_date""", {"days": days})
    return {"days": days, "items": rows}


@router.get("/coverage-check")
def coverage_check(product_id: int, fault_category_id: int, service_date: date | None = None,
                   db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    if db.get(Product, product_id) is None:
        raise NotFoundError(f"Product {product_id} not found.")
    decision = svc.check_product_coverage(db, product_id, service_date or date.today(), fault_category_id)
    return decision.as_dict() | {"service_date": str(service_date or date.today())}


@router.get("/claims")
def claims(covered: bool | None = None, paging: Paging = Depends(), db: Session = Depends(get_db),
           _: User = Depends(get_current_user)):
    """Historical warranty claims: service requests evaluated against a warranty."""
    where = "WHERE sr.warranty_id IS NOT NULL"
    params: dict = {"limit": paging.page_size, "offset": paging.offset}
    if covered is not None:
        where += " AND sr.warranty_covered = :covered"
        params["covered"] = covered
    total = _rows(db, f"SELECT COUNT(*) AS n FROM service_requests sr {where}", params)[0]["n"]
    items = _rows(db, f"""
        SELECT sr.service_request_id, sr.reported_at, p.serial_number, pm.model_name, fc.name AS fault_category,
               w.warranty_id, w.warranty_type, sr.warranty_covered, sr.coverage_notes, sr.request_status,
               COALESCE((SELECT SUM(warranty_cost) FROM v_repair_costs rc
                         WHERE rc.service_request_id = sr.service_request_id), 0) AS warranty_cost,
               COALESCE((SELECT SUM(total_cost) FROM v_repair_costs rc
                         WHERE rc.service_request_id = sr.service_request_id), 0) AS total_cost
        FROM service_requests sr
        JOIN warranties w ON w.warranty_id = sr.warranty_id
        JOIN products p ON p.product_id = sr.product_id
        JOIN product_models pm ON pm.product_model_id = p.product_model_id
        JOIN fault_categories fc ON fc.fault_category_id = sr.fault_category_id
        {where} ORDER BY sr.reported_at DESC LIMIT :limit OFFSET :offset""", params)
    return page_body(items, total, paging)


@router.get("/expenditure")
def expenditure(months: int = Query(24, ge=1, le=60), db: Session = Depends(get_db),
                _: User = Depends(get_current_user)):
    monthly = _rows(db, """
        SELECT to_char(month, 'YYYY-MM') AS month, repairs, warranty_repairs, total_repair_cost, warranty_cost,
               customer_cost
        FROM v_monthly_warranty_expenditure
        WHERE month >= date_trunc('month', now()) - make_interval(months => :m - 1) ORDER BY month""", {"m": months})
    by_type = _rows(db, """
        SELECT COALESCE(w.warranty_type, 'No warranty') AS warranty_type, COUNT(*) AS repairs,
               SUM(rc.warranty_cost) AS warranty_cost, SUM(rc.total_cost) AS total_cost
        FROM v_repair_costs rc JOIN service_requests sr ON sr.service_request_id = rc.service_request_id
        LEFT JOIN warranties w ON w.warranty_id = sr.warranty_id
        GROUP BY 1 ORDER BY warranty_cost DESC""")
    by_category = _rows(db, """
        SELECT pm.product_category AS category, SUM(rc.warranty_cost) AS warranty_cost, COUNT(*) AS repairs
        FROM v_repair_costs rc JOIN products p ON p.product_id = rc.product_id
        JOIN product_models pm ON pm.product_model_id = p.product_model_id
        GROUP BY 1 ORDER BY warranty_cost DESC""")
    return {"monthly": monthly, "by_type": by_type, "by_category": by_category}


@router.post("", response_model=WarrantyOut, status_code=status.HTTP_201_CREATED)
def register_warranty(body: WarrantyIn, db: Session = Depends(get_db), user: User = Depends(require_roles(*MANAGERS))):
    product = db.get(Product, body.product_id)
    if product is None:
        raise NotFoundError(f"Product {body.product_id} not found.")
    if body.start_date < product.purchase_date:
        raise BusinessRuleError("A warranty cannot start before the product's purchase date.")
    if body.warranty_type == "Manufacturer" and body.parent_warranty_id:
        raise BusinessRuleError("A manufacturer warranty cannot have a parent warranty.")
    if body.parent_warranty_id:
        parent = db.get(Warranty, body.parent_warranty_id)
        if parent is None or parent.product_id != body.product_id:
            raise BusinessRuleError("Parent warranty must belong to the same product.")
    w = Warranty(**body.model_dump(), extended_warranty=body.warranty_type != "Manufacturer")
    db.add(w)
    db.flush()
    audit.log(db, "warranty_registered", "warranty", w.warranty_id, user.user_id,
              {"product_id": body.product_id, "type": body.warranty_type})
    db.commit()
    return WarrantyOut.model_validate(w).model_copy(update={"effective_status": svc.effective_status(w)})


@router.post("/{warranty_id}/extend", response_model=WarrantyOut, status_code=status.HTTP_201_CREATED)
def extend(warranty_id: int, body: WarrantyExtendIn, db: Session = Depends(get_db),
           user: User = Depends(require_roles(*MANAGERS))):
    base = db.get(Warranty, warranty_id)
    if base is None:
        raise NotFoundError(f"Warranty {warranty_id} not found.")
    ext = svc.extend_warranty(db, base, user_id=user.user_id, **body.model_dump())
    db.commit()
    return WarrantyOut.model_validate(ext).model_copy(update={"effective_status": svc.effective_status(ext)})


@router.post("/{warranty_id}/void", response_model=WarrantyOut)
def void(warranty_id: int, body: WarrantyVoidIn, db: Session = Depends(get_db),
         user: User = Depends(require_roles(*MANAGERS))):
    w = db.get(Warranty, warranty_id)
    if w is None:
        raise NotFoundError(f"Warranty {warranty_id} not found.")
    if w.warranty_status != "Valid":
        raise BusinessRuleError(f"Warranty is already {w.warranty_status.lower()}.")
    w.warranty_status = body.status
    w.coverage_details = (w.coverage_details or "") + f" [{body.status.upper()} {date.today()}: {body.reason}]"
    audit.log(db, "warranty_" + body.status.lower(), "warranty", warranty_id, user.user_id, {"reason": body.reason})
    db.commit()
    return WarrantyOut.model_validate(w).model_copy(update={"effective_status": svc.effective_status(w)})
