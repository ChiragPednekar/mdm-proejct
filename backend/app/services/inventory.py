"""Spare-parts inventory operations.

All functions only *flush*; the caller owns the transaction and commits once,
so a repair and its stock deductions succeed or fail together.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, InsufficientStockError, NotFoundError
from app.models import InventoryTransaction, Part, RepairHistory, RepairPart
from app.services import audit


@dataclass
class PartLine:
    part_id: int
    quantity: int


def lock_parts(db: Session, part_ids: list[int]) -> dict[int, Part]:
    """SELECT ... FOR UPDATE in a stable order (avoids deadlocks between
    concurrent repairs touching the same parts)."""
    rows = db.scalars(
        select(Part).where(Part.part_id.in_(sorted(set(part_ids)))).order_by(Part.part_id).with_for_update()
    ).all()
    return {p.part_id: p for p in rows}


def consume_parts_for_repair(
    db: Session,
    repair: RepairHistory,
    lines: list[PartLine],
    user_id: int | None = None,
    at: datetime | None = None,
) -> Decimal:
    """Deduct stock, write repair_parts lines and consumption transactions.

    Returns the parts cost (sum of quantity x unit cost at time of repair).
    Raises before any change if a line is invalid or stock is insufficient.
    """
    if not lines:
        return Decimal("0.00")
    ids = [l.part_id for l in lines]
    if len(ids) != len(set(ids)):
        raise BusinessRuleError("Each part may appear only once per repair; combine the quantities.")
    if any(l.quantity <= 0 for l in lines):
        raise BusinessRuleError("Part quantities must be positive.")

    parts = lock_parts(db, ids)
    missing = [i for i in ids if i not in parts]
    if missing:
        raise NotFoundError(f"Part(s) not found: {missing}")
    shortages = [
        {"part_id": l.part_id, "part_number": parts[l.part_id].part_number,
         "requested": l.quantity, "available": parts[l.part_id].stock_quantity}
        for l in lines
        if parts[l.part_id].stock_quantity < l.quantity
    ]
    if shortages:
        raise InsufficientStockError("Insufficient stock for one or more parts; nothing was deducted.", shortages)

    total = Decimal("0.00")
    for l in lines:
        part = parts[l.part_id]
        part.stock_quantity -= l.quantity
        db.add(RepairPart(
            repair_id=repair.repair_id, part_id=part.part_id,
            quantity_used=l.quantity, unit_cost_at_repair=part.unit_cost,
        ))
        db.add(InventoryTransaction(
            part_id=part.part_id,
            transaction_type="Repair Consumption",
            quantity_change=-l.quantity,
            stock_after=part.stock_quantity,
            repair_id=repair.repair_id,
            reason=f"Used in repair #{repair.repair_id}",
            user_id=user_id,
            **({"created_at": at} if at else {}),
        ))
        total += part.unit_cost * l.quantity
    db.flush()
    audit.log(db, "inventory_consumed", "repair", repair.repair_id, user_id,
              {"lines": [{"part_id": l.part_id, "quantity": l.quantity} for l in lines]})
    return total.quantize(Decimal("0.01"))


def adjust_stock(
    db: Session, part_id: int, quantity_change: int, transaction_type: str, reason: str, user_id: int | None
) -> Part:
    """Restock (positive) or authorized adjustment (either sign)."""
    if transaction_type not in ("Restock", "Adjustment"):
        raise BusinessRuleError("Only Restock and Adjustment transactions can be recorded manually.")
    if quantity_change == 0:
        raise BusinessRuleError("Quantity change cannot be zero.")
    if transaction_type == "Restock" and quantity_change < 0:
        raise BusinessRuleError("A restock must add stock; use an Adjustment to remove stock.")
    if not reason or not reason.strip():
        raise BusinessRuleError("A reason is required for inventory changes.")
    part = lock_parts(db, [part_id]).get(part_id)
    if part is None:
        raise NotFoundError(f"Part {part_id} not found.")
    new_qty = part.stock_quantity + quantity_change
    if new_qty < 0:
        raise InsufficientStockError(
            f"Adjustment would make stock negative ({part.stock_quantity} + {quantity_change}).",
            {"available": part.stock_quantity},
        )
    part.stock_quantity = new_qty
    db.add(InventoryTransaction(
        part_id=part.part_id, transaction_type=transaction_type, quantity_change=quantity_change,
        stock_after=new_qty, reason=reason.strip(), user_id=user_id,
    ))
    db.flush()
    audit.log(db, "inventory_" + transaction_type.lower(), "part", part.part_id, user_id,
              {"quantity_change": quantity_change, "stock_after": new_qty, "reason": reason})
    return part
