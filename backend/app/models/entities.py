"""Relational model for the Smart Warranty Intelligence system.

Conventions
-----------
* Surrogate integer primary keys named ``<entity>_id``.
* Enumerated domains are VARCHAR columns guarded by CHECK constraints (portable
  and easy to evolve through migrations, unlike native PG enums).
* Money is NUMERIC(12,2); timestamps are TIMESTAMPTZ stored in UTC.
* Foreign keys default to ON DELETE RESTRICT so that historical records
  (repairs, predictions, warranty claims) can never be silently orphaned.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# ---------------------------------------------------------------------------
# Domain value lists (also used by Pydantic schemas and the frontend)
# ---------------------------------------------------------------------------
PRODUCT_CATEGORIES = (
    "Laptop",
    "Refrigerator",
    "Washing Machine",
    "Air Conditioner",
    "Television",
)
PRODUCT_STATUSES = ("Active", "Under Repair", "Replaced", "Retired")
WARRANTY_TYPES = ("Manufacturer", "Extended", "Accidental Damage Protection")
WARRANTY_ADMIN_STATUSES = ("Valid", "Voided", "Cancelled")
REQUEST_STATUSES = ("Open", "Assigned", "In Progress", "Resolved", "Closed", "Cancelled")
PRIORITIES = ("Low", "Medium", "High", "Critical")
SEVERITIES = ("Minor", "Moderate", "Major", "Critical")
REPAIR_OUTCOMES = ("Fixed", "Partially Fixed", "Not Fixed", "Unit Replaced", "Referred")
EMPLOYMENT_STATUSES = ("Active", "On Leave", "Inactive")
USER_ROLES = ("admin", "service_manager", "technician")
RISK_LEVELS = ("Low", "Medium", "High")
INVENTORY_TXN_TYPES = ("Initial Stock", "Restock", "Repair Consumption", "Adjustment")
TRAINING_STATUSES = ("Running", "Completed", "Failed", "Insufficient Data")
MODEL_CLASSIFICATIONS = ("validated", "demonstration", "not_applicable")


def _in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join("'" + v.replace("'", "''") + "'" for v in values)
    return f"{column} IN ({quoted})"


def _now():
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------
class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        CheckConstraint("email IS NOT NULL OR phone IS NOT NULL", name="ck_customers_contact_required"),
        CheckConstraint("length(trim(full_name)) > 0", name="ck_customers_name_not_blank"),
        Index("ix_customers_full_name_lower", text("lower(full_name)")),
        Index("ix_customers_city", "city"),
    )

    customer_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    phone: Mapped[str | None] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = _now()

    products: Mapped[list[Product]] = relationship(back_populates="customer")


class Technician(Base):
    __tablename__ = "technicians"
    __table_args__ = (CheckConstraint(_in("employment_status", EMPLOYMENT_STATUSES), name="ck_technicians_status"),)

    technician_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    specialization: Mapped[str] = mapped_column(String(80), nullable=False)
    employment_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="Active")
    created_at: Mapped[datetime] = _now()


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(_in("role", USER_ROLES), name="ck_users_role"),
        CheckConstraint("role <> 'technician' OR technician_id IS NOT NULL", name="ck_users_technician_link"),
    )

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    technician_id: Mapped[int | None] = mapped_column(
        ForeignKey("technicians.technician_id", ondelete="SET NULL"), unique=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = _now()

    technician: Mapped[Technician | None] = relationship()


# ---------------------------------------------------------------------------
# Catalogue & registered units
# ---------------------------------------------------------------------------
class ProductModel(Base):
    __tablename__ = "product_models"
    __table_args__ = (
        UniqueConstraint("manufacturer", "model_name", name="uq_product_models_manufacturer_model"),
        CheckConstraint(_in("product_category", PRODUCT_CATEGORIES), name="ck_product_models_category"),
        CheckConstraint("standard_warranty_months BETWEEN 1 AND 120", name="ck_product_models_warranty_months"),
        CheckConstraint("release_year BETWEEN 1990 AND 2100", name="ck_product_models_release_year"),
        Index("ix_product_models_category", "product_category"),
    )

    product_model_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    manufacturer: Mapped[str] = mapped_column(String(80), nullable=False)
    model_name: Mapped[str] = mapped_column(String(80), nullable=False)
    product_category: Mapped[str] = mapped_column(String(40), nullable=False)
    model_description: Mapped[str | None] = mapped_column(Text)
    standard_warranty_months: Mapped[int] = mapped_column(Integer, nullable=False)
    release_year: Mapped[int] = mapped_column(Integer, nullable=False)

    products: Mapped[list[Product]] = relationship(back_populates="product_model")


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("purchase_price >= 0", name="ck_products_price_non_negative"),
        CheckConstraint(
            "installation_date IS NULL OR installation_date >= purchase_date", name="ck_products_install_after_purchase"
        ),
        CheckConstraint(_in("product_status", PRODUCT_STATUSES), name="ck_products_status"),
        Index("ix_products_customer_id", "customer_id"),
        Index("ix_products_product_model_id", "product_model_id"),
        Index("ix_products_purchase_date", "purchase_date"),
    )

    product_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    serial_number: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    product_model_id: Mapped[int] = mapped_column(
        ForeignKey("product_models.product_model_id", ondelete="RESTRICT"), nullable=False
    )
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.customer_id", ondelete="RESTRICT"), nullable=False)
    purchase_date: Mapped[date] = mapped_column(Date, nullable=False)
    purchase_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    installation_date: Mapped[date | None] = mapped_column(Date)
    product_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="Active")
    created_at: Mapped[datetime] = _now()

    customer: Mapped[Customer] = relationship(back_populates="products")
    product_model: Mapped[ProductModel] = relationship(back_populates="products")
    warranties: Mapped[list[Warranty]] = relationship(back_populates="product", order_by="Warranty.start_date")


class Warranty(Base):
    __tablename__ = "warranties"
    __table_args__ = (
        CheckConstraint("end_date > start_date", name="ck_warranties_date_range"),
        CheckConstraint(_in("warranty_type", WARRANTY_TYPES), name="ck_warranties_type"),
        CheckConstraint(_in("warranty_status", WARRANTY_ADMIN_STATUSES), name="ck_warranties_admin_status"),
        CheckConstraint(
            "extended_warranty = (warranty_type <> 'Manufacturer')", name="ck_warranties_extended_flag_consistent"
        ),
        CheckConstraint(
            "parent_warranty_id IS NULL OR warranty_type <> 'Manufacturer'", name="ck_warranties_parent_only_for_ext"
        ),
        # Needed as the target of the composite FK from service_requests.
        UniqueConstraint("warranty_id", "product_id", name="uq_warranties_id_product"),
        # A unit has at most one manufacturer warranty (partial unique index).
        Index(
            "uq_warranties_one_manufacturer_per_product",
            "product_id",
            unique=True,
            postgresql_where=text("warranty_type = 'Manufacturer'"),
        ),
        Index("ix_warranties_product_id", "product_id"),
        Index("ix_warranties_end_date", "end_date"),
    )

    warranty_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.product_id", ondelete="RESTRICT"), nullable=False)
    parent_warranty_id: Mapped[int | None] = mapped_column(
        ForeignKey("warranties.warranty_id", ondelete="RESTRICT")
    )
    warranty_type: Mapped[str] = mapped_column(String(40), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    coverage_details: Mapped[str | None] = mapped_column(Text)
    covers_parts: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    covers_labor: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    covers_wear_and_tear: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    covers_accidental_damage: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Administrative state only. Whether the warranty is *in force* on a given
    # date is derived from the dates (see services/warranty.py and the
    # v_warranty_effective_status view), never trusted from this column alone.
    warranty_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="Valid")
    extended_warranty: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = _now()

    product: Mapped[Product] = relationship(back_populates="warranties")
    parent: Mapped[Warranty | None] = relationship(remote_side="Warranty.warranty_id")


# ---------------------------------------------------------------------------
# Service operations
# ---------------------------------------------------------------------------
class FaultCategory(Base):
    """Lookup table of complaint / fault categories.

    The flags drive warranty exclusions and the ML target definition.
    """

    __tablename__ = "fault_categories"

    fault_category_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_customer_induced: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_wear_and_tear: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # False for non-failure visits (installation, preventive maintenance).
    counts_as_failure: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class ServiceRequest(Base):
    __tablename__ = "service_requests"
    __table_args__ = (
        CheckConstraint(_in("request_status", REQUEST_STATUSES), name="ck_service_requests_status"),
        CheckConstraint(_in("priority", PRIORITIES), name="ck_service_requests_priority"),
        CheckConstraint(_in("failure_severity", SEVERITIES), name="ck_service_requests_severity"),
        CheckConstraint(
            "request_status NOT IN ('Resolved', 'Closed') OR resolution_date IS NOT NULL",
            name="ck_service_requests_resolution_date_required",
        ),
        CheckConstraint(
            "request_status NOT IN ('Assigned', 'In Progress') OR assigned_technician_id IS NOT NULL",
            name="ck_service_requests_technician_required",
        ),
        CheckConstraint(
            "resolution_date IS NULL OR resolution_date >= reported_at", name="ck_service_requests_resolution_order"
        ),
        # The referenced warranty must belong to the same product.
        ForeignKeyConstraint(
            ["warranty_id", "product_id"],
            ["warranties.warranty_id", "warranties.product_id"],
            name="fk_service_requests_warranty_same_product",
            ondelete="RESTRICT",
        ),
        Index("ix_service_requests_product_id", "product_id"),
        Index("ix_service_requests_status", "request_status"),
        Index("ix_service_requests_reported_at", "reported_at"),
        Index("ix_service_requests_technician", "assigned_technician_id"),
        Index("ix_service_requests_fault_category", "fault_category_id"),
    )

    service_request_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.product_id", ondelete="RESTRICT"), nullable=False)
    warranty_id: Mapped[int | None] = mapped_column(Integer)
    complaint_description: Mapped[str] = mapped_column(Text, nullable=False)
    fault_category_id: Mapped[int] = mapped_column(
        ForeignKey("fault_categories.fault_category_id", ondelete="RESTRICT"), nullable=False
    )
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    priority: Mapped[str] = mapped_column(String(10), nullable=False, server_default="Medium")
    request_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="Open")
    failure_severity: Mapped[str] = mapped_column(String(10), nullable=False, server_default="Moderate")
    assigned_technician_id: Mapped[int | None] = mapped_column(
        ForeignKey("technicians.technician_id", ondelete="RESTRICT")
    )
    # Coverage decision recorded when the warranty was checked (a historical
    # fact: later edits to the warranty must not rewrite past claim decisions).
    warranty_covered: Mapped[bool | None] = mapped_column(Boolean)
    coverage_notes: Mapped[str | None] = mapped_column(Text)
    resolution_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    product: Mapped[Product] = relationship()
    warranty: Mapped[Warranty | None] = relationship(
        primaryjoin="ServiceRequest.warranty_id == Warranty.warranty_id",
        foreign_keys="ServiceRequest.warranty_id",
        viewonly=True,
    )
    fault_category: Mapped[FaultCategory] = relationship()
    technician: Mapped[Technician | None] = relationship()
    repairs: Mapped[list[RepairHistory]] = relationship(
        back_populates="service_request", order_by="RepairHistory.attempt_number"
    )


class Component(Base):
    __tablename__ = "components"
    __table_args__ = (UniqueConstraint("component_name", "manufacturer", name="uq_components_name_manufacturer"),)

    component_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component_name: Mapped[str] = mapped_column(String(80), nullable=False)
    component_category: Mapped[str] = mapped_column(String(60), nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(80))
    component_description: Mapped[str | None] = mapped_column(Text)


class RepairHistory(Base):
    __tablename__ = "repair_history"
    __table_args__ = (
        UniqueConstraint("service_request_id", "attempt_number", name="uq_repair_history_attempt"),
        CheckConstraint("attempt_number >= 1", name="ck_repair_history_attempt_positive"),
        CheckConstraint("labor_cost >= 0", name="ck_repair_history_labor_non_negative"),
        CheckConstraint("parts_cost >= 0", name="ck_repair_history_parts_non_negative"),
        CheckConstraint(_in("outcome", REPAIR_OUTCOMES), name="ck_repair_history_outcome"),
        Index("ix_repair_history_service_request", "service_request_id"),
        Index("ix_repair_history_technician", "technician_id"),
        Index("ix_repair_history_component", "component_id"),
        Index("ix_repair_history_repair_date", "repair_date"),
    )

    repair_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_request_id: Mapped[int] = mapped_column(
        ForeignKey("service_requests.service_request_id", ondelete="RESTRICT"), nullable=False
    )
    technician_id: Mapped[int] = mapped_column(
        ForeignKey("technicians.technician_id", ondelete="RESTRICT"), nullable=False
    )
    component_id: Mapped[int | None] = mapped_column(ForeignKey("components.component_id", ondelete="RESTRICT"))
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    diagnosis: Mapped[str] = mapped_column(Text, nullable=False)
    root_cause: Mapped[str | None] = mapped_column(Text)
    repair_action: Mapped[str] = mapped_column(Text, nullable=False)
    labor_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    # Total of the repair_parts lines, written in the same transaction as those
    # lines. Kept as an invoice snapshot; see DATABASE_DESIGN_DECISIONS.md.
    parts_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    repair_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    # True when this product had a previous completed repair within the repeat
    # window (90 days) before this request was reported.
    repeat_failure: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = _now()

    service_request: Mapped[ServiceRequest] = relationship(back_populates="repairs")
    technician: Mapped[Technician] = relationship()
    component: Mapped[Component | None] = relationship()
    parts: Mapped[list[RepairPart]] = relationship(back_populates="repair")


class Part(Base):
    __tablename__ = "parts"
    __table_args__ = (
        CheckConstraint("unit_cost >= 0", name="ck_parts_unit_cost_non_negative"),
        CheckConstraint("selling_price IS NULL OR selling_price >= 0", name="ck_parts_selling_price_non_negative"),
        CheckConstraint("stock_quantity >= 0", name="ck_parts_stock_non_negative"),
        CheckConstraint("reorder_level >= 0", name="ck_parts_reorder_non_negative"),
        Index("ix_parts_component_id", "component_id"),
    )

    part_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component_id: Mapped[int | None] = mapped_column(ForeignKey("components.component_id", ondelete="RESTRICT"))
    part_number: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    part_name: Mapped[str] = mapped_column(String(120), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    selling_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    stock_quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    reorder_level: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    supplier_name: Mapped[str | None] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    component: Mapped[Component | None] = relationship()


class RepairPart(Base):
    """Junction table resolving the M:N relationship repair_history <-> parts."""

    __tablename__ = "repair_parts"
    __table_args__ = (
        CheckConstraint("quantity_used > 0", name="ck_repair_parts_quantity_positive"),
        CheckConstraint("unit_cost_at_repair >= 0", name="ck_repair_parts_cost_non_negative"),
        Index("ix_repair_parts_part_id", "part_id"),
    )

    repair_id: Mapped[int] = mapped_column(
        ForeignKey("repair_history.repair_id", ondelete="RESTRICT"), primary_key=True
    )
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.part_id", ondelete="RESTRICT"), primary_key=True)
    quantity_used: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost_at_repair: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    repair: Mapped[RepairHistory] = relationship(back_populates="parts")
    part: Mapped[Part] = relationship()


class InventoryTransaction(Base):
    __tablename__ = "inventory_transactions"
    __table_args__ = (
        CheckConstraint(_in("transaction_type", INVENTORY_TXN_TYPES), name="ck_inventory_txn_type"),
        CheckConstraint("quantity_change <> 0", name="ck_inventory_txn_nonzero"),
        CheckConstraint("stock_after >= 0", name="ck_inventory_txn_stock_after"),
        CheckConstraint(
            "transaction_type <> 'Repair Consumption' OR (repair_id IS NOT NULL AND quantity_change < 0)",
            name="ck_inventory_txn_consumption_has_repair",
        ),
        Index("ix_inventory_txn_part_created", "part_id", "created_at"),
        Index("ix_inventory_txn_repair", "repair_id"),
    )

    inventory_transaction_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.part_id", ondelete="RESTRICT"), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    quantity_change: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_after: Mapped[int] = mapped_column(Integer, nullable=False)
    repair_id: Mapped[int | None] = mapped_column(ForeignKey("repair_history.repair_id", ondelete="RESTRICT"))
    reason: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.user_id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _now()

    part: Mapped[Part] = relationship()


# ---------------------------------------------------------------------------
# Machine learning
# ---------------------------------------------------------------------------
class ModelTrainingRun(Base):
    __tablename__ = "model_training_runs"
    __table_args__ = (
        CheckConstraint(_in("training_status", TRAINING_STATUSES), name="ck_training_runs_status"),
        CheckConstraint(_in("model_classification", MODEL_CLASSIFICATIONS), name="ck_training_runs_classification"),
        CheckConstraint("training_sample_count IS NULL OR training_sample_count >= 0", name="ck_training_runs_count"),
        Index(
            "uq_training_runs_single_active", "is_active", unique=True, postgresql_where=text("is_active")
        ),
    )

    training_run_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_name: Mapped[str] = mapped_column(String(80), nullable=False)
    model_version: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    training_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    training_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    training_dataset_version: Mapped[str | None] = mapped_column(String(120))
    training_sample_count: Mapped[int | None] = mapped_column(Integer)
    prediction_horizon_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    evaluation_metrics: Mapped[dict | None] = mapped_column(JSONB)
    parameters: Mapped[dict | None] = mapped_column(JSONB)
    model_artifact_reference: Mapped[str | None] = mapped_column(String(255))
    training_status: Mapped[str] = mapped_column(String(20), nullable=False)
    model_classification: Mapped[str] = mapped_column(String(20), nullable=False, server_default="not_applicable")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    notes: Mapped[str | None] = mapped_column(Text)
    triggered_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id", ondelete="SET NULL"))


class FailurePrediction(Base):
    __tablename__ = "failure_predictions"
    __table_args__ = (
        CheckConstraint("failure_probability >= 0 AND failure_probability <= 1", name="ck_predictions_probability"),
        CheckConstraint("prediction_horizon_days > 0", name="ck_predictions_horizon"),
        CheckConstraint(_in("risk_level", RISK_LEVELS), name="ck_predictions_risk_level"),
        CheckConstraint(_in("prediction_status", ("Current", "Superseded")), name="ck_predictions_status"),
        CheckConstraint(
            _in("model_classification", ("validated", "demonstration")), name="ck_predictions_classification"
        ),
        Index("ix_predictions_product_date", "product_id", "prediction_date"),
        Index(
            "uq_predictions_one_current",
            "product_id",
            "prediction_horizon_days",
            unique=True,
            postgresql_where=text("prediction_status = 'Current'"),
        ),
    )

    prediction_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.product_id", ondelete="RESTRICT"), nullable=False)
    training_run_id: Mapped[int] = mapped_column(
        ForeignKey("model_training_runs.training_run_id", ondelete="RESTRICT"), nullable=False
    )
    prediction_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    prediction_horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    failure_probability: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False)
    model_version: Mapped[str] = mapped_column(String(60), nullable=False)
    model_classification: Mapped[str] = mapped_column(String(20), nullable=False)
    feature_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    explanation_details: Mapped[list | None] = mapped_column(JSONB)
    prediction_status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="Current")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id", ondelete="SET NULL"))

    product: Mapped[Product] = relationship()


# ---------------------------------------------------------------------------
# Cross-cutting
# ---------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_timestamp", "timestamp"),
    )

    audit_log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.user_id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(60))
    timestamp: Mapped[datetime] = _now()
    details: Mapped[dict | None] = mapped_column(JSONB)


class AppSetting(Base):
    __tablename__ = "app_settings"

    setting_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    setting_value: Mapped[dict | list | str | int | float | bool] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
