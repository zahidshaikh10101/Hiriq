"""Cover letters for the candidate workspace (mounted at /api/candidate).

    POST   /letters             {job_id|text, tone?}: write a cover letter for a job from your own resume
    GET    /letters             your saved letters, newest first
    GET    /letters/{id}        one letter in full
    PATCH  /letters/{id}        {label?, text?}: rename it or edit the letter
    GET    /letters/{id}/pdf    the letter as a PDF download (made from the saved text, so your edits are included)
    DELETE /letters/{id}

The greeting, your name and contact details and the sign-off are filled in by code from your profile. The AI writes only the
paragraphs, and any paragraph with a number or skill your resume does not have is dropped (services/letter.py).
"""
from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import require_candidate
from app.db.models import User
from app.db.recruiter_models import Candidate, CoverLetter
from app.db.session import get_db
from app.routers._docs_common import MAX_SAVED, check_budget, clean_source, resolve_job
from app.routers.candidate import _db, _ensure, _err, _iso
from app.services import letter, llm, rewrite
from app.services.timeutil import now

router = APIRouter(tags=["candidate-letters"])
MAX_TEXT = 12000


class LetterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str | None = None
    text: str | None = None
    tone: str = "professional"


class LetterPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str | None = Field(default=None, max_length=120)
    text: str | None = Field(default=None, max_length=MAX_TEXT)


def _light(v: CoverLetter) -> dict:
    return {"id": str(v.id), "label": v.label, "job_id": str(v.job_id) if v.job_id else None, "job_title": v.job_title, "tone": v.tone,
            "created_at": _iso(v.created_at)}


def _full(v: CoverLetter) -> dict:
    return {**_light(v), "text": v.text, "content": v.content, "model": v.model}


def _run(db: Session, user: User, c: Candidate, job_id: str | None, text: str | None, tone: str) -> dict:
    check_budget(db, user)
    src = resolve_job(db, user, job_id, text)
    missing = rewrite.missing_job_skills(c.resume_text or "", list(src["job_view"]["skills_required"]) + list(src["job_view"]["skills_nice"]))
    years = {str(int(round(c.total_experience_years)))} if c.total_experience_years is not None else set()
    try:
        out, model = letter.write(c.resume_text or "", {**src["job_view"], "title": src["title"]}, missing, tone, years, user.id)
    except llm.LLMError as exc:
        raise _err(502 if exc.code == "bad_output" else 503, exc.code, exc.message)
    name = c.full_name or user.full_name or "Applicant"
    contact = [x for x in (c.email or user.email, c.phone or user.phone_e164, c.location) if x]
    body = letter.compose(out["paragraphs"], name, contact, src["company"], now().date())
    row = CoverLetter(candidate_id=c.id, job_id=src["job_id"], job_title=(src["title"] or "")[:200], label=f"For {src['title']}"[:120], tone=tone,
                      text=body, content={"dropped": out["dropped"]}, model=model)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _full(row)


@router.post("/letters")
async def make_letter(body: LetterIn, actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    if body.tone not in letter.TONES:
        raise _err(422, "bad_tone", "Choose a professional or a friendly tone.")
    job_id, text = clean_source(c, body.job_id, body.text, "A cover letter")
    if (db.scalar(select(func.count()).select_from(CoverLetter).where(CoverLetter.candidate_id == c.id)) or 0) >= MAX_SAVED:
        raise _err(409, "too_many", f"You have {MAX_SAVED} saved letters. Delete one to make room.")
    return await run_in_threadpool(_run, db, actor, c, job_id, text, body.tone)


def _mine(db: Session, c: Candidate, letter_id: str) -> CoverLetter:
    try:
        key = uuid.UUID(str(letter_id))
    except ValueError:
        raise _err(404, "not_found", "That letter does not exist.")
    v = db.get(CoverLetter, key)
    if v is None or v.candidate_id != c.id:
        raise _err(404, "not_found", "That letter does not exist.")
    return v


@router.get("/letters")
def list_letters(actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    c = _ensure(db, actor)
    rows = db.scalars(select(CoverLetter).where(CoverLetter.candidate_id == c.id).order_by(CoverLetter.created_at.desc())).all()
    return {"letters": [_light(v) for v in rows], "max": MAX_SAVED, "has_resume": bool((c.resume_text or "").strip())}


@router.get("/letters/{letter_id}")
def get_letter(letter_id: str, actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    return _full(_mine(db, _ensure(db, actor), letter_id))


@router.patch("/letters/{letter_id}")
def edit_letter(letter_id: str, body: LetterPatch, actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    v = _mine(db, _ensure(db, actor), letter_id)
    if body.label is not None:
        label = " ".join(body.label.split())
        if not label:
            raise _err(422, "bad_label", "Give the letter a name.")
        v.label = label
    if body.text is not None:
        if not body.text.strip():
            raise _err(422, "bad_text", "The letter cannot be empty.")
        v.text = body.text
    db.commit()
    db.refresh(v)
    return _full(v)


@router.get("/letters/{letter_id}/pdf")
def letter_pdf(letter_id: str, actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> Response:
    db = _db(db)
    v = _mine(db, _ensure(db, actor), letter_id)
    name = re.sub(r"[^A-Za-z0-9\-_ ]+", "", v.label).strip().replace(" ", "-") or "cover-letter"
    return Response(letter.pdf(v.text, v.label), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}.pdf"', "Cache-Control": "no-store"})


@router.delete("/letters/{letter_id}")
def delete_letter(letter_id: str, actor: User = Depends(require_candidate), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    v = _mine(db, _ensure(db, actor), letter_id)
    db.delete(v)
    db.commit()
    return {"deleted": True}
