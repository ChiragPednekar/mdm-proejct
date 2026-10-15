from test_service_requests import BASE, assign, new_request, repair_body


def metric(summary, key):
    return next(m for m in summary["metrics"] if m["key"] == key)


def test_dashboard_reflects_database_changes(client, world):
    h = world.headers()
    s = client.get("/api/v1/dashboard/summary", headers=h).json()
    assert metric(s, "total_products")["value"] == 1
    assert metric(s, "open_service_requests")["value"] == 0
    assert metric(s, "warranty_expenditure")["value"] == 0
    assert metric(s, "active_warranties")["value"] == 1
    assert metric(s, "low_stock_parts")["value"] == 1  # PN-SCR-1: 1 <= 2
    assert all(m["definition"] for m in s["metrics"])

    rid = new_request(client, world)["service_request_id"]
    s = client.get("/api/v1/dashboard/summary", headers=h).json()
    assert metric(s, "open_service_requests")["value"] == 1
    assign(client, world, rid)
    body = repair_body(world, parts=[{"part_id": world.part.part_id, "quantity": 1}], labor="500.00")
    client.post(f"{BASE}/{rid}/complete", json={"resolution_summary": "Repaired", "final_repair": body}, headers=h)
    s = client.get("/api/v1/dashboard/summary", headers=h).json()
    assert metric(s, "open_service_requests")["value"] == 0
    assert metric(s, "warranty_expenditure")["value"] == 3000.0  # 500 labor + 2500 part, fully covered
    assert metric(s, "repairs_completed_this_month")["value"] == 1
    rf = metric(s, "repeat_failure_rate")
    assert rf["denominator"] == 1 and rf["numerator"] == 0 and rf["value"] == 0
    t = client.get("/api/v1/dashboard/trends", headers=h).json()
    assert t["monthly_activity"][-1]["service_requests"] == 1
    assert {r["risk_level"] for r in t["risk_distribution"]} == {"Low", "Medium", "High"}


def test_reports_run_with_parameters(client, world):
    h = world.headers()
    catalog = client.get("/api/v1/analytics/reports", headers=h).json()
    assert len(catalog) == 12
    for rep in catalog:
        r = client.get(f"/api/v1/analytics/{rep['name']}", headers=h)
        assert r.status_code == 200, (rep["name"], r.text)
    r = client.get("/api/v1/analytics/parts_below_reorder", headers=h).json()
    assert r["row_count"] == 1 and r["rows"][0]["shortfall"] == 1
    r = client.get("/api/v1/analytics/active_warranties", params={"category": "Laptop"}, headers=h).json()
    assert r["row_count"] == 1
    assert client.get("/api/v1/analytics/active_warranties", params={"category": "Toaster"},
                      headers=h).status_code == 422
    assert client.get("/api/v1/analytics/top_replaced_components", params={"limit": "1; DROP TABLE parts"},
                      headers=h).status_code == 422
    assert client.get("/api/v1/analytics/no_such_report", headers=h).status_code == 404


def test_defect_analytics_filters(client, world):
    h = world.headers()
    rid = new_request(client, world)["service_request_id"]
    assign(client, world, rid)
    client.post(f"{BASE}/{rid}/complete", json={"resolution_summary": "Repaired", "final_repair": repair_body(world)},
                headers=h)
    d = client.get("/api/v1/analytics/defects", headers=h).json()
    assert d["summary"]["failure_requests"] == 1
    assert d["frequently_replaced_components"][0]["component_name"] == "Battery Pack"
    assert d["definitions"]["first_time_fix_rate"]
    empty = client.get("/api/v1/analytics/defects", params={"category": "Television"}, headers=h).json()
    assert empty["summary"]["failure_requests"] == 0
