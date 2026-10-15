from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.v1._util import Paging, page_body, paginate
from app.core.database import get_db
from app.core.deps import MANAGERS, get_current_user, require_roles
from app.core.errors import NotFoundError
from app.models import Component, InventoryTransaction, Part, User
from app.schemas.common import PartIn, PartOut, PartUpdate, StockAdjustIn
from app.services import audit, inventory as svc
from app.services.analytics import _rows

router = APIRouter(prefix="/inventory", tags=["inventory"])


def _part_out(p: Part, component_name: str | None) -> dict:
    return PartOut.model_validate(p).model_copy(update={
        "component_name": component_name, "low_stock": p.stock_quantity <= p.reorder_level}).model_dump()


@router.get("/parts")
def list_parts(
    q: str | None = Query(None, max_length=100),
    component_id: int | None = None,
    low_stock: bool = False,
    sort: str = Query("part_number", pattern="^(part_number|stock|shortfall|cost)$"),
    paging: Paging = Depends(),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(Part, Component.component_name).outerjoin(Component, Component.component_id == Part.component_id)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Part.part_number).like(like), func.lower(Part.part_name).like(like),
                              func.lower(Part.supplier_name).like(like)))
    if component_id:
        stmt = stmt.where(Part.component_id == component_id)
    if low_stock:
        stmt = stmt.where(Part.stock_quantity <= Part.reorder_level)
    order = {"part_number": Part.part_number, "stock": Part.stock_quantity,
             "shortfall": (Part.stock_quantity - Part.reorder_level), "cost": Part.unit_cost.desc()}[sort]
    rows, total = paginate(db, stmt.order_by(order, Part.part_id), paging)
    return page_body([_part_out(p, c) for p, c in rows], total, paging)


@router.get("/low-stock")
def low_stock(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return _rows(db, "SELECT * FROM v_low_stock_parts ORDER BY shortfall DESC, part_number")


@router.post("/parts", status_code=status.HTTP_201_CREATED)
def create_part(body: PartIn, db: Session = Depends(get_db), user: User = Depends(require_roles(*MANAGERS))):
    if body.component_id and db.get(Component, body.component_id) is None:
        raise NotFoundError(f"Component {body.component_id} not found.")
    data = body.model_dump(exclude={"initial_stock"})
    p = Part(**data, stock_quantity=body.initial_stock)
    db.add(p)
    db.flush()
    if body.initial_stock:
        db.add(InventoryTransaction(part_id=p.part_id, transaction_type="Initial Stock",
                                    quantity_change=body.initial_stock, stock_after=body.initial_stock,
                                    reason="Opening balance", user_id=user.user_id))
    audit.log(db, "part_created", "part", p.part_id, user.user_id, {"part_number": p.part_number})
    db.commit()
    return _part_out(p, p.component.component_name if p.component else None)


@router.get("/parts/{part_id}")
def part_detail(part_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    p = db.get(Part, part_id)
    if p is None:
        raise NotFoundError(f"Part {part_id} not found.")
    usage = _rows(db, """
        SELECT r.repair_id, r.service_request_id, r.repair_date, pr.serial_number, rp.quantity_used,
               rp.unit_cost_at_repair, rp.quantity_used * rp.unit_cost_at_repair AS line_total
        FROM repair_parts rp JOIN repair_history r ON r.repair_id = rp.repair_id
        JOIN service_requests sr ON sr.service_request_id = r.service_request_id
        JOIN products pr ON pr.product_id = sr.product_id
        WHERE rp.part_id = :pid ORDER BY r.repair_date DESC LIMIT 50""", {"pid": part_id})
    monthly = _rows(db, """
        SELECT to_char(date_trunc('month', created_at), 'YYYY-MM') AS month,
               -SUM(quantity_change) AS consumed
        FROM inventory_transactions WHERE part_id = :pid AND transaction_type = 'Repair Consumption'
          AND created_at >= now() - INTERVAL '12 months'
        GROUP BY 1 ORDER BY 1""", {"pid": part_id})
    txns = _rows(db, """
        SELECT t.inventory_transaction_id, t.created_at, t.transaction_type, t.quantity_change, t.stock_after,
               t.repair_id, t.reason, u.username
        FROM inventory_transactions t LEFT JOIN users u ON u.user_id = t.user_id
        WHERE t.part_id = :pid ORDER BY t.created_at DESC, t.inventory_transaction_id DESC LIMIT 100""",
                 {"pid": part_id})
    return {"part": _part_out(p, p.component.component_name if p.component else None), "usage": usage,
            "monthly_consumption": monthly, "transactions": txns}


@router.patch("/parts/{part_id}")
def update_part(part_id: int, body: PartUpdate, db: Session = Depends(get_db),
                user: User = Depends(require_roles(*MANAGERS))):
    p = db.get(Part, part_id)
    if p is None:
        raise NotFoundError(f"Part {part_id} not found.")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("component_id") and db.get(Component, changes["component_id"]) is None:
        raise NotFoundError(f"Component {changes['component_id']} not found.")
    for k, v in changes.items():
        setattr(p, k, v)
    # Historical repairs keep unit_cost_at_repair; changing unit_cost affects only future repairs.
    audit.log(db, "part_updated", "part", part_id, user.user_id, {k: str(v) for k, v in changes.items()})
    db.commit()
    db.refresh(p)
    return _part_out(p, p.component.component_name if p.component else None)


@router.post("/parts/{part_id}/adjust")
def adjust(part_id: int, body: StockAdjustIn, db: Session = Depends(get_db),
           user: User = Depends(require_roles(*MANAGERS))):
    p = svc.adjust_stock(db, part_id, body.quantity_change, body.transaction_type, body.reason, user.user_id)
    db.commit()
    db.refresh(p)
    return _part_out(p, p.component.component_name if p.component else None)


@router.get("/transactions")
def transactions(part_id: int | None = None, transaction_type: str | None = None, paging: Paging = Depends(),
                 db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    where, params = ["1=1"], {"limit": paging.page_size, "offset": paging.offset}
    if part_id:
        where.append("t.part_id = :part_id")
        params["part_id"] = part_id
    if transaction_type:
        where.append("t.transaction_type = :tt")
        params["tt"] = transaction_type
    w = " AND ".join(where)
    total = _rows(db, f"SELECT COUNT(*) AS n FROM inventory_transactions t WHERE {w}", params)[0]["n"]
    items = _rows(db, f"""
        SELECT t.inventory_transaction_id, t.created_at, t.transaction_type, t.quantity_change, t.stock_after,
               t.repair_id, t.reason, p.part_id, p.part_number, p.part_name, u.username
        FROM inventory_transactions t JOIN parts p ON p.part_id = t.part_id
        LEFT JOIN users u ON u.user_id = t.user_id
        WHERE {w} ORDER BY t.created_at DESC, t.inventory_transaction_id DESC LIMIT :limit OFFSET :offset""", params)
    return page_body(items, total, paging)


@router.get("/cost-analysis")
def cost_analysis(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return {
        "by_part": _rows(db, """SELECT * FROM v_part_consumption WHERE total_quantity_used > 0
                                ORDER BY total_cost_at_repair DESC LIMIT 15"""),
        "by_component": _rows(db, """
            SELECT COALESCE(component_name, 'Unassigned') AS component_name,
                   SUM(total_quantity_used) AS quantity, SUM(total_cost_at_repair) AS cost
            FROM v_part_consumption GROUP BY 1 HAVING SUM(total_quantity_used) > 0 ORDER BY cost DESC"""),
        "stock_value": _rows(db, "SELECT COALESCE(SUM(stock_quantity * unit_cost), 0) AS value, "
                                 "SUM(stock_quantity) AS units FROM parts")[0],
    }
