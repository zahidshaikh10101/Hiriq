"""Recruiter module tables: jobs, candidates, matches, the hiring pipeline, feedback labels, and the activity feed.

Kept in its own file so models.py stays about accounts. init_db.py imports this module, so
`python -m app.db.init_db` and the API's startup upgrade create these tables automatically.

Privacy rule baked into the design: a recruiter only ever sees candidates they uploaded themselves
(owner_id) plus platform candidates who signed up on Hiriq (source = 'platform').
"""
from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models import BigId, Json, _in

JOB_STATUSES = ("draft", "open", "closed")
# Order matters: the funnel is read left to right. "rejected" is a side exit, not a stage on the way.
STAGES = ("sourced", "shortlisted", "interview", "offer", "hired")
PIPELINE_STAGES = STAGES + ("rejected",)
CANDIDATE_SOURCES = ("upload", "platform")
EVENT_KINDS = ("job", "resume", "match", "pipeline")
AI_PURPOSES = ("jd", "parse", "match", "ask", "other")
STRONG_SCORE = 70  # a match at or above this counts as "strong" on the overview


class Job(Base):
    """A job a recruiter is hiring for. `description` holds the generated JD text."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(_in("status", JOB_STATUSES), name="ck_jobs_status"),
        Index("ix_jobs_owner_status", "owner_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    department: Mapped[str | None] = mapped_column(String(120))
    location: Mapped[str | None] = mapped_column(String(120))
    work_mode: Mapped[str | None] = mapped_column(String(20))        # onsite | hybrid | remote
    employment_type: Mapped[str | None] = mapped_column(String(30))  # full-time, contract, ...
    experience_min: Mapped[int | None] = mapped_column(Integer)      # years
    experience_max: Mapped[int | None] = mapped_column(Integer)
    qualification: Mapped[str | None] = mapped_column(String(200))
    salary_min: Mapped[int | None] = mapped_column(Integer)          # per year, in salary_currency
    salary_max: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    skills_required: Mapped[list] = mapped_column(Json, nullable=False, default=list)  # must-haves
    skills_nice: Mapped[list] = mapped_column(Json, nullable=False, default=list)      # nice-to-haves
    responsibilities: Mapped[str | None] = mapped_column(Text)       # the recruiter's day-to-day notes
    description: Mapped[str | None] = mapped_column(Text)            # the generated, editable JD
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="draft")
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.false())
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Candidate(Base):
    """A person a recruiter can match against jobs: either an uploaded resume or a Hiriq platform user."""

    __tablename__ = "candidates"
    __table_args__ = (
        CheckConstraint(_in("source", CANDIDATE_SOURCES), name="ck_candidates_source"),
        UniqueConstraint("owner_id", "file_hash", name="uq_candidate_owner_filehash"),  # same file twice = one row
        Index("ix_candidates_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # The recruiter who uploaded the resume. NULL for platform candidates. Deleting the recruiter deletes their uploads.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # Set for platform candidates (a Hiriq account). One candidate row per account.
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    source: Mapped[str] = mapped_column(String(10), nullable=False, server_default="upload")

    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(30))
    location: Mapped[str | None] = mapped_column(String(160))
    linkedin_url: Mapped[str | None] = mapped_column(String(300))
    github_url: Mapped[str | None] = mapped_column(String(300))
    current_title: Mapped[str | None] = mapped_column(String(160))
    current_company: Mapped[str | None] = mapped_column(String(160))
    total_experience_years: Mapped[float | None] = mapped_column(Float)
    qualification: Mapped[str | None] = mapped_column(String(200))
    skills: Mapped[list] = mapped_column(Json, nullable=False, default=list)   # flat list of skill names
    profile: Mapped[dict | None] = mapped_column(Json)                          # the full parsed profile (employers, education, ...)
    resume_text: Mapped[str | None] = mapped_column(Text)                       # extracted text, used for search (RAG) later
    file_name: Mapped[str | None] = mapped_column(String(255))
    file_hash: Mapped[str | None] = mapped_column(String(64))                   # SHA-256 of the file: re-uploads cost nothing
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class JobMatch(Base):
    """The explained score of one candidate against one job."""

    __tablename__ = "job_matches"
    __table_args__ = (
        UniqueConstraint("job_id", "candidate_id", name="uq_match_job_candidate"),
        Index("ix_matches_job_score", "job_id", "score"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)       # 0 to 100
    breakdown: Mapped[dict | None] = mapped_column(Json)               # weighted parts: skills, experience, ...
    explanation: Mapped[dict | None] = mapped_column(Json)             # matched / missing skills, cited evidence
    model_version: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PipelineEntry(Base):
    """Where a candidate stands for a job. `reached` is the furthest stage index, so the funnel survives a rejection."""

    __tablename__ = "pipeline_entries"
    __table_args__ = (
        CheckConstraint(_in("stage", PIPELINE_STAGES), name="ck_pipeline_stage"),
        UniqueConstraint("job_id", "candidate_id", name="uq_pipeline_job_candidate"),
        Index("ix_pipeline_job_stage", "job_id", "stage"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False, server_default="sourced")
    reached: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")  # index into STAGES
    rejection_reason: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class MatchFeedback(Base):
    """A recruiter's thumbs up (1) or down (-1) on a match. These are the labels the ranker is trained on later."""

    __tablename__ = "match_feedback"
    __table_args__ = (
        CheckConstraint("label IN (-1, 1)", name="ck_feedback_label"),
        UniqueConstraint("job_id", "candidate_id", "recruiter_id", name="uq_feedback_once"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    recruiter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    label: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RecruiterEvent(Base):
    """Backs the overview's activity feed. Separate from the admin audit log, which has fixed categories."""

    __tablename__ = "recruiter_events"
    __table_args__ = (
        CheckConstraint(_in("kind", EVENT_KINDS), name="ck_recruiter_event_kind"),
        Index("ix_recruiter_events_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"))
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AiCall(Base):
    """One call to the language model. Powers the admin AI-usage panel; no prompts or resume text are stored."""

    __tablename__ = "ai_calls"
    __table_args__ = (Index("ix_ai_calls_owner_purpose_created", "owner_id", "purpose", "created_at"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)   # one of AI_PURPOSES
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[str | None] = mapped_column(String(200))             # short reason when ok is false
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
