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
    # Platform candidates only. A member shows up in recruiter pools only after choosing to (default: hidden).
    visible_to_recruiters: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.false())
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


class CandidateJobMatch(Base):
    """How a candidate sees their own fit to an open job. Always scored with the default weights and never shown to recruiters
    (a recruiter may change the weights per job, so the two scores for the same pair can differ)."""

    __tablename__ = "candidate_job_matches"
    __table_args__ = (
        UniqueConstraint("candidate_id", "job_id", name="uq_cmatch_candidate_job"),
        Index("ix_cmatch_candidate_score", "candidate_id", "score"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)       # 0 to 100
    breakdown: Mapped[dict | None] = mapped_column(Json)
    explanation: Mapped[dict | None] = mapped_column(Json)             # also holds cand_sig and job_sig, to spot a stale score
    model_version: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ResumeVersion(Base):
    """A saved tailored copy of a member's resume for one job. The original resume is never changed.
    `job_id` is empty for a pasted job description and when the job is later deleted; `job_title` keeps the label."""

    __tablename__ = "resume_versions"
    __table_args__ = (Index("ix_resume_versions_candidate_created", "candidate_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    job_title: Mapped[str | None] = mapped_column(String(200))
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    content: Mapped[dict] = mapped_column(Json, nullable=False)        # summary, rewrites, skills_first, gaps, dropped
    text: Mapped[str] = mapped_column(Text, nullable=False)            # the tailored resume text (the person can edit it)
    score_before: Mapped[float | None] = mapped_column(Float)
    score_after: Mapped[float | None] = mapped_column(Float)
    model: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class InterviewPrep(Base):
    """A saved interview-prep set for one job: likely questions tied to the member's own resume lines."""

    __tablename__ = "interview_preps"
    __table_args__ = (Index("ix_interview_preps_candidate_created", "candidate_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    job_title: Mapped[str | None] = mapped_column(String(200))
    content: Mapped[dict] = mapped_column(Json, nullable=False)        # questions, stories, ask_them, gaps, dropped
    model: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CoverLetter(Base):
    """A saved cover letter for one job. `text` is the whole letter and the member can edit it; the PDF is made from it on request."""

    __tablename__ = "cover_letters"
    __table_args__ = (Index("ix_cover_letters_candidate_created", "candidate_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    job_title: Mapped[str | None] = mapped_column(String(200))
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    tone: Mapped[str] = mapped_column(String(20), nullable=False, server_default="professional")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[dict] = mapped_column(Json, nullable=False)        # dropped paragraphs and why
    model: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Application(Base):
    """A candidate's application to one open job. Applying is the one moment a member shares their details with a recruiter,
    so everything the recruiter sees is a snapshot taken then: the resume text sent (original or a tailored version), the
    cover letter if any, a short message, and the contact details. Later edits or deletions of the originals change nothing here.
    Withdrawing deletes the row, so the recruiter's access ends with it."""

    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("job_id", "candidate_id", name="uq_application_job_candidate"),
        Index("ix_applications_job_created", "job_id", "created_at"),
        Index("ix_applications_candidate_created", "candidate_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    resume_label: Mapped[str] = mapped_column(String(120), nullable=False)
    resume_text: Mapped[str] = mapped_column(Text, nullable=False)
    letter_label: Mapped[str | None] = mapped_column(String(120))
    letter_text: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)
    contact: Mapped[dict] = mapped_column(Json, nullable=False)          # email, phone, location, linkedin_url, github_url, portfolio_url
    fit_score: Mapped[float | None] = mapped_column(Float)              # standard weights, scored when the member applied
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ExternalJob(Base):
    """A job post fetched from an outside feed (Indeed through the Jobs API), kept so Hiriq builds its own library of the market.
    Public job text only: nothing about any candidate is stored here, and no score either (scores are worked out per candidate
    when asked). One row per post: fetching the same post again only refreshes the text and `last_seen_at`.
    `read` is what the rules reader found in the text (skills, years, degree), so market questions need no re-reading."""

    __tablename__ = "external_jobs"
    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_external_job_provider_id"),
        Index("ix_external_jobs_last_seen", "last_seen_at"),
        Index("ix_external_jobs_title", "title"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    company: Mapped[str | None] = mapped_column(String(160))
    location: Mapped[str | None] = mapped_column(String(160))
    country: Mapped[str | None] = mapped_column(String(2))
    remote: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    apply_url: Mapped[str | None] = mapped_column(String(600))
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    last_query: Mapped[str | None] = mapped_column(String(100))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


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
