"""Bring an existing database up to the current schema.  Safe to run any number of times.

    python -m app.db.upgrade

The API also runs this once when it starts, so a new column or rule never leaves you with a crashing signup.
What it does today:
 - users.date_of_birth and users.tokens_valid_after (new columns)
 - otp_codes accepts the purpose 'reset' (forgot password) as well as 'signup'
 - candidates.visible_to_recruiters (new column, default false: members opt in) and candidate_job_matches (new table)
 - resume_versions, interview_preps and cover_letters (new tables): saved tailored resumes, interview prep, cover letters
 - pending_signups (new table): an unverified sign-up now waits there instead of in `users`
   Old half-finished sign-ups left in `users` (never verified, no Google link, never signed in) are removed, because
   their password could have been set by someone other than the email's owner.
Your users, admins and audit log are never touched.
"""
from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import models  # noqa: F401  (registers the tables)
from app.db.init_db import init_db
from app.db.session import engine

NEW_PURPOSES = "purpose IN ('signup', 'reset')"


def upgrade() -> list[str]:
    if engine is None:
        raise SystemExit("DATABASE_URL is not set. Put it in backend/.env first.")
    done: list[str] = []
    init_db()  # creates anything missing, seeds plans

    cols = {c["name"] for c in inspect(engine).get_columns("users")}
    cand_cols = {c["name"] for c in inspect(engine).get_columns("candidates")}
    with engine.begin() as conn:
        if "date_of_birth" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN date_of_birth DATE"))
            done.append("added users.date_of_birth")
        if "tokens_valid_after" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN tokens_valid_after TIMESTAMP WITH TIME ZONE"))
            done.append("added users.tokens_valid_after")

        if "visible_to_recruiters" not in cand_cols:
            conn.execute(text("ALTER TABLE candidates ADD COLUMN visible_to_recruiters BOOLEAN NOT NULL DEFAULT false"))
            done.append("added candidates.visible_to_recruiters (members are hidden from recruiters until they opt in)")

        stale = conn.execute(text(
            "DELETE FROM users WHERE email_verified = :no AND password_hash IS NOT NULL AND role <> 'admin' "
            "AND last_login_at IS NULL AND id NOT IN (SELECT user_id FROM auth_identities)"
        ), {"no": False}).rowcount
        if stale:
            done.append(f"removed {stale} unverified half-finished sign-up(s) from users")

        if engine.dialect.name == "postgresql":
            rows = conn.execute(text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'otp_codes'::regclass AND contype = 'c'"
            )).all()
            purpose_checks = [(n, d) for n, d in rows if "purpose" in d]
            if not any("reset" in d for _, d in purpose_checks):
                for name, _ in purpose_checks:
                    conn.execute(text(f'ALTER TABLE otp_codes DROP CONSTRAINT "{name}"'))
                conn.execute(text(f"ALTER TABLE otp_codes ADD CONSTRAINT ck_otp_purpose CHECK ({NEW_PURPOSES})"))
                done.append("otp_codes now accepts password-reset codes")
    return done


if __name__ == "__main__":
    changes = upgrade()
    print("Database upgraded:" if changes else "Database already up to date.", *changes, sep="\n  - " if changes else "")
