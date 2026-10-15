"""Extract product histories from PostgreSQL and build point-in-time snapshots."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ml.features import (
    FEATURE_COLUMNS,
    ProductHistory,
    RepairEvent,
    RequestEvent,
    WarrantyTerm,
    compute_features,
    target_label,
    unit_replaced_before,
)

_PRODUCTS_SQL = """
SELECT p.product_id, p.purchase_date, p.installation_date, p.purchase_price, p.product_status,
       pm.product_category, pm.manufacturer, pm.model_name, pm.release_year
FROM products p JOIN product_models pm ON pm.product_model_id = p.product_model_id
{where}
"""
_WARRANTIES_SQL = """
SELECT product_id, start_date, end_date, warranty_status, warranty_type FROM warranties {where}
"""
_REQUESTS_SQL = """
SELECT sr.product_id, sr.reported_at, fc.counts_as_failure, fc.is_customer_induced, fc.name AS fault_name
FROM service_requests sr JOIN fault_categories fc ON fc.fault_category_id = sr.fault_category_id
WHERE sr.request_status <> 'Cancelled' {and_where}
"""
_REPAIRS_SQL = """
SELECT sr.product_id, r.repair_date, r.outcome, (r.labor_cost + r.parts_cost) AS total_cost,
       COALESCE((SELECT SUM(rp.quantity_used) FROM repair_parts rp WHERE rp.repair_id = r.repair_id), 0) AS parts_qty
FROM repair_history r JOIN service_requests sr ON sr.service_request_id = r.service_request_id
{where}
"""


def load_histories(db: Session, product_ids: list[int] | None = None) -> dict[int, ProductHistory]:
    params: dict = {}
    if product_ids is not None:
        params["ids"] = list(product_ids)
        w_p, w_w, w_sr, w_r = (
            "WHERE p.product_id = ANY(:ids)", "WHERE product_id = ANY(:ids)",
            "AND sr.product_id = ANY(:ids)", "WHERE sr.product_id = ANY(:ids)",
        )
    else:
        w_p = w_w = w_sr = w_r = ""
    histories: dict[int, ProductHistory] = {}
    for row in db.execute(text(_PRODUCTS_SQL.format(where=w_p)), params).mappings():
        histories[row["product_id"]] = ProductHistory(
            product_id=row["product_id"],
            purchase_date=row["purchase_date"],
            installation_date=row["installation_date"],
            purchase_price=float(row["purchase_price"]),
            product_category=row["product_category"],
            manufacturer=row["manufacturer"],
            product_model=row["model_name"],
            release_year=row["release_year"],
        )
    for row in db.execute(text(_WARRANTIES_SQL.format(where=w_w)), params).mappings():
        if row["product_id"] in histories:
            histories[row["product_id"]].warranties.append(
                WarrantyTerm(row["start_date"], row["end_date"], row["warranty_status"], row["warranty_type"])
            )
    for row in db.execute(text(_REQUESTS_SQL.format(and_where=w_sr)), params).mappings():
        if row["product_id"] in histories:
            histories[row["product_id"]].requests.append(
                RequestEvent(row["reported_at"], row["counts_as_failure"], row["is_customer_induced"], row["fault_name"])
            )
    for row in db.execute(text(_REPAIRS_SQL.format(where=w_r)), params).mappings():
        if row["product_id"] in histories:
            histories[row["product_id"]].repairs.append(
                RepairEvent(row["repair_date"], row["outcome"], float(row["total_cost"]), int(row["parts_qty"]))
            )
    return histories


def monthly_cutoffs(first: date, last: date) -> list[datetime]:
    out = []
    d = date(first.year, first.month, 1)
    while d <= last:
        out.append(datetime(d.year, d.month, d.day, tzinfo=timezone.utc))
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def build_snapshots(
    histories: dict[int, ProductHistory], observation_end: datetime, horizon_days: int
) -> pd.DataFrame:
    """One row per (product, monthly cutoff) with features and a label.

    A snapshot is eligible only if
    * the product was purchased before the cutoff;
    * the unit had not been replaced before the cutoff; and
    * the full horizon has been observed: cutoff + horizon <= observation_end.
      Recent cutoffs are EXCLUDED rather than labelled negative, because the
      absence of a failure there is not yet known (right-censoring).
    """
    if not histories:
        return pd.DataFrame(columns=["product_id", "cutoff", *FEATURE_COLUMNS, "label"])
    earliest = min(h.purchase_date for h in histories.values())
    last_cutoff = (observation_end - timedelta(days=horizon_days)).date()
    rows = []
    for cutoff in monthly_cutoffs(earliest + timedelta(days=1), last_cutoff):
        for h in histories.values():
            if h.purchase_date >= cutoff.date() or unit_replaced_before(h, cutoff):
                continue
            feats = compute_features(h, cutoff)
            rows.append({"product_id": h.product_id, "cutoff": cutoff, **feats,
                         "label": target_label(h, cutoff, horizon_days)})
    return pd.DataFrame(rows)


def validate_dataset(df: pd.DataFrame) -> dict:
    """Data-quality checks; raises ValueError on a hard failure."""
    if df.empty:
        return {"rows": 0, "positives": 0, "issues": ["no eligible snapshots"]}
    issues = []
    if df["label"].isna().any() or not set(df["label"].unique()) <= {0, 1}:
        raise ValueError("Labels must be 0/1 with no missing values.")
    if (df["product_age_days"] < 0).any():
        raise ValueError("Negative product age: a snapshot predates its purchase.")
    if df.duplicated(["product_id", "cutoff"]).any():
        raise ValueError("Duplicate (product, cutoff) snapshots.")
    missing = {c: int(df[c].isna().sum()) for c in FEATURE_COLUMNS if df[c].isna().any()}
    if missing:
        issues.append(f"missing values imputed by the pipeline: {missing}")
    return {
        "rows": int(len(df)),
        "products": int(df["product_id"].nunique()),
        "positives": int(df["label"].sum()),
        "positive_rate": round(float(df["label"].mean()), 4),
        "first_cutoff": str(df["cutoff"].min().date()),
        "last_cutoff": str(df["cutoff"].max().date()),
        "missing_values": missing,
        "issues": issues,
    }


def dataset_version(provenance: str, histories: dict[int, ProductHistory], observation_end: datetime) -> str:
    counts = defaultdict(int)
    for h in histories.values():
        counts["requests"] += len(h.requests)
        counts["repairs"] += len(h.repairs)
    fingerprint = f"{len(histories)}:{counts['requests']}:{counts['repairs']}:{observation_end.date()}"
    digest = hashlib.sha1(fingerprint.encode()).hexdigest()[:8]
    return f"{provenance}@{observation_end.date()}#{digest}"
