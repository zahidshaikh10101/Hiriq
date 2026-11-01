"""Recruiter API (mounted at /api/recruiter). Every route needs a signed-in recruiter.

Phase 1: the overview. Every number comes from the database; with no data the lists are empty and the
page shows empty states instead of invented figures.
Scope rule: a recruiter sees their own jobs, their own uploaded resumes, and platform candidates. Nobody else's.
"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import require_recruiter
from app.db.models import User
from app.db.recruiter_models import (
    STAGES, STRONG_SCORE, Candidate, Job, JobMatch, PipelineEntry, RecruiterEvent,
)
from app.db.session import get_db
from app.services.timeutil import aware, now

router = APIRouter(tags=["recruiter"])

STAGE_LABEL = {"sourced": "Sourced", "shortlisted": "Shortlisted", "interview": "Interview", "offer": "Offer", "hired": "Hired"}
BANDS = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 101)]  # score bands for the match-quality chart
BAND_LABELS = ["0–19", "20–39", "40–59", "60–79", "80–100"]
STALE_JOB_DAYS = 30
TONE = {"job": "a3", "resume": "a2", "match": "a1", "pipeline": "a4"}


def _db(db: Session | None) -> Session:
    if db is None:
        raise HTTPException(503, detail={"code": "no_database", "message": "The database is not configured."})
    return db


def _iso(dt) -> str | None:
    dt = aware(dt)
    return dt.isoformat() if dt else None


def _pool_filter(actor: User):
    """Candidates this recruiter may see: their own uploads plus platform candidates."""
    return or_(Candidate.owner_id == actor.id, Candidate.source == "platform")


def _norm(skill: str) -> str:
    return " ".join(str(skill).lower().split())


def _drop_off(counts: list[int]) -> list[int | None]:
    """Percent lost between each stage and the one before it. None where there is nothing to compare."""
    out: list[int | None] = [None]
    for prev, cur in zip(counts, counts[1:]):
        out.append(round((1 - cur / prev) * 100) if prev else None)
    return out


@router.get("/overview")
def overview(actor: User = Depends(require_recruiter), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    t = now()
    week_ago, two_weeks_ago = t - timedelta(days=7), t - timedelta(days=14)

    # ---- jobs ----
    jobs = db.scalars(select(Job).where(Job.owner_id == actor.id)).all()
    by_status = Counter(j.status for j in jobs)
    open_jobs = sorted((j for j in jobs if j.status == "open"), key=lambda j: aware(j.opened_at or j.created_at), reverse=True)

    # ---- candidates ----
    # The pool = this recruiter's uploaded resumes + Hiriq members (verified, active candidate accounts).
    # A member counts as soon as they join; they become matchable once they have a profile with skills.
    uploads_total = db.scalar(select(func.count()).select_from(Candidate).where(Candidate.owner_id == actor.id)) or 0
    members = db.scalar(
        select(func.count()).select_from(User).where(User.role == "candidate", User.status == "active", User.email_verified.is_(True))
    ) or 0
    pool_total = uploads_total + members
    uploaded =db.scalars(select(Candidate.created_at).where(Candidate.owner_id == actor.id, Candidate.created_at >= two_weeks_ago)).all()
    parsed_this_week = sum(1 for c in uploaded if aware(c) >= week_ago)
    parsed_last_week = len(uploaded) - parsed_this_week

    # ---- pipeline (only entries on this recruiter's jobs) ----
    entries = db.execute(
        select(PipelineEntry.stage, PipelineEntry.reached, Job.status)
        .join(Job, Job.id == PipelineEntry.job_id).where(Job.owner_id == actor.id)
    ).all()
    # The funnel is the whole history (every job). The "right now" counts only look at open jobs.
    stage_now = Counter(stage for stage, _, job_status in entries if job_status == "open")
    reached = [sum(1 for _, r, _ in entries if r >= i) for i in range(len(STAGES))]
    drops = _drop_off(reached)
    funnel = [{"stage": s, "label": STAGE_LABEL[s], "count": reached[i], "drop": drops[i]} for i, s in enumerate(STAGES)]

    # ---- job health + match quality (open jobs only) ----
    job_ids = [j.id for j in open_jobs]
    scores_by_job: dict = {jid: [] for jid in job_ids}
    entry_count: Counter = Counter()
    if job_ids:
        for jid, score in db.execute(select(JobMatch.job_id, JobMatch.score).where(JobMatch.job_id.in_(job_ids))).all():
            scores_by_job[jid].append(score)
        for (jid,) in db.execute(select(PipelineEntry.job_id).where(PipelineEntry.job_id.in_(job_ids))).all():
            entry_count[jid] += 1

    health = []
    for j in open_jobs:
        scores = scores_by_job[j.id]
        strong = sum(1 for s in scores if s >= STRONG_SCORE)
        if not scores and not entry_count[j.id]:
            state, note = "bad", "No candidates matched yet"
        elif strong == 0:
            state, note = "warn", "No strong matches. Revisit the JD or widen the pool"
        else:
            state, note = "good", f"{strong} strong match{'es' if strong != 1 else ''}"
        health.append({"job_id": str(j.id), "title": j.title, "matched": len(scores), "strong": strong, "state": state, "note": note})
    health.sort(key=lambda h: {"bad": 0, "warn": 1, "good": 2}[h["state"]])

    quality = []
    for j in open_jobs[:6]:
        scores = scores_by_job[j.id]
        bands = [sum(1 for s in scores if lo <= s < hi) for lo, hi in BANDS]
        top = db.execute(
            select(JobMatch.score, Candidate.id, Candidate.full_name, Candidate.current_title)
            .join(Candidate, Candidate.id == JobMatch.candidate_id)
            .where(JobMatch.job_id == j.id).order_by(JobMatch.score.desc()).limit(5)
        ).all()
        quality.append({
            "job_id": str(j.id), "title": j.title, "bands": bands, "band_labels": BAND_LABELS, "total": len(scores),
            "top": [{"candidate_id": str(cid), "name": name, "headline": title, "score": round(score)} for score, cid, name, title in top],
        })

    # ---- skills in demand: what your open jobs ask for vs how many pool candidates have it ----
    wanted: Counter = Counter()
    shown_name: dict[str, str] = {}
    for j in open_jobs:
        for raw in {_norm(s): s for s in (j.skills_required or [])}.values():
            key = _norm(raw)
            wanted[key] += 1
            shown_name.setdefault(key, str(raw).strip())
    skills = []
    skill_rows = [s for (s,) in db.execute(select(Candidate.skills).where(_pool_filter(actor))).all() if s]
    if wanted:
        have: Counter = Counter()
        for cand_skills in skill_rows:
            for key in {_norm(s) for s in cand_skills}:
                if key in wanted:
                    have[key] += 1
        for key, jobs_asking in wanted.most_common(8):
            skills.append({"skill": shown_name[key], "jobs": jobs_asking, "candidates": have[key]})

    # ---- needs action ----
    waiting_total = stage_now.get("sourced", 0)
    waiting = db.execute(
        select(Candidate.id, Candidate.full_name, Job.title, Job.id)
        .select_from(PipelineEntry)
        .join(Job, Job.id == PipelineEntry.job_id).join(Candidate, Candidate.id == PipelineEntry.candidate_id)
        .where(Job.owner_id == actor.id, Job.status == "open", PipelineEntry.stage == "sourced")
        .order_by(PipelineEntry.created_at.asc()).limit(5)
    ).all()
    stale = []
    for j in open_jobs:
        days = (t - aware(j.opened_at or j.created_at)).days
        if days >= STALE_JOB_DAYS:
            stale.append({"job_id": str(j.id), "title": j.title, "days": days})
    stale.sort(key=lambda s: -s["days"])

    # ---- activity ----
    events = db.scalars(
        select(RecruiterEvent).where(RecruiterEvent.owner_id == actor.id).order_by(RecruiterEvent.created_at.desc(), RecruiterEvent.id.desc()).limit(8)
    ).all()

    has_demo = bool(
        db.scalar(select(func.count()).select_from(Job).where(Job.owner_id == actor.id, Job.is_demo.is_(True)))
        or db.scalar(select(func.count()).select_from(Candidate).where(Candidate.owner_id == actor.id, Candidate.is_demo.is_(True)))
    )

    def delta(cur: int, prev: int) -> str | None:
        if cur == prev:
            return None
        return f"+{cur - prev}" if cur > prev else f"−{prev - cur}"

    return {
        "me": {"name": actor.full_name, "company": actor.company, "designation": actor.designation},
        "has_demo": has_demo,
        "empty": not jobs and uploads_total == 0,
        "skills_pool": len(skill_rows),  # candidates with skills listed: the group "skills in demand" is measured against
        "kpis": [
            {"key": "open", "label": "Open jobs", "value": by_status.get("open", 0), "sub": f"{len(jobs)} in total"},
            {"key": "closed", "label": "Closed jobs", "value": by_status.get("closed", 0), "sub": f"{by_status.get('draft', 0)} drafts"},
            {"key": "pool", "label": "Candidates in pool", "value": pool_total,
             "sub": f"{uploads_total} uploaded · {members} Hiriq member{'' if members == 1 else 's'}"},
            {"key": "parsed", "label": "Resumes parsed this week", "value": parsed_this_week, "delta": delta(parsed_this_week, parsed_last_week), "sub": None},
            {"key": "shortlisted", "label": "Shortlisted", "value": stage_now.get("shortlisted", 0), "sub": "Across open jobs"},
            {"key": "interview", "label": "In interview", "value": stage_now.get("interview", 0), "sub": None},
        ],
        "funnel": funnel,
        "job_health": health,
        "match_quality": quality,
        "skills_in_demand": skills,
        "needs_action": {
            "waiting_total": waiting_total,
            "waiting": [{"candidate_id": str(cid), "name": name, "job": title, "job_id": str(jid)} for cid, name, title, jid in waiting],
            "stale_jobs": stale,
            "stale_days": STALE_JOB_DAYS,
        },
        "activity": [{"text": e.text, "at": _iso(e.created_at), "tone": TONE.get(e.kind, "a1")} for e in events],
    }
