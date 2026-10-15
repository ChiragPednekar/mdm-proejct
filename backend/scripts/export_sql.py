"""Regenerate the standalone SQL files in backend/sql/ from the source of truth.

    python -m scripts.export_sql

* sql/schema.sql            - full DDL (tables, constraints, indexes, views) rendered
                              from the Alembic migrations in offline mode
* sql/analytics_queries.sql - the 12 parameterized reports from app/services/analytics.py
                              plus catalogue / integrity queries
"""
import io
import re
from contextlib import redirect_stdout
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.services.analytics import REPORTS, _resolve_default

BACKEND = Path(__file__).resolve().parents[1]
SQL_DIR = BACKEND / "sql"

CATALOGUE_QUERIES = """
-- =====================================================================
-- Schema / catalogue queries (PostgreSQL system catalogue)
-- =====================================================================

-- Tables and row counts (statistics estimate)
SELECT relname AS table_name, n_live_tup AS approx_rows
FROM pg_stat_user_tables ORDER BY relname;

-- Primary keys, foreign keys, unique and check constraints per table
SELECT tc.table_name, tc.constraint_type, tc.constraint_name,
       string_agg(kcu.column_name, ', ' ORDER BY kcu.ordinal_position) AS columns
FROM information_schema.table_constraints tc
LEFT JOIN information_schema.key_column_usage kcu
       ON kcu.constraint_name = tc.constraint_name AND kcu.table_name = tc.table_name
WHERE tc.table_schema = 'public'
GROUP BY tc.table_name, tc.constraint_type, tc.constraint_name
ORDER BY tc.table_name, tc.constraint_type;

-- Foreign keys with their ON DELETE rules
SELECT conrelid::regclass AS child_table, conname, confrelid::regclass AS parent_table,
       CASE confdeltype WHEN 'r' THEN 'RESTRICT' WHEN 'a' THEN 'NO ACTION' WHEN 'c' THEN 'CASCADE'
                        WHEN 'n' THEN 'SET NULL' WHEN 'd' THEN 'SET DEFAULT' END AS on_delete
FROM pg_constraint WHERE contype = 'f' ORDER BY 1, 2;

-- Indexes (including partial and expression indexes)
SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' ORDER BY tablename, indexname;

-- Views
SELECT table_name AS view_name FROM information_schema.views WHERE table_schema = 'public' ORDER BY 1;

-- =====================================================================
-- Integrity checks (each should return 0)
-- =====================================================================

-- Stored parts_cost snapshot equals the sum of its junction lines
SELECT COUNT(*) AS parts_cost_mismatches FROM v_repair_costs WHERE parts_cost <> parts_cost_from_lines;

-- Stock on hand equals the inventory ledger
SELECT COUNT(*) AS stock_ledger_mismatches
FROM parts p
WHERE p.stock_quantity <> (SELECT COALESCE(SUM(t.quantity_change), 0) FROM inventory_transactions t WHERE t.part_id = p.part_id);

-- A service request's warranty always belongs to the same product (also enforced by a composite FK)
SELECT COUNT(*) AS cross_product_warranties
FROM service_requests sr JOIN warranties w ON w.warranty_id = sr.warranty_id
WHERE w.product_id <> sr.product_id;

-- At most one Current prediction per product and horizon (also enforced by a partial unique index)
SELECT product_id, prediction_horizon_days, COUNT(*) FROM failure_predictions
WHERE prediction_status = 'Current' GROUP BY 1, 2 HAVING COUNT(*) > 1;

-- =====================================================================
-- Transaction & rollback demonstration (run in psql)
-- =====================================================================
-- BEGIN;
--   UPDATE parts SET stock_quantity = stock_quantity - 1 WHERE part_id = 1;
--   SELECT stock_quantity FROM parts WHERE part_id = 1;      -- reduced inside the transaction
--   UPDATE parts SET stock_quantity = -5 WHERE part_id = 1;  -- violates ck_parts_stock_non_negative
-- ROLLBACK;                                                  -- (an error aborts the transaction anyway)
-- SELECT stock_quantity FROM parts WHERE part_id = 1;        -- unchanged

-- =====================================================================
-- Query optimisation demonstration
-- =====================================================================
-- EXPLAIN ANALYZE SELECT * FROM products WHERE serial_number = 'BRL-RF-26-00019';           -- unique index scan
-- EXPLAIN ANALYZE SELECT * FROM service_requests WHERE reported_at >= now() - INTERVAL '30 days'; -- ix_service_requests_reported_at
-- EXPLAIN ANALYZE SELECT * FROM customers WHERE lower(full_name) = 'nadia rao';              -- expression index
"""


def render_schema() -> str:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", "postgresql+psycopg://user:pass@localhost/db")
    buf = io.StringIO()
    cfg.output_buffer = buf
    with redirect_stdout(io.StringIO()):
        command.upgrade(cfg, "head", sql=True)
    return ("-- Generated by `python -m scripts.export_sql` from the Alembic migrations.\n"
            "-- Apply with: psql \"$DATABASE_URL\" -f sql/schema.sql  (or `alembic upgrade head`)\n\n" + buf.getvalue())


def render_reports() -> str:
    parts = ["-- Generated by `python -m scripts.export_sql` from app/services/analytics.py.\n"
             "-- Runnable as-is:  psql \"$DATABASE_URL\" -f sql/analytics_queries.sql\n"
             "-- The API runs the same statements with bound parameters (:name); here psql variables\n"
             "-- (\\set + :'name') supply the defaults, resolved on the export date for date parameters.\n"]
    for i, r in enumerate(REPORTS, start=1):
        params = ", ".join(f":{p.name} ({p.type}, default {p.default})" for p in r.params) or "none"
        sets = "".join(f"\\set {p.name} {_resolve_default(p)}\n" for p in r.params)
        sql = r.sql.strip()
        for p in r.params:  # :name -> psql interpolation; (?<!:) keeps ::casts intact
            repl = f":{p.name}" if p.type == "int" else f":'{p.name}'"
            sql = re.sub(rf"(?<!:):{p.name}\b", repl, sql)
        parts.append(f"\n-- ---------------------------------------------------------------------\n"
                     f"-- {i:02d}. {r.title}\n-- {r.description}\n-- Concepts: {', '.join(r.concepts)}\n"
                     f"-- Parameters: {params}\n-- ---------------------------------------------------------------------\n"
                     f"{sets}{sql};\n")
    return "".join(parts) + CATALOGUE_QUERIES


def main() -> None:
    SQL_DIR.mkdir(exist_ok=True)
    (SQL_DIR / "schema.sql").write_text(render_schema())
    (SQL_DIR / "analytics_queries.sql").write_text(render_reports())
    for f in ("schema.sql", "analytics_queries.sql"):
        text = (SQL_DIR / f).read_text()
        print(f, len(text.splitlines()), "lines;", len(re.findall(r"CREATE (?:TABLE|OR REPLACE VIEW)", text)), "tables/views")


if __name__ == "__main__":
    main()
