from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models import Product, Warranty


def test_create_customer_and_validation(client, world):
    h = world.headers()
    r = client.post("/api/v1/customers", json={"full_name": "Nadia Rao", "email": "nadia@example.com",
                                                "phone": "+91 98765 43210", "city": "Pune"}, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["product_count"] == 0
    # Missing both email and phone -> validation error
    r = client.post("/api/v1/customers", json={"full_name": "No Contact"}, headers=h)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    # Duplicate email -> 409 with a friendly message
    r = client.post("/api/v1/customers", json={"full_name": "Dup", "email": "nadia@example.com"}, headers=h)
    assert r.status_code == 409
    assert "already exists" in r.json()["error"]["message"]


def test_register_product_creates_manufacturer_warranty(client, world, db):
    body = {"product_model_id": world.model.product_model_id, "customer_id": world.customer.customer_id,
            "purchase_date": str(date.today() - timedelta(days=10)), "purchase_price": "45999.00"}
    r = client.post("/api/v1/products", json=body, headers=world.headers())
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["product"]["serial_number"].startswith("TES-LT-")
    w = data["warranty"]
    assert w["warranty_type"] == "Manufacturer"
    start, end = date.fromisoformat(w["start_date"]), date.fromisoformat(w["end_date"])
    assert start == date.today() - timedelta(days=10)
    assert 364 <= (end - start).days <= 366  # 12 standard months


def test_serial_number_uniqueness(client, world):
    body = {"serial_number": world.product.serial_number, "product_model_id": world.model.product_model_id,
            "customer_id": world.customer.customer_id, "purchase_date": str(date.today()), "purchase_price": "1"}
    r = client.post("/api/v1/products", json=body, headers=world.headers())
    assert r.status_code == 409
    assert "serial number" in r.json()["error"]["message"]


def test_product_date_validation(client, world):
    body = {"product_model_id": world.model.product_model_id, "customer_id": world.customer.customer_id,
            "purchase_date": str(date.today() + timedelta(days=3)), "purchase_price": "10"}
    assert client.post("/api/v1/products", json=body, headers=world.headers()).status_code == 422


def test_product_profile_and_search(client, world):
    h = world.headers()
    prof = client.get(f"/api/v1/products/{world.product.product_id}", headers=h).json()
    assert prof["coverage"]["covered_today"] is True
    assert prof["warranties"][0]["effective_status"] == "Active"
    assert prof["latest_prediction"] is None
    found = client.get("/api/v1/products", params={"q": "tst-lt"}, headers=h).json()
    assert found["total"] == 1
    assert client.get("/api/v1/products", params={"category": "Television"}, headers=h).json()["total"] == 0


def test_referential_integrity_restrict(client, world, db):
    # API: cannot delete a customer who owns products.
    r = client.delete(f"/api/v1/customers/{world.customer.customer_id}", headers=world.headers())
    assert r.status_code == 409
    # Database: FK to a non-existent model is rejected.
    with pytest.raises(IntegrityError):
        db.add(Product(serial_number="X-1", product_model_id=9999, customer_id=world.customer.customer_id,
                       purchase_date=date.today(), purchase_price=1))
        db.flush()
    db.rollback()
    # Database: ON DELETE RESTRICT protects warranty history.
    with pytest.raises(IntegrityError):
        db.execute(text("DELETE FROM products WHERE product_id = :id"), {"id": world.product.product_id})
    db.rollback()


def test_check_constraints(db, world):
    with pytest.raises(IntegrityError):  # end_date must be after start_date
        db.add(Warranty(product_id=world.product.product_id, warranty_type="Extended", extended_warranty=True,
                        start_date=date.today(), end_date=date.today() - timedelta(days=1)))
        db.flush()
    db.rollback()
    with pytest.raises(IntegrityError):  # only one manufacturer warranty per product (partial unique index)
        db.add(Warranty(product_id=world.product.product_id, warranty_type="Manufacturer", extended_warranty=False,
                        start_date=date.today(), end_date=date.today() + timedelta(days=30)))
        db.flush()
    db.rollback()
