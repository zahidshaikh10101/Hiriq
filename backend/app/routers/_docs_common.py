"""What the three "documents from your resume for one job" features share: tailored resume, interview prep, cover letter.

Each takes an open Hiriq job (`job_id`) or a pasted job description (`text`), needs an uploaded resume, and counts against
one shared hourly AI budget (all three log their AI calls under the purpose "other").
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.db.models import User
from app.db.recruiter_models import Candidate
from app.routers.candidate import MAX_PASTE_CHARS, MIN_PASTE_CHARS, _err, _get_open_job, _recent_ai
from app.routers.matches import _job_view
from app.services import jobread, llm

AI_DOCS_PER_HOUR = 12      # successful tailorings + interview preps + cover letters per candidate per hour
MAX_SAVED = 20             # saved items of each kind per candidate


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str | None = None
    text: str | None = None


def clean_source(c: Candidate, job_id: str | None, text: str | None, what: str) -> tuple[str | None, str | None]:
    """Checks that exactly one source was given and the resume exists. Returns (job_id, trimmed text)."""
    text = (text or "").strip()
    if bool(job_id) == bool(text):
        raise _err(422, "bad_request", "Choose an open job, or paste a job description, not both.")
    if not (c.resume_text or "").strip():
        raise _err(409, "no_resume", f"Upload your resume first. {what} is built from what you have already written.")
    if text:
        if len(text) < MIN_PASTE_CHARS:
            raise _err(422, "too_short", "That is too short to be a job description. Paste the whole post.")
        if len(text) > MAX_PASTE_CHARS:
            raise _err(422, "too_long", f"That is longer than {MAX_PASTE_CHARS:,} characters. Paste only the role and requirements.")
    return job_id, text or None


def check_budget(db: Session, user: User) -> None:
    if _recent_ai(db, user, "other") >= AI_DOCS_PER_HOUR:
        raise _err(429, "slow_down", "That is a lot of documents for one hour. Try again a little later.")


def resolve_job(db: Session, user: User, job_id: str | None, text: str | None) -> dict:
    """The job as the engine sees it: {job_view, title, job_id (uuid or None), company}. Raises clear 4xx/5xx errors."""
    if job_id:
        job, owner = _get_open_job(db, job_id)
        view = _job_view(job)
        if not (view["skills_required"] or view["skills_nice"]):
            raise _err(422, "need_skills", "This job lists no skills yet, so there is nothing to build on.")
        return {"job_view": view, "title": job.title, "job_id": job.id, "company": (owner.company if owner else None) or None}
    try:
        read, _m = jobread.read(text or "", owner_id=user.id)
    except llm.LLMError as exc:
        raise _err(502 if exc.code == "bad_output" else 503, exc.code, exc.message)
    if not read.skills_required and not read.skills_nice:
        raise _err(422, "no_skills_found", "No skills could be found in that text. Paste the full job description, including the requirements.")
    view = {"skills_required": read.skills_required, "skills_nice": read.skills_nice, "experience_min": read.experience_min,
            "experience_max": read.experience_max, "location": read.location, "work_mode": read.work_mode,
            "qualification": read.qualification, "text": "\n".join(x for x in (read.title, text) if x)}
    return {"job_view": view, "title": read.title or "Pasted job", "job_id": None, "company": None}
