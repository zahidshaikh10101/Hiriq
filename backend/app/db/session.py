"""Database engine and session. engine/SessionLocal are None until DATABASE_URL is set."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def _make_engine():
    url = settings.database_url
    if not url:
        return None
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(
        url,
        pool_pre_ping=True,   # Neon suspends idle compute; this transparently reconnects
        pool_recycle=300,
        pool_size=5,
        max_overflow=5,
        # Safe with Neon's pooled and direct endpoints alike.
        connect_args={"prepare_threshold": None},
    )


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False) if engine else None


def get_db() -> Iterator[Session | None]:
    """FastAPI dependency. Yields None when no database is configured."""
    if SessionLocal is None:
        yield None
        return
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
