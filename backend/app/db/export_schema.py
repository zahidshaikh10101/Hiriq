"""Write the PostgreSQL DDL for the models to ../db/schema.sql (reference / manual runs in the Neon SQL editor).

    python -m app.db.export_schema
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db import models  # noqa: F401  (registers tables)
from app.db.base import Base

OUT = Path(__file__).resolve().parents[2] / "db" / "schema.sql"


def build() -> str:
    dialect = postgresql.dialect()
    parts = ["-- Hiriq schema (PostgreSQL). Generated from app/db/models.py; do not edit by hand.\n"]
    for table in Base.metadata.sorted_tables:
        parts.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";\n")
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            parts.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";\n")
    parts.append(
        "INSERT INTO plans (id, name, live) VALUES\n"
        "  ('free','Free',true),('basic','Basic',false),('pro','Pro',false),('premium','Premium',false)\n"
        "ON CONFLICT (id) DO NOTHING;\n"
    )
    return "\n".join(parts)


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(), encoding="utf-8")
    print("Wrote", OUT)
