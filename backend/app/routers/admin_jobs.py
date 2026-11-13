"""Admin jobs and sources (mounted at /api/admin). Every route needs a signed-in admin.

Two kinds of job live side by side here:
 - "portal"  jobs: posted on Hiriq by a recruiter (the `jobs` table). An admin can create one for any recruiter,
                   edit it, open or close it, and delete it (deleting also removes its matches and pipeline entries).
 - "outside" jobs: public posts collected from the outside feed, or added by hand (the `external_jobs` table).

    GET    /jobs?source=all|portal|outside&status=&q=      one list of both, with counts
    GET    /jobs/{source}/{id}                             one job, in full, for the edit form
    POST   /jobs/portal            PUT /jobs/portal/{id}            DELETE /jobs/portal/{id}
    POST   /jobs/outside           PUT /jobs/outside/{id}           DELETE /jobs/outside/{id}

Every change is written to the audit log (category Data).
"""
from __future__ import annotations

import uuid
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.db.models import User
from app.db.recruiter_models import ExternalJob, Job
from app.db.session import get_db
from app.routers.jobs import FIELDS, MIN_JD_CHARS, JobIn
from app.services import audit, jobkeys
from app.services.timeutil import aware, now

router = APIRouter(tags=["admin"])


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


def _db(db: Session | None) -> Session:
    if db is None:
        raise _err(503, "no_database", "The database is not configured.")
    return db


def _iso(dt) -> str | None:
    dt = aware(dt)
    return dt.isoformat() if dt else None


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise _err(404, "not_found", "That job no longer exists.")


def _label(u: User) -> str:
    return u.username or u.full_name


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# ---------------- request bodies ----------------
class PortalJobIn(JobIn):
    status: Literal["draft", "open", "closed"] = "draft"
    owner_id: uuid.UUID | None = None          # the recruiter it belongs to; blank means the admin who creates it


class OutsideJobIn(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    company: str | None = Field(default=None, max_length=160)
    location: str | None = Field(default=None, max_length=160)
    remote: bool = False
    apply_url: str | None = Field(default=None, max_length=600)
    description: str = Field(default="", max_length=6000)

    @field_validator("title", "company", "location", "apply_url", mode="before")
    @classmethod
    def _tidy(cls, v):
        if v is None:
            return None
        v = " ".join(str(v).split())
        return v or None

    @field_validator("apply_url")
    @classmethod
    def _url(cls, v):
        if v is None:
            return None
        p = urlparse(v)
        if p.scheme not in ("http", "https") or not p.netloc:
            raise ValueError("The apply link must start with http:// or https://")
        return v


# ---------------- rows ----------------
def _owner_names(db: Session, ids: set) -> dict:
    if not ids:
        return {}
    return {u.id: u for u in db.scalars(select(User).where(User.id.in_(list(ids)))).all()}


def _portal_row(j: Job, owner: User | None) -> dict:
    return {
        "id": str(j.id), "source": "portal", "title": j.title, "company": (owner.company if owner else None) or j.department,
        "location": j.location, "status": j.status, "work_mode": j.work_mode, "employment_type": j.employment_type,
        "owner": _label(owner) if owner else "Deleted account", "owner_id": str(j.owner_id), "provider": "Hiriq",
        "apply_url": None, "is_demo": bool(j.is_demo), "created_at": _iso(j.created_at), "updated_at": _iso(j.updated_at or j.created_at),
    }


def _outside_row(j: ExternalJob) -> dict:
    return {
        "id": str(j.id), "source": "outside", "title": j.title, "company": j.company, "location": j.location, "status": None,
        "work_mode": "remote" if j.remote else None, "employment_type": None, "owner": None, "owner_id": None,
        "provider": "Added by hand" if j.provider == "manual" else j.provider.title(), "apply_url": j.apply_url, "is_demo": False,
        "created_at": _iso(j.first_seen_at), "updated_at": _iso(j.last_seen_at),
    }


def _portal_detail(j: Job, owner: User | None) -> dict:
    data = _portal_row(j, owner)
    for f in FIELDS:
        data[f] = list(getattr(j, f) or []) if f in ("skills_required", "skills_nice") else getattr(j, f)
    return data


def _outside_detail(j: ExternalJob) -> dict:
    return {**_outside_row(j), "remote": bool(j.remote), "description": j.description or ""}


# ---------------- list ----------------
@router.get("/jobs")
def list_jobs(source: Literal["all", "portal", "outside"] = "all", status: Literal["all", "draft", "open", "closed"] = "all",
              q: str = Query("", max_length=100), limit: int = Query(300, ge=1, le=1000),
              actor: User = Depends(require_admin), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    needle = f"%{q.strip().lower()}%" if q.strip() else None
    rows: list[dict] = []

    if source in ("all", "portal"):
        stmt = select(Job).order_by(Job.created_at.desc())
        if status != "all":
            stmt = stmt.where(Job.status == status)
        if needle:
            stmt = stmt.where(or_(func.lower(Job.title).like(needle), func.lower(func.coalesce(Job.location, "")).like(needle),
                                  func.lower(func.coalesce(Job.department, "")).like(needle)))
        jobs = db.scalars(stmt.limit(limit)).all()
        owners = _owner_names(db, {j.owner_id for j in jobs})
        rows += [_portal_row(j, owners.get(j.owner_id)) for j in jobs]

    if source in ("all", "outside") and status == "all":       # outside posts have no draft/open/closed state
        stmt = select(ExternalJob).order_by(ExternalJob.last_seen_at.desc())
        if needle:
            stmt = stmt.where(or_(func.lower(ExternalJob.title).like(needle), func.lower(func.coalesce(ExternalJob.company, "")).like(needle),
                                  func.lower(func.coalesce(ExternalJob.location, "")).like(needle)))
        rows += [_outside_row(j) for j in db.scalars(stmt.limit(limit)).all()]

    rows.sort(key=lambda r: r["updated_at"] or "", reverse=True)

    by_status = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    by_provider = dict(db.execute(select(ExternalJob.provider, func.count()).group_by(ExternalJob.provider)).all())
    last_seen = db.scalar(select(func.max(ExternalJob.last_seen_at)))
    owners = db.scalars(select(User).where(User.role.in_(("recruiter", "admin")), User.status == "active").order_by(User.full_name)).all()
    return {
        "jobs": rows[:limit],
        "summary": {
            "portal": {"total": sum(by_status.values()), "open": by_status.get("open", 0), "draft": by_status.get("draft", 0), "closed": by_status.get("closed", 0)},
            "outside": {"total": sum(by_provider.values()), "last_fetched": _iso(last_seen),
                        "sources": [{"name": "Added by hand" if k == "manual" else k.title(), "count": v} for k, v in sorted(by_provider.items())]},
        },
        "owners": [{"id": str(u.id), "name": _label(u), "email": u.email, "role": u.role} for u in owners],
        "me": str(actor.id),
    }


@router.get("/jobs/{source}/{job_id}")
def get_job(source: Literal["portal", "outside"], job_id: str, actor: User = Depends(require_admin),
            db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    if source == "portal":
        j = db.get(Job, _uuid(job_id))
        if j is None:
            raise _err(404, "not_found", "That job no longer exists.")
        return _portal_detail(j, db.get(User, j.owner_id))
    e = db.get(ExternalJob, _uuid(job_id))
    if e is None:
        raise _err(404, "not_found", "That job no longer exists.")
    return _outside_detail(e)


# ---------------- portal jobs ----------------
def _apply_portal(job: Job, body: PortalJobIn) -> None:
    for f in FIELDS:
        setattr(job, f, getattr(body, f))
    if body.status == "open":
        if len((job.description or "").strip()) < MIN_JD_CHARS:
            raise _err(422, "need_description", "Write the job description (at least a few sentences) before opening the job.")
        if not (job.skills_required or []):
            raise _err(422, "need_skills", "Add at least one required skill so candidates can be matched to this job.")
    if body.status != job.status:
        if body.status == "open":
            job.opened_at, job.closed_at = now(), None
        elif body.status == "closed":
            job.closed_at = now()
        elif body.status == "draft":
            job.opened_at = job.closed_at = None
        job.status = body.status


def _owner_for(db: Session, actor: User, owner_id: uuid.UUID | None) -> User:
    if owner_id is None:
        return actor
    owner = db.get(User, owner_id)
    if owner is None or owner.role not in ("recruiter", "admin"):
        raise _err(422, "bad_owner", "A job can only belong to a recruiter or an admin.")
    return owner


@router.post("/jobs/portal", status_code=201)
def create_portal_job(body: PortalJobIn, request: Request, actor: User = Depends(require_admin),
                      db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    owner = _owner_for(db, actor, body.owner_id)
    job = Job(owner_id=owner.id, title=body.title, status="draft")
    _apply_portal(job, body)
    db.add(job)
    audit.record(db, "Data", f"created the job {job.title} for {_label(owner)}", actor_id=actor.id, actor_label=_label(actor), ip=_ip(request))
    db.commit()
    db.refresh(job)
    return _portal_detail(job, owner)


@router.put("/jobs/portal/{job_id}")
def update_portal_job(job_id: str, body: PortalJobIn, request: Request, actor: User = Depends(require_admin),
                      db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    job = db.get(Job, _uuid(job_id))
    if job is None:
        raise _err(404, "not_found", "That job no longer exists.")
    if body.owner_id is not None and body.owner_id != job.owner_id:
        job.owner_id = _owner_for(db, actor, body.owner_id).id
    old_status = job.status
    _apply_portal(job, body)
    said = f"edited the job {job.title}" if old_status == job.status else f"edited the job {job.title} and set it from {old_status} to {job.status}"
    audit.record(db, "Data", said, actor_id=actor.id, actor_label=_label(actor), ip=_ip(request))
    db.commit()
    db.refresh(job)
    return _portal_detail(job, db.get(User, job.owner_id))


@router.delete("/jobs/portal/{job_id}")
def delete_portal_job(job_id: str, request: Request, actor: User = Depends(require_admin),
                      db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    job = db.get(Job, _uuid(job_id))
    if job is None:
        raise _err(404, "not_found", "That job no longer exists.")
    title = job.title
    db.delete(job)
    audit.record(db, "Data", f"deleted the job {title}", actor_id=actor.id, actor_label=_label(actor), ip=_ip(request))
    db.commit()
    return {"status": "deleted"}


# ---------------- outside jobs ----------------
def _set_keys(db: Session, job: ExternalJob) -> None:
    """Fill the duplicate-detection keys. An apply link already in the library cannot be added a second time."""
    akey = jobkeys.apply_key(job.apply_url)
    if akey:
        clash = db.scalars(select(ExternalJob).where(ExternalJob.apply_key == akey)).first()
        if clash is not None and clash.id != job.id:
            raise _err(409, "duplicate", f"That apply link is already in the library (as {clash.title}).")
    job.apply_key = akey
    job.dedupe_key = jobkeys.dedupe_key(job.title, job.company, job.location)


@router.post("/jobs/outside", status_code=201)
def create_outside_job(body: OutsideJobIn, request: Request, actor: User = Depends(require_admin),
                       db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    job = ExternalJob(provider="manual", external_id=f"manual-{uuid.uuid4()}", title=body.title, company=body.company,
                      location=body.location, remote=body.remote, apply_url=body.apply_url, description=body.description,
                      read={}, last_query=None)
    _set_keys(db, job)
    db.add(job)
    audit.record(db, "Data", f"added the outside job {job.title}", actor_id=actor.id, actor_label=_label(actor), ip=_ip(request))
    db.commit()
    db.refresh(job)
    return _outside_detail(job)


@router.put("/jobs/outside/{job_id}")
def update_outside_job(job_id: str, body: OutsideJobIn, request: Request, actor: User = Depends(require_admin),
                       db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    job = db.get(ExternalJob, _uuid(job_id))
    if job is None:
        raise _err(404, "not_found", "That job no longer exists.")
    job.title, job.company, job.location = body.title, body.company, body.location
    job.remote, job.apply_url, job.description = body.remote, body.apply_url, body.description
    _set_keys(db, job)
    job.read = {}                                  # the reader's notes belong to the old text; they are rebuilt when needed
    audit.record(db, "Data", f"edited the outside job {job.title}", actor_id=actor.id, actor_label=_label(actor), ip=_ip(request))
    db.commit()
    db.refresh(job)
    return _outside_detail(job)


@router.delete("/jobs/outside/{job_id}")
def delete_outside_job(job_id: str, request: Request, actor: User = Depends(require_admin),
                       db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    job = db.get(ExternalJob, _uuid(job_id))
    if job is None:
        raise _err(404, "not_found", "That job no longer exists.")
    title = job.title
    db.delete(job)
    audit.record(db, "Data", f"deleted the outside job {title}", actor_id=actor.id, actor_label=_label(actor), ip=_ip(request))
    db.commit()
    return {"status": "deleted"}
