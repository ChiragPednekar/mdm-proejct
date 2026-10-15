# Entity–Relationship Diagram

The diagram below is Mermaid `erDiagram` syntax (renders on GitHub, in VS Code with a Mermaid
extension, or at mermaid.live). Crow's-foot notation: `||` exactly one, `o|` zero or one,
`|{` one or more, `o{` zero or more. Only keys and the attributes that matter for the
relationships are shown; see [RELATIONAL_SCHEMA.md](RELATIONAL_SCHEMA.md) for every column.

```mermaid
erDiagram
    CUSTOMERS ||--o{ PRODUCTS : "owns"
    PRODUCT_MODELS ||--o{ PRODUCTS : "is model of"
    PRODUCTS ||--o{ WARRANTIES : "is covered by"
    WARRANTIES |o--o{ WARRANTIES : "extends (parent_warranty_id)"
    PRODUCTS ||--o{ SERVICE_REQUESTS : "has complaints"
    WARRANTIES |o--o{ SERVICE_REQUESTS : "evaluated against"
    FAULT_CATEGORIES ||--o{ SERVICE_REQUESTS : "classifies"
    TECHNICIANS |o--o{ SERVICE_REQUESTS : "is assigned"
    SERVICE_REQUESTS ||--o{ REPAIR_HISTORY : "has attempts"
    TECHNICIANS ||--o{ REPAIR_HISTORY : "performs"
    COMPONENTS |o--o{ REPAIR_HISTORY : "is repaired in"
    COMPONENTS |o--o{ PARTS : "is supplied as"
    REPAIR_HISTORY ||--o{ REPAIR_PARTS : "consumes"
    PARTS ||--o{ REPAIR_PARTS : "is used in"
    PARTS ||--o{ INVENTORY_TRANSACTIONS : "stock ledger"
    REPAIR_HISTORY |o--o{ INVENTORY_TRANSACTIONS : "causes"
    PRODUCTS ||--o{ FAILURE_PREDICTIONS : "is scored"
    MODEL_TRAINING_RUNS ||--o{ FAILURE_PREDICTIONS : "produced by"
    TECHNICIANS |o--o| USERS : "logs in as"
    USERS |o--o{ AUDIT_LOGS : "performs"
    USERS |o--o{ INVENTORY_TRANSACTIONS : "records"
    USERS |o--o{ MODEL_TRAINING_RUNS : "triggers"
    USERS |o--o{ FAILURE_PREDICTIONS : "requests"

    CUSTOMERS {
        int customer_id PK
        varchar full_name
        varchar email UK "nullable, unique when present"
        varchar phone
        varchar city
    }
    PRODUCT_MODELS {
        int product_model_id PK
        varchar manufacturer UK "UK(manufacturer, model_name)"
        varchar model_name UK
        varchar product_category
        int standard_warranty_months
        int release_year
    }
    PRODUCTS {
        int product_id PK
        varchar serial_number UK
        int product_model_id FK
        int customer_id FK
        date purchase_date
        numeric purchase_price
        date installation_date
        varchar product_status
    }
    WARRANTIES {
        int warranty_id PK
        int product_id FK
        int parent_warranty_id FK "self-reference for extensions"
        varchar warranty_type
        date start_date
        date end_date
        bool covers_parts
        bool covers_labor
        bool covers_wear_and_tear
        bool covers_accidental_damage
        varchar warranty_status "administrative only"
        bool extended_warranty
    }
    FAULT_CATEGORIES {
        int fault_category_id PK
        varchar name UK
        bool is_customer_induced
        bool is_wear_and_tear
        bool counts_as_failure
    }
    SERVICE_REQUESTS {
        int service_request_id PK
        int product_id FK
        int warranty_id FK "composite FK (warranty_id, product_id)"
        int fault_category_id FK
        int assigned_technician_id FK
        timestamptz reported_at
        varchar priority
        varchar failure_severity
        varchar request_status
        bool warranty_covered "decision recorded at intake"
        timestamptz resolution_date
    }
    TECHNICIANS {
        int technician_id PK
        varchar full_name
        varchar email UK
        varchar specialization
        varchar employment_status
    }
    REPAIR_HISTORY {
        int repair_id PK
        int service_request_id FK "UK(service_request_id, attempt_number)"
        int technician_id FK
        int component_id FK
        int attempt_number
        numeric labor_cost
        numeric parts_cost "snapshot of repair_parts total"
        timestamptz repair_date
        varchar outcome
        bool repeat_failure
        varchar idempotency_key UK
    }
    COMPONENTS {
        int component_id PK
        varchar component_name UK "UK(component_name, manufacturer)"
        varchar component_category
    }
    PARTS {
        int part_id PK
        int component_id FK
        varchar part_number UK
        numeric unit_cost
        int stock_quantity "CHECK >= 0"
        int reorder_level
    }
    REPAIR_PARTS {
        int repair_id PK, FK
        int part_id PK, FK
        int quantity_used "CHECK > 0"
        numeric unit_cost_at_repair
    }
    INVENTORY_TRANSACTIONS {
        bigint inventory_transaction_id PK
        int part_id FK
        int repair_id FK
        int user_id FK
        varchar transaction_type
        int quantity_change
        int stock_after
    }
    MODEL_TRAINING_RUNS {
        int training_run_id PK
        varchar model_version UK
        varchar training_status
        varchar model_classification
        jsonb evaluation_metrics
        bool is_active "partial UK: one active"
    }
    FAILURE_PREDICTIONS {
        int prediction_id PK
        int product_id FK
        int training_run_id FK
        numeric failure_probability "CHECK 0..1"
        varchar risk_level
        jsonb feature_snapshot
        varchar prediction_status "partial UK: one Current per product+horizon"
    }
    USERS {
        int user_id PK
        varchar username UK
        varchar role
        int technician_id FK, UK
    }
    AUDIT_LOGS {
        bigint audit_log_id PK
        int user_id FK
        varchar action
        varchar entity_type
        varchar entity_id
        jsonb details
    }
```

`APP_SETTINGS` (key/value configuration) has no relationships and is omitted from the diagram.

## Relationships and cardinalities

| Relationship | Type | Cardinality & participation | Implemented by |
|---|---|---|---|
| Customer **owns** Product | 1 : N | A product has exactly one current owner (total); a customer may own zero or more products (partial). | `products.customer_id` NOT NULL FK |
| Product Model **is model of** Product | 1 : N | Every product has exactly one model; a model may have zero units registered. | `products.product_model_id` NOT NULL FK |
| Product **is covered by** Warranty | 1 : N | A warranty belongs to exactly one product; a product has zero or more warranties, **at most one** of type Manufacturer. | `warranties.product_id` FK + partial unique index |
| Warranty **extends** Warranty | 1 : N (recursive / unary) | An extension optionally points to the warranty it extends; manufacturer warranties never have a parent. | `warranties.parent_warranty_id` self-FK + CHECK |
| Product **has** Service Request | 1 : N | Every request concerns exactly one product. | `service_requests.product_id` NOT NULL FK |
| Warranty **evaluated for** Service Request | 1 : N, optional | A request references zero or one warranty, which must belong to the **same product**. | Composite FK `(warranty_id, product_id) → warranties(warranty_id, product_id)` |
| Fault Category **classifies** Service Request | 1 : N | Every request has exactly one fault category. | `service_requests.fault_category_id` NOT NULL FK |
| Technician **is assigned** Service Request | 1 : N, optional | Zero or one technician; required (CHECK) once status is Assigned / In Progress. | Nullable FK + CHECK |
| Service Request **has** Repair attempt | 1 : N (weak-entity style) | A repair belongs to exactly one request; attempts are numbered 1..n per request. | NOT NULL FK + UNIQUE(service_request_id, attempt_number) |
| Technician **performs** Repair | 1 : N | Every repair has exactly one technician. | NOT NULL FK |
| Component **is repaired in** Repair | 1 : N, optional | Software-only repairs have no component. | Nullable FK |
| Repair **consumes** Part | **M : N** | A repair uses zero or more parts; a part is used in zero or more repairs. The relationship carries attributes (quantity, cost at repair). | Junction table `repair_parts`, composite PK (repair_id, part_id) |
| Component **is supplied as** Part | 1 : N, optional | | Nullable FK |
| Part **has** Inventory Transaction | 1 : N | The append-only stock ledger; consumption rows must reference a repair (CHECK). | NOT NULL FK + CHECK |
| Product **is scored by** Prediction | 1 : N | Historical predictions are kept; only one is `Current` per product and horizon. | FK + partial unique index |
| Training Run **produces** Prediction | 1 : N | Every prediction records the model run that produced it. | NOT NULL FK |
| Technician **logs in as** User | **1 : 1**, optional | A technician account is linked to exactly one technician record (UNIQUE FK); admins and managers have none. | `users.technician_id` UNIQUE FK + CHECK for role = technician |
| User **performs** Audit Log entry | 1 : N, optional | `ON DELETE SET NULL` keeps the audit trail if a user is removed. | Nullable FK |

## Entity notes

- **Strong entities**: customers, product_models, products, warranties, technicians, components, parts, fault_categories, users.
- **Weak-entity style**: `repair_history` is identified within its service request by `attempt_number` (it has its own surrogate key for convenience, but the business key is `(service_request_id, attempt_number)`).
- **Associative entity**: `repair_parts` resolves the many-to-many relationship and stores relationship attributes.
- **Derived / history entities**: `failure_predictions`, `model_training_runs`, `inventory_transactions` and `audit_logs` are append-oriented history tables; rows are never overwritten.
