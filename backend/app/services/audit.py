from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.db.models import AuditLog


def record(
    db: Session, category: str, action: str, *, actor_id: uuid.UUID | None = None, actor_label: str = "system",
    target_user_id: uuid.UUID | None = None, ip: str | None = None, meta: dict | None = None,
) -> None:
    """Add an audit row to the current transaction (the caller commits)."""
    db.add(AuditLog(
        category=category, action=action, actor_id=actor_id, actor_label=actor_label[:120],
        target_user_id=target_user_id, ip=ip, meta=meta,
    ))
