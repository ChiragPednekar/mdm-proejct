"""Pydantic request/response schemas."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

T = TypeVar("T")

ProductCategory = Literal["Laptop", "Refrigerator", "Washing Machine", "Air Conditioner", "Television"]
ProductStatus = Literal["Active", "Under Repair", "Replaced", "Retired"]
WarrantyType = Literal["Manufacturer", "Extended", "Accidental Damage Protection"]
RequestStatus = Literal["Open", "Assigned", "In Progress", "Resolved", "Closed", "Cancelled"]
Priority = Literal["Low", "Medium", "High", "Critical"]
Severity = Literal["Minor", "Moderate", "Major", "Critical"]
Outcome = Literal["Fixed", "Partially Fixed", "Not Fixed", "Unit Replaced", "Referred"]
EmploymentStatus = Literal["Active", "On Leave", "Inactive"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


def _strip(v: Any) -> Any:
    return v.strip() if isinstance(v, str) else v


# ---------------------------------------------------------------- auth
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class UserOut(ORM):
    user_id: int
    username: str
    email: str
    full_name: str
    role: str
    technician_id: int | None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ---------------------------------------------------------------- customers
class CustomerIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, pattern=r"^\+?[0-9 ()-]{7,20}$")
    address: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=80)

    _s = field_validator("full_name", "phone", "address", "city", mode="before")(_strip)

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, v: Any) -> Any:
        v = _strip(v)
        return (v or None) if isinstance(v, str) else v

    @model_validator(mode="after")
    def _contact(self):
        if not self.email and not self.phone:
            raise ValueError("Provide at least an email address or a phone number.")
        return self


class CustomerUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, pattern=r"^\+?[0-9 ()-]{7,20}$")
    address: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=80)


class CustomerOut(ORM):
    customer_id: int
    full_name: str
    email: str | None
    phone: str | None
    address: str | None
    city: str | None
    created_at: datetime
    product_count: int | None = None
    service_request_count: int | None = None


# ---------------------------------------------------------------- catalogue
class ProductModelIn(BaseModel):
    manufacturer: str = Field(min_length=2, max_length=80)
    model_name: str = Field(min_length=1, max_length=80)
    product_category: ProductCategory
    model_description: str | None = None
    standard_warranty_months: int = Field(ge=1, le=120)
    release_year: int = Field(ge=1990, le=2100)


class ProductModelOut(ORM):
    product_model_id: int
    manufacturer: str
    model_name: str
    product_category: str
    model_description: str | None
    standard_warranty_months: int
    release_year: int


class FaultCategoryOut(ORM):
    fault_category_id: int
    name: str
    description: str | None
    is_customer_induced: bool
    is_wear_and_tear: bool
    counts_as_failure: bool


class ComponentIn(BaseModel):
    component_name: str = Field(min_length=2, max_length=80)
    component_category: str = Field(min_length=2, max_length=60)
    manufacturer: str | None = Field(default=None, max_length=80)
    component_description: str | None = None


class ComponentOut(ORM):
    component_id: int
    component_name: str
    component_category: str
    manufacturer: str | None
    component_description: str | None


class TechnicianIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    specialization: str = Field(min_length=2, max_length=80)
    employment_status: EmploymentStatus = "Active"


class TechnicianUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    specialization: str | None = Field(default=None, min_length=2, max_length=80)
    employment_status: EmploymentStatus | None = None


class TechnicianOut(ORM):
    technician_id: int
    full_name: str
    email: str
    specialization: str
    employment_status: str


# ---------------------------------------------------------------- products
class ProductIn(BaseModel):
    serial_number: str | None = Field(default=None, min_length=4, max_length=40, pattern=r"^[A-Za-z0-9-]+$")
    product_model_id: int
    customer_id: int
    purchase_date: date
    purchase_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    installation_date: date | None = None
    register_manufacturer_warranty: bool = True

    @model_validator(mode="after")
    def _dates(self):
        if self.purchase_date > date.today():
            raise ValueError("purchase_date cannot be in the future.")
        if self.installation_date and self.installation_date < self.purchase_date:
            raise ValueError("installation_date cannot be before purchase_date.")
        return self


class ProductUpdate(BaseModel):
    product_status: ProductStatus | None = None
    installation_date: date | None = None
    customer_id: int | None = None


class ProductOut(ORM):
    product_id: int
    serial_number: str
    product_model_id: int
    customer_id: int
    purchase_date: date
    purchase_price: Decimal
    installation_date: date | None
    product_status: str
    created_at: datetime


# ---------------------------------------------------------------- warranties
class WarrantyIn(BaseModel):
    product_id: int
    warranty_type: WarrantyType
    start_date: date
    end_date: date
    coverage_details: str | None = None
    covers_parts: bool = True
    covers_labor: bool = True
    covers_wear_and_tear: bool = False
    covers_accidental_damage: bool = False
    parent_warranty_id: int | None = None

    @model_validator(mode="after")
    def _range(self):
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date.")
        return self


class WarrantyExtendIn(BaseModel):
    months: int = Field(ge=1, le=60)
    warranty_type: Literal["Extended", "Accidental Damage Protection"] = "Extended"
    covers_parts: bool = True
    covers_labor: bool = True
    covers_wear_and_tear: bool = False
    covers_accidental_damage: bool = False
    coverage_details: str | None = None


class WarrantyVoidIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)
    status: Literal["Voided", "Cancelled"] = "Voided"


class WarrantyOut(ORM):
    warranty_id: int
    product_id: int
    parent_warranty_id: int | None
    warranty_type: str
    start_date: date
    end_date: date
    coverage_details: str | None
    covers_parts: bool
    covers_labor: bool
    covers_wear_and_tear: bool
    covers_accidental_damage: bool
    warranty_status: str
    extended_warranty: bool
    created_at: datetime
    effective_status: str | None = None
    days_remaining: int | None = None


# ---------------------------------------------------------------- service requests
class ServiceRequestIn(BaseModel):
    product_id: int
    fault_category_id: int
    complaint_description: str = Field(min_length=5, max_length=2000)
    priority: Priority = "Medium"
    failure_severity: Severity = "Moderate"
    reported_at: datetime | None = None
    assigned_technician_id: int | None = None


class ServiceRequestUpdate(BaseModel):
    priority: Priority | None = None
    failure_severity: Severity | None = None
    complaint_description: str | None = Field(default=None, min_length=5, max_length=2000)
    assigned_technician_id: int | None = None
    request_status: RequestStatus | None = None


class PartLineIn(BaseModel):
    part_id: int
    quantity: int = Field(ge=1, le=50)


class RepairIn(BaseModel):
    technician_id: int
    diagnosis: str = Field(min_length=3, max_length=2000)
    root_cause: str | None = Field(default=None, max_length=1000)
    repair_action: str = Field(min_length=3, max_length=2000)
    component_id: int | None = None
    labor_cost: Decimal = Field(ge=0, le=1_000_000, max_digits=12, decimal_places=2)
    outcome: Outcome
    parts: list[PartLineIn] = Field(default_factory=list, max_length=20)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=64)


class CompleteIn(BaseModel):
    resolution_summary: str = Field(min_length=3, max_length=2000)
    final_repair: RepairIn | None = None


class RepairPartOut(BaseModel):
    part_id: int
    part_number: str
    part_name: str
    quantity_used: int
    unit_cost_at_repair: Decimal
    line_total: Decimal


class RepairOut(BaseModel):
    repair_id: int
    service_request_id: int
    attempt_number: int
    technician_id: int
    technician_name: str | None = None
    component_id: int | None
    component_name: str | None = None
    diagnosis: str
    root_cause: str | None
    repair_action: str
    labor_cost: Decimal
    parts_cost: Decimal
    total_cost: Decimal
    repair_date: datetime
    outcome: str
    repeat_failure: bool
    parts: list[RepairPartOut] = []


# ---------------------------------------------------------------- inventory
class PartIn(BaseModel):
    component_id: int | None = None
    part_number: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9-]+$")
    part_name: str = Field(min_length=2, max_length=120)
    unit_cost: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    selling_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    initial_stock: int = Field(default=0, ge=0, le=100000)
    reorder_level: int = Field(default=5, ge=0, le=100000)
    supplier_name: str | None = Field(default=None, max_length=120)


class PartUpdate(BaseModel):
    component_id: int | None = None
    part_name: str | None = Field(default=None, min_length=2, max_length=120)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    selling_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    reorder_level: int | None = Field(default=None, ge=0, le=100000)
    supplier_name: str | None = Field(default=None, max_length=120)


class StockAdjustIn(BaseModel):
    quantity_change: int = Field(ge=-100000, le=100000)
    transaction_type: Literal["Restock", "Adjustment"]
    reason: str = Field(min_length=3, max_length=500)


class PartOut(ORM):
    part_id: int
    component_id: int | None
    part_number: str
    part_name: str
    unit_cost: Decimal
    selling_price: Decimal | None
    stock_quantity: int
    reorder_level: int
    supplier_name: str | None
    updated_at: datetime
    component_name: str | None = None
    low_stock: bool | None = None


# ---------------------------------------------------------------- settings
class SettingsUpdate(BaseModel):
    risk_band_medium_min: float | None = Field(default=None, gt=0, lt=1)
    risk_band_high_min: float | None = Field(default=None, gt=0, lt=1)
    prediction_horizon_days: int | None = Field(default=None, ge=7, le=365)
    repeat_failure_window_days: int | None = Field(default=None, ge=7, le=365)
    expiring_soon_days: int | None = Field(default=None, ge=1, le=365)


class TrainIn(BaseModel):
    horizon_days: int | None = Field(default=None, ge=7, le=365)
