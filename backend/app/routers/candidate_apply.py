"""Applying to a job, from the candidate workspace (mounted at /api/candidate).

    POST   /jobs/{id}/apply        {version_id?, letter_id?, message?}: apply to an open job
    GET    /applications           your applications, newest first
    DELETE /applications/{id}      withdraw: the recruiter loses access to what you sent

Applying is the one moment your details go to a recruiter, and only to the owner of that job. What they get is a copy made
now: your resume text (your uploaded resume, or one of your tailored versions), a cover letter if you pick one, an optional
short message, your contact details and your fit score. Editing or deleting the originals later changes nothing in the copy;
withdrawing deletes it. Nothing is sent without this click, and nothing here ever scores your name, gender, photo, college or age.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import require_candidate
from app.db.models import User
from app.db.recruiter_models import Application, CoverLetter, Job, RecruiterEvent, ResumeVersion
from app.db.session import get_db
from app.routers.candidate import _db, _ensure, _err, _get_open_job, _iso
from app.routers.matches import _cand_view, _job_view
from app.services import matching

router = APIRouter(tags=["candidate-apply"])

MAX_APPLICATIONS = 100
MAX_MESSAGE = 1000


class ApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: str | None = None
    letter_id: str | None = None
    message: str | None = Field(default=None, max_length=MAX_MESSAGE)


def _key(raw: str | None, what: str) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        raise _err(404, "not_found", f"That {what} does not exist.")


def _item(a: Application, job: Job | None, owner: User | None) -> dict:
    return {
        "id": str(a.id), "job_id": str(a.job_id), "job_title": job.title if job else None, "company": (owner.company if owner else None) or None,
        "job_status": job.status if job else None, "resume_label": a.resume_label, "letter_label": a.letter_label,
        "has_message": bool(a.message), "applied_at": _iso(a.created_at),
    }


@router.post("/jobs/{job_id}/apply", status_code=201)
def apply(job_id: str, body: ApplyIn, actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    job, owner = _get_open_job(db, job_id)
    if not (c.resume_text or "").strip():
        raise _err(409, "no_resume", "Upload your resume first. A recruiter reads your resume when you apply.")
    if db.scalar(select(Application.id).where(Application.job_id == job.id, Application.candidate_id == c.id)) is not None:
        raise _err(409, "already_applied", "You have already applied to this job.")
    if (db.scalar(select(func.count()).select_from(Application).where(Application.candidate_id == c.id)) or 0) >= MAX_APPLICATIONS:
        raise _err(409, "too_many", f"You have {MAX_APPLICATIONS} applications. Withdraw one to make room.")

    text, label = c.resume_text, "Your uploaded resume"
    vid = _key(body.version_id, "version")
    if vid is not None:
        v = db.get(ResumeVersion, vid)
        if v is None or v.candidate_id != c.id:
            raise _err(404, "not_found", "That version does not exist.")
        text, label = v.text, v.label
    letter_text = letter_label = None
    lid = _key(body.letter_id, "letter")
    if lid is not None:
        letter = db.get(CoverLetter, lid)
        if letter is None or letter.candidate_id != c.id:
            raise _err(404, "not_found", "That letter does not exist.")
        letter_text, letter_label = letter.text, letter.label

    view = _cand_view(c)
    view["text"] = text
    score = matching.score_candidate(_job_view(job), view, dict(matching.DEFAULT_WEIGHTS), None)["score"]
    p = c.profile or {}
    contact = {"email": c.email or actor.email, "phone": c.phone or actor.phone_e164, "location": c.location, "linkedin_url": c.linkedin_url,
               "github_url": c.github_url, "portfolio_url": p.get("portfolio_url")}
    message = " ".join((body.message or "").split()) or None
    a = Application(job_id=job.id, candidate_id=c.id, resume_label=label[:120], resume_text=text, letter_label=letter_label, letter_text=letter_text,
                    message=message, contact=contact, fit_score=score)
    db.add(a)
    db.add(RecruiterEvent(owner_id=job.owner_id, kind="pipeline", text=f"{c.full_name} applied to {job.title}", job_id=job.id, candidate_id=c.id))
    db.commit()
    db.refresh(a)
    return _item(a, job, owner)


@router.get("/applications")
def list_applications(actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    rows = db.execute(
        select(Application, Job, User).join(Job, Job.id == Application.job_id).outerjoin(User, User.id == Job.owner_id)
        .where(Application.candidate_id == c.id).order_by(Application.created_at.desc())
    ).all()
    return {"applications": [_item(a, j, u) for a, j, u in rows], "max": MAX_APPLICATIONS}


@router.delete("/applications/{application_id}")
def withdraw(application_id: str, actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    key = _key(application_id, "application")
    a = db.get(Application, key) if key else None
    if a is None or a.candidate_id != c.id:
        raise _err(404, "not_found", "That application does not exist.")
    db.delete(a)
    db.commit()
    return {"deleted": True}
