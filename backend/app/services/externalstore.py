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
from app.services import postingread

PROVIDER = "indeed"


def _when(iso: str | None) -> datetime | None:
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if iso else None
    except ValueError:
        return None


def save(db: Session, jobs: list[dict], query: str, country: str) -> dict[str, ExternalJob]:
    """Insert new posts and refresh known ones. Returns {provider id: row} for what could be saved."""
    ids = [j["id"] for j in jobs]
    if not ids:
        return {}
    now = datetime.now(timezone.utc)
    try:
        have = {r.external_id: r for r in db.scalars(select(ExternalJob).where(ExternalJob.provider == PROVIDER, ExternalJob.external_id.in_(ids))).all()}
        for j in jobs:
            row = have.get(j["id"])
            if row is None:
                row = ExternalJob(provider=PROVIDER, external_id=j["id"], first_seen_at=now)
                db.add(row)
                have[j["id"]] = row
            row.title, row.company, row.location, row.country = j["title"], j["company"], j["location"], (country or None)
            row.remote, row.apply_url, row.description = bool(j["remote"]), j["apply_url"], j["description"]
            row.posted_at, row.last_query, row.last_seen_at = _when(j["posted_at"]), query[:100], now
            row.read = postingread.read(j["title"], j["description"])
        db.commit()
        return {k: v for k, v in have.items() if k in ids}
    except SQLAlchemyError:
        db.rollback()                 # also covers two searches saving the same new post at once
        return {}
