"""Finding jobs for the candidate workspace (mounted at /api/candidate).

    GET /recommendations    open Hiriq jobs ranked by how well you fit, with why and what is missing (rules only, instant)
    GET /external/status    is the outside job feed switched on?
    GET /external           search jobs outside Hiriq (?q=&location=&page=): each with which of YOUR skills the posting mentions

An outside job has no skill list, so it gets no 0-100 score here. To score one, send its description to POST /match/paste
(or /rewrite) from the screen. Your location is never scored; it only fills the search box.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import require_candidate
from app.db.models import User
from app.db.recruiter_models import CandidateJobMatch
from app.db.session import get_db
from app.routers.candidate import _db, _ensure, _err, _fit, _has_skills, _matchable, _open_jobs, _public_job, _score_and_store
from app.routers.matches import _cand_sig
from app.services import externaljobs, resume

router = APIRouter(tags=["candidate-discover"])

EXTERNAL_PER_HOUR = 15
_hits: dict[str, list[float]] = defaultdict(list)     # per server process; a restart clears it


def _reason(fit: dict) -> str:
    total, met = fit["required_total"], fit["required_met"]
    if not total:
        return "This job lists no required skills."
    text = f"You show {met} of {total} required skills"
    if fit["required_related"]:
        text += f", {fit['required_related']} more through related tools"
    gaps = fit["missing_required"][:3]
    return text + (f". Missing: {', '.join(gaps)}" if gaps else "") + "."


@router.get("/recommendations")
def recommendations(
    min_score: int = Query(default=30, ge=0, le=100), work_mode: str | None = Query(default=None, pattern="^(onsite|hybrid|remote)$"),
    limit: int = Query(default=20, ge=1, le=50), actor: User = Depends(require_candidate), db: Session | None = Depends(get_db),
) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    if not _matchable(c):
        raise _err(409, "no_profile", "Add your resume or some skills first, then we can suggest jobs.")
    csig = _cand_sig(c)
    rows = {r.job_id: r for r in db.scalars(select(CandidateJobMatch).where(CandidateJobMatch.candidate_id == c.id)).all()}
    items, considered, refreshed = [], 0, False
    for job, owner in _open_jobs(db):
        if not _has_skills(job) or (work_mode and job.work_mode != work_mode):
            continue
        considered += 1
        fit = _fit(rows.get(job.id), c, job, full=True, csig=csig)
        if fit is None or fit["stale"]:                       # new job, or you or the job changed: score it again (rules only)
            rows[job.id] = _score_and_store(db, c, job)
            refreshed = True
            fit = _fit(rows[job.id], c, job, full=True, csig=csig)
        items.append((job, owner, fit))
    if refreshed:
        db.commit()
    items.sort(key=lambda t: (-t[2]["score"], -t[2]["required_met"], -(t[0].created_at.timestamp() if t[0].created_at else 0)))
    shown = [t for t in items if t[2]["score"] >= min_score]
    out = []
    for job, owner, fit in shown[:limit]:
        req = (fit["explanation"].get("skills") or {}).get("required", [])
        matched = [r["skill"] for r in req if r["credit"] >= 1][:6]
        slim = {k: v for k, v in fit.items() if k not in ("explanation", "weights", "parts")}
        out.append({**_public_job(job, owner), "fit": slim, "matched": matched, "gaps": fit["missing_required"][:4], "reason": _reason(fit)})
    return {"has_profile": True, "considered": considered, "hidden_below": len(items) - len(shown), "min_score": min_score,
            "strong": sum(1 for t in items if t[2]["score"] >= 70), "recommended": out}


@router.get("/external/status")
def external_status(actor: User = Depends(require_candidate)) -> dict:
    return {"configured": externaljobs.configured()}


def _external(c, user_id: str, q: str, location: str, page: int) -> dict:
    stamps = [t for t in _hits[user_id] if time.time() - t < 3600]
    if len(stamps) >= EXTERNAL_PER_HOUR:
        _hits[user_id] = stamps
        raise _err(429, "slow_down", "That is a lot of searches for one hour. Try again a little later.")
    try:
        jobs = externaljobs.search(q, location, page)
    except externaljobs.ExternalError as exc:
        raise _err(exc.status, exc.code, exc.message)
    stamps.append(time.time())
    _hits[user_id] = stamps
    mine = resume.clean_skills(list(c.skills or []))
    for j in jobs:
        low = j["description"].lower()
        j["skills_in_posting"] = [s for s in mine if resume._skill_pattern(s).search(low)][:12]
    jobs.sort(key=lambda j: -len(j["skills_in_posting"]))
    return {"configured": True, "q": q, "location": location, "page": page, "your_skills": len(mine), "jobs": jobs}


@router.get("/external")
async def external_search(
    q: str = Query(min_length=2, max_length=100), location: str = Query(default="", max_length=100), page: int = Query(default=1, ge=1, le=5),
    actor: User = Depends(require_candidate), db: Session | None = Depends(get_db),
) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    if not externaljobs.configured():
        raise _err(503, "not_configured", "The outside job feed is not set up on this server.")
    return await run_in_threadpool(_external, c, str(actor.id), re.sub(r"\s+", " ", q).strip(), re.sub(r"\s+", " ", location).strip(), page)
