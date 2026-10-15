"""Dashboard metrics, parameterized SQL reports and defect analytics.

Every number is computed by a SQL query at request time; nothing is cached or
hard-coded. All user input reaches SQL only through bound parameters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, NotFoundError
from app.services import settings_service


def _rows(db: Session, sql: str, params: dict | None = None) -> list[dict]:
    return [_jsonable(dict(r)) for r in db.execute(text(sql), params or {}).mappings()]


def _scalar(db: Session, sql: str, params: dict | None = None) -> Any:
    return db.execute(text(sql), params or {}).scalar()


def _jsonable(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if isinstance(v, Decimal):
            v = float(v)
        out[k] = v
    return out


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def dashboard_summary(db: Session) -> dict:
    repeat_window = int(settings_service.get_setting(db, "repeat_failure_window_days"))
    m: list[dict] = []

    def metric(key: str, label: str, value: Any, definition: str, **extra) -> None:
        m.append({"key": key, "label": label, "value": value, "definition": definition, **extra})

    metric("total_products", "Registered products", _scalar(db, "SELECT COUNT(*) FROM products"),
           "All registered product units, any status.")
    metric("active_warranties", "Active warranties",
           _scalar(db, "SELECT COUNT(*) FROM v_warranty_effective_status WHERE effective_status = 'Active'"),
           "Warranty contracts that are Valid and whose start_date <= today <= end_date.",
           products=_scalar(db, "SELECT COUNT(DISTINCT product_id) FROM v_warranty_effective_status "
                                "WHERE effective_status = 'Active'"))
    metric("expired_warranties", "Expired warranties",
           _scalar(db, "SELECT COUNT(*) FROM v_warranty_effective_status WHERE effective_status = 'Expired'"),
           "Valid warranty contracts whose end_date is before today.",
           products_without_cover=_scalar(db, """
               SELECT COUNT(*) FROM products p
               WHERE NOT EXISTS (SELECT 1 FROM v_warranty_effective_status w
                                 WHERE w.product_id = p.product_id AND w.effective_status IN ('Active', 'Pending'))"""))
    metric("open_service_requests", "Open service requests",
           _scalar(db, "SELECT COUNT(*) FROM service_requests WHERE request_status IN ('Open','Assigned','In Progress')"),
           "Requests in status Open, Assigned or In Progress.")
    metric("repairs_completed_this_month", "Repairs completed this month",
           _scalar(db, """SELECT COUNT(*) FROM repair_history
                          WHERE outcome IN ('Fixed', 'Unit Replaced')
                            AND repair_date >= date_trunc('month', now())"""),
           "Repair attempts with outcome Fixed or Unit Replaced dated in the current calendar month.")
    total_wc = _scalar(db, "SELECT COALESCE(SUM(warranty_cost), 0) FROM v_repair_costs")
    wc_12 = _scalar(db, "SELECT COALESCE(SUM(warranty_cost), 0) FROM v_repair_costs "
                        "WHERE repair_date >= now() - INTERVAL '12 months'")
    metric("warranty_expenditure", "Warranty repair expenditure", float(total_wc),
           "Sum of labor and/or parts cost borne by the warranty (per the covering warranty's terms) "
           "for repairs on covered requests, all time.", last_12_months=float(wc_12), unit="currency")
    metric("high_risk_products", "High-risk products",
           _scalar(db, "SELECT COUNT(*) FROM failure_predictions WHERE prediction_status = 'Current' "
                       "AND risk_level = 'High'"),
           "Products whose current (latest) prediction falls in the High risk band.",
           medium=_scalar(db, "SELECT COUNT(*) FROM failure_predictions WHERE prediction_status = 'Current' "
                              "AND risk_level = 'Medium'"))
    rf = db.execute(text("""
        SELECT COUNT(*) AS denominator,
               COUNT(*) FILTER (WHERE EXISTS (
                   SELECT 1 FROM repair_history r JOIN service_requests sr2
                     ON sr2.service_request_id = r.service_request_id
                   WHERE sr2.product_id = sr.product_id AND sr2.service_request_id <> sr.service_request_id
                     AND r.repair_date < sr.reported_at
                     AND r.repair_date >= sr.reported_at - make_interval(days => :w))) AS numerator
        FROM service_requests sr JOIN fault_categories fc ON fc.fault_category_id = sr.fault_category_id
        WHERE fc.counts_as_failure AND sr.reported_at >= now() - INTERVAL '365 days'
          AND sr.request_status <> 'Cancelled'
    """), {"w": repeat_window}).mappings().one()
    rate = round(rf["numerator"] / rf["denominator"], 4) if rf["denominator"] else None
    metric("repeat_failure_rate", "Repeat-failure rate", rate,
           f"Failure requests reported in the last 365 days that arrived within {repeat_window} days after a "
           "previous repair on the same product, divided by all failure requests reported in the last 365 days.",
           numerator=rf["numerator"], denominator=rf["denominator"], unit="ratio")
    metric("low_stock_parts", "Parts at/below reorder level", _scalar(db, "SELECT COUNT(*) FROM v_low_stock_parts"),
           "Parts whose stock_quantity <= reorder_level.")

    return {
        "metrics": m,
        "top_components": _rows(db, """
            SELECT component_name, repair_count, repeat_repairs, total_repair_cost
            FROM v_component_failure_stats WHERE repair_count > 0
            ORDER BY repair_count DESC, component_name LIMIT 6"""),
        "top_models": _rows(db, """
            SELECT manufacturer, model_name, product_category, repairs, registered_units, repairs_per_100_units
            FROM v_model_repair_stats WHERE repairs > 0
            ORDER BY repairs DESC, repairs_per_100_units DESC LIMIT 6"""),
        "low_stock": _rows(db, "SELECT * FROM v_low_stock_parts ORDER BY shortfall DESC, part_number LIMIT 8"),
    }


def dashboard_trends(db: Session, months: int = 12) -> dict:
    months = max(3, min(months, 36))
    params = {"months": months}
    return {
        "monthly_activity": _rows(db, """
            WITH m AS (SELECT generate_series(date_trunc('month', now()) - make_interval(months => :months - 1),
                                              date_trunc('month', now()), INTERVAL '1 month')::date AS month)
            SELECT to_char(m.month, 'YYYY-MM') AS month,
                   (SELECT COUNT(*) FROM service_requests sr
                     WHERE date_trunc('month', sr.reported_at)::date = m.month) AS service_requests,
                   (SELECT COUNT(*) FROM repair_history r WHERE r.outcome IN ('Fixed', 'Unit Replaced')
                       AND date_trunc('month', r.repair_date)::date = m.month) AS completed_repairs
            FROM m ORDER BY m.month""", params),
        "warranty_expenditure": _rows(db, """
            WITH m AS (SELECT generate_series(date_trunc('month', now()) - make_interval(months => :months - 1),
                                              date_trunc('month', now()), INTERVAL '1 month')::date AS month)
            SELECT to_char(m.month, 'YYYY-MM') AS month,
                   COALESCE(e.warranty_cost, 0) AS warranty_cost,
                   COALESCE(e.customer_cost, 0) AS customer_cost
            FROM m LEFT JOIN v_monthly_warranty_expenditure e ON e.month = m.month
            ORDER BY m.month""", params),
        "failures_by_category": _rows(db, """
            SELECT pm.product_category AS category, COUNT(*) AS failures
            FROM service_requests sr
            JOIN fault_categories fc ON fc.fault_category_id = sr.fault_category_id AND fc.counts_as_failure
            JOIN products p ON p.product_id = sr.product_id
            JOIN product_models pm ON pm.product_model_id = p.product_model_id
            GROUP BY pm.product_category ORDER BY failures DESC"""),
        "top_defects": _rows(db, """
            SELECT fc.name AS fault_category, COALESCE(co.component_name, '—') AS component, COUNT(*) AS occurrences
            FROM repair_history r
            JOIN service_requests sr ON sr.service_request_id = r.service_request_id
            JOIN fault_categories fc ON fc.fault_category_id = sr.fault_category_id AND fc.counts_as_failure
            LEFT JOIN components co ON co.component_id = r.component_id
            WHERE r.attempt_number = 1
            GROUP BY fc.name, co.component_name ORDER BY occurrences DESC LIMIT 8"""),
        "failures_by_component": _rows(db, """
            SELECT component_name AS component, repair_count AS failures FROM v_component_failure_stats
            WHERE repair_count > 0 ORDER BY repair_count DESC LIMIT 12"""),
        "risk_distribution": _rows(db, """
            SELECT b.risk_level, COUNT(fp.prediction_id) AS products
            FROM (VALUES ('Low', 1), ('Medium', 2), ('High', 3)) AS b(risk_level, ord)
            LEFT JOIN failure_predictions fp ON fp.risk_level = b.risk_level AND fp.prediction_status = 'Current'
            GROUP BY b.risk_level, b.ord ORDER BY b.ord"""),
    }


# ---------------------------------------------------------------------------
# Parameterized SQL reports (DBMS demonstration module)
# ---------------------------------------------------------------------------
@dataclass
class Param:
    name: str
    type: str  # int | date | str | choice
    default: Any
    label: str
    choices: list[str] | None = None
    minimum: int | None = None
    maximum: int | None = None


@dataclass
class Report:
    name: str
    title: str
    description: str
    concepts: list[str]
    sql: str
    params: list[Param] = field(default_factory=list)


def _today_minus(days: int) -> date:
    return date.today() - timedelta(days=days)


REPORTS: list[Report] = [
    Report("active_warranties", "Products with active warranties",
           "Units currently covered, using the derived effective status (dates + administrative status).",
           ["View", "JOIN", "WHERE", "ORDER BY"],
           """SELECT p.serial_number, pm.manufacturer, pm.model_name, c.full_name AS customer,
       w.warranty_type, w.start_date, w.end_date, w.days_remaining
FROM v_warranty_effective_status w
JOIN products p        ON p.product_id = w.product_id
JOIN product_models pm ON pm.product_model_id = p.product_model_id
JOIN customers c       ON c.customer_id = p.customer_id
WHERE w.effective_status = 'Active'
  AND (:category = 'All' OR pm.product_category = :category)
ORDER BY w.end_date
LIMIT :limit""",
           [Param("category", "choice", "All", "Category",
                  ["All", "Laptop", "Refrigerator", "Washing Machine", "Air Conditioner", "Television"]),
            Param("limit", "int", 50, "Max rows", minimum=1, maximum=500)]),
    Report("expired_warranties", "Products with expired warranties",
           "Units with at least one warranty but no coverage in force or pending today.",
           ["GROUP BY", "HAVING", "Correlated subquery", "NOT EXISTS", "Aggregate MAX"],
           """SELECT p.serial_number, pm.model_name, c.full_name AS customer,
       MAX(w.end_date) AS coverage_ended, CURRENT_DATE - MAX(w.end_date) AS days_since_expiry
FROM products p
JOIN warranties w      ON w.product_id = p.product_id AND w.warranty_status = 'Valid'
JOIN product_models pm ON pm.product_model_id = p.product_model_id
JOIN customers c       ON c.customer_id = p.customer_id
GROUP BY p.product_id, p.serial_number, pm.model_name, c.full_name
HAVING MAX(w.end_date) < CURRENT_DATE
   AND NOT EXISTS (SELECT 1 FROM warranties w2
                   WHERE w2.product_id = p.product_id AND w2.warranty_status = 'Valid'
                     AND w2.end_date >= CURRENT_DATE)
ORDER BY coverage_ended DESC
LIMIT :limit""",
           [Param("limit", "int", 50, "Max rows", minimum=1, maximum=500)]),
    Report("customers_multiple_requests", "Customers with more than N service requests",
           "Customers ranked by number of service requests across all of their products.",
           ["JOIN (3 tables)", "GROUP BY", "HAVING", "COUNT DISTINCT"],
           """SELECT c.customer_id, c.full_name, c.city,
       COUNT(DISTINCT p.product_id) AS products,
       COUNT(sr.service_request_id) AS service_requests,
       MAX(sr.reported_at)::date AS last_request
FROM customers c
JOIN products p          ON p.customer_id = c.customer_id
JOIN service_requests sr ON sr.product_id = p.product_id
GROUP BY c.customer_id, c.full_name, c.city
HAVING COUNT(sr.service_request_id) > :min_requests
ORDER BY service_requests DESC, c.full_name""",
           [Param("min_requests", "int", 1, "More than", minimum=0, maximum=100)]),
    Report("top_replaced_components", "Most frequently replaced components",
           "Components ranked by the quantity of spare parts consumed in repairs (M:N junction table).",
           ["Junction table", "JOIN", "SUM", "GROUP BY", "LIMIT"],
           """SELECT co.component_name, co.component_category,
       SUM(rp.quantity_used) AS units_replaced,
       COUNT(DISTINCT rp.repair_id) AS repairs,
       SUM(rp.quantity_used * rp.unit_cost_at_repair) AS parts_spend
FROM repair_parts rp
JOIN parts pa      ON pa.part_id = rp.part_id
JOIN components co ON co.component_id = pa.component_id
GROUP BY co.component_id, co.component_name, co.component_category
ORDER BY units_replaced DESC
LIMIT :limit""",
           [Param("limit", "int", 5, "Top N", minimum=1, maximum=50)]),
    Report("models_by_repair_expenditure", "Product models ranked by repair expenditure",
           "Uses the v_model_repair_stats view and a RANK() window function.",
           ["View", "Window function RANK()", "CTE (inside view)"],
           """SELECT RANK() OVER (ORDER BY total_repair_cost DESC) AS rank,
       manufacturer, model_name, product_category, registered_units, repairs,
       total_repair_cost, warranty_cost, avg_cost_per_repair
FROM v_model_repair_stats
WHERE repairs > 0
ORDER BY rank
LIMIT :limit""",
           [Param("limit", "int", 15, "Max rows", minimum=1, maximum=100)]),
    Report("monthly_warranty_expenditure", "Monthly warranty expenditure",
           "Warranty vs. customer-paid repair cost per month in a date range.",
           ["View", "date_trunc", "BETWEEN", "SUM"],
           """SELECT to_char(month, 'YYYY-MM') AS month, repairs, warranty_repairs,
       total_repair_cost, warranty_cost, customer_cost
FROM v_monthly_warranty_expenditure
WHERE month BETWEEN date_trunc('month', CAST(:start_date AS date)) AND :end_date
ORDER BY month""",
           [Param("start_date", "date", "today-365", "From"), Param("end_date", "date", "today", "To")]),
    Report("avg_repair_cost_by_category", "Average repair cost by product category",
           "Average, minimum and maximum cost per repair attempt for each category.",
           ["JOIN", "AVG / MIN / MAX", "GROUP BY", "ROUND"],
           """SELECT pm.product_category,
       COUNT(*) AS repairs,
       ROUND(AVG(rc.total_cost), 2) AS avg_cost,
       MIN(rc.total_cost) AS min_cost,
       MAX(rc.total_cost) AS max_cost,
       ROUND(AVG(rc.labor_cost), 2) AS avg_labor,
       ROUND(AVG(rc.parts_cost), 2) AS avg_parts
FROM v_repair_costs rc
JOIN products p        ON p.product_id = rc.product_id
JOIN product_models pm ON pm.product_model_id = p.product_model_id
GROUP BY pm.product_category
ORDER BY avg_cost DESC""", []),
    Report("repeat_failure_analysis", "Repeat-failure analysis by model",
           "LAG() over each product's failure reports gives the gap since its previous failure; "
           "repeats are failures within the window.",
           ["CTE", "Window function LAG()", "PARTITION BY", "FILTER", "HAVING"],
           """WITH failures AS (
    SELECT sr.product_id, sr.reported_at,
           LAG(sr.reported_at) OVER (PARTITION BY sr.product_id ORDER BY sr.reported_at) AS previous_failure
    FROM service_requests sr
    JOIN fault_categories fc ON fc.fault_category_id = sr.fault_category_id
    WHERE fc.counts_as_failure AND sr.request_status <> 'Cancelled'
)
SELECT pm.manufacturer, pm.model_name, pm.product_category,
       COUNT(*) AS failures,
       COUNT(*) FILTER (WHERE f.reported_at - f.previous_failure <= make_interval(days => :window_days)) AS repeat_failures,
       ROUND(100.0 * COUNT(*) FILTER (WHERE f.reported_at - f.previous_failure <= make_interval(days => :window_days))
             / COUNT(*), 1) AS repeat_pct
FROM failures f
JOIN products p        ON p.product_id = f.product_id
JOIN product_models pm ON pm.product_model_id = p.product_model_id
GROUP BY pm.product_model_id, pm.manufacturer, pm.model_name, pm.product_category
HAVING COUNT(*) >= :min_failures
ORDER BY repeat_pct DESC, failures DESC""",
           [Param("window_days", "int", 90, "Window (days)", minimum=1, maximum=365),
            Param("min_failures", "int", 5, "Min failures", minimum=1, maximum=100)]),
    Report("technicians_ranked", "Technicians ranked by completed repairs",
           "DENSE_RANK() over successful repairs in a period, with average labor billed.",
           ["LEFT JOIN", "Window function DENSE_RANK()", "FILTER", "GROUP BY"],
           """SELECT DENSE_RANK() OVER (ORDER BY COUNT(r.repair_id) FILTER
                                (WHERE r.outcome IN ('Fixed', 'Unit Replaced')) DESC) AS rank,
       t.full_name, t.specialization, t.employment_status,
       COUNT(r.repair_id) FILTER (WHERE r.outcome IN ('Fixed', 'Unit Replaced')) AS completed_repairs,
       COUNT(r.repair_id) AS total_attempts,
       ROUND(AVG(r.labor_cost), 2) AS avg_labor
FROM technicians t
LEFT JOIN repair_history r ON r.technician_id = t.technician_id
     AND r.repair_date >= CAST(:start_date AS date)
GROUP BY t.technician_id, t.full_name, t.specialization, t.employment_status
ORDER BY rank, t.full_name""",
           [Param("start_date", "date", "today-365", "Since")]),
    Report("parts_below_reorder", "Parts below reorder level",
           "Live inventory status from the v_low_stock_parts view.",
           ["View", "LEFT JOIN", "Computed column"],
           """SELECT part_number, part_name, component_name, stock_quantity, reorder_level, shortfall, supplier_name
FROM v_low_stock_parts
ORDER BY shortfall DESC, part_number""", []),
    Report("products_multiple_repairs_window", "Products with multiple repairs within N days",
           "Self-join of repair_history: pairs of repairs on the same product within the window.",
           ["Self-join", "DISTINCT", "Interval arithmetic", "GROUP BY"],
           """SELECT p.serial_number, pm.manufacturer, pm.model_name,
       COUNT(DISTINCT r2.repair_id) + 1 AS repairs_in_cluster,
       MIN(r1.repair_date)::date AS first_repair,
       MAX(r2.repair_date)::date AS last_repair
FROM repair_history r1
JOIN service_requests s1 ON s1.service_request_id = r1.service_request_id
JOIN repair_history r2   ON r2.repair_id <> r1.repair_id
JOIN service_requests s2 ON s2.service_request_id = r2.service_request_id
                         AND s2.product_id = s1.product_id
                         AND s2.service_request_id <> s1.service_request_id
JOIN products p          ON p.product_id = s1.product_id
JOIN product_models pm   ON pm.product_model_id = p.product_model_id
WHERE r2.repair_date > r1.repair_date
  AND r2.repair_date <= r1.repair_date + make_interval(days => :days)
GROUP BY p.product_id, p.serial_number, pm.manufacturer, pm.model_name
ORDER BY repairs_in_cluster DESC, last_repair DESC""",
           [Param("days", "int", 90, "Window (days)", minimum=1, maximum=730)]),
    Report("high_risk_with_active_warranty", "At-risk products with active warranty coverage",
           "Current predictions at or above a risk band whose product is still under warranty "
           "(potential warranty liability).",
           ["EXISTS subquery", "JOIN", "ORDER BY"],
           """SELECT p.serial_number, pm.model_name, c.full_name AS customer,
       fp.failure_probability, fp.risk_level, fp.prediction_date::date AS predicted_on,
       fp.model_classification
FROM failure_predictions fp
JOIN products p        ON p.product_id = fp.product_id
JOIN product_models pm ON pm.product_model_id = p.product_model_id
JOIN customers c       ON c.customer_id = p.customer_id
WHERE fp.prediction_status = 'Current'
  AND (CASE fp.risk_level WHEN 'High' THEN 3 WHEN 'Medium' THEN 2 ELSE 1 END)
      >= (CASE :min_risk WHEN 'High' THEN 3 WHEN 'Medium' THEN 2 ELSE 1 END)
  AND EXISTS (SELECT 1 FROM v_warranty_effective_status w
              WHERE w.product_id = p.product_id AND w.effective_status = 'Active')
ORDER BY fp.failure_probability DESC""",
           [Param("min_risk", "choice", "High", "Minimum risk", ["High", "Medium", "Low"])]),
]
_REPORTS = {r.name: r for r in REPORTS}


def report_catalog() -> list[dict]:
    return [{"name": r.name, "title": r.title, "description": r.description, "concepts": r.concepts, "sql": r.sql,
             "params": [p.__dict__ | {"default": _resolve_default(p)} for p in r.params]} for r in REPORTS]


def _resolve_default(p: Param) -> Any:
    if p.type == "date" and isinstance(p.default, str):
        if p.default == "today":
            return date.today().isoformat()
        if p.default.startswith("today-"):
            return _today_minus(int(p.default.split("-")[1])).isoformat()
    return p.default


def run_report(db: Session, name: str, raw: dict[str, str]) -> dict:
    report = _REPORTS.get(name)
    if report is None:
        raise NotFoundError(f"Unknown report '{name}'.")
    params: dict[str, Any] = {}
    for p in report.params:
        value: Any = raw.get(p.name, _resolve_default(p))
        try:
            if p.type == "int":
                value = int(value)
                if (p.minimum is not None and value < p.minimum) or (p.maximum is not None and value > p.maximum):
                    raise ValueError
            elif p.type == "date":
                value = date.fromisoformat(str(value))
            elif p.type == "choice" and value not in (p.choices or []):
                raise ValueError
        except (TypeError, ValueError):
            raise BusinessRuleError(f"Invalid value for parameter '{p.name}'.")
        params[p.name] = value
    rows = _rows(db, report.sql, params)
    columns = list(rows[0].keys()) if rows else []
    return {"name": report.name, "title": report.title, "sql": report.sql,
            "params": {k: str(v) for k, v in params.items()}, "columns": columns, "rows": rows,
            "row_count": len(rows)}


# ---------------------------------------------------------------------------
# Defect analytics (Module 5) with shared filters
# ---------------------------------------------------------------------------
def _defect_filters(f: dict) -> tuple[str, dict]:
    clauses, params = [], {}
    if f.get("start_date"):
        clauses.append("sr.reported_at >= :start_date")
        params["start_date"] = f["start_date"]
    if f.get("end_date"):
        clauses.append("sr.reported_at < CAST(:end_date AS date) + 1")
        params["end_date"] = f["end_date"]
    for key, col in (("category", "pm.product_category"), ("manufacturer", "pm.manufacturer"),
                     ("product_model_id", "pm.product_model_id"), ("severity", "sr.failure_severity")):
        if f.get(key):
            clauses.append(f"{col} = :{key}")
            params[key] = f[key]
    if f.get("component_id"):
        clauses.append("EXISTS (SELECT 1 FROM repair_history rx WHERE rx.service_request_id = sr.service_request_id "
                       "AND rx.component_id = :component_id)")
        params["component_id"] = f["component_id"]
    return (" AND " + " AND ".join(clauses)) if clauses else "", params


_BASE = """
FROM service_requests sr
JOIN fault_categories fc ON fc.fault_category_id = sr.fault_category_id
JOIN products p          ON p.product_id = sr.product_id
JOIN product_models pm   ON pm.product_model_id = p.product_model_id
WHERE sr.request_status <> 'Cancelled' {where}
"""


def defect_analytics(db: Session, filters: dict) -> dict:
    where, params = _defect_filters(filters)
    window = int(filters.get("window_days") or settings_service.get_setting(db, "repeat_failure_window_days"))
    params["window"] = window
    base = _BASE.format(where=where)
    ftf_follow = 30

    ftf = db.execute(text(f"""
        WITH resolved AS (
            SELECT sr.service_request_id, sr.product_id, sr.resolution_date,
                   (SELECT COUNT(*) FROM repair_history r WHERE r.service_request_id = sr.service_request_id) AS attempts,
                   (SELECT r.outcome FROM repair_history r WHERE r.service_request_id = sr.service_request_id
                     ORDER BY r.attempt_number LIMIT 1) AS first_outcome
            {base} AND fc.counts_as_failure AND sr.request_status IN ('Resolved', 'Closed')
              AND sr.resolution_date <= now() - make_interval(days => {ftf_follow})
        )
        SELECT COUNT(*) AS denominator,
               COUNT(*) FILTER (WHERE attempts = 1 AND first_outcome = 'Fixed' AND NOT EXISTS (
                   SELECT 1 FROM service_requests n JOIN fault_categories nf ON nf.fault_category_id = n.fault_category_id
                   WHERE n.product_id = resolved.product_id AND nf.counts_as_failure
                     AND n.reported_at > resolved.resolution_date
                     AND n.reported_at <= resolved.resolution_date + make_interval(days => {ftf_follow}))) AS numerator
        FROM resolved"""), params).mappings().one()

    mttr = _rows(db, f"""
        SELECT pm.product_category AS category,
               ROUND(AVG(EXTRACT(EPOCH FROM (sr.resolution_date - sr.reported_at)) / 86400.0)::numeric, 2) AS avg_days,
               COUNT(*) AS resolved_requests
        {base} AND sr.resolution_date IS NOT NULL AND fc.counts_as_failure
        GROUP BY pm.product_category ORDER BY avg_days DESC""", params)
    overall_mttr = _scalar(db, f"""
        SELECT ROUND(AVG(EXTRACT(EPOCH FROM (sr.resolution_date - sr.reported_at)) / 86400.0)::numeric, 2)
        {base} AND sr.resolution_date IS NOT NULL AND fc.counts_as_failure""", params)

    return {
        "filters": {k: v for k, v in filters.items() if v not in (None, "")},
        "definitions": {
            "first_time_fix_rate": (f"Resolved failure requests (resolved at least {ftf_follow} days ago) fixed in a "
                                    f"single attempt with outcome 'Fixed' and no new failure request on the same "
                                    f"product within {ftf_follow} days, divided by all such resolved requests."),
            "mean_time_to_repair": "Average days from complaint reported_at to resolution_date for resolved failures.",
            "recurring_fault": f"A failure reported within {window} days after a previous failure of the same "
                               "product with the same fault category.",
            "high_cost_model": "Models whose average cost per repair is at least 1.25x the average across all models "
                               "(minimum 3 repairs).",
        },
        "summary": {
            "failure_requests": _scalar(db, f"SELECT COUNT(*) {base} AND fc.counts_as_failure", params),
            "first_time_fix_rate": round(ftf["numerator"] / ftf["denominator"], 4) if ftf["denominator"] else None,
            "first_time_fix_numerator": ftf["numerator"],
            "first_time_fix_denominator": ftf["denominator"],
            "mean_time_to_repair_days": float(overall_mttr) if overall_mttr is not None else None,
        },
        "frequently_replaced_components": _rows(db, f"""
            SELECT co.component_name, COUNT(DISTINCT r.repair_id) AS repairs,
                   COALESCE(SUM(rp.quantity_used), 0) AS parts_used,
                   COALESCE(SUM(rp.quantity_used * rp.unit_cost_at_repair), 0) AS parts_spend
            {base.replace('WHERE', 'JOIN repair_history r ON r.service_request_id = sr.service_request_id '
                          'JOIN components co ON co.component_id = r.component_id '
                          'LEFT JOIN repair_parts rp ON rp.repair_id = r.repair_id WHERE', 1)}
            GROUP BY co.component_name ORDER BY repairs DESC LIMIT 10""", params),
        "repeat_products": _rows(db, f"""
            SELECT p.product_id, p.serial_number, pm.model_name, COUNT(*) AS failures,
                   MIN(sr.reported_at)::date AS first_failure, MAX(sr.reported_at)::date AS last_failure
            {base} AND fc.counts_as_failure
            GROUP BY p.product_id, p.serial_number, pm.model_name HAVING COUNT(*) >= 2
            ORDER BY failures DESC, last_failure DESC LIMIT 15""", params),
        "recurring_faults": _rows(db, f"""
            WITH f AS (
                SELECT sr.product_id, fc.name AS fault, sr.reported_at,
                       LAG(sr.reported_at) OVER (PARTITION BY sr.product_id, sr.fault_category_id
                                                 ORDER BY sr.reported_at) AS prev
                {base} AND fc.counts_as_failure)
            SELECT fault, COUNT(*) FILTER (WHERE reported_at - prev <= make_interval(days => :window)) AS recurrences,
                   COUNT(*) AS occurrences
            FROM f GROUP BY fault ORDER BY recurrences DESC, occurrences DESC""", params),
        "high_cost_models": _rows(db, f"""
            WITH per_model AS (
                SELECT pm.product_model_id, pm.manufacturer, pm.model_name, pm.product_category,
                       COUNT(r.repair_id) AS repairs, AVG(r.labor_cost + r.parts_cost) AS avg_cost
                {base.replace('WHERE', 'JOIN repair_history r ON r.service_request_id = sr.service_request_id WHERE', 1)}
                GROUP BY pm.product_model_id, pm.manufacturer, pm.model_name, pm.product_category
                HAVING COUNT(r.repair_id) >= 3)
            SELECT manufacturer, model_name, product_category, repairs, ROUND(avg_cost, 2) AS avg_cost,
                   ROUND(avg_cost / NULLIF((SELECT AVG(avg_cost) FROM per_model), 0), 2) AS cost_ratio
            FROM per_model
            WHERE avg_cost >= 1.25 * (SELECT AVG(avg_cost) FROM per_model)
            ORDER BY cost_ratio DESC""", params),
        "repeat_components": _rows(db, f"""
            SELECT co.component_name, COUNT(*) AS repairs,
                   COUNT(*) FILTER (WHERE r.repeat_failure) AS repeat_repairs,
                   ROUND(100.0 * COUNT(*) FILTER (WHERE r.repeat_failure) / COUNT(*), 1) AS repeat_pct
            {base.replace('WHERE', 'JOIN repair_history r ON r.service_request_id = sr.service_request_id '
                          'JOIN components co ON co.component_id = r.component_id WHERE', 1)}
            GROUP BY co.component_name HAVING COUNT(*) >= 3
            ORDER BY repeat_pct DESC, repairs DESC LIMIT 10""", params),
        "mttr_by_category": mttr,
        "claims_by_category": _rows(db, f"""
            SELECT pm.product_category AS category, to_char(date_trunc('quarter', sr.reported_at), 'YYYY-"Q"Q') AS period,
                   COUNT(*) FILTER (WHERE sr.warranty_covered) AS covered_claims,
                   COUNT(*) FILTER (WHERE NOT COALESCE(sr.warranty_covered, false)) AS not_covered
            {base} AND fc.counts_as_failure
            GROUP BY 1, 2 ORDER BY 2, 1""", params),
    }
