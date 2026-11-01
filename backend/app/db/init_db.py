"""Create all tables and seed the plans.  Run from the backend folder:

    python -m app.db.init_db

Safe to run repeatedly (only creates what is missing). When the schema starts changing
under real data, switch to Alembic migrations.
"""
from __future__ import annotations

from sqlalchemy import inspect

from app.db import models
from app.db.base import Base
from app.db.session import SessionLocal, engine

PLANS = [("free", "Free", True), ("basic", "Basic", False), ("pro", "Pro", False), ("premium", "Premium", False)]


def init_db() -> list[str]:
    if engine is None or SessionLocal is None:
        raise SystemExit("DATABASE_URL is not set. Put it in backend/.env first.")
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for pid, name, live in PLANS:
            if db.get(models.Plan, pid) is None:
                db.add(models.Plan(id=pid, name=name, live=live))
        db.commit()
    return sorted(inspect(engine).get_table_names())


if __name__ == "__main__":
    tables = init_db()
    print("Database ready. Tables:", ", ".join(tables))
