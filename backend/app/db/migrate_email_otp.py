"""One-time upgrade for a database created by the earlier (phone OTP) version.  Run from backend/:

    python -m app.db.migrate_email_otp

 - users.phone_e164 stops being UNIQUE (phones are optional and unverified now)
 - otp_codes is rebuilt to hold email codes (it only ever holds short-lived codes)
Safe to run more than once. Your users, admin and audit log are untouched.
"""
from __future__ import annotations

from sqlalchemy import text

from app.db.base import Base
from app.db import models  # noqa: F401
from app.db.init_db import init_db
from app.db.session import engine


def migrate() -> None:
    if engine is None:
        raise SystemExit("DATABASE_URL is not set. Put it in backend/.env first.")
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_phone_e164_key"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_phone_e164 ON users (phone_e164)"))
        conn.execute(text("DROP TABLE IF EXISTS otp_codes"))
    init_db()  # recreates otp_codes with the new shape


if __name__ == "__main__":
    migrate()
    print("Migration done.")
