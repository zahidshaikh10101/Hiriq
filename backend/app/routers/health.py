from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine

router = APIRouter(tags=["health"])


def _database_state() -> str:
    if engine is None:
        return "not_configured"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok"
    except Exception:  # connection refused, bad password, Neon waking up, ...
        return "unreachable"


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.version,
        "auth_ready": settings.auth_ready,
        "database": _database_state(),
        "google_ready": bool(settings.google_client_id),
        "email_provider": settings.email_provider,
    }
