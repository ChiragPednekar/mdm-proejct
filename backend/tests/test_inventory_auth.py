from sqlalchemy import func, select

from app.models import InventoryTransaction, Part


def test_restock_and_adjustment(client, world, db):
    h = world.headers("service_manager")
    url = f"/api/v1/inventory/parts/{world.part.part_id}/adjust"
    r = client.post(url, json={"quantity_change": 10, "transaction_type": "Restock", "reason": "PO-1"}, headers=h)
    assert r.status_code == 200 and r.json()["stock_quantity"] == 15
    r = client.post(url, json={"quantity_change": -20, "transaction_type": "Adjustment", "reason": "count"}, headers=h)
    assert r.status_code == 409  # would go negative
    r = client.post(url, json={"quantity_change": -3, "transaction_type": "Restock", "reason": "x"}, headers=h)
    assert r.status_code == 422  # a restock must add stock
    db.expire_all()
    ledger = db.scalar(select(func.sum(InventoryTransaction.quantity_change))
                       .where(InventoryTransaction.part_id == world.part.part_id))
    assert ledger == db.get(Part, world.part.part_id).stock_quantity == 15


def test_low_stock_and_create_part(client, world):
    h = world.headers()
    low = client.get("/api/v1/inventory/low-stock", headers=h).json()
    assert [p["part_number"] for p in low] == ["PN-SCR-1"]
    r = client.post("/api/v1/inventory/parts", headers=h, json={
        "part_number": "PN-NEW-1", "part_name": "New part", "unit_cost": "10.00", "initial_stock": 3,
        "reorder_level": 1, "component_id": world.component.component_id})
    assert r.status_code == 201 and r.json()["low_stock"] is False
    dup = client.post("/api/v1/inventory/parts", headers=h, json={
        "part_number": "PN-NEW-1", "part_name": "Dup", "unit_cost": "1.00"})
    assert dup.status_code == 409


def test_authentication_and_roles(client, world):
    assert client.get("/api/v1/products").status_code == 401
    assert client.get("/api/v1/products", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    bad = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert bad.status_code == 401
    ok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw-admin"})
    assert ok.status_code == 200 and ok.json()["user"]["role"] == "admin"
    tech = world.headers("technician")
    assert client.post("/api/v1/inventory/parts", headers=tech, json={
        "part_number": "PN-T-1", "part_name": "x", "unit_cost": "1"}).status_code == 403
    assert client.post("/api/v1/models/train", headers=tech).status_code == 403
    assert client.put("/api/v1/settings", headers=world.headers("service_manager"),
                      json={"risk_band_high_min": 0.7}).status_code == 403
    r = client.put("/api/v1/settings", headers=world.headers(), json={"risk_band_medium_min": 0.8})
    assert r.status_code == 422  # medium must stay below high
