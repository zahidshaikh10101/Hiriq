"""Candidates: resume upload and the pool a recruiter searches (mounted at /api/recruiter). Every route needs a
signed-in recruiter.

    POST   /candidates          upload ONE resume (the raw file as the request body, name in X-Filename)
    GET    /candidates          the pool: your uploads plus Hiriq members (?q=&source=all|upload|platform)
    GET    /candidates/{id}     one candidate, with the parsed profile
    PUT    /candidates/{id}     correct what the reader got wrong (your own uploads only)
    DELETE /candidates/{id}     remove one of your uploads

Scope: a recruiter sees their own uploads and the Hiriq members who chose to be visible, nobody else's uploads (someone else's id answers 404).
Members' contact details stay hidden for now: a member did not hand their email or phone to every recruiter.
Re-uploading the same file costs nothing: the file hash finds the earlier row and no AI call is made.
"""
from __future__ import annotations

import re
import urllib.parse
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import require_recruiter
from app.db.models import User
from app.db.recruiter_models import AiCall, Candidate, RecruiterEvent
from app.db.session import get_db
from app.services import llm, resume, resume_text
from app.services.timeutil import aware, now

router = APIRouter(tags=["candidates"])

PARSE_PER_HOUR = 40       # successful AI reads per recruiter per hour (failed attempts do not count against you)
MAX_UPLOADS = 300         # resumes one recruiter can keep
SOURCES = ("all", "upload", "platform")


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


def _db(db: Session | None) -> Session:
    if db is None:
        raise _err(503, "no_database", "The database is not configured.")
    return db


def _iso(dt) -> str | None:
    dt = aware(dt)
    return dt.isoformat() if dt else None


# ---------- who may see whom ----------
def _members_visible():
    """Platform candidates count only while their account is active and verified, and only if they chose to be visible."""
    return and_(Candidate.source == "platform", Candidate.visible_to_recruiters.is_(True), User.role == "candidate",
                User.status == "active", User.email_verified.is_(True))


def _sync_members(db: Session) -> None:
    """Every active, verified candidate account gets a candidate row, so they can be listed now and matched later."""
    missing = db.execute(
        select(User.id, User.full_name).outerjoin(Candidate, Candidate.user_id == User.id)
        .where(User.role == "candidate", User.status == "active", User.email_verified.is_(True), Candidate.id.is_(None))
    ).all()
    if not missing:
        return
    for uid, name in missing:
        db.add(Candidate(user_id=uid, source="platform", full_name=(name or "Hiriq member")[:160], skills=[]))
    try:
        db.commit()
    except IntegrityError:  # another request added the same member a moment ago
        db.rollback()


def _find(db: Session, actor: User, candidate_id: str) -> Candidate:
    """The candidate if this recruiter may see it, else 404 (never 403: other people's data does not 'exist')."""
    try:
        key = uuid.UUID(str(candidate_id))
    except ValueError:
        raise _err(404, "not_found", "That candidate does not exist.")
    c = db.get(Candidate, key)
    if c is None:
        raise _err(404, "not_found", "That candidate does not exist.")
    if c.owner_id == actor.id:
        return c
    if c.source == "platform" and c.user_id is not None and c.visible_to_recruiters:
        u = db.get(User, c.user_id)
        if u is not None and u.role == "candidate" and u.status == "active" and u.email_verified:
            return c
    raise _err(404, "not_found", "That candidate does not exist.")


def _own(c: Candidate, actor: User) -> None:
    if c.owner_id != actor.id:
        raise _err(403, "not_yours", "Member profiles belong to the member. You can only edit or remove resumes you uploaded.")


# ---------- output ----------
def _out(c: Candidate, detail: bool = False) -> dict:
    member = c.source == "platform"
    data = {
        "id": str(c.id), "source": c.source, "full_name": c.full_name, "current_title": c.current_title,
        "current_company": c.current_company, "location": c.location, "total_experience_years": c.total_experience_years,
        "qualification": c.qualification, "skills": list(c.skills or []), "is_demo": bool(c.is_demo),
        "created_at": _iso(c.created_at),
    }
    if detail:
        p = c.profile or {}
        data.update({
            "email": None if member else c.email, "phone": None if member else c.phone, "contact_hidden": member,
            "linkedin_url": None if member else c.linkedin_url, "github_url": None if member else c.github_url,
            "portfolio_url": None if member else p.get("portfolio_url"),
            "employers": p.get("employers") or [], "education": p.get("education") or [],
            "certifications": p.get("certifications") or [], "experience_basis": p.get("experience_basis"),
            "parsed_by": p.get("parsed_by"), "file_name": c.file_name, "has_text": bool(c.resume_text),
        })
    return data


# ---------- upload ----------
def _file_name(request: Request) -> str:
    raw = request.headers.get("x-filename", "")
    try:
        return urllib.parse.unquote(raw)[:255]
    except Exception:  # noqa: BLE001
        return raw[:255]


async def _read_body(request: Request) -> bytes:
    """The whole body, refusing to buffer more than one resume's worth."""
    limit = resume_text.MAX_BYTES
    too_big = _err(413, "too_big", f"This file is larger than {limit // (1024 * 1024)} MB.")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise too_big
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise too_big
        chunks.append(chunk)
    return b"".join(chunks)


def _duplicate_email(db: Session, actor: User, c: Candidate) -> dict | None:
    if not c.email:
        return None
    other = db.scalars(
        select(Candidate).where(Candidate.owner_id == actor.id, Candidate.id != c.id, func.lower(Candidate.email) == c.email.lower()).limit(1)
    ).first()
    return {"id": str(other.id), "name": other.full_name} if other else None


def _ingest(db: Session, actor: User, name: str, data: bytes) -> tuple[dict, int]:
    """Runs in a worker thread: it can wait on the AI for a while without freezing the server."""
    digest = resume.file_hash(data)
    existing = db.scalars(select(Candidate).where(Candidate.owner_id == actor.id, Candidate.file_hash == digest)).first()
    if existing:
        return {**_out(existing, True), "already_added": True, "same_email_as": None}, 200

    total = db.scalar(select(func.count()).select_from(Candidate).where(Candidate.owner_id == actor.id)) or 0
    if total >= MAX_UPLOADS:
        raise _err(409, "pool_full", f"You have {MAX_UPLOADS} uploaded resumes. Remove some before adding more.")
    recent = db.scalar(
        select(func.count()).select_from(AiCall)
        .where(AiCall.owner_id == actor.id, AiCall.purpose == "parse", AiCall.ok.is_(True), AiCall.created_at >= now() - timedelta(hours=1))
    ) or 0
    if recent >= PARSE_PER_HOUR:
        raise _err(429, "slow_down", "That is a lot of resumes for one hour. Try again a little later.")

    try:
        fields = resume.parse(name, data, owner_id=actor.id)
    except resume_text.ResumeFileError as exc:
        raise _err(422, exc.code, exc.message)
    except llm.LLMError as exc:
        raise _err(502 if exc.code == "bad_output" else 503, exc.code, exc.message)
    fields.pop("model", None)

    c = Candidate(owner_id=actor.id, source="upload", **fields)
    db.add(c)
    try:
        db.flush()
        db.add(RecruiterEvent(owner_id=actor.id, kind="resume", text=f"You added {c.full_name}'s resume", candidate_id=c.id))
        db.commit()
    except IntegrityError:  # the same file arrived twice at once
        db.rollback()
        existing = db.scalars(select(Candidate).where(Candidate.owner_id == actor.id, Candidate.file_hash == digest)).first()
        if existing:
            return {**_out(existing, True), "already_added": True, "same_email_as": None}, 200
        raise
    return {**_out(c, True), "already_added": False, "same_email_as": _duplicate_email(db, actor, c)}, 201


@router.post("/candidates")
async def upload_resume(request: Request, actor: User = Depends(require_recruiter), db: Session | None = Depends(get_db)):
    db = _db(db)
    data = await _read_body(request)
    name = _file_name(request)
    body, status = await run_in_threadpool(_ingest, db, actor, name, data)
    return JSONResponse(body, status_code=status)


# ---------- the pool ----------
@router.get("/candidates")
def list_candidates(
    q: str | None = Query(default=None, max_length=100), source: str = "all",
    limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
    actor: User = Depends(require_recruiter), db: Session | None = Depends(get_db),
) -> dict:
    db = _db(db)
    if source not in SOURCES:
        raise _err(422, "bad_source", "Source must be all, upload or platform.")
    _sync_members(db)
    pool = db.scalars(
        select(Candidate).outerjoin(User, User.id == Candidate.user_id)
        .where(or_(Candidate.owner_id == actor.id, _members_visible()))
        .order_by(Candidate.created_at.desc(), Candidate.id)
    ).all()
    counts = {"all": len(pool), "upload": sum(1 for c in pool if c.source == "upload"), "platform": sum(1 for c in pool if c.source == "platform")}
    shown = [c for c in pool if source == "all" or c.source == source]
    words = [w for w in re.split(r"\s+", (q or "").lower().strip()) if w]
    if words:
        def hay(c: Candidate) -> str:
            return " ".join([c.full_name or "", c.current_title or "", c.current_company or "", c.location or "", c.qualification or "", " ".join(c.skills or [])]).lower()
        shown = [c for c in shown if all(w in hay(c) for w in words)]
    page = shown[offset:offset + limit]
    return {"counts": counts, "total": len(shown), "candidates": [_out(c) for c in page]}


@router.get("/candidates/{candidate_id}")
def get_candidate(candidate_id: str, actor: User = Depends(require_recruiter), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    c = _find(db, actor, candidate_id)
    if c.source != "platform" and c.resume_text and "portfolio_url" not in (c.profile or {}):
        # resumes read before this field existed: look once in the saved text (no AI involved), and remember the answer
        c.profile = {**(c.profile or {}), "portfolio_url": resume.find_portfolio(c.resume_text)}
        db.commit()
        db.refresh(c)
    return _out(c, True)


# ---------- editing ----------
class CandidateIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=30)
    location: str | None = Field(default=None, max_length=160)
    linkedin_url: str | None = Field(default=None, max_length=300)
    github_url: str | None = Field(default=None, max_length=300)
    portfolio_url: str | None = Field(default=None, max_length=300)
    current_title: str | None = Field(default=None, max_length=160)
    current_company: str | None = Field(default=None, max_length=160)
    total_experience_years: float | None = Field(default=None, ge=0, le=60)
    qualification: str | None = Field(default=None, max_length=200)
    skills: list[str] = Field(default_factory=list)

    @field_validator("full_name", mode="before")
    @classmethod
    def _name(cls, v):
        return " ".join(str(v).split()) if v is not None else v

    @field_validator("email", "phone", "location", "linkedin_url", "github_url", "portfolio_url", "current_title", "current_company", "qualification", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if v is None:
            return None
        v = " ".join(str(v).split())
        return v or None

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        if v is not None and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]{2,}", v):
            raise ValueError("That email address does not look right.")
        return v.lower() if v else v

    @field_validator("linkedin_url")
    @classmethod
    def _linkedin(cls, v):
        if v is not None and not re.match(r"https?://([\w-]+\.)*linkedin\.com/", v, re.I):
            raise ValueError("The LinkedIn link should be a web address that starts with https:// and points to linkedin.com.")
        return v

    @field_validator("github_url")
    @classmethod
    def _github(cls, v):
        if v is not None and not re.match(r"https?://([\w-]+\.)*github\.com/", v, re.I):
            raise ValueError("The GitHub link should be a web address that starts with https:// and points to github.com.")
        return v

    @field_validator("portfolio_url")
    @classmethod
    def _portfolio(cls, v):
        if v is None:
            return v
        if not re.match(r"https?://[^\s/]+\.[^\s/]{2,}", v, re.I) or re.search(r"\s", v):
            raise ValueError("The website should be a web address that starts with https://, for example https://yourname.dev.")
        return v

    @field_validator("skills")
    @classmethod
    def _skills(cls, v):
        return resume.clean_skills(v)


@router.put("/candidates/{candidate_id}")
def update_candidate(candidate_id: str, body: CandidateIn, actor: User = Depends(require_recruiter), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    c = _find(db, actor, candidate_id)
    _own(c, actor)
    years_changed = body.total_experience_years != c.total_experience_years
    fields = body.model_dump()
    portfolio = fields.pop("portfolio_url")
    keep_portfolio = "portfolio_url" not in body.model_fields_set      # a caller that never mentions it must not wipe it
    for key, value in fields.items():
        setattr(c, key, value)
    profile = dict(c.profile or {})
    if not keep_portfolio:
        profile["portfolio_url"] = portfolio
    if years_changed:
        profile["experience_basis"] = "edited"  # no longer computed from the job dates
    c.profile = profile
    db.commit()
    db.refresh(c)
    return _out(c, True)


@router.delete("/candidates/{candidate_id}")
def delete_candidate(candidate_id: str, actor: User = Depends(require_recruiter), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    c = _find(db, actor, candidate_id)
    _own(c, actor)
    name = c.full_name
    db.delete(c)
    db.add(RecruiterEvent(owner_id=actor.id, kind="resume", text=f"You removed {name}'s resume"))
    db.commit()
    return {"ok": True}
