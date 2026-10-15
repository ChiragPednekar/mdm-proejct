# SQL Queries, Views and DBMS Concepts

Everything below runs against the live database. The application exposes the reports at
`GET /api/v1/analytics/{report_name}` and in the **Analytics & Reports** page, which shows the
exact SQL next to the result. All application queries use **bound parameters** (`:name`) through
SQLAlchemy, so user input never becomes part of the SQL text.

| File | Contents |
|---|---|
| `backend/sql/schema.sql` | Complete DDL (tables, constraints, indexes, views, default settings) rendered from the Alembic migrations |
| `backend/sql/analytics_queries.sql` | The 12 reports (runnable in `psql`), system-catalogue queries, integrity checks, transaction and `EXPLAIN` demos |
| `backend/app/services/analytics.py` | Source of truth for reports, dashboard metrics and defect analytics |
| `backend/alembic/versions/0002_analytical_views.py` | Source of truth for the 10 views |

Regenerate the SQL files with `python -m scripts.export_sql` (from `backend/`).

## Views

| View | Purpose | Concepts |
|---|---|---|
| `v_warranty_effective_status` | Effective status (Active/Pending/Expired/Voided) **derived** from dates + administrative state; days remaining | `CASE`, date arithmetic |
| `v_repair_costs` | Per repair: labor, parts, total, **warranty-borne vs customer cost** according to the covering warranty's terms; recomputed `parts_cost_from_lines` for auditing | 3-way join, `LEFT JOIN` to a grouped derived table, `COALESCE` |
| `v_service_request_overview` | Request joined with product, model, customer, fault and technician; `days_to_resolve` | 6-table join, `LEFT JOIN`, interval → days |
| `v_repeat_failures` | Each request with the most recent repair on the same product in the prior 90 days | `JOIN LATERAL`, correlated `ORDER BY … LIMIT 1` |
| `v_component_failure_stats` | Repairs, affected products, repeat repairs and cost per component | `LEFT JOIN`, `COUNT(DISTINCT)`, `FILTER` |
| `v_model_repair_stats` | Units, requests, repairs, cost, repairs per 100 units per model | **CTEs** (`WITH units, reqs, reps`), view-on-view |
| `v_monthly_warranty_expenditure` | Monthly repair, warranty and customer cost | `date_trunc`, `GROUP BY`, `FILTER` |
| `v_low_stock_parts` | Parts at or below their reorder level with shortfall | Computed column, `WHERE` |
| `v_part_consumption` | Quantity and cost consumed per part (junction aggregation) | M:N aggregation |
| `v_technician_performance` | Repairs, successful repairs and labor billed per technician | `LEFT JOIN` keeps technicians with no repairs |

## The 12 required reports

| # | Report (`report_name`) | Parameters | Key SQL concepts |
|---|---|---|---|
| 1 | Products with active warranties (`active_warranties`) | category, limit | View, multi-table JOIN |
| 2 | Products with expired warranties (`expired_warranties`) | limit | `GROUP BY` + `HAVING MAX(end_date) < CURRENT_DATE` + correlated `NOT EXISTS` subquery |
| 3 | Customers with more than N service requests (`customers_multiple_requests`) | min_requests | 3-table join, `COUNT(DISTINCT)`, `HAVING` |
| 4 | Top five most frequently replaced components (`top_replaced_components`) | limit (default 5) | Junction-table aggregation, `SUM`, `ORDER BY … LIMIT` |
| 5 | Product models ranked by repair expenditure (`models_by_repair_expenditure`) | limit | Window function `RANK() OVER (ORDER BY …)` over a view |
| 6 | Monthly warranty expenditure (`monthly_warranty_expenditure`) | start_date, end_date | `BETWEEN`, `date_trunc`, view |
| 7 | Average repair cost by category (`avg_repair_cost_by_category`) | — | `AVG`, `MIN`, `MAX`, `ROUND`, `GROUP BY` |
| 8 | Repeat-failure analysis (`repeat_failure_analysis`) | window_days, min_failures | **CTE** + `LAG() OVER (PARTITION BY product ORDER BY reported_at)`, `FILTER`, `HAVING` |
| 9 | Technicians ranked by completed repairs (`technicians_ranked`) | start_date | `DENSE_RANK()`, `LEFT JOIN` with a join-condition filter (keeps technicians with zero repairs) |
| 10 | Parts below reorder level (`parts_below_reorder`) | — | View |
| 11 | Products with multiple repairs within N days (`products_multiple_repairs_window`) | days | **Self-join** of `repair_history`, interval arithmetic |
| 12 | High-risk products with active warranty (`high_risk_with_active_warranty`) | min_risk | `EXISTS` subquery, `CASE` ordinal comparison |

Example (report 8):

```sql
WITH failures AS (
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
ORDER BY repeat_pct DESC, failures DESC;
```

## Dashboard metric definitions

Each `/dashboard/summary` metric returns its definition with the value, and the UI shows it on hover.

| Metric | Definition |
|---|---|
| Active warranties | Warranty contracts that are `Valid` and `start_date ≤ today ≤ end_date` |
| Expired warranties | `Valid` contracts with `end_date < today`; also reports products with no coverage in force or pending |
| Open service requests | Status Open, Assigned or In Progress |
| Repairs completed this month | Repair attempts with outcome Fixed / Unit Replaced dated in the current calendar month |
| Warranty repair expenditure | Σ warranty-borne cost from `v_repair_costs` (labor and/or parts per the covering warranty's terms), all time and last 12 months |
| Repeat-failure rate | **Numerator:** failure requests reported in the last 365 days that arrived within the repeat window (default 90 days) after a previous repair on the same product. **Denominator:** all failure requests reported in the last 365 days. Window: rolling 365 days. |
| First-time fix rate (defect analytics) | Resolved failure requests (resolved ≥ 30 days ago) fixed in exactly one attempt with outcome Fixed and with no new failure request on the product within 30 days ÷ all such resolved failure requests |
| Mean time to repair | Average of `resolution_date − reported_at` (days) over resolved failure requests |

## DBMS concepts and where they are demonstrated

| Concept | Where |
|---|---|
| Primary keys | Surrogate integer PKs on every table; composite PK on `repair_parts (repair_id, part_id)` |
| Candidate keys / UNIQUE | `products.serial_number`, `parts.part_number`, `customers.email`, `(manufacturer, model_name)`, `(service_request_id, attempt_number)`, `repair_history.idempotency_key`, `users.username` |
| Foreign keys & referential integrity | 23 FKs: 18 `ON DELETE RESTRICT`, 5 `SET NULL` (only actor references such as `audit_logs.user_id`, so history survives user removal); **composite FK** guaranteeing a request's warranty belongs to the same product |
| CHECK constraints | Status domains, `end_date > start_date`, `stock_quantity >= 0`, `0 ≤ failure_probability ≤ 1`, "Resolved ⇒ resolution_date present", "Assigned ⇒ technician present", consumption rows reference a repair |
| Partial unique indexes | One manufacturer warranty per product; one active model; one *Current* prediction per product and horizon |
| Expression index | `lower(full_name)` on customers for case-insensitive search |
| 1:1, 1:N, M:N, recursive relationships | users ↔ technicians (1:1), customer → products (1:N), repairs ↔ parts via `repair_parts` (M:N), warranty → parent warranty (recursive) |
| Joins | Inner, left outer, self-join (report 11), `LATERAL` join (`v_repeat_failures`) |
| Aggregates, GROUP BY, HAVING | Reports 2, 3, 4, 7, 8, 11; most views |
| Subqueries | Correlated `NOT EXISTS` (report 2), `EXISTS` (report 12), scalar subqueries (product list risk, customer counts) |
| CTEs | `v_model_repair_stats`, report 8, defect analytics (`per_model`, `resolved`) |
| Window functions | `RANK()` (report 5), `DENSE_RANK()` (report 9), `LAG()` (report 8, recurring faults) |
| Views | 10 views, including a view built on another view (`v_model_repair_stats` uses `v_repair_costs`) |
| Transactions & rollback | Repair + junction rows + stock deduction + ledger + audit commit as **one transaction**; any failure (e.g. insufficient stock) rolls everything back. Tests: `test_insufficient_stock_rolls_back_everything`, `test_complete_with_final_repair_is_atomic_success` |
| Concurrency control | `SELECT … FOR UPDATE` on the service request and on parts (locked in `part_id` order to avoid deadlocks); idempotency keys prevent double deduction from duplicate submissions |
| Indexing & optimisation | FK columns, date columns (`reported_at`, `repair_date`, `end_date`), status, composite `(part_id, created_at)` for the ledger, `(product_id, prediction_date)`; see the `EXPLAIN ANALYZE` examples in `analytics_queries.sql` |
| System catalogue | Constraint, FK-rule, index and view listings in `analytics_queries.sql` |
