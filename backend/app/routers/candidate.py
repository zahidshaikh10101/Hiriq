"""Candidate workspace (mounted at /api/candidate). Every route needs a signed-in candidate.

    GET    /me                 your profile, the resume state and whether recruiters can see you
    POST   /resume             upload ONE resume (the raw file as the request body, name in X-Filename); the AI reads it
    PUT    /profile            correct what the reader got wrong, or fill the profile by hand
    DELETE /resume             remove your resume and profile details (hides you from recruiters and withdraws your applications)
    PUT    /visibility         {visible: true|false}: let recruiters find you, or not (default: not)
    GET    /insights           profile completeness, skills with evidence, experience, and the skills open jobs ask for
    GET    /jobs               open jobs, with your fit when you have scored one (?q=&limit=&offset=)
    GET    /jobs/{id}          one open job, with your full match if you have one
    POST   /jobs/match         score every open job against your profile (instant, rules only)
    POST   /jobs/{id}/match    score one open job, with skill gaps and evidence
    POST   /match/paste        {text}: score a job description you paste (one AI call reads it; nothing is stored)

Your profile is the same candidate row recruiters see, but a recruiter finds it only while you have switched
"visible to recruiters" on, and never sees your email, phone or links. Scores here use the standard weights without location (skills 42, qualification 21,
experience 32, keywords 5), so where you live never changes your fit.
Nothing here ever scores your name, gender, photo, college or age, and no step contacts a recruiter for you.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import require_candidate
from app.db.models import User
from app.db.recruiter_models import AiCall, Application, Candidate, CandidateJobMatch, Job
from app.db.session import get_db
from app.routers.candidates import CandidateIn
from app.routers.matches import _cand_sig, _cand_view, _job_view

# The standard weights with location switched off (same proportions, re-spread to 100).
CANDIDATE_WEIGHTS = {"skills": 42, "qualification": 21, "experience": 32, "location": 0, "keywords": 5}
from app.services import jobread, llm, matching, resume, resume_text
from app.services.timeutil import aware, now

router = APIRouter(tags=["candidate"])

PARSE_PER_HOUR = 10        # successful AI resume reads per candidate per hour
PASTE_PER_HOUR = 15        # successful AI readings of a pasted job description per candidate per hour
MAX_JOBS = 200             # open jobs looked at in one request
MIN_PASTE_CHARS = 200
MAX_PASTE_CHARS = 12_000
NOT_SCORED = ["name", "gender", "photo", "college", "age"]


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


def _db(db: Session | None) -> Session:
    if db is None:
        raise _err(503, "no_database", "The database is not configured.")
    return db


def _iso(dt) -> str | None:
    dt = aware(dt)
    return dt.isoformat() if dt else None


# ---------------------------------------------------------------- your candidate row
def _ensure(db: Session, user: User) -> Candidate:
    """The candidate row of this account (one per account). Made on first use, already hidden from recruiters."""
    c = db.scalars(select(Candidate).where(Candidate.user_id == user.id)).first()
    if c is not None:
        return c
    c = Candidate(user_id=user.id, source="platform", full_name=(user.full_name or "Hiriq member")[:160], skills=[],
                  visible_to_recruiters=False)
    db.add(c)
    try:
        db.commit()
    except IntegrityError:  # another request made it a moment ago
        db.rollback()
        c = db.scalars(select(Candidate).where(Candidate.user_id == user.id)).first()
        if c is None:
            raise
    return c


def _matchable(c: Candidate) -> bool:
    return bool(c.skills) or bool(c.resume_text)


def _mine(c: Candidate, user: User) -> dict:
    p = c.profile or {}
    return {
        "id": str(c.id), "full_name": c.full_name, "email": c.email or user.email, "phone": c.phone or user.phone_e164,
        "location": c.location, "current_title": c.current_title, "current_company": c.current_company,
        "total_experience_years": c.total_experience_years, "qualification": c.qualification, "skills": list(c.skills or []),
        "linkedin_url": c.linkedin_url, "github_url": c.github_url, "portfolio_url": p.get("portfolio_url"),
        "employers": p.get("employers") or [], "education": p.get("education") or [], "certifications": p.get("certifications") or [],
        "experience_basis": p.get("experience_basis"), "parsed_by": p.get("parsed_by"), "file_name": c.file_name,
        "has_resume": bool(c.resume_text), "has_profile": _matchable(c), "visible_to_recruiters": bool(c.visible_to_recruiters),
        "not_scored": NOT_SCORED,
    }


# ---------------------------------------------------------------- profile
@router.get("/me")
def me(actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    return _mine(_ensure(db, actor), actor)


def _file_name(request: Request) -> str:
    raw = request.headers.get("x-filename", "")
    try:
        return urllib.parse.unquote(raw)[:255]
    except Exception:  # noqa: BLE001
        return raw[:255]


async def _read_body(request: Request) -> bytes:
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


def _recent_ai(db: Session, user: User, purpose: str) -> int:
    return db.scalar(
        select(func.count()).select_from(AiCall)
        .where(AiCall.owner_id == user.id, AiCall.purpose == purpose, AiCall.ok.is_(True), AiCall.created_at >= now() - timedelta(hours=1))
    ) or 0


def _ingest(db: Session, user: User, name: str, data: bytes) -> tuple[dict, int]:
    """Runs in a worker thread: it can wait on the AI for a while without freezing the server."""
    c = _ensure(db, user)
    digest = resume.file_hash(data)
    if c.file_hash == digest and c.resume_text:
        return {**_mine(c, user), "already_added": True}, 200
    if _recent_ai(db, user, "parse") >= PARSE_PER_HOUR:
        raise _err(429, "slow_down", "That is a lot of resume uploads for one hour. Try again a little later.")
    try:
        fields = resume.parse(name, data, owner_id=user.id)
    except resume_text.ResumeFileError as exc:
        raise _err(422, exc.code, exc.message)
    except llm.LLMError as exc:
        raise _err(502 if exc.code == "bad_output" else 503, exc.code, exc.message)
    fields.pop("model", None)
    fields.pop("full_name", None)      # your account name stays; you can change it in the profile
    for key, value in fields.items():
        setattr(c, key, value)
    c.email = fields.get("email") or c.email
    db.commit()
    db.refresh(c)
    return {**_mine(c, user), "already_added": False}, 201


@router.post("/resume")
async def upload_resume(request: Request, actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)):
    db = _db(db)
    data = await _read_body(request)
    name = _file_name(request)
    body, status = await run_in_threadpool(_ingest, db, actor, name, data)
    return JSONResponse(body, status_code=status)


@router.put("/profile")
def update_profile(body: CandidateIn, actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    years_changed = body.total_experience_years != c.total_experience_years
    fields = body.model_dump()
    portfolio = fields.pop("portfolio_url")
    keep_portfolio = "portfolio_url" not in body.model_fields_set
    for key, value in fields.items():
        setattr(c, key, value)
    profile = dict(c.profile or {})
    if not keep_portfolio:
        profile["portfolio_url"] = portfolio
    if years_changed:
        profile["experience_basis"] = "edited"
    c.profile = profile
    if not _matchable(c):
        c.visible_to_recruiters = False        # nothing to show: never visible with an empty profile
    db.commit()
    db.refresh(c)
    return _mine(c, actor)


@router.delete("/resume")
def delete_resume(actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    for col in ("email", "phone", "location", "linkedin_url", "github_url", "current_title", "current_company",
                "total_experience_years", "qualification", "resume_text", "file_name", "file_hash", "profile"):
        setattr(c, col, None)
    c.skills = []
    c.visible_to_recruiters = False
    for row in db.scalars(select(CandidateJobMatch).where(CandidateJobMatch.candidate_id == c.id)).all():
        db.delete(row)
    for row in db.scalars(select(Application).where(Application.candidate_id == c.id)).all():
        db.delete(row)                 # your details leave with your resume: recruiters lose the copy you sent them
    db.commit()
    return _mine(c, actor)


class VisibilityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visible: bool


@router.put("/visibility")
def set_visibility(body: VisibilityIn, actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    if body.visible and not _matchable(c):
        raise _err(409, "no_profile", "Add your resume or some skills first, so recruiters have something to see.")
    c.visible_to_recruiters = body.visible
    db.commit()
    return _mine(c, actor)


# ---------------------------------------------------------------- jobs (what a candidate may see of a recruiter's job)
def _open_jobs(db: Session) -> list[tuple[Job, User | None]]:
    rows = db.execute(
        select(Job, User).outerjoin(User, User.id == Job.owner_id).where(Job.status == "open")
        .order_by(Job.opened_at.desc().nulls_last(), Job.created_at.desc()).limit(MAX_JOBS)
    ).all()
    return [(j, u) for j, u in rows]


def _public_job(job: Job, owner: User | None, detail: bool = False) -> dict:
    """Only what a job post shows. Nothing about the recruiter's pool, pipeline, notes or other candidates."""
    data = {
        "id": str(job.id), "title": job.title, "company": (owner.company if owner else None) or None, "department": job.department,
        "location": job.location, "work_mode": job.work_mode, "employment_type": job.employment_type,
        "experience_min": job.experience_min, "experience_max": job.experience_max, "qualification": job.qualification,
        "salary_min": job.salary_min, "salary_max": job.salary_max, "salary_currency": job.salary_currency,
        "skills_required": list(job.skills_required or []), "skills_nice": list(job.skills_nice or []),
        "posted_at": _iso(job.opened_at or job.created_at),
    }
    if detail:
        data["description"] = job.description
    return data


def _job_sig(job: Job) -> str:
    return hashlib.sha256(json.dumps(_job_view(job), sort_keys=True, default=str).encode()).hexdigest()[:16]


def _fit(row: CandidateJobMatch | None, c: Candidate, job: Job, full: bool = False, csig: str | None = None) -> dict | None:
    """Your stored score for a job, or None. `stale` says your profile or the job changed since it was scored."""
    if row is None:
        return None
    e, b = row.explanation or {}, row.breakdown or {}
    req = (e.get("skills") or {}).get("required", [])
    out = {
        "score": int(round(row.score)), "assessed_weight": b.get("assessed_weight"), "parts": b.get("parts"),
        "required_total": len(req), "required_met": sum(1 for r in req if r["credit"] >= 1),
        "required_related": sum(1 for r in req if 0 < r["credit"] < 1), "missing_required": [r["skill"] for r in req if r["credit"] == 0],
        "summary": e.get("summary"), "computed_at": _iso(row.created_at),
        "stale": e.get("cand_sig") != (csig or _cand_sig(c)) or e.get("job_sig") != _job_sig(job)
                 or b.get("weights") != CANDIDATE_WEIGHTS,
    }
    if full:
        out["explanation"] = e
        out["weights"] = b.get("weights")
    return out


def _get_open_job(db: Session, job_id: str) -> tuple[Job, User | None]:
    try:
        key = uuid.UUID(str(job_id))
    except ValueError:
        raise _err(404, "not_found", "That job does not exist.")
    row = db.execute(select(Job, User).outerjoin(User, User.id == Job.owner_id).where(Job.id == key, Job.status == "open")).first()
    if row is None:
        raise _err(404, "not_found", "That job does not exist.")
    return row[0], row[1]


def _score_and_store(db: Session, c: Candidate, job: Job) -> CandidateJobMatch:
    result = matching.score_candidate(_job_view(job), _cand_view(c), CANDIDATE_WEIGHTS, None)
    explanation = dict(result["explanation"])
    explanation["cand_sig"] = _cand_sig(c)
    explanation["job_sig"] = _job_sig(job)
    row = db.scalars(select(CandidateJobMatch).where(CandidateJobMatch.candidate_id == c.id, CandidateJobMatch.job_id == job.id)).first()
    if row is None:
        row = CandidateJobMatch(candidate_id=c.id, job_id=job.id, score=0)
        db.add(row)
    row.score = result["score"]
    row.breakdown = result["breakdown"]
    row.explanation = explanation
    row.model_version = matching.VERSION
    row.created_at = now()
    return row


def _has_skills(job: Job) -> bool:
    return bool(job.skills_required) or bool(job.skills_nice)


@router.get("/jobs")
def list_jobs(
    q: str | None = Query(default=None, max_length=100), limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
    actor: User = Depends(require_candidate), db: Session | None = Depends(get_db),
) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    jobs = _open_jobs(db)
    words = [w for w in re.split(r"\s+", (q or "").lower().strip()) if w]
    if words:
        def hay(j: Job, u: User | None) -> str:
            return " ".join([j.title or "", j.department or "", j.location or "", (u.company if u else "") or "",
                             " ".join(j.skills_required or []), " ".join(j.skills_nice or [])]).lower()
        jobs = [(j, u) for j, u in jobs if all(w in hay(j, u) for w in words)]
    rows = {r.job_id: r for r in db.scalars(select(CandidateJobMatch).where(CandidateJobMatch.candidate_id == c.id)).all()}
    csig = _cand_sig(c)
    items = [{**_public_job(j, u), "fit": _fit(rows.get(j.id), c, j, csig=csig)} for j, u in jobs]
    # scored jobs first (best fit first); the rest keep newest-first
    scored = sorted([i for i in items if i["fit"]], key=lambda i: -i["fit"]["score"])
    items = scored + [i for i in items if not i["fit"]]
    return {"total": len(items), "scored": len(scored), "has_profile": _matchable(c), "jobs": items[offset:offset + limit]}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    job, owner = _get_open_job(db, job_id)
    row = db.scalars(select(CandidateJobMatch).where(CandidateJobMatch.candidate_id == c.id, CandidateJobMatch.job_id == job.id)).first()
    return {**_public_job(job, owner, detail=True), "fit": _fit(row, c, job, full=True), "has_profile": _matchable(c)}


@router.post("/jobs/match")
def match_all(actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    if not _matchable(c):
        raise _err(409, "no_profile", "Add your resume or some skills first, then score the jobs.")
    scored = skipped = 0
    for job, _ in _open_jobs(db):
        if not _has_skills(job):
            skipped += 1
            continue
        _score_and_store(db, c, job)
        scored += 1
    db.commit()
    out = list_jobs(None, 50, 0, actor, db)
    return {**out, "ran": scored, "skipped_no_skills": skipped}


@router.post("/jobs/{job_id}/match")
def match_one(job_id: str, actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    job, owner = _get_open_job(db, job_id)
    if not _matchable(c):
        raise _err(409, "no_profile", "Add your resume or some skills first, then score this job.")
    if not _has_skills(job):
        raise _err(422, "need_skills", "This job lists no skills yet, so there is nothing to compare.")
    row = _score_and_store(db, c, job)
    db.commit()
    db.refresh(row)
    return {**_public_job(job, owner, detail=True), "fit": _fit(row, c, job, full=True), "has_profile": True}


# ---------------------------------------------------------------- match a pasted job description
class PasteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


def _paste(db: Session, user: User, c: Candidate, text: str) -> dict:
    if _recent_ai(db, user, "match") >= PASTE_PER_HOUR:
        raise _err(429, "slow_down", "That is a lot of pasted jobs for one hour. Try again a little later.")
    try:
        read, model = jobread.read(text, owner_id=user.id)
    except llm.LLMError as exc:
        raise _err(502 if exc.code == "bad_output" else 503, exc.code, exc.message)
    if not read.skills_required and not read.skills_nice:
        raise _err(422, "no_skills_found", "No skills could be found in that text. Paste the full job description, including the requirements.")
    view = {"skills_required": read.skills_required, "skills_nice": read.skills_nice, "experience_min": read.experience_min,
            "experience_max": read.experience_max, "location": read.location, "work_mode": read.work_mode,
            "qualification": read.qualification, "text": "\n".join(x for x in (read.title, text) if x)}
    result = matching.score_candidate(view, _cand_view(c), CANDIDATE_WEIGHTS, None)
    e, b = result["explanation"], result["breakdown"]
    req = e["skills"]["required"]
    return {
        "read": read.model_dump(), "model": model, "score": int(round(result["score"])), "assessed_weight": b.get("assessed_weight"),
        "parts": b.get("parts"), "weights": b.get("weights"), "explanation": e,
        "required_total": len(req), "required_met": sum(1 for r in req if r["credit"] >= 1),
        "missing_required": [r["skill"] for r in req if r["credit"] == 0], "summary": e.get("summary"), "stored": False,
    }


@router.post("/match/paste")
async def match_paste(body: PasteIn, actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    text = body.text.strip()
    if not _matchable(c):
        raise _err(409, "no_profile", "Add your resume or some skills first, then match a job.")
    if len(text) < MIN_PASTE_CHARS:
        raise _err(422, "too_short", "That is too short to be a job description. Paste the whole post.")
    if len(text) > MAX_PASTE_CHARS:
        raise _err(422, "too_long", f"That is longer than {MAX_PASTE_CHARS:,} characters. Paste only the role and requirements.")
    return await run_in_threadpool(_paste, db, actor, c, text)


# ---------------------------------------------------------------- insights
# Display groups only; they never feed a score.
CATEGORIES: dict[str, set[str]] = {
    "Languages": {"python", "r", "java", "javascript", "typescript", "c#", "c++", "go", "scala", "kotlin", "php", "ruby", "sql"},
    "Databases": {"postgresql", "mysql", "sql server", "oracle", "sqlite", "mariadb", "mongodb", "redis", "cassandra", "dynamodb"},
    "BI and reporting": {"power bi", "excel", "tableau", "looker", "qlik", "metabase", "superset", "quicksight", "dax", "power query"},
    "Data engineering": {"snowflake", "bigquery", "redshift", "databricks", "apache spark", "pyspark", "hadoop", "hive", "flink", "kafka",
                         "rabbitmq", "kinesis", "airflow", "dagster", "prefect", "dbt", "etl", "data warehousing", "pyspark sql"},
    "Cloud and DevOps": {"aws", "azure", "gcp", "docker", "kubernetes", "terraform", "git", "ci/cd", "jenkins", "github actions"},
    "ML and statistics": {"machine learning", "deep learning", "nlp", "llm", "scikit-learn", "tensorflow", "pytorch", "keras", "pandas",
                          "numpy", "statistics", "a/b testing"},
    "Web and APIs": {"react", "angular", "vue", "node.js", ".net", "fastapi", "flask", "django", "spring boot", "rest api"},
}


def _category(skill: str) -> str:
    key = matching.canon(skill)
    for name, members in CATEGORIES.items():
        if key in members:
            return name
    return "Other"


def _evidence_state(line: str | None) -> str:
    if not line:
        return "not_shown"
    return "listed_only" if line.lower().lstrip("•-* ").startswith(matching.LINE_HEADERS) else "shown"


def _checklist(c: Candidate, user: User) -> dict:
    p = c.profile or {}
    items = [
        ("resume", "Resume uploaded", bool(c.resume_text), "Upload a PDF, Word or text resume."),
        ("headline", "Current or target role", bool(c.current_title), "Add your role title."),
        ("location", "Location", bool(c.location), "Add your city."),
        ("experience", "Years of experience", c.total_experience_years is not None, "Add your total years of experience."),
        ("qualification", "Highest qualification", bool(c.qualification), "Add your highest degree."),
        ("skills", "At least 5 skills", len(c.skills or []) >= 5, "List the tools and languages you use."),
        ("employers", "Work history", bool(p.get("employers")), "Add your employers with dates."),
        ("education", "Education", bool(p.get("education")), "Add your degrees."),
        ("links", "A profile link", bool(c.linkedin_url or c.github_url or p.get("portfolio_url")), "Add LinkedIn, GitHub or a portfolio link."),
        ("phone", "Phone number", bool(c.phone or user.phone_e164), "Add a phone number so you can be reached."),
    ]
    done = sum(1 for _, _, ok, _ in items if ok)
    return {"percent": round(100 * done / len(items)), "items": [{"key": k, "label": l, "done": ok, "hint": None if ok else h} for k, l, ok, h in items]}


def _market(db: Session, c: Candidate, lines: list[str]) -> dict:
    """Which skills the open jobs ask for most, and whether your resume shows them (the same check the matcher uses)."""
    jobs = _open_jobs(db)
    demand: dict[str, dict] = {}
    for job, _ in jobs:
        for s in job.skills_required or []:
            key = matching.canon(s)
            d = demand.setdefault(key, {"skill": s, "jobs": 0})
            d["jobs"] += 1
    listed: dict[str, str] = {}
    for s in c.skills or []:
        listed.setdefault(matching.canon(s), str(s))
    rows = []
    for key, d in sorted(demand.items(), key=lambda kv: (-kv[1]["jobs"], kv[0]))[:15]:
        v = matching.assess_skill(d["skill"], listed, lines, None)
        rows.append({"skill": d["skill"], "jobs": d["jobs"], "status": v["status"], "credit": v["credit"], "evidence": v["evidence"]})
    return {"open_jobs": len(jobs), "in_demand": rows, "gaps": [r for r in rows if r["credit"] == 0][:8]}


@router.get("/insights")
def insights(actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    p = c.profile or {}
    lines = [l for l in str(c.resume_text or "").splitlines() if l.strip()]
    skills = []
    for s in c.skills or []:
        line = matching.find_line(lines, matching.aliases_of(matching.canon(s))) if lines else None
        skills.append({"skill": s, "category": _category(s), "evidence": line, "state": _evidence_state(line) if lines else "no_resume"})
    groups: dict[str, int] = {}
    for s in skills:
        groups[s["category"]] = groups.get(s["category"], 0) + 1
    employers = [{"company": e.get("company"), "title": e.get("title"), "start": e.get("start"), "end": e.get("end")}
                 for e in (p.get("employers") or []) if isinstance(e, dict)][:8]
    return {
        "has_profile": _matchable(c), "has_resume": bool(c.resume_text),
        "completeness": _checklist(c, actor),
        "skills": {"count": len(skills), "items": skills[:60], "by_category": sorted(({"category": k, "count": v} for k, v in groups.items()), key=lambda x: -x["count"]),
                   "shown": sum(1 for s in skills if s["state"] == "shown"), "listed_only": sum(1 for s in skills if s["state"] == "listed_only")},
        "experience": {"years": c.total_experience_years, "basis": p.get("experience_basis"), "current_title": c.current_title,
                       "current_company": c.current_company, "employers": employers},
        "market": _market(db, c, lines) if _matchable(c) else {"open_jobs": len(_open_jobs(db)), "in_demand": [], "gaps": []},
        "not_scored": NOT_SCORED,
    }
