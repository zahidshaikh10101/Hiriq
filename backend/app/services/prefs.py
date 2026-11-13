"""Job preferences: cleaning what the candidate types, and the first fetch of outside jobs after they save.

A preference list is "what I'd like, in order"; an empty list means no preference. Everything typed is untrusted text: it is
trimmed, limited and de-duplicated here, and later sent to the job feed only as a search word, never run.
The first fetch is kept deliberately small: the outside feed has a small monthly allowance for the whole server, so a save
makes at most EXTERNAL_SAVE_FETCH_CALLS searches (default 2, one page each) and only when the roles or places changed.
"""
from __future__ import annotations

import os
import re
import uuid

from sqlalchemy import select

from app.db import session as db_session
from app.db.recruiter_models import PREF_JOB_TYPES, PREF_MAX, PREF_WORK_MODES, CandidatePreference
from app.services import externaljobs, externalstore

_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .,'&()/+#-]{1,79}$")
_SPACES = re.compile(r"\s+")


def clean_list(values, name: str, limit: int) -> list[str]:
    """Trim, collapse spaces, drop repeats (ignoring case), check each item. Raises ValueError with a plain sentence."""
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError(f"{name.capitalize()} must be a list.")
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        if not isinstance(v, str):
            raise ValueError(f"Each item in {name} must be text.")
        t = _SPACES.sub(" ", v).strip()
        if not t:
            continue
        if not _TEXT.match(t):
            raise ValueError(f"\"{t[:40]}\" is not a valid entry for {name}. Use 2 to 80 letters, numbers or simple punctuation.")
        if t.lower() in seen:
            continue
        seen.add(t.lower())
        out.append(t)
    if len(out) > limit:
        raise ValueError(f"Choose at most {limit} {name}.")
    return out


def clean_choices(values, name: str, allowed: tuple[str, ...]) -> list[str]:
    """Only values from the allowed list, shown in the allowed order, no repeats."""
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError(f"{name.capitalize()} must be a list.")
    picked = {str(v).strip().lower() for v in values}
    bad = [v for v in picked if v not in allowed]
    if bad:
        raise ValueError(f"\"{sorted(bad)[0][:30]}\" is not one of: {', '.join(allowed)}.")
    return [a for a in allowed if a in picked]


def view(p: CandidatePreference | None) -> dict:
    return {
        "locations": list(p.locations or []) if p else [], "roles": list(p.roles or []) if p else [],
        "job_types": list(p.job_types or []) if p else [], "work_modes": list(p.work_modes or []) if p else [],
        "last_refreshed_at": p.last_refreshed_at.isoformat() if p and p.last_refreshed_at else None,
        "limits": dict(PREF_MAX), "options": {"job_types": list(PREF_JOB_TYPES), "work_modes": list(PREF_WORK_MODES)},
        "feed_on": externaljobs.configured(),
    }


def search_key(roles: list[str], locations: list[str]) -> tuple:
    """What the feed is actually asked: only roles and places. Job type and work mode do not change the search."""
    return (tuple(r.lower() for r in roles), tuple(l.lower() for l in locations))


def _calls_per_save() -> int:
    try:
        return max(0, min(int(os.getenv("EXTERNAL_SAVE_FETCH_CALLS", "2")), 5))
    except ValueError:
        return 2


def queries(roles: list[str], locations: list[str], limit: int) -> list[tuple[str, str]]:
    """The first few (role, place) searches. Each role is tried before a role is repeated in another place."""
    places = locations or [""]
    return [(r, l) for l in places for r in roles][:limit]


def fetch_for(candidate_id: uuid.UUID) -> int:
    """Background job after a save: fetch a few pages of outside jobs for this candidate's roles and keep them in the database.
    Returns how many posts were kept. Never raises: a failed fetch must not matter to the person who just saved."""
    if db_session.SessionLocal is None or not externaljobs.configured():
        return 0
    kept = 0
    try:
        with db_session.SessionLocal() as db:
            p = db.scalars(select(CandidatePreference).where(CandidatePreference.candidate_id == candidate_id)).first()
            if p is None or not p.roles:
                return 0
            for role, place in queries(list(p.roles), list(p.locations or []), _calls_per_save()):
                try:
                    found = externaljobs.search(role, place)
                except externaljobs.ExternalError as exc:
                    if exc.code in ("feed_busy", "not_configured", "monthly_limit"):
                        break
                    continue
                kept += len(externalstore.save(db, [dict(j) for j in found["jobs"]], role, externaljobs.country()))
                db.commit()
    except Exception:  # noqa: BLE001
        return kept
    return kept
