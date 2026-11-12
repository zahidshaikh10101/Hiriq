"""Hiring pipeline: a stage board per job, notes, and thumbs up/down on a match (mounted at /api/recruiter).
Every route needs a signed-in recruiter.

    GET    /jobs/{id}/pipeline                      the board: one column per stage, a rejected lane, and who can still be added
    POST   /jobs/{id}/pipeline                      add candidates (they start in "sourced"), body: {candidate_ids: [...]}
    PATCH  /jobs/{id}/pipeline/{cand_id}            move a candidate and/or edit the note / rejection reason
    DELETE /jobs/{id}/pipeline/{cand_id}            take a candidate off the board (their history on this job goes with them)
    PUT    /jobs/{id}/matches/{cand_id}/feedback    thumbs up (1), thumbs down (-1) or clear (0) on a match

Scope: your own job, and candidates from your own pool (your uploads plus active Hiriq members), plus anyone who applied to your jobs, nothing else.
An applicant is offered on the board of the job they applied to (and can be opened from the Applicants page); nobody is added automatically.
Nobody is ever moved automatically: every stage change here is a recruiter's own click.
`reached` remembers the furthest stage a candidate got to, so the Overview funnel still counts someone after a rejection
or after they are moved back a step. Thumbs are stored as labels for training the ranker later; they never change a score today.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.deps import require_recruiter
from app.db.models import User
from app.db.recruiter_models import PIPELINE_STAGES, STAGES, Application, Candidate, Job, JobMatch, MatchFeedback, PipelineEntry, RecruiterEvent
from app.db.session import get_db
from app.routers.candidates import _find, _members_visible, _sync_members  # the pool rules live in one place
from app.services.timeutil import aware

router = APIRouter(tags=["pipeline"])

STAGE_LABEL = {"sourced": "Sourced", "shortlisted": "Shortlisted", "interview": "Interview", "offer": "Offer", "hired": "Hired", "rejected": "Rejected"}
MAX_ADD = 50          # candidates added in one request
MAX_AVAILABLE = 50    # people offered in the "add to pipeline" list
MAX_NOTE = 2000
MAX_REASON = 200


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


def _db(db: Session | None) -> Session:
    if db is None:
        raise _err(503, "no_database", "The database is not configured.")
    return db


def _iso(dt) -> str | None:
    dt = aware(dt)
    return dt.isoformat() if dt else None


# ---------------------------------------------------------------- loading
def _job(db: Session, actor: User, job_id: str) -> Job:
    try:
        key = uuid.UUID(str(job_id))
    except ValueError:
        raise _err(404, "not_found", "That job does not exist.")
    job = db.scalars(select(Job).where(Job.id == key, Job.owner_id == actor.id)).first()
    if job is None:
        raise _err(404, "not_found", "That job does not exist.")
    return job


def _pool(db: Session, actor: User) -> dict:
    _sync_members(db)
    rows = db.scalars(
        select(Candidate).outerjoin(User, User.id == Candidate.user_id)
        .where(or_(Candidate.owner_id == actor.id, _members_visible()))
    ).all()
    return {c.id: c for c in rows}


def _entry(db: Session, job: Job, candidate_id: uuid.UUID) -> PipelineEntry | None:
    return db.scalars(select(PipelineEntry).where(PipelineEntry.job_id == job.id, PipelineEntry.candidate_id == candidate_id)).first()


# ---------------------------------------------------------------- output
def _headline(c: Candidate) -> str | None:
    return " at ".join(x for x in (c.current_title, c.current_company) if x) or None


def _card(e: PipelineEntry, c: Candidate, score: float | None, label: int | None) -> dict:
    return {
        "entry_id": str(e.id), "candidate_id": str(c.id), "name": c.full_name, "source": c.source, "headline": _headline(c),
        "location": c.location, "years": c.total_experience_years, "score": None if score is None else int(round(score)),
        "stage": e.stage, "note": e.note, "rejection_reason": e.rejection_reason, "feedback": label,
        "added_at": _iso(e.created_at), "moved_at": _iso(e.updated_at or e.created_at),
    }


def _sort_key(card: dict):
    return (card["score"] is None, -(card["score"] or 0), (card["name"] or "").lower(), card["candidate_id"])


def _counts(entries: list[PipelineEntry]) -> dict:
    out = {s: 0 for s in PIPELINE_STAGES}
    for e in entries:
        out[e.stage] += 1
    out["total"] = len(entries)
    return out


def _board(db: Session, actor: User, job: Job) -> dict:
    pool = _pool(db, actor)
    people = dict(pool)    # the pool, plus whoever applied to THIS job (they are not offered for other jobs)
    for c in db.scalars(select(Candidate).join(Application, Application.candidate_id == Candidate.id).where(Application.job_id == job.id)).all():
        people[c.id] = c
    entries = [e for e in db.scalars(select(PipelineEntry).where(PipelineEntry.job_id == job.id)).all() if e.candidate_id in people]
    scores = dict(db.execute(select(JobMatch.candidate_id, JobMatch.score).where(JobMatch.job_id == job.id)).all())
    labels = dict(db.execute(
        select(MatchFeedback.candidate_id, MatchFeedback.label).where(MatchFeedback.job_id == job.id, MatchFeedback.recruiter_id == actor.id)
    ).all())

    cards = [_card(e, people[e.candidate_id], scores.get(e.candidate_id), labels.get(e.candidate_id)) for e in entries]
    by_stage = {s: sorted((c for c in cards if c["stage"] == s), key=_sort_key) for s in PIPELINE_STAGES}

    on_board = {e.candidate_id for e in entries}
    free = [c for cid, c in pool.items() if cid not in on_board]
    free.sort(key=lambda c: (c.id not in scores, -(scores.get(c.id) or 0), (c.full_name or "").lower(), str(c.id)))
    available = [{
        "candidate_id": str(c.id), "name": c.full_name, "source": c.source, "headline": _headline(c), "location": c.location,
        "years": c.total_experience_years, "score": int(round(scores[c.id])) if c.id in scores else None,
        "has_profile": bool(c.skills) or bool(c.resume_text), "feedback": labels.get(c.id),
    } for c in free[:MAX_AVAILABLE]]

    return {
        "job": {"id": str(job.id), "title": job.title, "status": job.status, "location": job.location, "work_mode": job.work_mode},
        "stages": [{"stage": s, "label": STAGE_LABEL[s], "count": len(by_stage[s]), "cards": by_stage[s]} for s in STAGES],
        "rejected": {"stage": "rejected", "label": STAGE_LABEL["rejected"], "count": len(by_stage["rejected"]), "cards": by_stage["rejected"]},
        "counts": _counts(entries), "available": available, "available_total": len(free),
        "can_add": job.status != "closed",
    }


def _event(db: Session, actor: User, job: Job, text: str, candidate_id: uuid.UUID | None = None) -> None:
    db.add(RecruiterEvent(owner_id=actor.id, kind="pipeline", text=text, job_id=job.id, candidate_id=candidate_id))


# ---------------------------------------------------------------- the board
@router.get("/jobs/{job_id}/pipeline")
def get_board(job_id: str, actor: User = Depends(require_recruiter), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    return _board(db, actor, _job(db, actor, job_id))


class AddIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_ids: list[str] = Field(min_length=1, max_length=MAX_ADD)


@router.post("/jobs/{job_id}/pipeline", status_code=201)
def add_to_board(job_id: str, body: AddIn, response: Response, actor: User = Depends(require_recruiter),
                 db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    job = _job(db, actor, job_id)
    if job.status == "closed":
        raise _err(409, "closed", "This job is closed. Reopen it to add more candidates.")
    people: dict[uuid.UUID, Candidate] = {}
    for raw in body.candidate_ids:
        c = _find(db, actor, raw)                  # 404 unless this recruiter may see the candidate; nothing is added if any one fails
        people.setdefault(c.id, c)
    have = {cid for (cid,) in db.execute(select(PipelineEntry.candidate_id).where(PipelineEntry.job_id == job.id)).all()}
    added = [c for cid, c in people.items() if cid not in have]
    for c in added:
        db.add(PipelineEntry(job_id=job.id, candidate_id=c.id, stage="sourced", reached=0))
    if added:
        who = added[0].full_name if len(added) == 1 else f"{len(added)} candidates"
        _event(db, actor, job, f"You added {who} to the {job.title} pipeline", added[0].id if len(added) == 1 else None)
    db.commit()
    if not added:
        response.status_code = 200      # nothing new was created, so not "201 Created"
    return {**_board(db, actor, job), "added": len(added), "already_there": len(people) - len(added)}


class MoveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: str | None = None
    note: str | None = Field(default=None, max_length=MAX_NOTE)
    rejection_reason: str | None = Field(default=None, max_length=MAX_REASON)


def _clean(text: str | None) -> str | None:
    text = (text or "").strip()
    return text or None


@router.patch("/jobs/{job_id}/pipeline/{candidate_id}")
def update_entry(job_id: str, candidate_id: str, body: MoveIn, actor: User = Depends(require_recruiter),
                 db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    job = _job(db, actor, job_id)
    c = _find(db, actor, candidate_id)
    entry = _entry(db, job, c.id)
    if entry is None:
        raise _err(404, "not_on_board", "This candidate is not in this job's pipeline.")
    sent = body.model_fields_set
    if "stage" in sent and body.stage not in PIPELINE_STAGES:
        raise _err(422, "bad_stage", "Stage must be one of: " + ", ".join(PIPELINE_STAGES) + ".")

    before = entry.stage
    if "stage" in sent and body.stage != before:
        entry.stage = body.stage
        if body.stage in STAGES:
            entry.reached = max(entry.reached, STAGES.index(body.stage))
        if before == "rejected" or body.stage != "rejected":
            entry.rejection_reason = None          # the reason belongs to a rejection, and only while it stands
        if body.stage == "rejected":
            _event(db, actor, job, f"You rejected {c.full_name} for {job.title}", c.id)
        elif before == "rejected":
            _event(db, actor, job, f"You moved {c.full_name} back to {STAGE_LABEL[body.stage]} for {job.title}", c.id)
        else:
            _event(db, actor, job, f"You moved {c.full_name} to {STAGE_LABEL[body.stage]} for {job.title}", c.id)
    if "rejection_reason" in sent and entry.stage == "rejected":
        entry.rejection_reason = _clean(body.rejection_reason)
    if "note" in sent:
        entry.note = _clean(body.note)
    db.commit()
    db.refresh(entry)

    score = db.scalar(select(JobMatch.score).where(JobMatch.job_id == job.id, JobMatch.candidate_id == c.id))
    label = db.scalar(select(MatchFeedback.label).where(MatchFeedback.job_id == job.id, MatchFeedback.candidate_id == c.id, MatchFeedback.recruiter_id == actor.id))
    counts = _counts([e for e in db.scalars(select(PipelineEntry).where(PipelineEntry.job_id == job.id)).all()])
    return {"card": _card(entry, c, score, label), "counts": counts}


@router.delete("/jobs/{job_id}/pipeline/{candidate_id}")
def remove_from_board(job_id: str, candidate_id: str, actor: User = Depends(require_recruiter), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    job = _job(db, actor, job_id)
    c = _find(db, actor, candidate_id)
    entry = _entry(db, job, c.id)
    if entry is None:
        raise _err(404, "not_on_board", "This candidate is not in this job's pipeline.")
    db.delete(entry)
    _event(db, actor, job, f"You took {c.full_name} off the {job.title} pipeline", c.id)
    db.commit()
    return {"ok": True, "counts": _counts(list(db.scalars(select(PipelineEntry).where(PipelineEntry.job_id == job.id)).all()))}


# ---------------------------------------------------------------- thumbs
class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: int


@router.put("/jobs/{job_id}/matches/{candidate_id}/feedback")
def set_feedback(job_id: str, candidate_id: str, body: FeedbackIn, actor: User = Depends(require_recruiter),
                 db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    job = _job(db, actor, job_id)
    c = _find(db, actor, candidate_id)
    if body.label not in (-1, 0, 1):
        raise _err(422, "bad_label", "The label must be 1 (thumbs up), -1 (thumbs down) or 0 (clear).")
    if db.scalar(select(JobMatch.id).where(JobMatch.job_id == job.id, JobMatch.candidate_id == c.id)) is None:
        raise _err(404, "not_ranked", "This candidate has not been ranked for this job yet.")
    row = db.scalars(select(MatchFeedback).where(MatchFeedback.job_id == job.id, MatchFeedback.candidate_id == c.id, MatchFeedback.recruiter_id == actor.id)).first()
    if body.label == 0:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(MatchFeedback(job_id=job.id, candidate_id=c.id, recruiter_id=actor.id, label=body.label))
    else:
        row.label = body.label
    db.commit()
    return {"candidate_id": str(c.id), "label": body.label or None}
