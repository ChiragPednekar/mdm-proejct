# Database Design Decisions

Short records of the non-obvious choices, the alternatives considered, and why.

## 1. PostgreSQL, migrated by Alembic

PostgreSQL provides the features this design relies on: partial unique indexes, expression
indexes, `JSONB`, `FILTER` clauses, window functions, `LATERAL` joins, transactional DDL and
row-level locking (`SELECT … FOR UPDATE`). The schema is created **only** through Alembic
migrations (`0001` tables/constraints/indexes, `0002` views and default settings), so every
environment, including the test database, is built the same way. Both migrations are reversible
(`alembic downgrade base` is verified). The automated tests also run on a real PostgreSQL
database (`warranty_test`) rather than SQLite, so constraints, views and locking are tested
exactly as they run in production.

## 2. Surrogate keys + enforced natural keys

Every table has an integer surrogate PK (stable, compact FKs), and every natural key is still
enforced with `UNIQUE`: serial number, part number, `(manufacturer, model_name)`,
`(service_request_id, attempt_number)`. The surrogate never replaces the business rule.

## 3. Enumerations as `VARCHAR` + `CHECK`, not native enums

Status and category domains (`request_status`, `warranty_type`, `outcome`, …) are VARCHAR
columns guarded by named CHECK constraints. They are as safe as PG enums, readable in any SQL
client, and adding a value is a one-line migration rather than `ALTER TYPE`. The same value lists
live in `app/models/entities.py` and drive the API validation (Pydantic `Literal`s).
**Fault categories** are a lookup table instead, because they carry attributes (customer-induced,
wear-and-tear, counts-as-failure) used by both warranty rules and the ML target.

## 4. Warranty status is derived, not trusted

`warranties.warranty_status` stores only the **administrative** state (Valid / Voided /
Cancelled). Whether a warranty is in force is always computed from its dates
(`services/warranty.effective_status`, view `v_warranty_effective_status`). A stored "Active" flag
would silently go stale the day after expiry.

## 5. Coverage is a rule, not an assumption

`evaluate_coverage(warranty, service_date, fault_category)` is one reusable function that checks
administrative state, date range, non-failure visits, customer-induced damage (unless accidental
damage is covered), wear and tear (unless covered), and whether parts and/or labor are covered.
`determine_coverage()` picks the applicable warranty among a product's warranties. The decision
and its reasons are **recorded on the service request at intake**, so later changes to the
warranty do not rewrite past claim decisions (see NORMALIZATION.md).

## 6. Same-product guarantee through a composite foreign key

A service request may reference a warranty, but only one belonging to the same product. Instead
of a trigger, `warranties` exposes `UNIQUE (warranty_id, product_id)` and `service_requests` has
`FOREIGN KEY (warranty_id, product_id) REFERENCES warranties (warranty_id, product_id)`. With
`MATCH SIMPLE` semantics a NULL `warranty_id` (no applicable warranty) is still allowed.

## 7. Delete rules preserve history

Almost all FKs are `ON DELETE RESTRICT`: a product with warranties or service history, a part
used in repairs, or a technician who performed repairs cannot be deleted. Removal is expressed by
status (`product_status = 'Retired'`, `employment_status = 'Inactive'`, `warranty_status =
'Voided'`). `SET NULL` is used only for actor references (`audit_logs.user_id`,
`inventory_transactions.user_id`, …) so the audit trail survives a user account being removed.
Nothing cascades deletes.

## 8. Repairs are separate from complaints

`service_requests` is the customer's complaint; `repair_history` stores each **attempt**
(numbered per request). A "Not Fixed" attempt followed by a "Fixed" attempt is two rows, which is
what makes first-time-fix rate and repeat-repair analysis possible.

## 9. Repair + inventory = one transaction

Recording a repair performs, in a single transaction:

1. `SELECT … FOR UPDATE` on the service request (serialises concurrent submissions);
2. validate the state transition and technician;
3. insert the `repair_history` row;
4. `SELECT … FOR UPDATE` on all referenced parts, **ordered by part_id** to avoid deadlocks;
5. verify stock for every line *before* changing anything;
6. deduct stock, insert `repair_parts` lines (with `unit_cost_at_repair`) and
   `inventory_transactions` ledger rows;
7. write `parts_cost` and an audit entry; commit.

Service functions only `flush()`; the API endpoint owns the single `commit()`. Any exception rolls
back the whole unit: a repair can never be saved while its inventory is unchanged, or the
reverse. `CHECK (stock_quantity >= 0)` is the database-level backstop.

**Duplicate submissions**: the client sends an `idempotency_key` (one per form instance). It is
`UNIQUE` on `repair_history`; resubmitting returns the existing repair without a second
deduction. Completing an already-resolved request returns `409 Conflict`.

## 10. Stock balance + append-only ledger

`parts.stock_quantity` is the current balance (lockable, CHECK-able);
`inventory_transactions` is the append-only ledger (`Initial Stock`, `Restock`, `Repair
Consumption`, `Adjustment`) with `stock_after`. Negative stock is rejected; corrections go
through an explicit, reason-required, role-restricted **Adjustment** workflow.

## 11. Service-request state machine

```
Open → Assigned → In Progress → Resolved → Closed
  ↑________|          ↑____________|   (unassign / reopen)
Open | Assigned | In Progress → Cancelled   (only while no repair is recorded)
```

The allowed-transition table lives in `services/service_requests.py`; resolution is only possible
through the `complete` workflow (it requires at least one repair). The database adds CHECKs so
that even a buggy client cannot store "Resolved without a resolution date" or "Assigned without a
technician".

## 12. Predictions and training runs are history, not state

`failure_predictions` keeps every prediction (`prediction_status` Current / Superseded) together
with the model version, the feature vector used (`feature_snapshot` JSONB) and the explanation.
A partial unique index guarantees one Current prediction per product and horizon.
`model_training_runs` records every run, including failed runs and runs with insufficient data;
a partial unique index allows only one active model. The model's **classification**
(`validated` / `demonstration` / `not_applicable`) is stored so the UI can never present a model
trained on synthetic data as validated.

## 13. JSONB only for documents

`JSONB` is used for write-once documents that are never filtered or joined on: evaluation reports,
model parameters, feature snapshots, explanation details, audit details and settings values.
Every queryable attribute is a typed column.

## 14. Money and time

Money is `NUMERIC(12,2)` (exact decimal arithmetic; the API serialises it as strings or numbers,
never floats in storage). Timestamps are `TIMESTAMPTZ`; every database session is pinned to UTC
(`-c timezone=UTC`), and the browser formats them in local time. Calendar facts (purchase date,
warranty dates) are `DATE`.

## 15. Personally identifiable information

Customer contact details are needed for service, so they are stored. Mitigations: authentication
is required for every endpoint; deletions are restricted; logs and audit entries record IDs and
field names rather than contact values; the seed data uses the reserved `example.com` domain and
fictional names. Production deployments should add encryption at rest and a retention policy
(see README, *Limitations*).

## 16. Indexing strategy

- Every FK column used in joins is indexed (PostgreSQL does not do this automatically).
- Date columns used for windows and trends: `service_requests.reported_at`,
  `repair_history.repair_date`, `warranties.end_date`, `products.purchase_date`.
- Status/category filters: `service_requests.request_status`, `product_models.product_category`.
- Composite `(part_id, created_at)` for the ledger, and `(product_id, prediction_date)` for
  prediction history.
- Expression index `lower(customers.full_name)` for case-insensitive search.
- Partial unique indexes for the three "at most one" business rules.
