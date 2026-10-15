import uuid
from decimal import Decimal

from sqlalchemy import func, select

from app.models import InventoryTransaction, Part, RepairHistory, RepairPart, ServiceRequest
from conftest import utc

BASE = "/api/v1/service-requests"


def new_request(client, world, fault="Electrical Failure", role="admin", **extra):
    body = {"product_id": world.product.product_id, "fault_category_id": world.faults[fault].fault_category_id,
            "complaint_description": "Laptop does not power on", "priority": "High", "failure_severity": "Major",
            **extra}
    r = client.post(BASE, json=body, headers=world.headers(role))
    assert r.status_code == 201, r.text
    return r.json()


def repair_body(world, parts=None, outcome="Fixed", labor="800.00", key=None):
    return {"technician_id": world.tech.technician_id, "diagnosis": "Battery cell failure",
            "repair_action": "Replaced battery", "component_id": world.component.component_id,
            "labor_cost": labor, "outcome": outcome, "parts": parts or [], "idempotency_key": key}


def assign(client, world, rid, role="admin"):
    r = client.patch(f"{BASE}/{rid}", json={"assigned_technician_id": world.tech.technician_id},
                     headers=world.headers(role))
    assert r.status_code == 200, r.text
    return r.json()


def stock(db, part):
    db.expire_all()
    return db.get(Part, part.part_id).stock_quantity


def test_create_request_checks_warranty(client, world):
    sr = new_request(client, world)
    assert sr["request_status"] == "Open"
    assert sr["warranty_covered"] is True and sr["warranty"]["warranty_id"] == world.warranty.warranty_id
    # Customer-induced damage: the in-force warranty is recorded but does not cover it.
    sr2 = new_request(client, world, fault="Physical Damage")
    assert sr2["warranty_covered"] is False and sr2["warranty"] is not None


def test_duplicate_open_request_rejected(client, world):
    new_request(client, world)
    body = {"product_id": world.product.product_id,
            "fault_category_id": world.faults["Electrical Failure"].fault_category_id,
            "complaint_description": "Same issue again"}
    assert client.post(BASE, json=body, headers=world.headers()).status_code == 409


def test_state_transitions(client, world):
    sr = new_request(client, world)
    rid, h = sr["service_request_id"], world.headers()
    # Open -> In Progress is not allowed (must be assigned first)
    r = client.patch(f"{BASE}/{rid}", json={"request_status": "In Progress"}, headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_state_transition"
    # Resolution only through the complete workflow
    assert client.patch(f"{BASE}/{rid}", json={"request_status": "Resolved"}, headers=h).status_code == 409
    d = assign(client, world, rid)
    assert d["request_status"] == "Assigned"
    d = client.patch(f"{BASE}/{rid}", json={"request_status": "In Progress"}, headers=h).json()
    assert d["request_status"] == "In Progress" and d["product"]["product_status"] == "Under Repair"
    # Completing without any repair is rejected
    r = client.post(f"{BASE}/{rid}/complete", json={"resolution_summary": "done"}, headers=h)
    assert r.status_code == 422
    client.post(f"{BASE}/{rid}/repairs", json=repair_body(world), headers=h)
    d = client.post(f"{BASE}/{rid}/complete", json={"resolution_summary": "Fixed"}, headers=h).json()
    assert d["request_status"] == "Resolved" and d["resolution_date"] and d["product"]["product_status"] == "Active"
    # Completing twice -> conflict; Resolved -> Closed allowed; Closed is terminal
    assert client.post(f"{BASE}/{rid}/complete", json={"resolution_summary": "Again"}, headers=h).status_code == 409
    assert client.patch(f"{BASE}/{rid}", json={"request_status": "Closed"}, headers=h).json()["request_status"] == "Closed"
    assert client.patch(f"{BASE}/{rid}", json={"priority": "Low"}, headers=h).status_code == 409


def test_cancel_not_allowed_after_repairs(client, world):
    rid = new_request(client, world)["service_request_id"]
    assign(client, world, rid)
    client.post(f"{BASE}/{rid}/repairs", json=repair_body(world, outcome="Not Fixed"), headers=world.headers())
    r = client.patch(f"{BASE}/{rid}", json={"request_status": "Cancelled"}, headers=world.headers())
    assert r.status_code == 409


def test_repair_deducts_inventory_and_costs(client, world, db):
    rid = new_request(client, world)["service_request_id"]
    assign(client, world, rid)
    body = repair_body(world, parts=[{"part_id": world.part.part_id, "quantity": 2},
                                     {"part_id": world.part2.part_id, "quantity": 1}])
    r = client.post(f"{BASE}/{rid}/repairs", json=body, headers=world.headers())
    assert r.status_code == 201, r.text
    detail = r.json()["request"]
    rep = detail["repairs"][0]
    assert rep["parts_cost"] == 5100.0  # 2 x 2500 + 1 x 100
    assert rep["labor_cost"] == 800.0 and rep["total_cost"] == 5900.0
    assert detail["costs"]["warranty"] == 5900.0 and detail["costs"]["customer"] == 0.0
    assert stock(db, world.part) == 3 and stock(db, world.part2) == 0
    lines = db.scalars(select(RepairPart).where(RepairPart.repair_id == rep["repair_id"])).all()
    assert {(l.part_id, l.quantity_used, l.unit_cost_at_repair) for l in lines} == {
        (world.part.part_id, 2, Decimal("2500.00")), (world.part2.part_id, 1, Decimal("100.00"))}
    txns = db.scalars(select(InventoryTransaction).where(InventoryTransaction.repair_id == rep["repair_id"])).all()
    assert sorted(t.quantity_change for t in txns) == [-2, -1]
    # Historical cost is frozen: a later price change does not alter past repair lines.
    client.patch(f"/api/v1/inventory/parts/{world.part.part_id}", json={"unit_cost": "9999.00"},
                 headers=world.headers())
    db.expire_all()
    assert db.scalar(select(RepairPart.unit_cost_at_repair).where(
        RepairPart.repair_id == rep["repair_id"], RepairPart.part_id == world.part.part_id)) == Decimal("2500.00")


def test_insufficient_stock_rolls_back_everything(client, world, db):
    rid = new_request(client, world)["service_request_id"]
    assign(client, world, rid)
    client.patch(f"{BASE}/{rid}", json={"request_status": "In Progress"}, headers=world.headers())
    body = repair_body(world, parts=[{"part_id": world.part.part_id, "quantity": 1},
                                     {"part_id": world.part2.part_id, "quantity": 5}])
    r = client.post(f"{BASE}/{rid}/complete", json={"resolution_summary": "done", "final_repair": body},
                    headers=world.headers())
    assert r.status_code == 409 and r.json()["error"]["code"] == "insufficient_stock"
    db.expire_all()
    assert db.get(ServiceRequest, rid).request_status == "In Progress"
    assert db.scalar(select(func.count()).select_from(RepairHistory)) == 0
    assert stock(db, world.part) == 5 and stock(db, world.part2) == 1  # nothing deducted


def test_complete_with_final_repair_is_atomic_success(client, world, db):
    rid = new_request(client, world)["service_request_id"]
    assign(client, world, rid)
    body = repair_body(world, parts=[{"part_id": world.part.part_id, "quantity": 1}])
    r = client.post(f"{BASE}/{rid}/complete", json={"resolution_summary": "Battery replaced", "final_repair": body},
                    headers=world.headers())
    assert r.status_code == 200, r.text
    assert r.json()["request_status"] == "Resolved" and len(r.json()["repairs"]) == 1
    assert stock(db, world.part) == 4


def test_idempotent_repair_submission(client, world, db):
    rid = new_request(client, world)["service_request_id"]
    assign(client, world, rid)
    key = uuid.uuid4().hex
    body = repair_body(world, parts=[{"part_id": world.part.part_id, "quantity": 1}], key=key)
    a = client.post(f"{BASE}/{rid}/repairs", json=body, headers=world.headers())
    b = client.post(f"{BASE}/{rid}/repairs", json=body, headers=world.headers())
    assert a.status_code == b.status_code == 201
    assert a.json()["repair_id"] == b.json()["repair_id"]
    assert stock(db, world.part) == 4  # deducted once
    assert len(b.json()["request"]["repairs"]) == 1


def test_duplicate_part_lines_rejected(client, world, db):
    rid = new_request(client, world)["service_request_id"]
    assign(client, world, rid)
    body = repair_body(world, parts=[{"part_id": world.part.part_id, "quantity": 1},
                                     {"part_id": world.part.part_id, "quantity": 1}])
    assert client.post(f"{BASE}/{rid}/repairs", json=body, headers=world.headers()).status_code == 422
    assert stock(db, world.part) == 5


def test_warranty_cost_split_respects_terms(client, world, db):
    world.warranty.covers_labor = False
    db.commit()
    rid = new_request(client, world)["service_request_id"]
    assign(client, world, rid)
    body = repair_body(world, parts=[{"part_id": world.part.part_id, "quantity": 1}], labor="1000.00")
    d = client.post(f"{BASE}/{rid}/repairs", json=body, headers=world.headers()).json()["request"]
    assert d["costs"] == {"labor": 1000.0, "parts": 2500.0, "total": 3500.0, "warranty": 2500.0, "customer": 1000.0}


def test_repeat_failure_flag(client, world, db):
    h = world.headers()
    rid = new_request(client, world, reported_at=utc(40).isoformat())["service_request_id"]
    assign(client, world, rid)
    client.post(f"{BASE}/{rid}/complete", json={"resolution_summary": "Repaired", "final_repair": repair_body(world)},
                headers=h)
    # The first repair is dated now, so backdate it to make the second request a repeat within 90 days.
    db.execute(RepairHistory.__table__.update().values(repair_date=utc(35)))
    db.commit()
    rid2 = new_request(client, world)["service_request_id"]
    assign(client, world, rid2)
    rep = client.post(f"{BASE}/{rid2}/repairs", json=repair_body(world), headers=h).json()["request"]["repairs"][0]
    assert rep["repeat_failure"] is True


def test_technician_scope(client, world):
    rid = new_request(client, world)["service_request_id"]
    client.patch(f"{BASE}/{rid}", json={"assigned_technician_id": world.tech2.technician_id}, headers=world.headers())
    # The technician user is linked to world.tech, not tech2.
    r = client.post(f"{BASE}/{rid}/repairs", json=repair_body(world), headers=world.headers("technician"))
    assert r.status_code == 403


def test_list_filters_and_pagination(client, world):
    new_request(client, world)
    new_request(client, world, fault="Physical Damage")
    h = world.headers()
    page = client.get(BASE, params={"page_size": 1}, headers=h).json()
    assert page["total"] == 2 and len(page["items"]) == 1
    assert client.get(BASE, params={"warranty_covered": "false"}, headers=h).json()["total"] == 1
    assert client.get(BASE, params={"status": ["Open"], "q": "power"}, headers=h).json()["total"] == 2


def test_integrity_queries_hold_after_workflow(client, world, db):
    """parts_cost snapshot == junction total, and stock == ledger (see NORMALIZATION.md)."""
    from sqlalchemy import text

    rid = new_request(client, world)["service_request_id"]
    assign(client, world, rid)
    body = repair_body(world, parts=[{"part_id": world.part.part_id, "quantity": 2},
                                     {"part_id": world.part2.part_id, "quantity": 1}])
    client.post(f"{BASE}/{rid}/complete", json={"resolution_summary": "Repaired", "final_repair": body},
                headers=world.headers())
    client.post(f"/api/v1/inventory/parts/{world.part.part_id}/adjust", headers=world.headers(),
                json={"quantity_change": 4, "transaction_type": "Restock", "reason": "PO-7"})
    assert db.execute(text("SELECT COUNT(*) FROM v_repair_costs WHERE parts_cost <> parts_cost_from_lines")).scalar() == 0
    assert db.execute(text("""SELECT COUNT(*) FROM parts p WHERE p.stock_quantity <>
        (SELECT COALESCE(SUM(quantity_change), 0) FROM inventory_transactions t WHERE t.part_id = p.part_id)""")).scalar() == 0
