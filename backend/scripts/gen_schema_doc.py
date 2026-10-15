"""Generate dbms_documentation/RELATIONAL_SCHEMA.md from the SQLAlchemy metadata.

    python -m scripts.gen_schema_doc
"""
from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.dialects import postgresql

from app.models import Base

OUT = Path(__file__).resolve().parents[2] / "dbms_documentation" / "RELATIONAL_SCHEMA.md"
ORDER = ["customers", "technicians", "users", "product_models", "products", "warranties", "fault_categories",
         "service_requests", "components", "repair_history", "parts", "repair_parts", "inventory_transactions",
         "model_training_runs", "failure_predictions", "audit_logs", "app_settings"]

INTRO = """# Relational Schema

Generated from the SQLAlchemy models (`backend/app/models/entities.py`) by
`python -m scripts.gen_schema_doc`; the executable DDL is `backend/sql/schema.sql`
(rendered from the Alembic migrations). Notation: **PK** primary key, **FK** foreign key,
**UQ** unique, **NN** not null. Every FK is `ON DELETE RESTRICT` unless stated otherwise,
so historical records cannot be orphaned.

## Compact relational notation

"""


def compact(t) -> str:
    cols = []
    for c in t.columns:
        name = f"<u>{c.name}</u>" if c.primary_key else c.name
        if c.foreign_keys:
            name += "†"
        cols.append(name)
    return f"- **{t.name}**({', '.join(cols)})"


def main() -> None:
    tables = [Base.metadata.tables[n] for n in ORDER]
    lines = [INTRO]
    lines += [compact(t) for t in tables]
    lines.append("\n<u>underlined</u> = primary key, † = foreign key.\n")
    for t in tables:
        lines.append(f"\n## `{t.name}`\n")
        lines.append("| Column | Type | Null | Default | Key / reference |")
        lines.append("|---|---|---|---|---|")
        for c in t.columns:
            ctype = c.type.compile(dialect=postgresql.dialect())
            keys = []
            if c.primary_key:
                keys.append("PK")
            if c.unique:
                keys.append("UQ")
            for fk in c.foreign_keys:
                rule = fk.ondelete or "NO ACTION"
                keys.append(f"FK → `{fk.column.table.name}.{fk.column.name}` ({rule})")
            default = c.server_default.arg if c.server_default is not None else ""
            default = getattr(default, "text", default)
            lines.append(f"| `{c.name}` | {ctype} | {'yes' if c.nullable else 'NN'} | {str(default).replace('|', '/')} | {'; '.join(keys)} |")
        extra = []
        for con in sorted(t.constraints, key=lambda x: x.name or ""):
            if isinstance(con, CheckConstraint):
                extra.append(f"- CHECK `{con.name}`: `{con.sqltext}`")
            elif isinstance(con, UniqueConstraint) and len(con.columns) > 1:
                extra.append(f"- UNIQUE `{con.name}` ({', '.join(c.name for c in con.columns)})")
            elif isinstance(con, ForeignKeyConstraint) and len(con.columns) > 1:
                extra.append(f"- Composite FK `{con.name}` ({', '.join(c.name for c in con.columns)}) → "
                             f"`{con.referred_table.name}` ({', '.join(e.column.name for e in con.elements)})")
        for idx in sorted(t.indexes, key=lambda i: i.name):
            where = idx.dialect_options["postgresql"].get("where")
            cols = ", ".join(str(e) for e in idx.expressions)
            extra.append(f"- {'UNIQUE ' if idx.unique else ''}INDEX `{idx.name}` ({cols})"
                         + (f" WHERE `{where}`" if where is not None else ""))
        if extra:
            lines.append("\n**Constraints & indexes**\n")
            lines += extra
    OUT.write_text("\n".join(lines) + "\n")
    print("wrote", OUT, len(lines), "lines")


if __name__ == "__main__":
    _ = Index  # imported for type completeness
    main()
