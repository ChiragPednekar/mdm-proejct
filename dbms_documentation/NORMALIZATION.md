# Normalization

The schema targets **Third Normal Form (3NF)** for all operational tables (and BCNF for most of
them). The few deliberate exceptions are listed at the end with their justification.

## Step 0 — the unnormalized starting point

A service centre's paper job card typically looks like one wide record:

```
JOB(job_no, serial_no, model_name, manufacturer, category, std_warranty_months,
    customer_name, customer_phone, customer_city, purchase_date, warranty_type, warranty_end,
    complaint, fault_category, technician_name, technician_specialization,
    { attempt_no, diagnosis, labor_cost, { part_no, part_name, qty, unit_cost } } )
```

It has **repeating groups** (several repair attempts per job, several parts per attempt) and
massive redundancy: the customer's phone, the model's warranty length and the technician's
specialization are repeated on every job card.

## First Normal Form (1NF)

> Every attribute holds a single atomic value; there are no repeating groups; each row is identified by a key.

Actions taken:

1. Repair attempts moved to their own relation `repair_history`, keyed by
   `(service_request_id, attempt_number)`.
2. Parts used per attempt moved to `repair_parts`, keyed by `(repair_id, part_id)`.
3. Multi-valued "warranty exclusions" are **not** stored as a comma-separated list on the warranty.
   They are expressed as atomic boolean coverage terms on `warranties`
   (`covers_parts`, `covers_labor`, `covers_wear_and_tear`, `covers_accidental_damage`) and atomic
   classification flags on `fault_categories`.
4. Structured JSON columns (`feature_snapshot`, `evaluation_metrics`, `audit_logs.details`) are used
   only for **write-once documents that are never queried relationally** (an ML feature vector as
   it was at prediction time, an evaluation report). Every value the application filters, joins or
   aggregates on lives in a typed column.

## Second Normal Form (2NF)

> 1NF, and no non-key attribute depends on only part of a composite candidate key.

Only relations with composite keys can violate 2NF:

| Relation | Composite key | Check |
|---|---|---|
| `repair_parts` | (repair_id, part_id) | `quantity_used` and `unit_cost_at_repair` depend on the *pair* (how many of this part, at what price, in this repair). `part_name` is **not** stored here, since it depends on `part_id` alone and would violate 2NF; it is joined from `parts`. ✔ |
| `repair_history` | business key (service_request_id, attempt_number) | Every attribute (diagnosis, costs, outcome…) describes the specific attempt, not the request as a whole. Request-level facts (complaint, priority, product) stay in `service_requests`. ✔ |
| `product_models` | candidate key (manufacturer, model_name) | All attributes describe the model; nothing depends on the manufacturer alone (manufacturers carry no attributes of their own, so a separate `manufacturers` table would add a join without removing redundancy). ✔ |

## Third Normal Form (3NF)

> 2NF, and no non-key attribute depends transitively on the key through another non-key attribute.

Transitive dependencies found in the job card, and how they were removed:

| Transitive dependency in the job card | Resolution |
|---|---|
| job → serial_no → model_name → manufacturer, category, std_warranty_months | `products(product_model_id)` → `product_models` |
| job → serial_no → customer → phone, city | `products(customer_id)` → `customers` |
| job → technician_name → specialization | `technicians` table; requests/repairs store only `technician_id` |
| job → fault_category → is_customer_induced, is_wear_and_tear | `fault_categories` lookup table |
| repair line → part_no → part_name, supplier, current unit_cost | `parts` table |

## Functional dependencies (key relations)

```
customers:            customer_id → full_name, email, phone, address, city, created_at
                      email → customer_id                      (candidate key when not null)
product_models:       product_model_id → manufacturer, model_name, product_category, …
                      {manufacturer, model_name} → product_model_id
products:             product_id → serial_number, product_model_id, customer_id, purchase_date, …
                      serial_number → product_id               (candidate key)
warranties:           warranty_id → product_id, parent_warranty_id, warranty_type, start_date, end_date,
                                    covers_*, warranty_status, extended_warranty
service_requests:     service_request_id → product_id, warranty_id, fault_category_id, reported_at,
                                           priority, failure_severity, request_status, …
repair_history:       repair_id → service_request_id, attempt_number, technician_id, component_id, …
                      {service_request_id, attempt_number} → repair_id      (candidate key)
                      idempotency_key → repair_id                           (candidate key when not null)
parts:                part_id → part_number, part_name, component_id, unit_cost, stock_quantity, …
                      part_number → part_id                    (candidate key)
repair_parts:         {repair_id, part_id} → quantity_used, unit_cost_at_repair
fault_categories:     fault_category_id → name, is_customer_induced, is_wear_and_tear, counts_as_failure
                      name → fault_category_id                 (candidate key)
failure_predictions:  prediction_id → product_id, training_run_id, prediction_date, horizon, probability,
                                      risk_level, model_version, …
users:                user_id → username, email, role, technician_id, …
                      username → user_id ; email → user_id ; technician_id → user_id (when not null)
```

In every relation, each determinant on the left is a candidate key, so these relations are also
in **BCNF**, except for the documented cases below.

## Deliberate, controlled redundancy

Each of these is a conscious trade-off. None introduces an update anomaly that the application
cannot control.

| Column | Why it exists | How consistency is protected |
|---|---|---|
| `repair_parts.unit_cost_at_repair` | **Historical fact**, not redundancy: the price actually charged. `parts.unit_cost` changes over time; recomputing old repairs from today's price would rewrite history. | Written once at repair time; never updated. |
| `repair_history.parts_cost` | Invoice snapshot = Σ(quantity × unit_cost_at_repair) for that repair. Required by the specification; it lets cost reports avoid a junction aggregation for every row. | Written in the **same transaction** as the junction rows, by a single code path (`services/inventory.py`). The view `v_repair_costs` exposes `parts_cost_from_lines` next to it, and `sql/analytics_queries.sql` contains an integrity query that must return 0 (the test suite checks this). |
| `service_requests.warranty_covered`, `coverage_notes` | **Decision record**: whether the claim was accepted at intake and why. Later edits to a warranty (e.g. voiding it) must not silently change past claim decisions. | Written by `determine_coverage()` at intake. |
| `warranties.extended_warranty` | Required flag, functionally dependent on `warranty_type`. | `CHECK (extended_warranty = (warranty_type <> 'Manufacturer'))` makes inconsistency impossible. |
| `repair_history.repeat_failure` | Historical flag: was there a repair on this product within the repeat window *at the time*? Recomputing it after the window setting changes would alter history. | Computed at write time from recorded history; the view `v_repeat_failures` derives the same concept dynamically for analysis. |
| `parts.stock_quantity` | Current balance, also derivable as Σ`inventory_transactions.quantity_change`. Keeping the balance makes `SELECT … FOR UPDATE` locking and the `CHECK (stock_quantity >= 0)` constraint possible. | Every change goes through one code path that writes the ledger row (with `stock_after`) in the same transaction; an integrity query compares balance and ledger. |
| `failure_predictions.model_version`, `model_classification` | Copied from the training run so a prediction stays self-describing even if run metadata is later edited. | The `training_run_id` FK is authoritative; copies are written once. |

## What is intentionally *not* stored

- **Warranty effective status** (Active / Expired / Pending) is never stored; it is derived from
  dates in `services/warranty.effective_status()` and the view `v_warranty_effective_status`.
  `warranty_status` holds only the administrative state (Valid / Voided / Cancelled).
- **Total repair cost**, **warranty-borne cost** and **customer cost** are computed in
  `v_repair_costs` rather than stored.
- **Product age**, **days remaining** and similar time-dependent values are computed at query time.
