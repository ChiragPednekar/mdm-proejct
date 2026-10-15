"""Test configuration.

Tests run against a dedicated PostgreSQL database (TEST_DATABASE_URL, default
warranty_test) that is migrated with Alembic and truncated between tests.
The environment is redirected BEFORE the application modules are imported.
"""
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from dotenv_shim import load_env  # noqa: F401  (tiny helper below)

ROOT = Path(__file__).resolve().parents[2]
_env = load_env(ROOT / ".env")
TEST_URL = os.environ.get("TEST_DATABASE_URL") or _env.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://warranty:warranty_dev@localhost:5432/warranty_test")
os.environ["DATABASE_URL"] = TEST_URL
os.environ["MODEL_ARTIFACT_DIR"] = tempfile.mkdtemp(prefix="warranty-models-")
os.environ["APP_ENV"] = "development"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal, engine  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Component,
    Customer,
    FaultCategory,
    InventoryTransaction,
    Part,
    Product,
    ProductModel,
    Technician,
    User,
    Warranty,
)

TABLES = ("audit_logs, failure_predictions, model_training_runs, inventory_transactions, repair_parts, "
          "repair_history, service_requests, warranties, products, customers, parts, components, users, "
          "technicians, product_models, fault_categories")


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    assert "test" in TEST_URL, "Refusing to run tests against a non-test database"
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_URL)
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def clean_tables():
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        conn.execute(text("""UPDATE app_settings SET setting_value = CASE setting_key
            WHEN 'risk_band_medium_min' THEN '0.30'::jsonb WHEN 'risk_band_high_min' THEN '0.60'::jsonb
            WHEN 'prediction_horizon_days' THEN '30'::jsonb WHEN 'repeat_failure_window_days' THEN '90'::jsonb
            WHEN 'expiring_soon_days' THEN '60'::jsonb ELSE '"operational"'::jsonb END"""))
    yield


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.rollback()
    s.close()


@pytest.fixture
def client():
    return TestClient(app)


class World:
    """Small, fully-known dataset for workflow tests."""

    def __init__(self, db):
        self.db = db
        f = {}
        for name, induced, wear, failure in [
            ("Electrical Failure", False, False, True), ("Battery Degradation", False, True, True),
            ("Physical Damage", True, False, True), ("Installation Request", False, False, False),
        ]:
            f[name] = FaultCategory(name=name, is_customer_induced=induced, is_wear_and_tear=wear,
                                    counts_as_failure=failure)
            db.add(f[name])
        self.faults = f
        self.model = ProductModel(manufacturer="Testco", model_name="T-1000", product_category="Laptop",
                                  standard_warranty_months=12, release_year=2024)
        self.customer = Customer(full_name="Test Customer", email="test.customer@example.com", phone="+91 9000000000")
        self.tech = Technician(full_name="Tina Tech", email="tina@example.com", specialization="Laptops")
        self.tech2 = Technician(full_name="Omar Other", email="omar@example.com", specialization="Laptops")
        self.component = Component(component_name="Battery Pack", component_category="Power")
        db.add_all([self.model, self.customer, self.tech, self.tech2, self.component])
        db.flush()
        self.part = Part(component_id=self.component.component_id, part_number="PN-BAT-1", part_name="Battery",
                         unit_cost=Decimal("2500.00"), stock_quantity=5, reorder_level=2)
        self.part2 = Part(component_id=self.component.component_id, part_number="PN-SCR-1", part_name="Screw kit",
                          unit_cost=Decimal("100.00"), stock_quantity=1, reorder_level=2)
        db.add_all([self.part, self.part2])
        db.flush()
        for p in (self.part, self.part2):
            db.add(InventoryTransaction(part_id=p.part_id, transaction_type="Initial Stock",
                                        quantity_change=p.stock_quantity, stock_after=p.stock_quantity))
        self.product = Product(serial_number="TST-LT-26-00001", product_model_id=self.model.product_model_id,
                               customer_id=self.customer.customer_id, purchase_date=date.today() - timedelta(days=100),
                               purchase_price=Decimal("50000.00"))
        db.add(self.product)
        db.flush()
        self.warranty = Warranty(product_id=self.product.product_id, warranty_type="Manufacturer",
                                 start_date=self.product.purchase_date,
                                 end_date=self.product.purchase_date + timedelta(days=364),
                                 covers_parts=True, covers_labor=True, extended_warranty=False)
        db.add(self.warranty)
        self.users = {}
        tech_user_tech = self.tech
        for role in ("admin", "service_manager", "technician"):
            u = User(username=role, email=f"{role}@example.com", full_name=role.title(),
                     password_hash=hash_password("pw-" + role), role=role,
                     technician_id=tech_user_tech.technician_id if role == "technician" else None)
            db.add(u)
            self.users[role] = u
        db.commit()

    def headers(self, role: str = "admin") -> dict:
        u = self.users[role]
        return {"Authorization": f"Bearer {create_access_token(u.user_id, u.role)}"}


@pytest.fixture
def world(db):
    return World(db)


def utc(days_ago: float = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)
