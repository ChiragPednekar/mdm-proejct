"""analytical views and default settings

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VIEWS: list[tuple[str, str]] = [
    (
        "v_warranty_effective_status",
        """
        -- Effective status is DERIVED from dates + administrative status,
        -- never trusted from the stored column alone.
        SELECT w.warranty_id,
               w.product_id,
               w.parent_warranty_id,
               w.warranty_type,
               w.extended_warranty,
               w.start_date,
               w.end_date,
               w.covers_parts,
               w.covers_labor,
               w.covers_wear_and_tear,
               w.covers_accidental_damage,
               w.warranty_status AS administrative_status,
               CASE
                   WHEN w.warranty_status <> 'Valid' THEN w.warranty_status
                   WHEN CURRENT_DATE < w.start_date THEN 'Pending'
                   WHEN CURRENT_DATE > w.end_date THEN 'Expired'
                   ELSE 'Active'
               END AS effective_status,
               (w.end_date - CURRENT_DATE) AS days_remaining
        FROM warranties w
        """,
    ),
    (
        "v_repair_costs",
        """
        -- parts_cost_from_lines recomputes the cost from the junction table so the
        -- stored repair_history.parts_cost snapshot can be audited against it.
        SELECT r.repair_id,
               r.service_request_id,
               sr.product_id,
               r.technician_id,
               r.component_id,
               r.repair_date,
               r.outcome,
               r.repeat_failure,
               r.labor_cost,
               r.parts_cost,
               COALESCE(lines.parts_total, 0)::numeric(12,2) AS parts_cost_from_lines,
               (r.labor_cost + r.parts_cost)::numeric(12,2) AS total_cost,
               COALESCE(sr.warranty_covered, false) AS warranty_covered,
               CASE WHEN COALESCE(sr.warranty_covered, false) THEN
                   (CASE WHEN w.covers_labor THEN r.labor_cost ELSE 0 END
                  + CASE WHEN w.covers_parts THEN r.parts_cost ELSE 0 END)
               ELSE 0 END::numeric(12,2) AS warranty_cost,
               ((r.labor_cost + r.parts_cost) -
                CASE WHEN COALESCE(sr.warranty_covered, false) THEN
                   (CASE WHEN w.covers_labor THEN r.labor_cost ELSE 0 END
                  + CASE WHEN w.covers_parts THEN r.parts_cost ELSE 0 END)
                ELSE 0 END)::numeric(12,2) AS customer_cost
        FROM repair_history r
        JOIN service_requests sr ON sr.service_request_id = r.service_request_id
        LEFT JOIN warranties w ON w.warranty_id = sr.warranty_id
        LEFT JOIN (
            SELECT repair_id, SUM(quantity_used * unit_cost_at_repair) AS parts_total
            FROM repair_parts GROUP BY repair_id
        ) lines ON lines.repair_id = r.repair_id
        """,
    ),
    (
        "v_service_request_overview",
        """
        SELECT sr.service_request_id,
               sr.product_id,
               p.serial_number,
               pm.product_model_id,
               pm.manufacturer,
               pm.model_name,
               pm.product_category,
               c.customer_id,
               c.full_name AS customer_name,
               fc.name AS fault_category,
               fc.counts_as_failure,
               sr.complaint_description,
               sr.priority,
               sr.failure_severity,
               sr.request_status,
               sr.reported_at,
               sr.resolution_date,
               sr.warranty_id,
               sr.warranty_covered,
               t.technician_id,
               t.full_name AS technician_name,
               EXTRACT(EPOCH FROM (sr.resolution_date - sr.reported_at)) / 86400.0 AS days_to_resolve
        FROM service_requests sr
        JOIN products p ON p.product_id = sr.product_id
        JOIN product_models pm ON pm.product_model_id = p.product_model_id
        JOIN customers c ON c.customer_id = p.customer_id
        JOIN fault_categories fc ON fc.fault_category_id = sr.fault_category_id
        LEFT JOIN technicians t ON t.technician_id = sr.assigned_technician_id
        """,
    ),
    (
        "v_repeat_failures",
        """
        -- A service request is a repeat failure when the same product had a
        -- previous repair dated within the 90 days before the new report.
        SELECT sr.service_request_id,
               sr.product_id,
               sr.reported_at,
               prev.repair_id AS previous_repair_id,
               prev.repair_date AS previous_repair_date,
               prev.component_id AS previous_component_id,
               EXTRACT(EPOCH FROM (sr.reported_at - prev.repair_date)) / 86400.0 AS days_since_previous_repair
        FROM service_requests sr
        JOIN LATERAL (
            SELECT r.repair_id, r.repair_date, r.component_id
            FROM repair_history r
            JOIN service_requests sr2 ON sr2.service_request_id = r.service_request_id
            WHERE sr2.product_id = sr.product_id
              AND sr2.service_request_id <> sr.service_request_id
              AND r.repair_date < sr.reported_at
              AND r.repair_date >= sr.reported_at - INTERVAL '90 days'
            ORDER BY r.repair_date DESC
            LIMIT 1
        ) prev ON true
        """,
    ),
    (
        "v_component_failure_stats",
        """
        SELECT co.component_id,
               co.component_name,
               co.component_category,
               COUNT(r.repair_id) AS repair_count,
               COUNT(DISTINCT sr.product_id) AS affected_products,
               COUNT(*) FILTER (WHERE r.repeat_failure) AS repeat_repairs,
               COALESCE(SUM(r.labor_cost + r.parts_cost), 0)::numeric(12,2) AS total_repair_cost
        FROM components co
        LEFT JOIN repair_history r ON r.component_id = co.component_id
        LEFT JOIN service_requests sr ON sr.service_request_id = r.service_request_id
        GROUP BY co.component_id, co.component_name, co.component_category
        """,
    ),
    (
        "v_model_repair_stats",
        """
        WITH units AS (
            SELECT product_model_id, COUNT(*) AS registered_units
            FROM products GROUP BY product_model_id
        ), reqs AS (
            SELECT p.product_model_id, COUNT(*) AS service_requests
            FROM service_requests sr JOIN products p ON p.product_id = sr.product_id
            GROUP BY p.product_model_id
        ), reps AS (
            SELECT p.product_model_id,
                   COUNT(*) AS repairs,
                   SUM(rc.total_cost) AS total_repair_cost,
                   SUM(rc.warranty_cost) AS warranty_cost
            FROM v_repair_costs rc JOIN products p ON p.product_id = rc.product_id
            GROUP BY p.product_model_id
        )
        SELECT pm.product_model_id,
               pm.manufacturer,
               pm.model_name,
               pm.product_category,
               COALESCE(u.registered_units, 0) AS registered_units,
               COALESCE(q.service_requests, 0) AS service_requests,
               COALESCE(r.repairs, 0) AS repairs,
               COALESCE(r.total_repair_cost, 0)::numeric(12,2) AS total_repair_cost,
               COALESCE(r.warranty_cost, 0)::numeric(12,2) AS warranty_cost,
               CASE WHEN COALESCE(u.registered_units, 0) = 0 THEN NULL
                    ELSE ROUND(COALESCE(r.repairs, 0)::numeric * 100 / u.registered_units, 1) END
                   AS repairs_per_100_units,
               CASE WHEN COALESCE(r.repairs, 0) = 0 THEN NULL
                    ELSE ROUND(r.total_repair_cost / r.repairs, 2) END AS avg_cost_per_repair
        FROM product_models pm
        LEFT JOIN units u ON u.product_model_id = pm.product_model_id
        LEFT JOIN reqs q ON q.product_model_id = pm.product_model_id
        LEFT JOIN reps r ON r.product_model_id = pm.product_model_id
        """,
    ),
    (
        "v_monthly_warranty_expenditure",
        """
        SELECT date_trunc('month', rc.repair_date)::date AS month,
               COUNT(*) AS repairs,
               COUNT(*) FILTER (WHERE rc.warranty_covered) AS warranty_repairs,
               SUM(rc.total_cost)::numeric(12,2) AS total_repair_cost,
               SUM(rc.warranty_cost)::numeric(12,2) AS warranty_cost,
               SUM(rc.customer_cost)::numeric(12,2) AS customer_cost
        FROM v_repair_costs rc
        GROUP BY 1
        """,
    ),
    (
        "v_low_stock_parts",
        """
        SELECT pa.part_id, pa.part_number, pa.part_name, pa.stock_quantity, pa.reorder_level,
               (pa.reorder_level - pa.stock_quantity) AS shortfall,
               pa.supplier_name, co.component_name
        FROM parts pa
        LEFT JOIN components co ON co.component_id = pa.component_id
        WHERE pa.stock_quantity <= pa.reorder_level
        """,
    ),
    (
        "v_part_consumption",
        """
        SELECT pa.part_id, pa.part_number, pa.part_name, co.component_name,
               COALESCE(SUM(rp.quantity_used), 0) AS total_quantity_used,
               COUNT(rp.repair_id) AS repairs_using_part,
               COALESCE(SUM(rp.quantity_used * rp.unit_cost_at_repair), 0)::numeric(12,2) AS total_cost_at_repair
        FROM parts pa
        LEFT JOIN components co ON co.component_id = pa.component_id
        LEFT JOIN repair_parts rp ON rp.part_id = pa.part_id
        GROUP BY pa.part_id, pa.part_number, pa.part_name, co.component_name
        """,
    ),
    (
        "v_technician_performance",
        """
        SELECT t.technician_id, t.full_name, t.specialization, t.employment_status,
               COUNT(r.repair_id) AS repairs_performed,
               COUNT(r.repair_id) FILTER (WHERE r.outcome IN ('Fixed', 'Unit Replaced')) AS successful_repairs,
               COALESCE(SUM(r.labor_cost), 0)::numeric(12,2) AS labor_billed
        FROM technicians t
        LEFT JOIN repair_history r ON r.technician_id = t.technician_id
        GROUP BY t.technician_id, t.full_name, t.specialization, t.employment_status
        """,
    ),
]

DEFAULT_SETTINGS = [
    ("risk_band_medium_min", "0.30", "Probability at or above which a prediction is labelled Medium risk."),
    ("risk_band_high_min", "0.60", "Probability at or above which a prediction is labelled High risk."),
    ("prediction_horizon_days", "30", "Default prediction horizon (days) for training and prediction."),
    ("repeat_failure_window_days", "90", "Window used to flag a repair as a repeat failure."),
    ("expiring_soon_days", "60", "Warranties ending within this many days are listed as expiring soon."),
    ("dataset_provenance", '"operational"', "operational | synthetic_demo. Set by the seed script."),
]


def upgrade() -> None:
    for name, sql in VIEWS:
        op.execute(f"CREATE OR REPLACE VIEW {name} AS {sql}")
    for key, value, description in DEFAULT_SETTINGS:
        op.execute(
            "INSERT INTO app_settings (setting_key, setting_value, description) "
            f"VALUES ('{key}', '{value}'::jsonb, '{description}') ON CONFLICT (setting_key) DO NOTHING"
        )


def downgrade() -> None:
    for name, _ in reversed(VIEWS):
        op.execute(f"DROP VIEW IF EXISTS {name}")
    op.execute("DELETE FROM app_settings")
