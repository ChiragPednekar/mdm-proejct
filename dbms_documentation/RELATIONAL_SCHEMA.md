# Relational Schema

Generated from the SQLAlchemy models (`backend/app/models/entities.py`) by
`python -m scripts.gen_schema_doc`; the executable DDL is `backend/sql/schema.sql`
(rendered from the Alembic migrations). Notation: **PK** primary key, **FK** foreign key,
**UQ** unique, **NN** not null. Every FK is `ON DELETE RESTRICT` unless stated otherwise,
so historical records cannot be orphaned.

## Compact relational notation


- **customers**(<u>customer_id</u>, full_name, email, phone, address, city, created_at)
- **technicians**(<u>technician_id</u>, full_name, email, specialization, employment_status, created_at)
- **users**(<u>user_id</u>, username, email, full_name, password_hash, role, technician_id†, is_active, created_at)
- **product_models**(<u>product_model_id</u>, manufacturer, model_name, product_category, model_description, standard_warranty_months, release_year)
- **products**(<u>product_id</u>, serial_number, product_model_id†, customer_id†, purchase_date, purchase_price, installation_date, product_status, created_at)
- **warranties**(<u>warranty_id</u>, product_id†, parent_warranty_id†, warranty_type, start_date, end_date, coverage_details, covers_parts, covers_labor, covers_wear_and_tear, covers_accidental_damage, warranty_status, extended_warranty, created_at)
- **fault_categories**(<u>fault_category_id</u>, name, description, is_customer_induced, is_wear_and_tear, counts_as_failure)
- **service_requests**(<u>service_request_id</u>, product_id†, warranty_id†, complaint_description, fault_category_id†, reported_at, priority, request_status, failure_severity, assigned_technician_id†, warranty_covered, coverage_notes, resolution_date, resolution_summary, created_at, updated_at)
- **components**(<u>component_id</u>, component_name, component_category, manufacturer, component_description)
- **repair_history**(<u>repair_id</u>, service_request_id†, technician_id†, component_id†, attempt_number, diagnosis, root_cause, repair_action, labor_cost, parts_cost, repair_date, outcome, repeat_failure, idempotency_key, created_at)
- **parts**(<u>part_id</u>, component_id†, part_number, part_name, unit_cost, selling_price, stock_quantity, reorder_level, supplier_name, updated_at)
- **repair_parts**(<u>repair_id</u>†, <u>part_id</u>†, quantity_used, unit_cost_at_repair)
- **inventory_transactions**(<u>inventory_transaction_id</u>, part_id†, transaction_type, quantity_change, stock_after, repair_id†, reason, user_id†, created_at)
- **model_training_runs**(<u>training_run_id</u>, model_name, model_version, training_started_at, training_completed_at, training_dataset_version, training_sample_count, prediction_horizon_days, evaluation_metrics, parameters, model_artifact_reference, training_status, model_classification, is_active, notes, triggered_by†)
- **failure_predictions**(<u>prediction_id</u>, product_id†, training_run_id†, prediction_date, prediction_horizon_days, failure_probability, risk_level, model_version, model_classification, feature_snapshot, explanation, explanation_details, prediction_status, created_by†)
- **audit_logs**(<u>audit_log_id</u>, user_id†, action, entity_type, entity_id, timestamp, details)
- **app_settings**(<u>setting_key</u>, setting_value, description, updated_at)

<u>underlined</u> = primary key, † = foreign key.


## `customers`

| Column | Type | Null | Default | Key / reference |
|---|---|---|---|---|
| `customer_id` | INTEGER | NN |  | PK |
| `full_name` | VARCHAR(120) | NN |  |  |
| `email` | VARCHAR(254) | yes |  | UQ |
| `phone` | VARCHAR(30) | yes |  |  |
| `address` | VARCHAR(255) | yes |  |  |
| `city` | VARCHAR(80) | yes |  |  |
| `created_at` | TIMESTAMP WITH TIME ZONE | NN | now() |  |

**Constraints & indexes**

- CHECK `ck_customers_contact_required`: `email IS NOT NULL OR phone IS NOT NULL`
- CHECK `ck_customers_name_not_blank`: `length(trim(full_name)) > 0`
- INDEX `ix_customers_city` (customers.city)
- INDEX `ix_customers_full_name_lower` (lower(full_name))

## `technicians`

| Column | Type | Null | Default | Key / reference |
|---|---|---|---|---|
| `technician_id` | INTEGER | NN |  | PK |
| `full_name` | VARCHAR(120) | NN |  |  |
| `email` | VARCHAR(254) | NN |  | UQ |
| `specialization` | VARCHAR(80) | NN |  |  |
| `employment_status` | VARCHAR(20) | NN | Active |  |
| `created_at` | TIMESTAMP WITH TIME ZONE | NN | now() |  |

**Constraints & indexes**

- CHECK `ck_technicians_status`: `employment_status IN ('Active', 'On Leave', 'Inactive')`

## `users`

| Column | Type | Null | Default | Key / reference |
|---|---|---|---|---|
| `user_id` | INTEGER | NN |  | PK |
| `username` | VARCHAR(50) | NN |  | UQ |
| `email` | VARCHAR(254) | NN |  | UQ |
| `full_name` | VARCHAR(120) | NN |  |  |
| `password_hash` | VARCHAR(255) | NN |  |  |
| `role` | VARCHAR(20) | NN |  |  |
| `technician_id` | INTEGER | yes |  | UQ; FK → `technicians.technician_id` (SET NULL) |
| `is_active` | BOOLEAN | NN | true |  |
| `created_at` | TIMESTAMP WITH TIME ZONE | NN | now() |  |

**Constraints & indexes**

- CHECK `ck_users_role`: `role IN ('admin', 'service_manager', 'technician')`
- CHECK `ck_users_technician_link`: `role <> 'technician' OR technician_id IS NOT NULL`

## `product_models`

| Column | Type | Null | Default | Key / reference |
|---|---|---|---|---|
| `product_model_id` | INTEGER | NN |  | PK |
| `manufacturer` | VARCHAR(80) | NN |  |  |
| `model_name` | VARCHAR(80) | NN |  |  |
| `product_category` | VARCHAR(40) | NN |  |  |
| `model_description` | TEXT | yes |  |  |
| `standard_warranty_months` | INTEGER | NN |  |  |
| `release_year` | INTEGER | NN |  |  |

**Constraints & indexes**

- CHECK `ck_product_models_category`: `product_category IN ('Laptop', 'Refrigerator', 'Washing Machine', 'Air Conditioner', 'Television')`
- CHECK `ck_product_models_release_year`: `release_year BETWEEN 1990 AND 2100`
- CHECK `ck_product_models_warranty_months`: `standard_warranty_months BETWEEN 1 AND 120`
- UNIQUE `uq_product_models_manufacturer_model` (manufacturer, model_name)
- INDEX `ix_product_models_category` (product_models.product_category)

## `products`

| Column | Type | Null | Default | Key / reference |
|---|---|---|---|---|
| `product_id` | INTEGER | NN |  | PK |
| `serial_number` | VARCHAR(40) | NN |  | UQ |
| `product_model_id` | INTEGER | NN |  | FK → `product_models.product_model_id` (RESTRICT) |
| `customer_id` | INTEGER | NN |  | FK → `customers.customer_id` (RESTRICT) |
| `purchase_date` | DATE | NN |  |  |
| `purchase_price` | NUMERIC(12, 2) | NN |  |  |
| `installation_date` | DATE | yes |  |  |
| `product_status` | VARCHAR(20) | NN | Active |  |
| `created_at` | TIMESTAMP WITH TIME ZONE | NN | now() |  |

**Constraints & indexes**

- CHECK `ck_products_install_after_purchase`: `installation_date IS NULL OR installation_date >= purchase_date`
- CHECK `ck_products_price_non_negative`: `purchase_price >= 0`
- CHECK `ck_products_status`: `product_status IN ('Active', 'Under Repair', 'Replaced', 'Retired')`
- INDEX `ix_products_customer_id` (products.customer_id)
- INDEX `ix_products_product_model_id` (products.product_model_id)
- INDEX `ix_products_purchase_date` (products.purchase_date)

## `warranties`

| Column | Type | Null | Default | Key / reference |
|---|---|---|---|---|
| `warranty_id` | INTEGER | NN |  | PK |
| `product_id` | INTEGER | NN |  | FK → `products.product_id` (RESTRICT) |
| `parent_warranty_id` | INTEGER | yes |  | FK → `warranties.warranty_id` (RESTRICT) |
| `warranty_type` | VARCHAR(40) | NN |  |  |
| `start_date` | DATE | NN |  |  |
| `end_date` | DATE | NN |  |  |
| `coverage_details` | TEXT | yes |  |  |
| `covers_parts` | BOOLEAN | NN | true |  |
| `covers_labor` | BOOLEAN | NN | true |  |
| `covers_wear_and_tear` | BOOLEAN | NN | false |  |
| `covers_accidental_damage` | BOOLEAN | NN | false |  |
| `warranty_status` | VARCHAR(20) | NN | Valid |  |
| `extended_warranty` | BOOLEAN | NN | false |  |
| `created_at` | TIMESTAMP WITH TIME ZONE | NN | now() |  |

**Constraints & indexes**

- CHECK `ck_warranties_admin_status`: `warranty_status IN ('Valid', 'Voided', 'Cancelled')`
- CHECK `ck_warranties_date_range`: `end_date > start_date`
- CHECK `ck_warranties_extended_flag_consistent`: `extended_warranty = (warranty_type <> 'Manufacturer')`
- CHECK `ck_warranties_parent_only_for_ext`: `parent_warranty_id IS NULL OR warranty_type <> 'Manufacturer'`
- CHECK `ck_warranties_type`: `warranty_type IN ('Manufacturer', 'Extended', 'Accidental Damage Protection')`
- UNIQUE `uq_warranties_id_product` (warranty_id, product_id)
- INDEX `ix_warranties_end_date` (warranties.end_date)
- INDEX `ix_warranties_product_id` (warranties.product_id)
- UNIQUE INDEX `uq_warranties_one_manufacturer_per_product` (warranties.product_id) WHERE `warranty_type = 'Manufacturer'`

## `fault_categories`

| Column | Type | Null | Default | Key / reference |
|---|---|---|---|---|
| `fault_category_id` | INTEGER | NN |  | PK |
| `name` | VARCHAR(60) | NN |  | UQ |
| `description` | TEXT | yes |  |  |
| `is_customer_induced` | BOOLEAN | NN | false |  |
| `is_wear_and_tear` | BOOLEAN | NN | false |  |
| `counts_as_failure` | BOOLEAN | NN | true |  |

## `service_requests`

| Column | Type | Null | Default | Key / reference |
|---|---|---|---|---|
| `service_request_id` | INTEGER | NN |  | PK |
| `product_id` | INTEGER | NN |  | FK → `warranties.product_id` (RESTRICT); FK → `products.product_id` (RESTRICT) |
| `warranty_id` | INTEGER | yes |  | FK → `warranties.warranty_id` (RESTRICT) |
| `complaint_description` | TEXT | NN |  |  |
| `fault_category_id` | INTEGER | NN |  | FK → `fault_categories.fault_category_id` (RESTRICT) |
| `reported_at` | TIMESTAMP WITH TIME ZONE | NN |  |  |
| `priority` | VARCHAR(10) | NN | Medium |  |
| `request_status` | VARCHAR(20) | NN | Open |  |
| `failure_severity` | VARCHAR(10) | NN | Moderate |  |
| `assigned_technician_id` | INTEGER | yes |  | FK → `technicians.technician_id` (RESTRICT) |
| `warranty_covered` | BOOLEAN | yes |  |  |
| `coverage_notes` | TEXT | yes |  |  |
| `resolution_date` | TIMESTAMP WITH TIME ZONE | yes |  |  |
| `resolution_summary` | TEXT | yes |  |  |
| `created_at` | TIMESTAMP WITH TIME ZONE | NN | now() |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NN | now() |  |

**Constraints & indexes**

- CHECK `ck_service_requests_priority`: `priority IN ('Low', 'Medium', 'High', 'Critical')`
- CHECK `ck_service_requests_resolution_date_required`: `request_status NOT IN ('Resolved', 'Closed') OR resolution_date IS NOT NULL`
- CHECK `ck_service_requests_resolution_order`: `resolution_date IS NULL OR resolution_date >= reported_at`
- CHECK `ck_service_requests_severity`: `failure_severity IN ('Minor', 'Moderate', 'Major', 'Critical')`
- CHECK `ck_service_requests_status`: `request_status IN ('Open', 'Assigned', 'In Progress', 'Resolved', 'Closed', 'Cancelled')`
- CHECK `ck_service_requests_technician_required`: `request_status NOT IN ('Assigned', 'In Progress') OR assigned_technician_id IS NOT NULL`
- Composite FK `fk_service_requests_warranty_same_product` (warranty_id, product_id) → `warranties` (warranty_id, product_id)
- INDEX `ix_service_requests_fault_category` (service_requests.fault_category_id)
- INDEX `ix_service_requests_product_id` (service_requests.product_id)
- INDEX `ix_service_requests_reported_at` (service_requests.reported_at)
- INDEX `ix_service_requests_status` (service_requests.request_status)
- INDEX `ix_service_requests_technician` (service_requests.assigned_technician_id)

## `components`

| Column | Type | Null | Default | Key / reference |
|---|---|---|---|---|
| `component_id` | INTEGER | NN |  | PK |
| `component_name` | VARCHAR(80) | NN |  |  |
| `component_category` | VARCHAR(60) | NN |  |  |
| `manufacturer` | VARCHAR(80) | yes |  |  |
| `component_description` | TEXT | yes |  |  |

**Constraints & indexes**

- UNIQUE `uq_components_name_manufacturer` (component_name, manufacturer)

## `repair_history`

| Column | Type | Null | Default | Key / reference |
|---|---|---|---|---|
| `repair_id` | INTEGER | NN |  | PK |
| `service_request_id` | INTEGER | NN |  | FK → `service_requests.service_request_id` (RESTRICT) |
| `technician_id` | INTEGER | NN |  | FK → `technicians.technician_id` (RESTRICT) |
| `component_id` | INTEGER | yes |  | FK → `components.component_id` (RESTRICT) |
| `attempt_number` | INTEGER | NN |  |  |
| `diagnosis` | TEXT | NN |  |  |
| `root_cause` | TEXT | yes |  |  |
| `repair_action` | TEXT | NN |  |  |
| `labor_cost` | NUMERIC(12, 2) | NN | 0 |  |
| `parts_cost` | NUMERIC(12, 2) | NN | 0 |  |
| `repair_date` | TIMESTAMP WITH TIME ZONE | NN |  |  |
| `outcome` | VARCHAR(20) | NN |  |  |
| `repeat_failure` | BOOLEAN | NN | false |  |
| `idempotency_key` | VARCHAR(64) | yes |  | UQ |
| `created_at` | TIMESTAMP WITH TIME ZONE | NN | now() |  |

**Constraints & indexes**

- CHECK `ck_repair_history_attempt_positive`: `attempt_number >= 1`
- CHECK `ck_repair_history_labor_non_negative`: `labor_cost >= 0`
- CHECK `ck_repair_history_outcome`: `outcome IN ('Fixed', 'Partially Fixed', 'Not Fixed', 'Unit Replaced', 'Referred')`
- CHECK `ck_repair_history_parts_non_negative`: `parts_cost >= 0`
- UNIQUE `uq_repair_history_attempt` (service_request_id, attempt_number)
- INDEX `ix_repair_history_component` (repair_history.component_id)
- INDEX `ix_repair_history_repair_date` (repair_history.repair_date)
- INDEX `ix_repair_history_service_request` (repair_history.service_request_id)
- INDEX `ix_repair_history_technician` (repair_history.technician_id)

## `parts`

| Column | Type | Null | Default | Key / reference |
|---|---|---|---|---|
| `part_id` | INTEGER | NN |  | PK |
| `component_id` | INTEGER | yes |  | FK → `components.component_id` (RESTRICT) |
| `part_number` | VARCHAR(40) | NN |  | UQ |
| `part_name` | VARCHAR(120) | NN |  |  |
| `unit_cost` | NUMERIC(12, 2) | NN |  |  |
| `selling_price` | NUMERIC(12, 2) | yes |  |  |
| `stock_quantity` | INTEGER | NN | 0 |  |
| `reorder_level` | INTEGER | NN | 5 |  |
| `supplier_name` | VARCHAR(120) | yes |  |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NN | now() |  |

**Constraints & indexes**

- CHECK `ck_parts_reorder_non_negative`: `reorder_level >= 0`
- CHECK `ck_parts_selling_price_non_negative`: `selling_price IS NULL OR selling_price >= 0`
- CHECK `ck_parts_stock_non_negative`: `stock_quantity >= 0`
- CHECK `ck_parts_unit_cost_non_negative`: `unit_cost >= 0`
- INDEX `ix_parts_component_id` (parts.component_id)

## `repair_parts`

| Column | Type | Null | Default | Key / reference |
|---|---|---|---|---|
| `repair_id` | INTEGER | NN |  | PK; FK → `repair_history.repair_id` (RESTRICT) |
| `part_id` | INTEGER | NN |  | PK; FK → `parts.part_id` (RESTRICT) |
| `quantity_used` | INTEGER | NN |  |  |
| `unit_cost_at_repair` | NUMERIC(12, 2) | NN |  |  |

**Constraints & indexes**

- CHECK `ck_repair_parts_cost_non_negative`: `unit_cost_at_repair >= 0`
- CHECK `ck_repair_parts_quantity_positive`: `quantity_used > 0`
- INDEX `ix_repair_parts_part_id` (repair_parts.part_id)

## `inventory_transactions`

| Column | Type | Null | Default | Key / reference |
|---|---|---|---|---|
| `inventory_transaction_id` | BIGINT | NN |  | PK |
| `part_id` | INTEGER | NN |  | FK → `parts.part_id` (RESTRICT) |
| `transaction_type` | VARCHAR(30) | NN |  |  |
| `quantity_change` | INTEGER | NN |  |  |
| `stock_after` | INTEGER | NN |  |  |
| `repair_id` | INTEGER | yes |  | FK → `repair_history.repair_id` (RESTRICT) |
| `reason` | TEXT | yes |  |  |
| `user_id` | INTEGER | yes |  | FK → `users.user_id` (SET NULL) |
| `created_at` | TIMESTAMP WITH TIME ZONE | NN | now() |  |

**Constraints & indexes**

- CHECK `ck_inventory_txn_consumption_has_repair`: `transaction_type <> 'Repair Consumption' OR (repair_id IS NOT NULL AND quantity_change < 0)`
- CHECK `ck_inventory_txn_nonzero`: `quantity_change <> 0`
- CHECK `ck_inventory_txn_stock_after`: `stock_after >= 0`
- CHECK `ck_inventory_txn_type`: `transaction_type IN ('Initial Stock', 'Restock', 'Repair Consumption', 'Adjustment')`
- INDEX `ix_inventory_txn_part_created` (inventory_transactions.part_id, inventory_transactions.created_at)
- INDEX `ix_inventory_txn_repair` (inventory_transactions.repair_id)

## `model_training_runs`

| Column | Type | Null | Default | Key / reference |
|---|---|---|---|---|
| `training_run_id` | INTEGER | NN |  | PK |
| `model_name` | VARCHAR(80) | NN |  |  |
| `model_version` | VARCHAR(60) | NN |  | UQ |
| `training_started_at` | TIMESTAMP WITH TIME ZONE | NN |  |  |
| `training_completed_at` | TIMESTAMP WITH TIME ZONE | yes |  |  |
| `training_dataset_version` | VARCHAR(120) | yes |  |  |
| `training_sample_count` | INTEGER | yes |  |  |
| `prediction_horizon_days` | INTEGER | NN | 30 |  |
| `evaluation_metrics` | JSONB | yes |  |  |
| `parameters` | JSONB | yes |  |  |
| `model_artifact_reference` | VARCHAR(255) | yes |  |  |
| `training_status` | VARCHAR(20) | NN |  |  |
| `model_classification` | VARCHAR(20) | NN | not_applicable |  |
| `is_active` | BOOLEAN | NN | false |  |
| `notes` | TEXT | yes |  |  |
| `triggered_by` | INTEGER | yes |  | FK → `users.user_id` (SET NULL) |

**Constraints & indexes**

- CHECK `ck_training_runs_classification`: `model_classification IN ('validated', 'demonstration', 'not_applicable')`
- CHECK `ck_training_runs_count`: `training_sample_count IS NULL OR training_sample_count >= 0`
- CHECK `ck_training_runs_status`: `training_status IN ('Running', 'Completed', 'Failed', 'Insufficient Data')`
- UNIQUE INDEX `uq_training_runs_single_active` (model_training_runs.is_active) WHERE `is_active`

## `failure_predictions`

| Column | Type | Null | Default | Key / reference |
|---|---|---|---|---|
| `prediction_id` | INTEGER | NN |  | PK |
| `product_id` | INTEGER | NN |  | FK → `products.product_id` (RESTRICT) |
| `training_run_id` | INTEGER | NN |  | FK → `model_training_runs.training_run_id` (RESTRICT) |
| `prediction_date` | TIMESTAMP WITH TIME ZONE | NN |  |  |
| `prediction_horizon_days` | INTEGER | NN |  |  |
| `failure_probability` | NUMERIC(6, 5) | NN |  |  |
| `risk_level` | VARCHAR(10) | NN |  |  |
| `model_version` | VARCHAR(60) | NN |  |  |
| `model_classification` | VARCHAR(20) | NN |  |  |
| `feature_snapshot` | JSONB | NN |  |  |
| `explanation` | TEXT | NN |  |  |
| `explanation_details` | JSONB | yes |  |  |
| `prediction_status` | VARCHAR(12) | NN | Current |  |
| `created_by` | INTEGER | yes |  | FK → `users.user_id` (SET NULL) |

**Constraints & indexes**

- CHECK `ck_predictions_classification`: `model_classification IN ('validated', 'demonstration')`
- CHECK `ck_predictions_horizon`: `prediction_horizon_days > 0`
- CHECK `ck_predictions_probability`: `failure_probability >= 0 AND failure_probability <= 1`
- CHECK `ck_predictions_risk_level`: `risk_level IN ('Low', 'Medium', 'High')`
- CHECK `ck_predictions_status`: `prediction_status IN ('Current', 'Superseded')`
- INDEX `ix_predictions_product_date` (failure_predictions.product_id, failure_predictions.prediction_date)
- UNIQUE INDEX `uq_predictions_one_current` (failure_predictions.product_id, failure_predictions.prediction_horizon_days) WHERE `prediction_status = 'Current'`

## `audit_logs`

| Column | Type | Null | Default | Key / reference |
|---|---|---|---|---|
| `audit_log_id` | BIGINT | NN |  | PK |
| `user_id` | INTEGER | yes |  | FK → `users.user_id` (SET NULL) |
| `action` | VARCHAR(60) | NN |  |  |
| `entity_type` | VARCHAR(60) | NN |  |  |
| `entity_id` | VARCHAR(60) | yes |  |  |
| `timestamp` | TIMESTAMP WITH TIME ZONE | NN | now() |  |
| `details` | JSONB | yes |  |  |

**Constraints & indexes**

- INDEX `ix_audit_logs_entity` (audit_logs.entity_type, audit_logs.entity_id)
- INDEX `ix_audit_logs_timestamp` (audit_logs.timestamp)

## `app_settings`

| Column | Type | Null | Default | Key / reference |
|---|---|---|---|---|
| `setting_key` | VARCHAR(80) | NN |  | PK |
| `setting_value` | JSONB | NN |  |  |
| `description` | TEXT | yes |  |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NN | now() |  |
