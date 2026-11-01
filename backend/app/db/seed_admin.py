"""Create (or reset the password of) the first admin from .env.  Run from the backend folder:

    python -m app.db.seed_admin

Needs DATABASE_URL, ADMIN_USERNAME, ADMIN_EMAIL, ADMIN_PASSWORD (12+ characters) in backend/.env.
Run `python -m app.db.init_db` first.
"""
from __future__ import annotations

import os

from sqlalchemy import select

from app.core.security import hash_password
from app.db import models
from app.db.session import SessionLocal


def seed_admin() -> str:
    if SessionLocal is None:
        raise SystemExit("DATABASE_URL is not set. Put it in backend/.env first.")
    username = os.getenv("ADMIN_USERNAME", "admin").strip().lower()
    email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "")
    name = os.getenv("ADMIN_NAME", "Platform admin").strip() or "Platform admin"
    if not email or "@" not in email:
        raise SystemExit("Set ADMIN_EMAIL in backend/.env.")
    if len(password) < 12:
        raise SystemExit("Set ADMIN_PASSWORD (12+ characters) in backend/.env.")

    with SessionLocal() as db:
        user = db.scalar(select(models.User).where((models.User.username == username) | (models.User.email == email)))
        created = user is None
        if created:
            user = models.User(email=email, username=username, full_name=name)
            db.add(user)
        user.role = "admin"
        user.status = "active"
        user.email_verified = True
        user.password_hash = hash_password(password)
        user.failed_logins = 0
        user.locked_until = None
        db.flush()
        if db.get(models.AdminProfile, user.id) is None:
            db.add(models.AdminProfile(user_id=user.id, is_superadmin=True, permissions=[]))
        db.add(models.AuditLog(
            category="Users", actor_label="system",
            action=f"{'created' if created else 'reset the password of'} admin {username}", target_user_id=user.id,
        ))
        db.commit()
    return f"Admin {'created' if created else 'updated'}: log in with '{username}' or '{email}'."


if __name__ == "__main__":
    print(seed_admin())
