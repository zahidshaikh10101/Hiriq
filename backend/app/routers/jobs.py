"""Jobs and the JD writer (mounted at /api/recruiter). Every route needs a signed-in recruiter, and a recruiter
only ever touches their own jobs: someone else's job id answers 404, as if it did not exist.

    GET    /jobs                  list (filter with ?status=open|draft|closed)
    POST   /jobs                  create a draft
    POST   /jobs/generate         write a JD from the form (nothing is saved)
    GET    /jobs/{id}             one job
    PUT    /jobs/{id}             edit (not while closed)
    POST   /jobs/{id}/publish     open a draft, or reopen a closed job
    POST   /jobs/{id}/close       close an open job
    POST   /jobs/{id}/clone       copy into a new draft
    DELETE /jobs/{id}             delete a draft (jobs that were open keep their history: close them instead)
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import require_recruiter
from app.db.models import User
from app.db.recruiter_models import AiCall, Job, JobMatch, PipelineEntry, RecruiterEvent
from app.db.session import get_db
from app.services import jd, llm
from app.services.timeutil import aware, now

router = APIRouter(tags=["jobs"])

WORK_MODES = ("onsite", "hybrid", "remote")
EMPLOYMENT_TYPES = ("full-time", "part-time", "contract", "internship")
CURRENCIES = ("INR", "USD", "EUR", "GBP")
GENERATE_PER_HOUR = 30
MIN_JD_CHARS = 80


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


def _db(db: Session | None) -> Session:
    if db is None:
        raise _err(503, "no_database", "The database is not configured.")
    return db


def _iso(dt) -> str | None:
    dt = aware(dt)
    return dt.isoformat() if dt else None


# ---------- request body ----------
def _clean_skills(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        skill = " ".join(str(raw).split())
        key = skill.lower()
        if skill and key not in seen:
            seen.add(key)
            out.append(skill[:60])
    return out[:30]


class JobIn(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    department: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=120)
    work_mode: str | None = None
    employment_type: str | None = None
    experience_min: int | None = Field(default=None, ge=0, le=50)
    experience_max: int | None = Field(default=None, ge=0, le=50)
    qualification: str | None = Field(default=None, max_length=200)
    salary_min: int | None = Field(default=None, ge=0, le=10_000_000_000)
    salary_max: int | None = Field(default=None, ge=0, le=10_000_000_000)
    salary_currency: str = "INR"
    skills_required: list[str] = Field(default_factory=list)
    skills_nice: list[str] = Field(default_factory=list)
    responsibilities: str | None = Field(default=None, max_length=3000)
    description: str | None = Field(default=None, max_length=20000)

    @field_validator("title", mode="before")
    @classmethod
    def _title(cls, v):
        return " ".join(str(v).split()) if v is not None else v

    @field_validator("department", "location", "qualification", "responsibilities", "description", "work_mode", "employment_type", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if v is None:
            return None
        v = str(v).strip()
        return v or None

    @field_validator("work_mode")
    @classmethod
    def _work_mode(cls, v):
        if v is not None and v not in WORK_MODES:
            raise ValueError("Work mode must be onsite, hybrid or remote.")
        return v

    @field_validator("employment_type")
    @classmethod
    def _employment(cls, v):
        if v is not None and v not in EMPLOYMENT_TYPES:
            raise ValueError("Employment type must be full-time, part-time, contract or internship.")
        return v

    @field_validator("salary_currency", mode="before")
    @classmethod
    def _currency(cls, v):
        v = str(v or "INR").strip().upper()
        if v not in CURRENCIES:
            raise ValueError("Currency must be one of " + ", ".join(CURRENCIES) + ".")
        return v

    @field_validator("skills_required", "skills_nice")
    @classmethod
    def _skills(cls, v):
        return _clean_skills(v)

    @model_validator(mode="after")
    def _ranges(self):
        if self.experience_min is not None and self.experience_max is not None and self.experience_min > self.experience_max:
            raise ValueError("Minimum experience cannot be more than the maximum.")
        if self.salary_min is not None and self.salary_max is not None and self.salary_min > self.salary_max:
            raise ValueError("Minimum salary cannot be more than the maximum.")
        required = {s.lower() for s in self.skills_required}
        self.skills_nice = [s for s in self.skills_nice if s.lower() not in required]  # a skill is one or the other
        return self


# ---------- output ----------
FIELDS = (
    "title", "department", "location", "work_mode", "employment_type", "experience_min", "experience_max", "qualification",
    "salary_min", "salary_max", "salary_currency", "skills_required", "skills_nice", "responsibilities", "description",
)


def _out(j: Job, matched: int = 0, in_pipeline: int = 0, detail: bool = True) -> dict:
    data = {
        "id": str(j.id), "title": j.title, "status": j.status, "location": j.location, "work_mode": j.work_mode,
        "experience_min": j.experience_min, "experience_max": j.experience_max, "is_demo": bool(j.is_demo),
        "skills_required": list(j.skills_required or []), "matched": matched, "in_pipeline": in_pipeline,
        "opened_at": _iso(j.opened_at), "closed_at": _iso(j.closed_at), "created_at": _iso(j.created_at),
        "updated_at": _iso(j.updated_at or j.created_at),
    }
    if detail:
        for f in FIELDS:
            data[f] = list(getattr(j, f) or []) if f in ("skills_required", "skills_nice") else getattr(j, f)
        data["has_description"] = bool((j.description or "").strip())
        data["wording_flags"] = jd.check_wording(j.description)
    return data


def _counts(db: Session, job_ids: list) -> tuple[dict, dict]:
    if not job_ids:
        return {}, {}
    matched = dict(db.execute(select(JobMatch.job_id, func.count()).where(JobMatch.job_id.in_(job_ids)).group_by(JobMatch.job_id)).all())
    pipe = dict(db.execute(select(PipelineEntry.job_id, func.count()).where(PipelineEntry.job_id.in_(job_ids)).group_by(PipelineEntry.job_id)).all())
    return matched, pipe


def _mine(db: Session, actor: User, job_id: str) -> Job:
    try:
        key = uuid.UUID(str(job_id))
    except ValueError:
        raise _err(404, "not_found", "That job does not exist.")
    job = db.get(Job, key)
    if job is None or job.owner_id != actor.id:
        raise _err(404, "not_found", "That job does not exist.")
    return job


def _event(db: Session, actor: User, text: str, job: Job | None = None) -> None:
    db.add(RecruiterEvent(owner_id=actor.id, kind="job", text=text, job_id=job.id if job else None))


# ---------- routes ----------
@router.get("/jobs")
def list_jobs(status: str | None = None, actor: User = Depends(require_recruiter), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    if status is not None and status not in ("draft", "open", "closed"):
        raise _err(422, "bad_status", "Status must be draft, open or closed.")
    jobs = db.scalars(select(Job).where(Job.owner_id == actor.id)).all()
    counts = {"all": len(jobs), "open": 0, "draft": 0, "closed": 0}
    for j in jobs:
        counts[j.status] += 1
    shown = [j for j in jobs if status is None or j.status == status]
    shown.sort(key=lambda j: aware(j.updated_at or j.created_at), reverse=True)
    matched, pipe = _counts(db, [j.id for j in shown])
    return {"counts": counts, "jobs": [_out(j, matched.get(j.id, 0), pipe.get(j.id, 0), detail=False) for j in shown]}


@router.post("/jobs", status_code=201)
def create_job(body: JobIn, actor: User = Depends(require_recruiter), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    job = Job(owner_id=actor.id, status="draft", **body.model_dump())
    db.add(job)
    db.flush()
    _event(db, actor, f"You created the job {job.title}", job)
    db.commit()
    db.refresh(job)
    return _out(job)


@router.post("/jobs/generate")
def generate_jd(body: JobIn, actor: User = Depends(require_recruiter), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    if not body.skills_required and not body.responsibilities:
        raise _err(422, "need_details", "Add at least one required skill or a few lines about the day-to-day work, so the JD has something real to say.")
    since = now() - timedelta(hours=1)
    recent = db.scalar(select(func.count()).select_from(AiCall).where(AiCall.owner_id == actor.id, AiCall.purpose == "jd", AiCall.ok.is_(True), AiCall.created_at >= since)) or 0
    if recent >= GENERATE_PER_HOUR:
        raise _err(429, "slow_down", "That is a lot of rewrites for one hour. Edit the text by hand or try again later.")
    try:
        out = jd.generate(body.model_dump(), owner_id=actor.id)
    except llm.LLMError as exc:
        raise _err(502 if exc.code == "bad_output" else 503, exc.code, exc.message)
    out["wording_flags"] = jd.check_wording(out["description"])
    return out


@router.get("/jobs/{job_id}")
def get_job(job_id: str, actor: User = Depends(require_recruiter), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    job = _mine(db, actor, job_id)
    matched, pipe = _counts(db, [job.id])
    return _out(job, matched.get(job.id, 0), pipe.get(job.id, 0))


@router.put("/jobs/{job_id}")
def update_job(job_id: str, body: JobIn, actor: User = Depends(require_recruiter), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    job = _mine(db, actor, job_id)
    if job.status == "closed":
        raise _err(409, "closed", "This job is closed. Reopen it to edit it.")
    values = body.model_dump()
    if "description" not in body.model_fields_set:
        values.pop("description")  # not sent: keep the text that is saved
    for key, value in values.items():
        setattr(job, key, value)
    db.commit()
    db.refresh(job)
    matched, pipe = _counts(db, [job.id])
    return _out(job, matched.get(job.id, 0), pipe.get(job.id, 0))


@router.post("/jobs/{job_id}/publish")
def publish_job(job_id: str, actor: User = Depends(require_recruiter), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    job = _mine(db, actor, job_id)
    if job.status == "open":
        return _out(job)  # already open: nothing to do
    if len((job.description or "").strip()) < MIN_JD_CHARS:
        raise _err(422, "need_description", "Write or generate the job description before opening the job.")
    if not (job.skills_required or []):
        raise _err(422, "need_skills", "Add at least one required skill so candidates can be matched to this job.")
    reopened = job.status == "closed"
    job.status, job.opened_at, job.closed_at = "open", now(), None
    _event(db, actor, f"You {'reopened' if reopened else 'opened'} the job {job.title}", job)
    db.commit()
    db.refresh(job)
    return _out(job)


@router.post("/jobs/{job_id}/close")
def close_job(job_id: str, actor: User = Depends(require_recruiter), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    job = _mine(db, actor, job_id)
    if job.status == "closed":
        return _out(job)
    if job.status == "draft":
        raise _err(409, "not_open", "Only open jobs can be closed. Delete the draft instead.")
    job.status, job.closed_at = "closed", now()
    _event(db, actor, f"You closed the job {job.title}", job)
    db.commit()
    db.refresh(job)
    return _out(job)


@router.post("/jobs/{job_id}/clone", status_code=201)
def clone_job(job_id: str, actor: User = Depends(require_recruiter), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    src = _mine(db, actor, job_id)
    copy = Job(owner_id=actor.id, status="draft", **{f: (list(getattr(src, f) or []) if f in ("skills_required", "skills_nice") else getattr(src, f)) for f in FIELDS})
    copy.title = f"{src.title} (copy)"[:160]
    db.add(copy)
    db.flush()
    _event(db, actor, f"You copied {src.title} into a new draft", copy)
    db.commit()
    db.refresh(copy)
    return _out(copy)


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str, actor: User = Depends(require_recruiter), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    job = _mine(db, actor, job_id)
    if job.status != "draft":
        raise _err(409, "not_draft", "Only drafts can be deleted. Close this job instead so its history is kept.")
    title = job.title
    db.delete(job)
    _event(db, actor, f"You deleted the draft {title}")
    db.commit()
    return {"ok": True}
