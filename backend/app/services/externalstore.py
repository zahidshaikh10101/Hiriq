"""Keeps every outside job post Hiriq fetches in the external_jobs table, one row per post.

Public job text only. Nothing about the candidate who searched is saved with it, and no score (scores are per candidate and
are worked out when shown). Saving never blocks a search: if the database refuses, the search still answers, just without
a job_ref (so the "Detailed analysis" button is not offered for that post).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.recruiter_models import ExternalJob
from app.services import jobkeys, postingread

PROVIDER = "indeed"


def _when(iso: str | None) -> datetime | None:
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if iso else None
    except ValueError:
        return None


def _find_same(db: Session, provider: str, external_id: str, akey: str | None, dkey: str | None, seen: dict) -> ExternalJob | None:
    """The row this post already has: same provider and id, else the same apply link, else the same title-company-city."""
    row = db.scalars(select(ExternalJob).where(ExternalJob.provider == provider, ExternalJob.external_id == external_id)).first()
    if row is None and akey:
        row = seen.get(("a", akey)) or db.scalars(select(ExternalJob).where(ExternalJob.apply_key == akey)).first()
    if row is None and dkey:
        row = seen.get(("d", dkey)) or db.scalars(select(ExternalJob).where(ExternalJob.dedupe_key == dkey)).first()
    return row


def save(db: Session, jobs: list[dict], query: str, country: str) -> dict[str, ExternalJob]:
    """Insert new posts and refresh known ones. Returns {provider id: row} for what could be saved.
    A post that is already in the library under another id or site (same apply link, or same title, company and city) refreshes
    that row instead of adding a second one, and is returned under its own provider id."""
    if not jobs:
        return {}
    now = datetime.now(timezone.utc)
    out: dict[str, ExternalJob] = {}
    seen: dict = {}                                   # rows added or touched in this batch, by key
    try:
        for j in jobs:
            akey = jobkeys.apply_key(j["apply_url"])
            dkey = jobkeys.dedupe_key(j["title"], j["company"], j["location"])
            row = _find_same(db, PROVIDER, j["id"], akey, dkey, seen)
            if row is None:
                row = ExternalJob(provider=PROVIDER, external_id=j["id"], first_seen_at=now, listed_at=now)
                db.add(row)
            row.title, row.company, row.location, row.country = j["title"], j["company"], j["location"], (country or None)
            row.remote, row.apply_url, row.description = bool(j["remote"]), j["apply_url"], j["description"]
            row.posted_at, row.last_query, row.last_seen_at = _when(j["posted_at"]), query[:100], now
            if row.posted_at:
                row.listed_at = row.posted_at
            # keep the key a row already has when this copy has no link (never replace a good key with nothing)
            row.apply_key = akey or row.apply_key
            row.dedupe_key = dkey or row.dedupe_key
            row.read = postingread.read(j["title"], j["description"])
            if row.apply_key:
                seen[("a", row.apply_key)] = row
            if row.dedupe_key:
                seen[("d", row.dedupe_key)] = row
            db.flush()                                # surfaces a clash now, row by row
            out[j["id"]] = row
        db.commit()
        return out
    except SQLAlchemyError:
        db.rollback()                 # also covers two searches saving the same new post at once
        return {}


def fresh_clause(days: int = jobkeys.FRESH_DAYS):
    """Use in a query: `select(ExternalJob).where(externalstore.fresh_clause())` keeps only posts newer than 30 days."""
    return ExternalJob.listed_at >= jobkeys.cutoff(days=days)


def purge_stale(db: Session, days: int = jobkeys.FRESH_DAYS) -> int:
    """Delete outside jobs older than 30 days (they are probably filled). Their feed rows go with them; a candidate's own
    tracker entries stay, because they keep a copy of the title, company and link. Jobs an admin added by hand are kept
    until an admin deletes them. Returns how many were removed."""
    stale = db.scalars(select(ExternalJob).where(ExternalJob.listed_at < jobkeys.cutoff(days=days), ExternalJob.provider != "manual")).all()
    for row in stale:
        db.delete(row)
    db.commit()
    return len(stale)
