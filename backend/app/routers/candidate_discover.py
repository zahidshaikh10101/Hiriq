"""Finding jobs for the candidate workspace (mounted at /api/candidate).

    GET /recommendations    open Hiriq jobs ranked by how well you fit, with why and what is missing (rules only, instant)
    GET /external/status    is the outside job feed switched on?
    GET /external           search jobs outside Hiriq, from Indeed (?q=&location=&radius=&page=): best estimated match first
    GET /external/jobs/{job_ref}/fit    the full, explained score of one outside job for you (rules only, instant)

An outside job has no skill list, so its percentage is an ESTIMATE: postingread.py finds the skills, years and degree the post
mentions and the same engine as a Hiriq job scores them against you. The screen labels it "estimated". For the careful
version, send the description to POST /match/paste (AI read). Every post fetched is kept in external_jobs (public text only).
Your location is never scored; it only fills the search box.
"""
from __future__ import annotations

import re
import time
import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import require_candidate
from app.db.models import User
from app.db.recruiter_models import CandidateJobMatch, ExternalJob
from app.db.session import get_db
from app.routers.candidate import CANDIDATE_WEIGHTS, _db, _ensure, _err, _fit, _has_skills, _matchable, _open_jobs, _public_job, _score_and_store
from app.routers.matches import _cand_sig, _cand_view
from app.services import externaljobs, externalstore, matching, postingread, resume

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


def _estimate(c, row: ExternalJob | None) -> dict | None:
    """The estimated match of one saved outside job, or None when the post names no skill we know (then nothing honest can be said)."""
    if row is None:
        return None
    read = row.read or {}
    if not read.get("skills_required") and not read.get("skills_nice"):
        return None
    result = matching.score_candidate(postingread.view(row.title, row.description, row.location, read), _cand_view(c), CANDIDATE_WEIGHTS, None)
    return result


def _brief(result: dict) -> dict:
    e, b = result["explanation"], result["breakdown"]
    req, nice = e["skills"]["required"], e["skills"]["nice"]
    everything = req + nice
    return {"score": int(round(result["score"])), "assessed_weight": b.get("assessed_weight"), "estimated": True,
            "required_total": len(req), "required_met": sum(1 for r in req if r["credit"] >= 1),
            "matched": [r["skill"] for r in everything if r["credit"] >= 1][:8],
            "missing": [r["skill"] for r in req if r["credit"] == 0][:5]}


def _external(c, user_id: str, q: str, location: str, page: int, radius: int, db: Session) -> dict:
    stamps = [t for t in _hits[user_id] if time.time() - t < 3600]
    if len(stamps) >= EXTERNAL_PER_HOUR:
        _hits[user_id] = stamps
        raise _err(429, "slow_down", "That is a lot of searches for one hour. Try again a little later.")
    try:
        found = externaljobs.search(q, location, page, radius)
    except externaljobs.ExternalError as exc:
        raise _err(exc.status, exc.code, exc.message)
    stamps.append(time.time())
    _hits[user_id] = stamps
    jobs = [dict(j) for j in found["jobs"]]                  # the cached copy stays untouched
    saved = externalstore.save(db, jobs, q, externaljobs.country())
    mine = resume.clean_skills(list(c.skills or []))
    can_score = _matchable(c)
    for j in jobs:
        low = j["description"].lower()
        j["skills_in_posting"] = [s for s in mine if resume._skill_pattern(s).search(low)][:12]
        row = saved.get(j["id"])
        j["job_ref"] = str(row.id) if row else None
        result = _estimate(c, row) if can_score else None
        j["match"] = _brief(result) if result else None
    jobs.sort(key=lambda j: (-(j["match"]["score"] if j["match"] else -1), -len(j["skills_in_posting"])))
    return {"configured": True, "q": q, "location": location, "page": page, "radius": radius, "has_more": found["has_more"],
            "your_skills": len(mine), "can_score": can_score, "jobs": jobs}


@router.get("/external")
async def external_search(
    q: str = Query(min_length=2, max_length=100), location: str = Query(default="", max_length=100), radius: int = Query(default=20, ge=5, le=100), page: int = Query(default=1, ge=1, le=5),
    actor: User = Depends(require_candidate), db: Session | None = Depends(get_db),
) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    if not externaljobs.configured():
        raise _err(503, "not_configured", "The outside job feed is not set up on this server.")
    return await run_in_threadpool(_external, c, str(actor.id), re.sub(r"\s+", " ", q).strip(), re.sub(r"\s+", " ", location).strip(), page, radius, db)


@router.get("/external/jobs/{job_ref}/fit")
def external_fit(job_ref: str, actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    """The detailed, explained estimate for one saved outside job: every skill with its evidence, and each part of the score."""
    db = _db(db)
    c = _ensure(db, actor)
    if not _matchable(c):
        raise _err(409, "no_profile", "Add your resume or some skills first, then check a job.")
    try:
        row = db.get(ExternalJob, uuid.UUID(str(job_ref)))
    except ValueError:
        row = None
    if row is None:
        raise _err(404, "not_found", "That job is no longer saved. Search again to bring it back.")
    result = _estimate(c, row)
    if result is None:
        raise _err(422, "no_skills_found", "This post names no skill Hiriq recognises, so it cannot be scored. Open it to read it yourself, or paste it into Jobs & match for an AI read.")
    e, b = result["explanation"], result["breakdown"]
    req = e["skills"]["required"]
    return {
        "job": {"job_ref": str(row.id), "title": row.title, "company": row.company, "location": row.location, "apply_url": row.apply_url},
        "read": row.read, "estimated": True, "score": int(round(result["score"])), "assessed_weight": b.get("assessed_weight"),
        "parts": b.get("parts"), "weights": b.get("weights"), "explanation": e, "required_total": len(req),
        "required_met": sum(1 for r in req if r["credit"] >= 1), "missing_required": [r["skill"] for r in req if r["credit"] == 0],
        "summary": e.get("summary"), "basis": "Estimated from the words of the post by rules, not read by AI. Open the post to check it.",
    }
