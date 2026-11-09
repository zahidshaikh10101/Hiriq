"""Resume tailoring for the candidate workspace (mounted at /api/candidate, next to routers/candidate.py).

    POST   /rewrite            {job_id} or {text}: tailor your resume to an open job or a pasted job description
    GET    /versions           your saved tailored resumes, newest first
    GET    /versions/{id}      one version in full
    PATCH  /versions/{id}      {label?, text?}: rename it, or edit the tailored text by hand
    DELETE /versions/{id}

Your own resume is never changed. The AI may only reword lines you already wrote; anything that adds a number or a
skill your resume does not have is dropped (see services/rewrite.py). Skills the job wants and you lack are shown as gaps.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import require_candidate
from app.db.models import User
from app.db.recruiter_models import Candidate, ResumeVersion
from app.db.session import get_db
from app.routers._docs_common import MAX_SAVED, check_budget, clean_source, resolve_job
from app.routers.candidate import CANDIDATE_WEIGHTS, _db, _ensure, _err, _iso
from app.routers.matches import _cand_view
from app.services import llm, matching, rewrite

router = APIRouter(tags=["candidate-resume"])

MAX_VERSIONS = MAX_SAVED
MAX_TEXT = 30000


class RewriteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str | None = None
    text: str | None = None


class VersionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str | None = Field(default=None, max_length=120)
    text: str | None = Field(default=None, max_length=MAX_TEXT)


def _light(v: ResumeVersion) -> dict:
    c = v.content or {}
    return {"id": str(v.id), "label": v.label, "job_id": str(v.job_id) if v.job_id else None, "job_title": v.job_title,
            "score_before": v.score_before, "score_after": v.score_after, "rewrites": len(c.get("rewrites") or []),
            "created_at": _iso(v.created_at)}


def _full(v: ResumeVersion) -> dict:
    return {**_light(v), "content": v.content, "text": v.text, "model": v.model}


def _score(job_view: dict, c: Candidate, text: str | None = None) -> float | None:
    view = _cand_view(c)
    if text is not None:
        view["text"] = text
    return matching.score_candidate(job_view, view, CANDIDATE_WEIGHTS, None)["score"]


def _run(db: Session, user: User, c: Candidate, body: RewriteIn) -> dict:
    check_budget(db, user)
    src = resolve_job(db, user, body.job_id, body.text)
    job_view, title = src["job_view"], src["title"]
    try:
        out, model = rewrite.tailor(c.resume_text or "", {**job_view, "title": title}, owner_id=user.id)
    except llm.LLMError as exc:
        raise _err(502 if exc.code == "bad_output" else 503, exc.code, exc.message)
    text = rewrite.apply(c.resume_text or "", out["summary"], out["rewrites"])
    v = ResumeVersion(candidate_id=c.id, job_id=src["job_id"], job_title=(title or "")[:200], label=f"For {title}"[:120], content=out, text=text,
                      score_before=_score(job_view, c), score_after=_score(job_view, c, text), model=model)
    db.add(v)
    db.commit()
    db.refresh(v)
    return _full(v)


@router.post("/rewrite")
async def make_version(body: RewriteIn, actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    job_id, text = clean_source(c, body.job_id, body.text, "Tailoring")
    if (db.scalar(select(func.count()).select_from(ResumeVersion).where(ResumeVersion.candidate_id == c.id)) or 0) >= MAX_VERSIONS:
        raise _err(409, "too_many", f"You have {MAX_VERSIONS} saved versions. Delete one to make room.")
    return await run_in_threadpool(_run, db, actor, c, RewriteIn(job_id=job_id, text=text))


def _mine_version(db: Session, c: Candidate, version_id: str) -> ResumeVersion:
    try:
        key = uuid.UUID(str(version_id))
    except ValueError:
        raise _err(404, "not_found", "That version does not exist.")
    v = db.get(ResumeVersion, key)
    if v is None or v.candidate_id != c.id:
        raise _err(404, "not_found", "That version does not exist.")
    return v


@router.get("/versions")
def list_versions(actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    rows = db.scalars(select(ResumeVersion).where(ResumeVersion.candidate_id == c.id).order_by(ResumeVersion.created_at.desc())).all()
    return {"versions": [_light(v) for v in rows], "max": MAX_VERSIONS, "has_resume": bool((c.resume_text or "").strip())}


@router.get("/versions/{version_id}")
def get_version(version_id: str, actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    return _full(_mine_version(db, _ensure(db, actor), version_id))


@router.patch("/versions/{version_id}")
def edit_version(version_id: str, body: VersionPatch, actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    v = _mine_version(db, _ensure(db, actor), version_id)
    if body.label is not None:
        label = " ".join(body.label.split())
        if not label:
            raise _err(422, "bad_label", "Give the version a name.")
        v.label = label
    if body.text is not None:
        if not body.text.strip():
            raise _err(422, "bad_text", "The resume text cannot be empty.")
        v.text = body.text
    db.commit()
    db.refresh(v)
    return _full(v)


@router.delete("/versions/{version_id}")
def delete_version(version_id: str, actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    v = _mine_version(db, _ensure(db, actor), version_id)
    db.delete(v)
    db.commit()
    return {"deleted": True}
