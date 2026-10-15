"""Point-in-time feature engineering for failure-risk prediction.

The single function :func:`compute_features` is used both to build training
snapshots and to score a product live, so training and serving can't drift.

Leakage rules: every feature uses ONLY events strictly before ``cutoff``:
* service requests with ``reported_at < cutoff``
* repairs with ``repair_date < cutoff`` (a request reported before the cutoff
  whose repair happened afterwards contributes the request, not the repair)
* warranties are contracts whose dates are known at sale time; their start/end
  dates are therefore legitimately known in advance.
Nothing about resolutions, future labels or inventory is used.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

NUMERIC_FEATURES = [
    "product_age_days",
    "days_since_installation",
    "model_age_years",
    "purchase_price",
    "warranty_active",
    "warranty_days_remaining",
    "warranty_age_days",
    "has_extended_coverage",
    "prior_service_requests",
    "prior_failures",
    "failures_30d",
    "failures_90d",
    "failures_180d",
    "prior_repairs",
    "days_since_last_repair",
    "prior_parts_replaced",
    "prior_repair_cost",
    "prior_unresolved_attempts",
    "prior_customer_induced",
]
CATEGORICAL_FEATURES = ["product_category", "manufacturer", "product_model", "last_fault_category"]
FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES

# Families of correlated features, permuted together for grouped importance.
FEATURE_GROUPS = {
    "Recent failure & repair history": ["failures_30d", "failures_90d", "failures_180d", "days_since_last_repair",
                                        "prior_unresolved_attempts", "last_fault_category"],
    "Lifetime service history": ["prior_service_requests", "prior_failures", "prior_repairs", "prior_parts_replaced",
                                 "prior_repair_cost", "prior_customer_induced"],
    "Product identity": ["product_category", "manufacturer", "product_model", "purchase_price", "model_age_years"],
    "Unit age": ["product_age_days", "days_since_installation", "warranty_age_days"],
    "Warranty position": ["warranty_active", "warranty_days_remaining", "has_extended_coverage"],
}

FEATURE_LABELS = {
    "product_age_days": "product age (days)",
    "days_since_installation": "days since installation",
    "model_age_years": "model age (years since release)",
    "purchase_price": "purchase price",
    "warranty_active": "warranty in force",
    "warranty_days_remaining": "warranty days remaining",
    "warranty_age_days": "days since warranty start",
    "has_extended_coverage": "has extended/ADP coverage",
    "prior_service_requests": "previous service requests",
    "prior_failures": "previous failures",
    "failures_30d": "failures in last 30 days",
    "failures_90d": "failures in last 90 days",
    "failures_180d": "failures in last 180 days",
    "prior_repairs": "previous repairs",
    "days_since_last_repair": "days since last repair",
    "prior_parts_replaced": "parts replaced so far",
    "prior_repair_cost": "historical repair spend",
    "prior_unresolved_attempts": "unsuccessful repair attempts",
    "prior_customer_induced": "customer-induced incidents",
    "product_category": "product category",
    "manufacturer": "manufacturer",
    "product_model": "product model",
    "last_fault_category": "most recent fault category",
}


@dataclass
class RequestEvent:
    reported_at: datetime
    counts_as_failure: bool
    customer_induced: bool
    fault_name: str


@dataclass
class RepairEvent:
    repair_date: datetime
    outcome: str
    total_cost: float
    parts_qty: int


@dataclass
class WarrantyTerm:
    start_date: date
    end_date: date
    status: str
    warranty_type: str


@dataclass
class ProductHistory:
    product_id: int
    purchase_date: date
    installation_date: date | None
    purchase_price: float
    product_category: str
    manufacturer: str
    product_model: str
    release_year: int
    warranties: list[WarrantyTerm] = field(default_factory=list)
    requests: list[RequestEvent] = field(default_factory=list)
    repairs: list[RepairEvent] = field(default_factory=list)


def _days(a: date, b: date) -> int:
    return (a - b).days


def compute_features(h: ProductHistory, cutoff: datetime) -> dict:
    cdate = cutoff.date()
    reqs = [r for r in h.requests if r.reported_at < cutoff]
    reps = [r for r in h.repairs if r.repair_date < cutoff]
    failures = [r for r in reqs if r.counts_as_failure]

    def failures_within(days: int) -> int:
        start = cutoff - timedelta(days=days)
        return sum(1 for r in failures if r.reported_at >= start)

    in_force = [w for w in h.warranties if w.status == "Valid" and w.start_date <= cdate <= w.end_date]
    started = [w for w in h.warranties if w.start_date <= cdate]
    last_fault = max(reqs, key=lambda r: r.reported_at).fault_name if reqs else "None"
    last_repair = max((r.repair_date for r in reps), default=None)

    return {
        "product_age_days": _days(cdate, h.purchase_date),
        "days_since_installation": _days(cdate, h.installation_date) if h.installation_date else None,
        "model_age_years": cdate.year - h.release_year,
        "purchase_price": float(h.purchase_price),
        "warranty_active": int(bool(in_force)),
        "warranty_days_remaining": max((_days(w.end_date, cdate) for w in in_force), default=0),
        "warranty_age_days": _days(cdate, min(w.start_date for w in started)) if started else None,
        "has_extended_coverage": int(any(w.warranty_type != "Manufacturer" and w.start_date <= cdate for w in h.warranties)),
        "prior_service_requests": len(reqs),
        "prior_failures": len(failures),
        "failures_30d": failures_within(30),
        "failures_90d": failures_within(90),
        "failures_180d": failures_within(180),
        "prior_repairs": len(reps),
        "days_since_last_repair": (cutoff - last_repair).days if last_repair else None,
        "prior_parts_replaced": int(sum(r.parts_qty for r in reps)),
        "prior_repair_cost": round(float(sum(r.total_cost for r in reps)), 2),
        "prior_unresolved_attempts": sum(1 for r in reps if r.outcome in ("Not Fixed", "Partially Fixed")),
        "prior_customer_induced": sum(1 for r in reqs if r.customer_induced),
        "product_category": h.product_category,
        "manufacturer": h.manufacturer,
        "product_model": f"{h.manufacturer} {h.product_model}",
        "last_fault_category": last_fault,
    }


def target_label(h: ProductHistory, cutoff: datetime, horizon_days: int) -> int:
    """1 if a qualifying failure is reported in [cutoff, cutoff + horizon)."""
    end = cutoff + timedelta(days=horizon_days)
    return int(any(r.counts_as_failure and cutoff <= r.reported_at < end for r in h.requests))


def unit_replaced_before(h: ProductHistory, cutoff: datetime) -> bool:
    """A unit swapped out before the cutoff is no longer observable."""
    return any(r.outcome == "Unit Replaced" and r.repair_date < cutoff for r in h.repairs)
