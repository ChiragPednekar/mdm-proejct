from datetime import date, timedelta

import pytest

from app.core.errors import BusinessRuleError
from app.models import FaultCategory, Warranty
from app.services.warranty import add_months, determine_coverage, effective_status, evaluate_coverage, extend_warranty

TODAY = date(2026, 6, 15)


def w(**kw):
    base = dict(warranty_id=1, product_id=1, warranty_type="Manufacturer", start_date=date(2026, 1, 1),
                end_date=date(2026, 12, 31), warranty_status="Valid", covers_parts=True, covers_labor=True,
                covers_wear_and_tear=False, covers_accidental_damage=False)
    base.update(kw)
    return Warranty(**base)


def fault(**kw):
    base = dict(name="Electrical Failure", is_customer_induced=False, is_wear_and_tear=False, counts_as_failure=True)
    base.update(kw)
    return FaultCategory(**base)


def test_covered_defect_within_dates():
    d = evaluate_coverage(w(), TODAY, fault())
    assert d.covered and d.covers_parts and d.covers_labor


def test_expired_and_not_started():
    assert not evaluate_coverage(w(end_date=date(2026, 6, 1)), TODAY, fault()).covered
    assert not evaluate_coverage(w(start_date=date(2026, 7, 1)), TODAY, fault()).covered


def test_voided_warranty_not_covered_even_within_dates():
    d = evaluate_coverage(w(warranty_status="Voided"), TODAY, fault())
    assert not d.covered and "voided" in d.reasons[0]


def test_exclusions_customer_induced_and_wear():
    assert not evaluate_coverage(w(), TODAY, fault(name="Drop", is_customer_induced=True)).covered
    assert evaluate_coverage(w(covers_accidental_damage=True), TODAY, fault(is_customer_induced=True)).covered
    assert not evaluate_coverage(w(), TODAY, fault(is_wear_and_tear=True)).covered
    assert evaluate_coverage(w(covers_wear_and_tear=True), TODAY, fault(is_wear_and_tear=True)).covered
    assert not evaluate_coverage(w(), TODAY, fault(counts_as_failure=False)).covered


def test_determine_coverage_prefers_applicable_warranty():
    manufacturer = w(warranty_id=1, end_date=date(2026, 3, 31))
    extended = w(warranty_id=2, warranty_type="Extended", start_date=date(2026, 4, 1), end_date=date(2027, 3, 31),
                 covers_labor=False)
    d = determine_coverage([manufacturer, extended], TODAY, fault())
    assert d.covered and d.warranty_id == 2 and d.covers_parts and not d.covers_labor
    none = determine_coverage([manufacturer], TODAY, fault())
    assert not none.covered and none.warranty_id is None
    assert not determine_coverage([], TODAY, fault()).covered


def test_effective_status_is_derived_from_dates():
    old = w(start_date=date(2020, 1, 1), end_date=date(2021, 1, 1))
    assert old.warranty_status == "Valid" and effective_status(old, TODAY) == "Expired"
    assert effective_status(w(), TODAY) == "Active"
    assert effective_status(w(start_date=date(2026, 9, 1)), TODAY) == "Pending"


def test_add_months_clamps_day():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


def test_extend_warranty_chains_after_current_end(db, world):
    ext = extend_warranty(db, world.warranty, months=12)
    assert ext.start_date == world.warranty.end_date + timedelta(days=1)
    assert ext.parent_warranty_id == world.warranty.warranty_id and ext.extended_warranty
    ext2 = extend_warranty(db, world.warranty, months=6)
    assert ext2.start_date == ext.end_date + timedelta(days=1)


def test_cannot_extend_lapsed_warranty(db, world):
    world.warranty.start_date = date.today() - timedelta(days=500)
    world.warranty.end_date = date.today() - timedelta(days=10)
    db.flush()
    with pytest.raises(BusinessRuleError):
        extend_warranty(db, world.warranty, months=12)


def test_warranty_api_extend_void_and_coverage(client, world):
    h = world.headers("service_manager")
    r = client.post(f"/api/v1/warranties/{world.warranty.warranty_id}/extend", json={"months": 24}, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["effective_status"] == "Pending"
    phys = world.faults["Physical Damage"].fault_category_id
    r = client.get("/api/v1/warranties/coverage-check", headers=h,
                   params={"product_id": world.product.product_id, "fault_category_id": phys})
    assert r.json()["covered"] is False and "customer-induced" in r.json()["reasons"][0]
    r = client.post(f"/api/v1/warranties/{world.warranty.warranty_id}/void", json={"reason": "Tampered seal"},
                    headers=h)
    assert r.json()["effective_status"] == "Voided"
    # Technicians may not void warranties.
    r = client.post(f"/api/v1/warranties/{world.warranty.warranty_id}/void", json={"reason": "whatever"},
                    headers=world.headers("technician"))
    assert r.status_code == 403


def test_expiring_soon_listing(client, world, db):
    world.warranty.end_date = date.today() + timedelta(days=20)
    db.commit()
    r = client.get("/api/v1/warranties/expiring", params={"days": 30}, headers=world.headers()).json()
    assert [i["warranty_id"] for i in r["items"]] == [world.warranty.warranty_id]
