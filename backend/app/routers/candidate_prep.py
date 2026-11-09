"""Interview preparation for the candidate workspace (mounted at /api/candidate).

    POST   /prep            {job_id} or {text}: likely questions for a job, tied to lines of your own resume
    GET    /preps           your saved sets, newest first
    GET    /preps/{id}      one set in full
    DELETE /preps/{id}

Questions and talking points come from the AI but every resume line and number is checked against your resume
(services/prep.py). Skill gaps come from the rules engine and are explained honestly: what the job wants, and the closest
thing you do show. Nothing here is a prediction of what you will really be asked.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import require_candidate
from app.db.models import User
from app.db.recruiter_models import Candidate, InterviewPrep
from app.db.session import get_db
from app.routers._docs_common import MAX_SAVED, Source, check_budget, clean_source, resolve_job
from app.routers.candidate import CANDIDATE_WEIGHTS, _db, _ensure, _err, _iso
from app.routers.matches import _cand_view
from app.services import llm, matching, prep

router = APIRouter(tags=["candidate-prep"])


def _light(p: InterviewPrep) -> dict:
    c = p.content or {}
    return {"id": str(p.id), "job_id": str(p.job_id) if p.job_id else None, "job_title": p.job_title,
            "questions": len(c.get("questions") or []), "created_at": _iso(p.created_at)}


def _full(p: InterviewPrep) -> dict:
    return {**_light(p), "content": p.content, "model": p.model}


def _years(c: Candidate) -> set[str]:
    y = c.total_experience_years
    return {str(int(round(y)))} if y is not None else set()


def _run(db: Session, user: User, c: Candidate, job_id: str | None, text: str | None) -> dict:
    check_budget(db, user)
    src = resolve_job(db, user, job_id, text)
    cand = _cand_view(c)
    result = matching.score_candidate(src["job_view"], cand, CANDIDATE_WEIGHTS, None)
    gaps = prep.gaps_from(result)
    try:
        out, model = prep.build(c.resume_text or "", {**src["job_view"], "title": src["title"]}, gaps, _years(c), user.id)
    except llm.LLMError as exc:
        raise _err(502 if exc.code == "bad_output" else 503, exc.code, exc.message)
    if not out["questions"]:
        raise _err(502, "bad_output", "The AI did not give usable questions. Try again.")
    out["gaps"] = gaps
    out["fit_score"] = round(result["score"])
    row = InterviewPrep(candidate_id=c.id, job_id=src["job_id"], job_title=(src["title"] or "")[:200], content=out, model=model)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _full(row)


@router.post("/prep")
async def make_prep(body: Source, actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    job_id, text = clean_source(c, body.job_id, body.text, "Interview prep")
    if (db.scalar(select(func.count()).select_from(InterviewPrep).where(InterviewPrep.candidate_id == c.id)) or 0) >= MAX_SAVED:
        raise _err(409, "too_many", f"You have {MAX_SAVED} saved prep sets. Delete one to make room.")
    return await run_in_threadpool(_run, db, actor, c, job_id, text)


def _mine(db: Session, c: Candidate, prep_id: str) -> InterviewPrep:
    try:
        key = uuid.UUID(str(prep_id))
    except ValueError:
        raise _err(404, "not_found", "That prep set does not exist.")
    p = db.get(InterviewPrep, key)
    if p is None or p.candidate_id != c.id:
        raise _err(404, "not_found", "That prep set does not exist.")
    return p


@router.get("/preps")
def list_preps(actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    rows = db.scalars(select(InterviewPrep).where(InterviewPrep.candidate_id == c.id).order_by(InterviewPrep.created_at.desc())).all()
    return {"preps": [_light(p) for p in rows], "max": MAX_SAVED, "has_resume": bool((c.resume_text or "").strip())}


@router.get("/preps/{prep_id}")
def get_prep(prep_id: str, actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    return _full(_mine(db, _ensure(db, actor), prep_id))


@router.delete("/preps/{prep_id}")
def delete_prep(prep_id: str, actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    p = _mine(db, _ensure(db, actor), prep_id)
    db.delete(p)
    db.commit()
    return {"deleted": True}
