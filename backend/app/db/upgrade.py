"""Bring an existing database up to the current schema.  Safe to run any number of times.

    python -m app.db.upgrade

The API also runs this once when it starts, so a new column or rule never leaves you with a crashing signup.
What it does today:
 - users.date_of_birth and users.tokens_valid_after (new columns)
 - otp_codes accepts the purpose 'reset' (forgot password) as well as 'signup'
 - candidates.visible_to_recruiters (new column, default false: members opt in) and candidate_job_matches (new table)
 - resume_versions, interview_preps and cover_letters (new tables): saved tailored resumes, interview prep, cover letters
 - applications (new table): a member's application to an open job, with the resume and letter sent
 - external_jobs.apply_key, dedupe_key and listed_at (new columns, filled for the jobs already stored; the apply_key is unique, so
   an old duplicate keeps an empty apply_key instead of failing), and the tables for job preferences, the personal job feed and the
   outside-job tracker (candidate_preferences, candidate_feed, external_applications)
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
from app.services import jobkeys

NEW_PURPOSES = "purpose IN ('signup', 'reset')"


def _upgrade_external_jobs(conn) -> list[str]:
    """New key and date columns on external_jobs, filled for the rows already there. Safe to run again."""
    done: list[str] = []
    cols = {c["name"] for c in inspect(conn).get_columns("external_jobs")}
    pg = conn.dialect.name == "postgresql"
    if "apply_key" not in cols:
        conn.execute(text("ALTER TABLE external_jobs ADD COLUMN apply_key VARCHAR(64)"))
        done.append("added external_jobs.apply_key")
    if "dedupe_key" not in cols:
        conn.execute(text("ALTER TABLE external_jobs ADD COLUMN dedupe_key VARCHAR(64)"))
        done.append("added external_jobs.dedupe_key")
    if "listed_at" not in cols:
        # SQLite cannot add a NOT NULL column with a changing default, so only PostgreSQL gets the constraint here
        conn.execute(text("ALTER TABLE external_jobs ADD COLUMN listed_at TIMESTAMP WITH TIME ZONE"
                          + (" NOT NULL DEFAULT now()" if pg else "")))
        conn.execute(text("UPDATE external_jobs SET listed_at = COALESCE(posted_at, first_seen_at)"))
        done.append("added external_jobs.listed_at (posted date, else first seen)")

    # Fill keys for rows that have none yet. The first row with a link keeps it; a later copy is left without an apply_key.
    rows = conn.execute(text("SELECT id, title, company, location, apply_url, apply_key, dedupe_key FROM external_jobs")).mappings().all()
    taken = {r["apply_key"] for r in rows if r["apply_key"]}
    filled = 0
    for r in rows:
        akey = r["apply_key"] or jobkeys.apply_key(r["apply_url"])
        if akey and akey in taken and akey != r["apply_key"]:
            akey = None
        dkey = r["dedupe_key"] or jobkeys.dedupe_key(r["title"], r["company"], r["location"])
        if (akey, dkey) != (r["apply_key"], r["dedupe_key"]):
            conn.execute(text("UPDATE external_jobs SET apply_key = :a, dedupe_key = :d WHERE id = :id"),
                         {"a": akey or r["apply_key"], "d": dkey, "id": r["id"]})
            if akey:
                taken.add(akey)
            filled += 1
    if filled:
        done.append(f"filled the duplicate-detection keys of {filled} outside job(s)")

    for name, ddl in (
        ("uq_external_jobs_apply_key", "CREATE UNIQUE INDEX IF NOT EXISTS uq_external_jobs_apply_key ON external_jobs (apply_key)"),
        ("ix_external_jobs_dedupe_key", "CREATE INDEX IF NOT EXISTS ix_external_jobs_dedupe_key ON external_jobs (dedupe_key)"),
        ("ix_external_jobs_listed_at", "CREATE INDEX IF NOT EXISTS ix_external_jobs_listed_at ON external_jobs (listed_at)"),
    ):
        existing = {i["name"] for i in inspect(conn).get_indexes("external_jobs")}
        if name not in existing:
            conn.execute(text(ddl))
            done.append(f"added index {name}")
    return done


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

        done += _upgrade_external_jobs(conn)

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
