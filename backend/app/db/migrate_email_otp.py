"""Move an old database from phone codes to email codes.  Safe to run any number of times.

    python -m app.db.migrate_email_otp

The first version of Hiriq sent one-time codes to a phone (otp_codes.phone_e164). Codes now go to an email address
(otp_codes.destination). A code only lives for a few minutes, so there is nothing worth carrying over: the old table is
dropped and rebuilt in the current shape. Users, admins and the audit log are never touched.
"""
from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import models
from app.db.session import engine


def migrate() -> list[str]:
    if engine is None:
        raise SystemExit("DATABASE_URL is not set. Put it in backend/.env first.")
    inspector = inspect(engine)
    if "otp_codes" in inspector.get_table_names():
        if "destination" in {c["name"] for c in inspector.get_columns("otp_codes")}:
            return []   # already the email version
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE otp_codes"))
    models.OtpCode.__table__.create(engine, checkfirst=True)
    return ["otp_codes rebuilt for email codes"]


if __name__ == "__main__":
    changes = migrate()
    print("Database upgraded:" if changes else "Database already up to date.", *changes, sep="\n  - " if changes else "")