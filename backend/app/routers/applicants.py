"""Who applied to my jobs (mounted at /api/recruiter). Every route needs a signed-in recruiter.

    GET /applicants                                my jobs with how many people applied
    GET /jobs/{id}/applicants                      the people who applied to one job (?sort=new|fit)
    GET /jobs/{id}/applicants/{application_id}     one application in full: contact details, the resume and letter they sent, their message

Scope: your own jobs only; someone else's job or application answers 404. An applicant chose to send these details to you
for this job, so the contact details appear here and nowhere else. Adding an applicant to the pipeline is your own click
(POST /jobs/{id}/pipeline); nobody is added or moved automatically, and the fit score is a guide that a person decides on.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import require_recruiter
from app.db.models import User
from app.db.recruiter_models import Application, Candidate, Job, PipelineEntry
from app.db.session import get_db
from app.services.timeutil import aware

router = APIRouter(tags=["applicants"])


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


def _db(db: Session | None) -> Session:
    if db is None:
        raise _err(503, "no_database", "The database is not configured.")
    return db


def _iso(dt) -> str | None:
    dt = aware(dt)
    return dt.isoformat() if dt else None


def _job(db: Session, actor: User, job_id: str) -> Job:
    try:
        key = uuid.UUID(str(job_id))
    except ValueError:
        raise _err(404, "not_found", "That job does not exist.")
    job = db.scalars(select(Job).where(Job.id == key, Job.owner_id == actor.id)).first()
    if job is None:
        raise _err(404, "not_found", "That job does not exist.")
    return job


def _row(a: Application, c: Candidate, stage: str | None) -> dict:
    return {
        "id": str(a.id), "candidate_id": str(c.id), "name": c.full_name,
        "headline": " at ".join(x for x in (c.current_title, c.current_company) if x) or None, "location": c.location,
        "years": c.total_experience_years, "skills": list(c.skills or [])[:12], "fit_score": None if a.fit_score is None else int(round(a.fit_score)),
        "resume_label": a.resume_label, "has_letter": bool(a.letter_text), "has_message": bool(a.message), "stage": stage, "applied_at": _iso(a.created_at),
    }


@router.get("/applicants")
def my_jobs(actor: User = Depends(require_recruiter), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    counts = dict(db.execute(
        select(Application.job_id, func.count()).join(Job, Job.id == Application.job_id).where(Job.owner_id == actor.id).group_by(Application.job_id)
    ).all())
    jobs = db.scalars(select(Job).where(Job.owner_id == actor.id, Job.status != "draft").order_by(Job.created_at.desc())).all()
    items = [{"id": str(j.id), "title": j.title, "status": j.status, "applicants": counts.get(j.id, 0)} for j in jobs]
    return {"jobs": items, "total": sum(i["applicants"] for i in items)}


@router.get("/jobs/{job_id}/applicants")
def list_applicants(job_id: str, sort: str = Query(default="new", pattern="^(new|fit)$"), actor: User = Depends(require_recruiter),
                    db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    job = _job(db, actor, job_id)
    stages = dict(db.execute(select(PipelineEntry.candidate_id, PipelineEntry.stage).where(PipelineEntry.job_id == job.id)).all())
    pairs = db.execute(
        select(Application, Candidate).join(Candidate, Candidate.id == Application.candidate_id).where(Application.job_id == job.id)
    ).all()
    rows = [_row(a, c, stages.get(c.id)) for a, c in pairs]
    if sort == "fit":
        rows.sort(key=lambda r: (r["fit_score"] is None, -(r["fit_score"] or 0), r["applied_at"] or ""))
    else:
        rows.sort(key=lambda r: r["applied_at"] or "", reverse=True)
    return {"job": {"id": str(job.id), "title": job.title, "status": job.status}, "applicants": rows, "total": len(rows)}


@router.get("/jobs/{job_id}/applicants/{application_id}")
def get_applicant(job_id: str, application_id: str, actor: User = Depends(require_recruiter), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    job = _job(db, actor, job_id)
    try:
        key = uuid.UUID(str(application_id))
    except ValueError:
        raise _err(404, "not_found", "That application does not exist.")
    a = db.get(Application, key)
    if a is None or a.job_id != job.id:
        raise _err(404, "not_found", "That application does not exist.")
    c = db.get(Candidate, a.candidate_id)
    stage = db.scalar(select(PipelineEntry.stage).where(PipelineEntry.job_id == job.id, PipelineEntry.candidate_id == a.candidate_id))
    return {
        **_row(a, c, stage), "skills": list(c.skills or []), "qualification": c.qualification, "contact": a.contact, "message": a.message,
        "resume_text": a.resume_text, "letter_label": a.letter_label, "letter_text": a.letter_text, "job": {"id": str(job.id), "title": job.title, "status": job.status},
    }
