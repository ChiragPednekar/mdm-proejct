"""Reproducible synthetic demonstration dataset.

Usage (from backend/):
    python -m scripts.seed --reset            # wipe all data and reseed
    python -m scripts.seed --reset --anchor-date 2026-10-15

All people, companies, models and contact details are FICTIONAL (emails use the
reserved example.com domain). Randomness uses a fixed seed (42), so the same
anchor date always yields the same dataset; with no --anchor-date the history
is generated relative to today so dashboards stay current.

Synthetic failure-generation assumptions (documented in README / ML docs)
-------------------------------------------------------------------------
Each registered unit is simulated day by day from purchase to the anchor date.
The daily probability of a qualifying failure is

    p = base_rate[category] * model_reliability[model]
        * (1 + 1.5 * exp(-age/45))                    # infant mortality
        * (1 + 0.6 * max(0, (age - 730) / 365))       # wear-out after 2 years
        * (1 + 0.25 * previous_failures)              # failure-prone units
        * (1 + 1.6 * exp(-days_since_last_repair/30)) # repeat-failure effect
        * (1.6 if air conditioner in Apr-Jun else 1)  # seasonal load

so there is a learnable — but entirely artificial — relationship between
history and future failures. Metrics of models trained on it are illustrative.
"""
from __future__ import annotations

import argparse
import math
import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import (
    Component,
    Customer,
    FaultCategory,
    InventoryTransaction,
    Part,
    Product,
    ProductModel,
    RepairHistory,
    RepairPart,
    ServiceRequest,
    Technician,
    User,
    Warranty,
)
from app.services import settings_service
from app.services.warranty import add_months, determine_coverage

SEED = 42
HISTORY_DAYS = 1280  # ~3.5 years
REPEAT_WINDOW = 90

ALL_TABLES = [
    "audit_logs", "failure_predictions", "model_training_runs", "inventory_transactions", "repair_parts",
    "repair_history", "service_requests", "warranties", "products", "customers", "parts", "components",
    "users", "technicians", "product_models", "fault_categories",
]

MANUFACTURERS = {
    "Novatek": "NVT", "Kelvra": "KLV", "Aurelion": "AUR", "Brightline": "BRL",
    "Zentro": "ZNT", "Meridian Home": "MRH", "Orbis": "ORB",
}
CATEGORY_CODES = {"Laptop": "LT", "Refrigerator": "RF", "Washing Machine": "WM", "Air Conditioner": "AC", "Television": "TV"}
CATEGORY_MAKERS = {
    "Laptop": ["Novatek", "Aurelion", "Zentro", "Orbis"],
    "Refrigerator": ["Kelvra", "Meridian Home", "Brightline"],
    "Washing Machine": ["Kelvra", "Meridian Home", "Brightline", "Orbis"],
    "Air Conditioner": ["Kelvra", "Brightline", "Zentro"],
    "Television": ["Novatek", "Aurelion", "Orbis", "Zentro"],
}
MODEL_NAMES = {
    "Laptop": ["AirBook 14", "ProEdge 15", "Studio X16", "Flex 13", "WorkMate 14", "Titan G17"],
    "Refrigerator": ["FrostFree 340", "CoolDoor 260", "SideBySide 600", "Compact 190", "TwinCool 420", "Inverter 310"],
    "Washing Machine": ["AquaWash 7", "FrontLoad 8.5", "TopLoad 6.5", "SteamCare 9", "EcoSpin 7.5", "TurboDry 10"],
    "Air Conditioner": ["Breeze 1.5T", "Inverter Split 1T", "Arctic 2T", "Window Cool 1.5T", "SmartAir 1.5T"],
    "Television": ["Vivid 43", "UltraView 55", "Cinema 65 OLED", "Smart 32", "Vista 50 QLED", "Crystal 43"],
}
PRICE_RANGE = {
    "Laptop": (42000, 165000), "Refrigerator": (18000, 95000), "Washing Machine": (16000, 62000),
    "Air Conditioner": (28000, 72000), "Television": (14000, 180000),
}
WARRANTY_MONTHS = {"Laptop": 12, "Refrigerator": 24, "Washing Machine": 24, "Air Conditioner": 12, "Television": 12}
BASE_DAILY_RATE = {"Laptop": 0.00078, "Refrigerator": 0.00056, "Washing Machine": 0.00082,
                   "Air Conditioner": 0.00075, "Television": 0.00045}

FAULTS = [
    # name, description, customer_induced, wear_and_tear, counts_as_failure
    ("Electrical Failure", "No power, tripping, burnt or failed electrical/electronic parts.", False, False, True),
    ("Mechanical Failure", "Moving-part, motor, hinge, bearing or mechanism failure.", False, False, True),
    ("Display Fault", "Lines, dead pixels, backlight or panel failure.", False, False, True),
    ("Cooling Failure", "Insufficient cooling, compressor or refrigerant issues, overheating.", False, False, True),
    ("Water Leakage", "Leaks from hoses, seals, drain or condensate lines.", False, False, True),
    ("Noise / Vibration", "Abnormal noise or vibration during operation.", False, False, True),
    ("Software / Firmware", "Boot failures, firmware bugs, control-board logic faults.", False, False, True),
    ("Battery Degradation", "Capacity loss consistent with normal ageing.", False, True, True),
    ("Seal / Gasket Wear", "Worn door gaskets or seals from normal use.", False, True, True),
    ("Physical Damage", "Drops, impacts, cracked housings or screens.", True, False, True),
    ("Liquid Damage", "Spills or liquid ingress caused by the user.", True, False, True),
    ("Installation Request", "New installation or re-installation visit (not a failure).", False, False, False),
    ("Preventive Maintenance", "Scheduled servicing / cleaning visit (not a failure).", False, False, False),
]

# category -> list of (fault name, component name, weight)
FAILURE_MODES = {
    "Laptop": [
        ("Electrical Failure", "Motherboard", 3), ("Display Fault", "Display Panel", 3), ("Mechanical Failure", "Hinge Assembly", 2),
        ("Mechanical Failure", "Keyboard Assembly", 2), ("Cooling Failure", "Cooling Fan", 2), ("Electrical Failure", "SSD Storage", 2),
        ("Battery Degradation", "Battery Pack", 3), ("Software / Firmware", None, 2), ("Physical Damage", "Display Panel", 1),
        ("Liquid Damage", "Keyboard Assembly", 1),
    ],
    "Refrigerator": [
        ("Cooling Failure", "Compressor", 4), ("Electrical Failure", "Thermostat", 2), ("Noise / Vibration", "Evaporator Fan Motor", 2),
        ("Cooling Failure", "Defrost Heater", 2), ("Seal / Gasket Wear", "Door Gasket", 2), ("Water Leakage", "Door Gasket", 1),
        ("Electrical Failure", "Control Board", 2), ("Physical Damage", "Door Gasket", 1),
    ],
    "Washing Machine": [
        ("Water Leakage", "Drain Pump", 3), ("Noise / Vibration", "Drum Bearing", 3), ("Mechanical Failure", "Door Lock", 2),
        ("Electrical Failure", "Control Board", 3), ("Water Leakage", "Inlet Valve", 2), ("Software / Firmware", None, 1),
        ("Seal / Gasket Wear", "Drum Bearing", 1), ("Physical Damage", "Door Lock", 1),
    ],
    "Air Conditioner": [
        ("Cooling Failure", "AC Compressor", 3), ("Electrical Failure", "Run Capacitor", 3), ("Noise / Vibration", "Outdoor Fan Motor", 2),
        ("Electrical Failure", "AC Control PCB", 2), ("Water Leakage", "Drain Pump", 1), ("Cooling Failure", "Refrigerant Charge", 2),
    ],
    "Television": [
        ("Display Fault", "LED Backlight Strip", 4), ("Electrical Failure", "Power Supply Board", 3), ("Display Fault", "TV Panel", 1),
        ("Software / Firmware", "TV Mainboard", 2), ("Physical Damage", "TV Panel", 1),
    ],
}
COMPONENTS = [
    # name, category, manufacturer, description
    ("Motherboard", "Electronics", "Orbis Components", "Laptop logic board"),
    ("Display Panel", "Display", "Lumis Displays", "Laptop LCD/OLED panel assembly"),
    ("Hinge Assembly", "Mechanical", "Fixwell Parts", "Laptop display hinge set"),
    ("Keyboard Assembly", "Input", "Fixwell Parts", "Keyboard with top case"),
    ("Cooling Fan", "Thermal", "AeroCool Industries", "CPU/GPU cooling fan"),
    ("SSD Storage", "Storage", "Datacore", "NVMe solid-state drive"),
    ("Battery Pack", "Power", "VoltCell", "Lithium-ion battery pack"),
    ("Compressor", "Refrigeration", "Coolcore Compressors", "Refrigerator hermetic compressor"),
    ("Thermostat", "Controls", "ThermoSense", "Refrigerator thermostat / sensor"),
    ("Evaporator Fan Motor", "Motors", "AeroCool Industries", "Freezer evaporator fan motor"),
    ("Defrost Heater", "Refrigeration", "ThermoSense", "Auto-defrost heating element"),
    ("Door Gasket", "Seals", "SealRite", "Magnetic door gasket"),
    ("Control Board", "Electronics", "Orbis Components", "Appliance main control PCB"),
    ("Drain Pump", "Pumps", "Hydroflow", "Drain / condensate pump"),
    ("Drum Bearing", "Mechanical", "Fixwell Parts", "Washer drum bearing and seal kit"),
    ("Door Lock", "Mechanical", "SealRite", "Washer door interlock"),
    ("Inlet Valve", "Plumbing", "Hydroflow", "Water inlet solenoid valve"),
    ("AC Compressor", "Refrigeration", "Coolcore Compressors", "Rotary inverter compressor"),
    ("Run Capacitor", "Electrical", "VoltCell", "Compressor/fan run capacitor"),
    ("Outdoor Fan Motor", "Motors", "AeroCool Industries", "Condenser fan motor"),
    ("AC Control PCB", "Electronics", "Orbis Components", "Indoor unit control board"),
    ("Refrigerant Charge", "Refrigeration", "Coolcore Compressors", "Refrigerant gas recharge"),
    ("LED Backlight Strip", "Display", "Lumis Displays", "TV LED backlight strips"),
    ("Power Supply Board", "Electrical", "VoltCell", "TV switched-mode power supply"),
    ("TV Panel", "Display", "Lumis Displays", "TV open-cell panel"),
    ("TV Mainboard", "Electronics", "Orbis Components", "TV main logic board"),
]
PART_COST = {  # component -> (min, max) unit cost
    "Motherboard": (9000, 22000), "Display Panel": (6000, 16000), "Hinge Assembly": (900, 2200),
    "Keyboard Assembly": (1800, 4500), "Cooling Fan": (700, 1600), "SSD Storage": (2500, 7000),
    "Battery Pack": (3000, 6500), "Compressor": (7000, 14000), "Thermostat": (600, 1500),
    "Evaporator Fan Motor": (900, 2100), "Defrost Heater": (700, 1600), "Door Gasket": (800, 2200),
    "Control Board": (2500, 6500), "Drain Pump": (900, 2400), "Drum Bearing": (1200, 3200),
    "Door Lock": (600, 1500), "Inlet Valve": (500, 1300), "AC Compressor": (9000, 18000),
    "Run Capacitor": (350, 900), "Outdoor Fan Motor": (2200, 4800), "AC Control PCB": (2400, 5600),
    "Refrigerant Charge": (1500, 3200), "LED Backlight Strip": (1500, 4200), "Power Supply Board": (2200, 5200),
    "TV Panel": (9000, 32000), "TV Mainboard": (3000, 7500),
}
SUPPLIERS = ["Apex Spares Pvt Ltd", "Unity Components", "PartsHub Distribution", "Prime OEM Supply", "Delta Service Parts"]
FIRST = ["Aarav", "Diya", "Rohan", "Ananya", "Kabir", "Meera", "Vihaan", "Isha", "Arjun", "Saanvi", "Nikhil", "Priya",
         "Rahul", "Neha", "Siddharth", "Kavya", "Aditya", "Tara", "Farhan", "Zoya", "Daniel", "Sofia", "Omar", "Leela",
         "Vikram", "Asha", "Karan", "Nisha", "Dev", "Ritu"]
LAST = ["Sharma", "Iyer", "Patel", "Kulkarni", "Reddy", "Menon", "Shah", "Desai", "Nair", "Gupta", "Joshi", "Rao",
        "Fernandes", "Khan", "Bose", "Pillai", "Mehta", "Chopra", "Sethi", "D'Souza"]
CITIES = ["Mumbai", "Pune", "Bengaluru", "Delhi", "Hyderabad", "Chennai", "Ahmedabad", "Kolkata"]
STREETS = ["MG Road", "Link Road", "Station Road", "Park Street", "Lake View Lane", "Hill Road", "Church Street", "Ring Road"]
TECHS = [
    ("Ravi Kumar", "Laptops & Computing"), ("Sunita Pawar", "Refrigeration"), ("Imran Sheikh", "Air Conditioning"),
    ("Pooja Hegde", "Washing Machines"), ("Manoj Tiwari", "Televisions & Displays"), ("Anita Das", "Laptops & Computing"),
    ("Joseph Mathew", "Refrigeration"), ("Kiran Rao", "Air Conditioning"), ("Leena George", "Washing Machines"),
    ("Sameer Kulkarni", "General Electronics"),
]
SPEC_FOR = {"Laptop": "Laptops & Computing", "Refrigerator": "Refrigeration", "Washing Machine": "Washing Machines",
            "Air Conditioner": "Air Conditioning", "Television": "Televisions & Displays"}
COMPLAINT_TEXT = {
    "Electrical Failure": ["Unit does not power on.", "Trips the breaker when switched on.", "Burning smell, then shut down."],
    "Mechanical Failure": ["Part feels loose and makes grinding sounds.", "Mechanism is stuck and will not move.", "Broken hinge/latch after normal use."],
    "Display Fault": ["Vertical lines across the screen.", "Screen goes dark after a few minutes.", "Flickering display and dim backlight."],
    "Cooling Failure": ["Not cooling adequately.", "Runs continuously but stays warm.", "Overheats and shuts down under load."],
    "Water Leakage": ["Water pooling under the unit.", "Leaks during the drain cycle.", "Water dripping from indoor unit."],
    "Noise / Vibration": ["Loud rattling noise during operation.", "Strong vibration and knocking.", "Humming noise from the fan area."],
    "Software / Firmware": ["Stuck on boot screen.", "Controls unresponsive; shows error code.", "Random restarts after update."],
    "Battery Degradation": ["Battery lasts under one hour.", "Battery not charging beyond 60%."],
    "Seal / Gasket Wear": ["Door does not seal properly.", "Seal visibly worn; frost build-up."],
    "Physical Damage": ["Unit was dropped; housing cracked.", "Screen cracked after impact."],
    "Liquid Damage": ["Liquid spilled on the unit; now not working.", "Keyboard unresponsive after spill."],
    "Installation Request": ["Installation of newly purchased unit.", "Re-installation after house move."],
    "Preventive Maintenance": ["Annual servicing requested.", "Routine cleaning and inspection."],
}


def _dt(d: date, rng: random.Random) -> datetime:
    """Business-hours timestamp (IST 08:30-18:30 expressed in UTC)."""
    minutes = rng.randint(3 * 60, 13 * 60)
    return datetime.combine(d, time(0, 0), tzinfo=timezone.utc) + timedelta(minutes=minutes)


def _money(x: float) -> Decimal:
    return Decimal(str(round(x, 2))).quantize(Decimal("0.01"))


def reset_database(db) -> None:
    db.execute(text("TRUNCATE " + ", ".join(ALL_TABLES) + " RESTART IDENTITY CASCADE"))
    db.commit()


def seed(anchor: date, reset: bool) -> dict:
    rng = random.Random(SEED)
    s = get_settings()
    db = SessionLocal()
    try:
        if reset:
            reset_database(db)
        elif db.execute(text("SELECT EXISTS (SELECT 1 FROM products)")).scalar():
            raise SystemExit("Database already contains data. Re-run with --reset to wipe and reseed.")

        start = anchor - timedelta(days=HISTORY_DAYS)

        # ---- reference data -------------------------------------------------
        faults = {}
        for name, desc, induced, wear, failure in FAULTS:
            fc = FaultCategory(name=name, description=desc, is_customer_induced=induced,
                               is_wear_and_tear=wear, counts_as_failure=failure)
            db.add(fc)
            faults[name] = fc
        components = {}
        for name, cat, maker, desc in COMPONENTS:
            c = Component(component_name=name, component_category=cat, manufacturer=maker, component_description=desc)
            db.add(c)
            components[name] = c
        db.flush()

        parts_by_component: dict[str, list[Part]] = defaultdict(list)
        part_seq = 1
        for cname, comp in components.items():
            n_parts = 1 if cname in ("Refrigerant Charge", "Run Capacitor", "Inlet Valve") else rng.choice([1, 2, 2, 3])
            for i in range(n_parts):
                lo, hi = PART_COST[cname]
                cost = rng.uniform(lo, hi) * (1 + 0.15 * i)
                variant = ["Standard", "OEM Premium", "Rev B"][i]
                p = Part(
                    component_id=comp.component_id,
                    part_number=f"PN-{comp.component_id:02d}{i + 1}-{part_seq:04d}",
                    part_name=f"{cname} ({variant})",
                    unit_cost=_money(round(cost, -1)),
                    selling_price=_money(round(cost * 1.25, -1)),
                    stock_quantity=0,
                    reorder_level=rng.choice([3, 4, 5, 6, 8]),
                    supplier_name=rng.choice(SUPPLIERS),
                )
                part_seq += 1
                db.add(p)
                parts_by_component[cname].append(p)

        models: list[ProductModel] = []
        reliability: dict[int, float] = {}
        for category, names in MODEL_NAMES.items():
            for name in names:
                maker = rng.choice(CATEGORY_MAKERS[category])
                pm = ProductModel(
                    manufacturer=maker, model_name=name, product_category=category,
                    model_description=f"{maker} {name} {category.lower()}",
                    standard_warranty_months=WARRANTY_MONTHS[category],
                    release_year=rng.randint(anchor.year - 6, anchor.year - 1),
                )
                db.add(pm)
                models.append(pm)
        db.flush()
        for pm in models:
            reliability[pm.product_model_id] = math.exp(rng.gauss(0, 0.35))
        # A few deliberately problematic models so model-level analytics have signal.
        for pm in rng.sample(models, 4):
            reliability[pm.product_model_id] *= 2.2

        techs = []
        for i, (name, spec) in enumerate(TECHS):
            status = "On Leave" if i == 8 else "Inactive" if i == 9 else "Active"
            t = Technician(full_name=name, email=f"{name.lower().replace(' ', '.')}@service.example.com",
                           specialization=spec, employment_status=status)
            db.add(t)
            techs.append(t)
        db.flush()

        demo_pw = s.demo_user_password if not s.is_production else None
        users_spec = [
            ("admin", "admin@service.example.com", "Asha Admin", "admin", None),
            ("manager", "manager@service.example.com", "Mohan Manager", "service_manager", None),
            ("tech.ravi", "ravi.tech@service.example.com", "Ravi Kumar", "technician", techs[0].technician_id),
            ("tech.sunita", "sunita.tech@service.example.com", "Sunita Pawar", "technician", techs[1].technician_id),
        ]
        generated_passwords = {}
        for username, email, full_name, role, tech_id in users_spec:
            pw = demo_pw or __import__("secrets").token_urlsafe(12)
            if demo_pw is None:
                generated_passwords[username] = pw
            db.add(User(username=username, email=email, full_name=full_name, password_hash=hash_password(pw),
                        role=role, technician_id=tech_id))

        customers = []
        used_emails = set()
        for i in range(100):
            fn, ln = rng.choice(FIRST), rng.choice(LAST)
            email = f"{fn.lower()}.{ln.lower().replace(chr(39), '')}{i + 1}@example.com"
            used_emails.add(email)
            created = _dt(start + timedelta(days=rng.randint(0, 200)), rng)
            c = Customer(
                full_name=f"{fn} {ln}",
                email=email if rng.random() > 0.08 else None,
                phone=f"+91 9{rng.randint(100000000, 999999999)}",
                address=f"{rng.randint(1, 250)}, {rng.choice(STREETS)}",
                city=rng.choice(CITIES),
                created_at=created,
            )
            db.add(c)
            customers.append(c)
        db.flush()

        # ---- products & warranties -------------------------------------------
        products: list[Product] = []
        serial_counter = defaultdict(int)
        for i in range(180):
            pm = rng.choice(models)
            cust = customers[i] if i < 100 else rng.choice(customers)
            purchase = start + timedelta(days=int(rng.triangular(0, HISTORY_DAYS - 20, 300)))
            code = MANUFACTURERS[pm.manufacturer]
            serial_counter[code] += 1
            lo, hi = PRICE_RANGE[pm.product_category]
            install = None
            if pm.product_category in ("Air Conditioner", "Washing Machine", "Refrigerator"):
                install = purchase + timedelta(days=rng.randint(0, 6))
            p = Product(
                serial_number=f"{code}-{CATEGORY_CODES[pm.product_category]}-{purchase:%y}-{serial_counter[code]:05d}",
                product_model_id=pm.product_model_id, customer_id=cust.customer_id, purchase_date=purchase,
                purchase_price=_money(round(rng.uniform(lo, hi), -2)), installation_date=install,
                product_status="Active", created_at=_dt(purchase, rng),
            )
            p.product_model = pm
            db.add(p)
            products.append(p)
        db.flush()

        warranties_by_product: dict[int, list[Warranty]] = defaultdict(list)
        model_by_id = {m.product_model_id: m for m in models}
        for p in products:
            pm = model_by_id[p.product_model_id]
            months = pm.standard_warranty_months
            base = Warranty(
                product_id=p.product_id, warranty_type="Manufacturer", start_date=p.purchase_date,
                end_date=add_months(p.purchase_date, months) - timedelta(days=1),
                coverage_details=f"Standard {months}-month manufacturer warranty (parts and labor). "
                                 "Excludes physical/liquid damage and normal wear.",
                covers_parts=True, covers_labor=True, extended_warranty=False,
                created_at=_dt(p.purchase_date, rng),
            )
            db.add(base)
            warranties_by_product[p.product_id].append(base)
        db.flush()
        for p in products:
            base = warranties_by_product[p.product_id][0]
            roll = rng.random()
            if roll < 0.28:
                months = rng.choice([12, 24, 36])
                ext_start = base.end_date + timedelta(days=1)
                ext = Warranty(
                    product_id=p.product_id, parent_warranty_id=base.warranty_id, warranty_type="Extended",
                    start_date=ext_start, end_date=add_months(ext_start, months) - timedelta(days=1),
                    coverage_details=f"{months}-month extended warranty: parts covered, labor covered, "
                                     "wear-and-tear components included.",
                    covers_parts=True, covers_labor=rng.random() < 0.7, covers_wear_and_tear=True,
                    extended_warranty=True, created_at=_dt(p.purchase_date + timedelta(days=rng.randint(0, 25)), rng),
                )
                db.add(ext)
                warranties_by_product[p.product_id].append(ext)
            elif roll < 0.36:
                adp = Warranty(
                    product_id=p.product_id, parent_warranty_id=base.warranty_id,
                    warranty_type="Accidental Damage Protection", start_date=p.purchase_date,
                    end_date=add_months(p.purchase_date, 24) - timedelta(days=1),
                    coverage_details="24-month accidental damage protection covering drops and liquid spills.",
                    covers_parts=True, covers_labor=True, covers_accidental_damage=True, extended_warranty=True,
                    created_at=_dt(p.purchase_date, rng),
                )
                db.add(adp)
                warranties_by_product[p.product_id].append(adp)
        # Two voided warranties (tampering by unauthorised repair shops).
        for p in rng.sample(products, 2):
            w = warranties_by_product[p.product_id][0]
            w.warranty_status = "Voided"
            w.coverage_details += " VOIDED: evidence of unauthorised third-party repair."
        db.flush()

        # ---- failure simulation ------------------------------------------------
        active_techs = [t for t in techs if t.employment_status == "Active"]
        events = []  # dicts describing service requests and their repairs
        retire_ids = {p.product_id for p in sorted(products, key=lambda x: x.purchase_date)[:3]}
        for p in products:
            pm = model_by_id[p.product_model_id]
            cat = pm.product_category
            rate = BASE_DAILY_RATE[cat] * reliability[pm.product_model_id]
            n_fail = 0
            last_repair: date | None = None
            busy_until = p.purchase_date
            end_day = anchor - timedelta(days=75) if p.product_id in retire_ids else anchor
            # Non-failure visits
            if p.installation_date and rng.random() < 0.25:
                events.append({"product": p, "fault": "Installation Request", "component": None,
                               "reported": p.installation_date, "non_failure": True})
            d = p.purchase_date + timedelta(days=1)
            replaced = False
            while d < end_day and not replaced:
                if d < busy_until:
                    d += timedelta(days=1)
                    continue
                age = (d - p.purchase_date).days
                hz = rate * (1 + 1.5 * math.exp(-age / 45)) * (1 + 0.6 * max(0.0, (age - 730) / 365))
                hz *= 1 + 0.25 * n_fail
                if last_repair is not None:
                    hz *= 1 + 1.6 * math.exp(-(d - last_repair).days / 30)
                if cat == "Air Conditioner" and d.month in (4, 5, 6):
                    hz *= 1.6
                if rng.random() < hz:
                    modes = FAILURE_MODES[cat]
                    fault, comp, _ = rng.choices(modes, weights=[m[2] for m in modes])[0]
                    ev = {"product": p, "fault": fault, "component": comp, "reported": d, "non_failure": False}
                    events.append(ev)
                    n_fail += 1
                    # Repair turnaround and attempts
                    first_fix = d + timedelta(days=rng.randint(1, 6))
                    attempts = []
                    r = rng.random()
                    if r < 0.80:
                        attempts.append(("Fixed", first_fix))
                    elif r < 0.88:
                        attempts.append(("Partially Fixed", first_fix))
                        attempts.append(("Fixed", first_fix + timedelta(days=rng.randint(2, 7))))
                    elif r < 0.95:
                        attempts.append(("Not Fixed", first_fix))
                        attempts.append(("Fixed", first_fix + timedelta(days=rng.randint(2, 8))))
                    elif r < 0.975 and age > 200:
                        attempts.append(("Unit Replaced", first_fix))
                        replaced = True
                    else:
                        attempts.append(("Fixed", first_fix))
                    ev["attempts"] = attempts
                    last_repair = attempts[-1][1]
                    busy_until = last_repair + timedelta(days=1)
                    d = busy_until
                    continue
                if rng.random() < 0.00035:
                    events.append({"product": p, "fault": "Preventive Maintenance", "component": None,
                                   "reported": d, "non_failure": True})
                d += timedelta(days=1)
            if replaced:
                p.product_status = "Replaced"
            elif p.product_id in retire_ids:
                p.product_status = "Retired"

        # Work-in-progress complaints from the last ~2 weeks, so the operational
        # pipeline (Open / Assigned / In Progress) has realistic volume.
        recently_busy = {e["product"].product_id for e in events if (anchor - e["reported"]).days <= 30}
        candidates = [p for p in products if p.product_status == "Active" and p.product_id not in recently_busy
                      and (anchor - p.purchase_date).days > 20]
        for p in rng.sample(candidates, 14):
            cat = model_by_id[p.product_model_id].product_category
            modes = FAILURE_MODES[cat]
            fault, comp, _ = rng.choices(modes, weights=[m[2] for m in modes])[0]
            events.append({"product": p, "fault": fault, "component": comp, "pipeline": True,
                           "reported": anchor - timedelta(days=rng.randint(0, 12)), "non_failure": False})

        # ---- materialise requests, repairs and inventory ------------------------
        events.sort(key=lambda e: e["reported"])
        stock = {}
        for comp_parts in parts_by_component.values():
            for part in comp_parts:
                stock[part.part_id] = rng.randint(part.reorder_level + 6, part.reorder_level + 18)
                db.add(InventoryTransaction(
                    part_id=part.part_id, transaction_type="Initial Stock", quantity_change=stock[part.part_id],
                    stock_after=stock[part.part_id], reason="Opening balance",
                    created_at=_dt(start - timedelta(days=1), rng),
                ))
        repairs_by_product: dict[int, list[datetime]] = defaultdict(list)
        counts = defaultdict(int)
        restock_cutoff = anchor - timedelta(days=45)

        def pick_tech(category: str) -> Technician:
            spec = SPEC_FOR[category]
            pool = [t for t in active_techs if t.specialization == spec] or active_techs
            return rng.choice(pool + [techs[9]] if rng.random() < 0.05 else pool)

        for ev in events:
            p: Product = ev["product"]
            pm = model_by_id[p.product_model_id]
            fault = faults[ev["fault"]]
            reported_dt = _dt(ev["reported"], rng)
            if reported_dt.date() > anchor or reported_dt > datetime.now(timezone.utc):
                continue
            decision = determine_coverage(warranties_by_product[p.product_id], ev["reported"], fault)
            severity = rng.choices(["Minor", "Moderate", "Major", "Critical"], weights=[3, 5, 3, 1])[0]
            priority = {"Minor": "Low", "Moderate": "Medium", "Major": "High", "Critical": "Critical"}[severity]
            if ev["non_failure"]:
                severity, priority = "Minor", "Low"
            tech = pick_tech(pm.product_category)
            sr = ServiceRequest(
                product_id=p.product_id, warranty_id=decision.warranty_id,
                complaint_description=rng.choice(COMPLAINT_TEXT[ev["fault"]]),
                fault_category_id=fault.fault_category_id, reported_at=reported_dt, priority=priority,
                failure_severity=severity, request_status="Open", assigned_technician_id=None,
                warranty_covered=decision.covered, coverage_notes=" ".join(decision.reasons),
                created_at=reported_dt,
            )
            db.add(sr)
            counts["service_requests"] += 1
            days_ago = (anchor - ev["reported"]).days
            attempts = ev.get("attempts") or [("Fixed", ev["reported"] + timedelta(days=rng.randint(0, 3)))]
            if ev.get("pipeline"):
                if days_ago <= 2:
                    sr.request_status = "Open"
                else:
                    sr.assigned_technician_id = tech.technician_id
                    sr.request_status = "Assigned" if days_ago <= 5 else "In Progress"
                    if sr.request_status == "In Progress":
                        p.product_status = "Under Repair"
                continue
            # Recent complaints stay in the pipeline.
            if days_ago <= 3:
                sr.request_status = rng.choice(["Open", "Open", "Assigned"])
                if sr.request_status == "Assigned":
                    sr.assigned_technician_id = tech.technician_id
                continue
            sr.assigned_technician_id = tech.technician_id
            done_attempts = [a for a in attempts if a[1] <= anchor - timedelta(days=1)]
            if not done_attempts:
                sr.request_status = "In Progress"
                p.product_status = "Under Repair" if p.product_status == "Active" else p.product_status
                continue
            db.flush()
            for n, (outcome, rdate) in enumerate(done_attempts, start=1):
                rdt = max(_dt(rdate, rng), reported_dt + timedelta(hours=2))
                prior = [x for x in repairs_by_product[p.product_id]
                         if reported_dt - timedelta(days=REPEAT_WINDOW) <= x < reported_dt]
                comp = components.get(ev["component"]) if ev["component"] else None
                labor = round(rng.uniform(400, 2600), -1) if not ev["non_failure"] else round(rng.uniform(300, 900), -1)
                rep = RepairHistory(
                    service_request_id=sr.service_request_id, technician_id=sr.assigned_technician_id,
                    component_id=comp.component_id if comp else None, attempt_number=n,
                    diagnosis=(f"{ev['component']} fault confirmed" if comp else f"{ev['fault']} diagnosed")
                    + (" (inspection)" if ev["non_failure"] else ""),
                    root_cause=None if ev["non_failure"] else rng.choice([
                        "Component defect", "Manufacturing defect", "Electrical surge", "Normal wear",
                        "Firmware bug", "Improper usage", "Loose connection",
                    ]),
                    repair_action={
                        "Fixed": "Replaced faulty component and tested", "Partially Fixed": "Temporary fix applied; part on order",
                        "Not Fixed": "Diagnosis inconclusive; escalated", "Unit Replaced": "Unit beyond economical repair; replaced",
                        "Referred": "Referred to manufacturer service centre",
                    }[outcome] if not ev["non_failure"] else "Service visit completed",
                    labor_cost=_money(labor), parts_cost=Decimal("0.00"), repair_date=rdt, outcome=outcome,
                    repeat_failure=bool(prior) and not ev["non_failure"], created_at=rdt,
                )
                db.add(rep)
                db.flush()
                counts["repairs"] += 1
                total_parts = Decimal("0.00")
                if comp and outcome in ("Fixed", "Partially Fixed", "Unit Replaced") and ev["component"] in parts_by_component:
                    choices = parts_by_component[ev["component"]]
                    n_lines = 2 if len(choices) > 1 and rng.random() < 0.2 else 1
                    for part in rng.sample(choices, n_lines):
                        qty = 1 if rng.random() < 0.85 else 2
                        if stock[part.part_id] < qty:
                            if rdt.date() >= restock_cutoff:
                                continue  # out of stock recently: technician sourced nothing
                            add = part.reorder_level * 3
                            stock[part.part_id] += add
                            db.add(InventoryTransaction(
                                part_id=part.part_id, transaction_type="Restock", quantity_change=add,
                                stock_after=stock[part.part_id], reason="Emergency restock",
                                created_at=rdt - timedelta(hours=1),
                            ))
                        stock[part.part_id] -= qty
                        db.add(RepairPart(repair_id=rep.repair_id, part_id=part.part_id, quantity_used=qty,
                                          unit_cost_at_repair=part.unit_cost))
                        db.add(InventoryTransaction(
                            part_id=part.part_id, transaction_type="Repair Consumption", quantity_change=-qty,
                            stock_after=stock[part.part_id], repair_id=rep.repair_id,
                            reason=f"Used in repair #{rep.repair_id}", created_at=rdt,
                        ))
                        total_parts += part.unit_cost * qty
                        counts["repair_part_lines"] += 1
                        if stock[part.part_id] <= part.reorder_level and rdt.date() < restock_cutoff:
                            add = part.reorder_level * 2 + rng.randint(2, 8)
                            stock[part.part_id] += add
                            db.add(InventoryTransaction(
                                part_id=part.part_id, transaction_type="Restock", quantity_change=add,
                                stock_after=stock[part.part_id], reason="Scheduled reorder",
                                created_at=rdt + timedelta(days=2),
                            ))
                rep.parts_cost = total_parts.quantize(Decimal("0.01"))
                repairs_by_product[p.product_id].append(rdt)
            last_outcome, last_date = done_attempts[-1]
            if len(done_attempts) < len(attempts) or last_outcome in ("Not Fixed", "Partially Fixed"):
                sr.request_status = "In Progress"
                if p.product_status == "Active":
                    p.product_status = "Under Repair"
            else:
                resolved = max(_dt(last_date, rng), reported_dt + timedelta(hours=3),
                               max(repairs_by_product[p.product_id]))
                sr.resolution_date = resolved
                sr.resolution_summary = f"Resolved: {last_outcome.lower()}."
                sr.request_status = "Closed" if (anchor - last_date).days > 10 else "Resolved"
        for part_list in parts_by_component.values():
            for part in part_list:
                part.stock_quantity = stock[part.part_id]
        # Make sure a handful of parts sit below reorder level (shrinkage found in audit).
        low = [pa for pl in parts_by_component.values() for pa in pl if pa.stock_quantity > pa.reorder_level]
        for part in rng.sample(low, 4):
            change = -(part.stock_quantity - rng.randint(0, part.reorder_level))
            part.stock_quantity += change
            db.add(InventoryTransaction(
                part_id=part.part_id, transaction_type="Adjustment", quantity_change=change,
                stock_after=part.stock_quantity, reason="Cycle count correction (damaged stock written off)",
                created_at=_dt(anchor - timedelta(days=rng.randint(5, 20)), rng),
            ))

        settings_service.set_setting(db, "dataset_provenance", "synthetic_demo")
        db.commit()

        summary = {
            "customers": len(customers), "products": len(products), "product_models": len(models),
            "manufacturers": len({m.manufacturer for m in models}),
            "warranties": sum(len(v) for v in warranties_by_product.values()),
            "components": len(components), "parts": sum(len(v) for v in parts_by_component.values()),
            "technicians": len(techs), **counts, "anchor_date": str(anchor),
        }
        if generated_passwords:
            summary["generated_passwords"] = generated_passwords
        return summary
    finally:
        db.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", action="store_true", help="TRUNCATE all application tables before seeding")
    ap.add_argument("--anchor-date", type=date.fromisoformat, default=None,
                    help="Last day of simulated history (default: today)")
    args = ap.parse_args()
    summary = seed(args.anchor_date or datetime.now(timezone.utc).date(), args.reset)
    for k, v in summary.items():
        print(f"{k:>20}: {v}")


if __name__ == "__main__":
    main()
