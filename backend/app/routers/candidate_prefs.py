"""Job preferences of the signed-in candidate (mounted at /api/candidate).

    GET    /preferences    places, roles, job types and work modes they want, when the feed was last refreshed, and the limits
    PUT    /preferences    save the whole set (add, edit and delete are all "send the new lists"); starts a background fetch
                           of outside jobs when the roles or places changed. Saving does NOT count as the daily refresh.
    DELETE /preferences    clear them all
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import require_candidate
from app.db.models import User
from app.db.recruiter_models import PREF_JOB_TYPES, PREF_MAX, PREF_WORK_MODES, CandidatePreference
from app.db.session import get_db
from app.routers.candidate import _db, _ensure
from app.services import externaljobs, prefs

router = APIRouter(tags=["candidate-preferences"])


class PrefsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    locations: list = []
    roles: list = []
    job_types: list = []
    work_modes: list = []

    @field_validator("locations")
    @classmethod
    def _locations(cls, v):
        return prefs.clean_list(v, "places", PREF_MAX["locations"])

    @field_validator("roles")
    @classmethod
    def _roles(cls, v):
        return prefs.clean_list(v, "roles", PREF_MAX["roles"])

    @field_validator("job_types")
    @classmethod
    def _types(cls, v):
        return prefs.clean_choices(v, "job types", PREF_JOB_TYPES)

    @field_validator("work_modes")
    @classmethod
    def _modes(cls, v):
        return prefs.clean_choices(v, "work modes", PREF_WORK_MODES)


def _row(db: Session, candidate_id):
    return db.scalars(select(CandidatePreference).where(CandidatePreference.candidate_id == candidate_id)).first()


@router.get("/preferences")
def get_preferences(actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    return prefs.view(_row(db, c.id))


@router.put("/preferences")
def save_preferences(body: PrefsBody, background: BackgroundTasks, actor: User = Depends(require_candidate),
                     db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    row = _row(db, c.id)
    before = prefs.search_key(list(row.roles or []), list(row.locations or [])) if row else ((), ())
    if row is None:
        row = CandidatePreference(candidate_id=c.id)
        db.add(row)
    row.locations, row.roles, row.job_types, row.work_modes = body.locations, body.roles, body.job_types, body.work_modes
    db.commit()
    db.refresh(row)
    changed = prefs.search_key(body.roles, body.locations) != before
    fetching = bool(changed and body.roles and externaljobs.configured())
    if fetching:
        background.add_task(prefs.fetch_for, c.id)
    out = prefs.view(row)
    out["fetching"] = fetching
    return out


@router.delete("/preferences")
def clear_preferences(actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    row = _row(db, c.id)
    if row is not None:
        db.delete(row)
        db.commit()
    return prefs.view(None)
