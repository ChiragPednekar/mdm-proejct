"""Warranty status and coverage rules.

Coverage is decided from the warranty's dates and terms plus the fault
category's exclusion flags. An "active" warranty does NOT automatically cover
every repair: customer-induced damage and wear-and-tear are excluded unless the
warranty explicitly includes them, and non-failure visits (installation,
preventive maintenance) are never warranty claims.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, NotFoundError
from app.models import FaultCategory, Product, Warranty
from app.services import audit

# When several warranties are in force, prefer the most specific one.
_TYPE_PRIORITY = {"Accidental Damage Protection": 0, "Manufacturer": 1, "Extended": 2}


def effective_status(w: Warranty, on: date | None = None) -> str:
    """Status derived from administrative state + dates."""
    on = on or date.today()
    if w.warranty_status != "Valid":
        return w.warranty_status
    if on < w.start_date:
        return "Pending"
    if on > w.end_date:
        return "Expired"
    return "Active"


@dataclass
class CoverageDecision:
    covered: bool
    warranty_id: int | None
    covers_parts: bool = False
    covers_labor: bool = False
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "covered": self.covered,
            "warranty_id": self.warranty_id,
            "covers_parts": self.covers_parts,
            "covers_labor": self.covers_labor,
            "reasons": self.reasons,
        }


def evaluate_coverage(w: Warranty, service_date: date, fault: FaultCategory) -> CoverageDecision:
    """Decide whether one warranty covers a repair for ``fault`` on ``service_date``."""
    reasons: list[str] = []
    if w.warranty_status != "Valid":
        reasons.append(f"Warranty #{w.warranty_id} is {w.warranty_status.lower()}.")
    if service_date < w.start_date:
        reasons.append(f"Service date {service_date} is before coverage starts ({w.start_date}).")
    if service_date > w.end_date:
        reasons.append(f"Warranty #{w.warranty_id} expired on {w.end_date}.")
    if not fault.counts_as_failure:
        reasons.append(f"'{fault.name}' is a non-failure service visit and is not a warranty claim.")
    if fault.is_customer_induced and not w.covers_accidental_damage:
        reasons.append(f"'{fault.name}' is customer-induced damage, excluded by this {w.warranty_type} warranty.")
    if fault.is_wear_and_tear and not w.covers_wear_and_tear:
        reasons.append(f"'{fault.name}' is wear and tear, excluded by this {w.warranty_type} warranty.")
    if not (w.covers_parts or w.covers_labor):
        reasons.append("Warranty covers neither parts nor labor.")

    if reasons:
        return CoverageDecision(False, w.warranty_id, reasons=reasons)
    terms = []
    terms.append("parts" if w.covers_parts else None)
    terms.append("labor" if w.covers_labor else None)
    covered_terms = " and ".join(t for t in terms if t)
    return CoverageDecision(
        True,
        w.warranty_id,
        covers_parts=w.covers_parts,
        covers_labor=w.covers_labor,
        reasons=[f"Covered by {w.warranty_type} warranty #{w.warranty_id} ({covered_terms})."],
    )


def determine_coverage(warranties: list[Warranty], service_date: date, fault: FaultCategory) -> CoverageDecision:
    """Pick the applicable warranty among a product's warranties."""
    if not warranties:
        return CoverageDecision(False, None, reasons=["No warranty is registered for this product."])
    decisions = [
        (evaluate_coverage(w, service_date, fault), w)
        for w in sorted(warranties, key=lambda w: (_TYPE_PRIORITY.get(w.warranty_type, 9), w.start_date))
    ]
    for decision, _ in decisions:
        if decision.covered:
            return decision
    # Not covered: report the warranty that was in force on that date, if any,
    # because its exclusion reasons are the relevant explanation.
    in_force = [
        (d, w)
        for d, w in decisions
        if w.start_date <= service_date <= w.end_date and w.warranty_status == "Valid"
    ]
    if in_force:
        d, _ = in_force[0]
        return CoverageDecision(False, d.warranty_id, reasons=d.reasons)
    latest = max(warranties, key=lambda w: w.end_date)
    return CoverageDecision(
        False,
        None,
        reasons=[f"No warranty in force on {service_date}; latest coverage ended {latest.end_date}."],
    )


def check_product_coverage(db: Session, product_id: int, service_date: date, fault_category_id: int) -> CoverageDecision:
    fault = db.get(FaultCategory, fault_category_id)
    if fault is None:
        raise NotFoundError(f"Fault category {fault_category_id} not found.")
    warranties = list(db.scalars(select(Warranty).where(Warranty.product_id == product_id)))
    return determine_coverage(warranties, service_date, fault)


def register_manufacturer_warranty(db: Session, product: Product, user_id: int | None = None) -> Warranty:
    months = product.product_model.standard_warranty_months
    w = Warranty(
        product_id=product.product_id,
        warranty_type="Manufacturer",
        start_date=product.purchase_date,
        end_date=add_months(product.purchase_date, months) - timedelta(days=1),
        coverage_details=f"Standard {months}-month manufacturer warranty covering defects in materials and "
        "workmanship (parts and labor). Excludes physical/liquid damage and normal wear.",
        covers_parts=True,
        covers_labor=True,
        extended_warranty=False,
    )
    db.add(w)
    db.flush()
    audit.log(db, "warranty_registered", "warranty", w.warranty_id, user_id, {"product_id": product.product_id})
    return w


def extend_warranty(
    db: Session,
    base: Warranty,
    months: int,
    warranty_type: str = "Extended",
    covers_parts: bool = True,
    covers_labor: bool = True,
    covers_wear_and_tear: bool = False,
    covers_accidental_damage: bool = False,
    coverage_details: str | None = None,
    today: date | None = None,
    user_id: int | None = None,
) -> Warranty:
    """Create an extension that starts the day after the latest coverage ends.

    An extension can only be purchased while the product still has (or will
    have) valid coverage; a lapsed warranty cannot be extended retroactively.
    """
    today = today or date.today()
    if warranty_type == "Manufacturer":
        raise BusinessRuleError("An extension cannot be a manufacturer warranty.")
    if base.warranty_status != "Valid":
        raise BusinessRuleError(f"Cannot extend a {base.warranty_status.lower()} warranty.")
    if not 1 <= months <= 60:
        raise BusinessRuleError("Extension length must be between 1 and 60 months.")
    chain_end = db.scalar(
        select(Warranty.end_date)
        .where(Warranty.product_id == base.product_id, Warranty.warranty_status == "Valid")
        .order_by(Warranty.end_date.desc())
        .limit(1)
    )
    if chain_end < today:
        raise BusinessRuleError(
            f"Coverage for this product lapsed on {chain_end}; expired warranties cannot be extended."
        )
    start = chain_end + timedelta(days=1)
    ext = Warranty(
        product_id=base.product_id,
        parent_warranty_id=base.warranty_id,
        warranty_type=warranty_type,
        start_date=start,
        end_date=add_months(start, months) - timedelta(days=1),
        coverage_details=coverage_details
        or f"{months}-month {warranty_type.lower()} purchased as an extension of warranty #{base.warranty_id}.",
        covers_parts=covers_parts,
        covers_labor=covers_labor,
        covers_wear_and_tear=covers_wear_and_tear,
        covers_accidental_damage=covers_accidental_damage,
        extended_warranty=True,
    )
    db.add(ext)
    db.flush()
    audit.log(
        db,
        "warranty_extended",
        "warranty",
        ext.warranty_id,
        user_id,
        {"parent_warranty_id": base.warranty_id, "months": months, "end_date": str(ext.end_date)},
    )
    return ext


def add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp day to the target month's length.
    for day in (d.day, 30, 29, 28):
        try:
            return date(year, month, min(d.day, day))
        except ValueError:
            continue
    raise ValueError("unreachable")
