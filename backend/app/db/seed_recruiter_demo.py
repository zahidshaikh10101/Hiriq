"""Put clearly-labelled SAMPLE data into one recruiter's account, so the dashboard has something to show.

    python -m app.db.seed_recruiter_demo you@example.com            # add sample data
    python -m app.db.seed_recruiter_demo you@example.com --clear    # remove it again

Everything it creates has is_demo = true, the overview shows a "Sample data" banner while any exists,
and --clear removes exactly those rows (your real jobs and candidates are never touched).
The people are fictional. Use it for screenshots and testing; never present it as real hiring data.
"""
from __future__ import annotations

import random
import sys
from datetime import timedelta

from sqlalchemy import delete, select

from app.db.init_db import init_db
from app.db.models import User
from app.db.recruiter_models import (
    STAGES, Candidate, Job, JobMatch, PipelineEntry, RecruiterEvent,
)
from app.db.session import SessionLocal
from app.services.timeutil import now

JOBS = [
    # title, status, days since opened, required skills
    ("Senior Data Analyst", "open", 12, ["SQL", "Python", "Power BI", "Excel"]),
    ("Machine Learning Engineer", "open", 41, ["Python", "PyTorch", "Docker", "AWS"]),
    ("BI Developer", "open", 5, ["SQL", "Tableau", "Excel", "Data Modeling"]),
    ("Data Engineer", "closed", 60, ["Python", "Spark", "Airflow", "SQL"]),
    ("Analytics Manager", "draft", 0, ["SQL", "Stakeholder Management", "A/B Testing"]),
]

CANDIDATES = [
    ("Aarav Mehta", "Data Analyst", 3.0, "Mumbai", ["SQL", "Python", "Excel", "Power BI", "Pandas"]),
    ("Priya Nair", "BI Analyst", 5.5, "Pune", ["SQL", "Tableau", "Excel", "Data Modeling"]),
    ("Rohan Kulkarni", "Data Scientist", 4.0, "Bengaluru", ["Python", "PyTorch", "Docker", "SQL"]),
    ("Sana Qureshi", "ML Engineer", 6.0, "Hyderabad", ["Python", "PyTorch", "AWS", "Docker", "Kubernetes"]),
    ("Vikram Iyer", "Data Engineer", 7.0, "Bengaluru", ["Python", "Spark", "Airflow", "SQL", "AWS"]),
    ("Neha Joshi", "Business Analyst", 2.5, "Mumbai", ["Excel", "SQL", "Jira"]),
    ("Ananya Rao", "Analytics Consultant", 8.0, "Pune", ["SQL", "A/B Testing", "Stakeholder Management", "Python"]),
    ("Kabir Shah", "Junior Analyst", 1.0, "Mumbai", ["Excel", "Power BI"]),
    ("Meera Pillai", "Data Analyst", 4.5, "Chennai", ["SQL", "Python", "Power BI", "Excel", "Tableau"]),
    ("Dev Malhotra", "Software Engineer", 3.5, "Delhi", ["Python", "Docker", "AWS"]),
    ("Isha Verma", "BI Developer", 5.0, "Mumbai", ["SQL", "Tableau", "Power BI", "Data Modeling", "Excel"]),
    ("Arjun Bose", "Data Analyst", 2.0, "Kolkata", ["SQL", "Excel", "Python"]),
]


def _score(job_skills: list[str], cand_skills: list[str], rng: random.Random) -> float:
    """A rough overlap score. Only for sample data; the real matcher arrives in Phase 4."""
    have = {s.lower() for s in cand_skills}
    hit = sum(1 for s in job_skills if s.lower() in have)
    base = 100 * hit / max(1, len(job_skills))
    return round(max(5.0, min(98.0, base * 0.85 + rng.uniform(-6, 12))), 1)


def clear(db, user: User) -> str:
    # Matches and pipeline entries disappear with their jobs / candidates (ON DELETE CASCADE).
    db.execute(delete(RecruiterEvent).where(RecruiterEvent.owner_id == user.id, RecruiterEvent.is_demo.is_(True)))
    jobs = db.execute(delete(Job).where(Job.owner_id == user.id, Job.is_demo.is_(True))).rowcount
    cands = db.execute(delete(Candidate).where(Candidate.owner_id == user.id, Candidate.is_demo.is_(True))).rowcount
    db.commit()
    return f"Removed {jobs} sample jobs and {cands} sample candidates."


def seed(db, user: User) -> str:
    if db.scalar(select(Job.id).where(Job.owner_id == user.id, Job.is_demo.is_(True)).limit(1)):
        return "Sample data is already there. Run with --clear first if you want a fresh set."
    rng = random.Random(7)
    t = now()

    jobs = []
    for title, status, days, skills in JOBS:
        opened = t - timedelta(days=days) if status != "draft" else None
        jobs.append(Job(
            owner_id=user.id, title=title, status=status, skills_required=skills, is_demo=True, opened_at=opened,
            closed_at=t - timedelta(days=days // 3) if status == "closed" else None,
            created_at=t - timedelta(days=days + 1), location="Mumbai", employment_type="full-time",
        ))
    db.add_all(jobs)
    cands = []
    for i, (name, headline, years, city, skills) in enumerate(CANDIDATES):
        cands.append(Candidate(
            owner_id=user.id, source="upload", full_name=name, current_title=headline, total_experience_years=years,
            location=city, skills=skills, is_demo=True, file_name=f"demo-{i + 1}.pdf", file_hash=f"demo-{user.id}-{i}",
            created_at=t - timedelta(days=rng.choice([0, 1, 2, 3, 5, 6, 9, 12])),
        ))
    db.add_all(cands)
    db.flush()

    open_jobs = [j for j in jobs if j.status in ("open", "closed")]
    for job in open_jobs:
        skills = next(s for title, _, _, s in JOBS if title == job.title)
        wanted = {s.lower() for s in skills}
        ranked = sorted(cands, key=lambda c: -len(wanted & {s.lower() for s in c.skills}))
        for rank, c in enumerate(ranked):
            score = _score(skills, c.skills, rng)
            db.add(JobMatch(job_id=job.id, candidate_id=c.id, score=score, model_version="sample"))
            if rank < 6:  # the top few enter the pipeline, at assorted stages
                reached = rng.choice([0, 0, 1, 1, 2, 3, 4]) if job.status == "open" else rng.choice([2, 3, 4])
                rejected = reached < 4 and rng.random() < 0.25
                db.add(PipelineEntry(job_id=job.id, candidate_id=c.id, reached=reached,
                                     stage="rejected" if rejected else STAGES[reached]))

    for text, kind, ago in [
        ("You created the job Senior Data Analyst", "job", timedelta(days=12)),
        ("You uploaded 4 resumes", "resume", timedelta(days=3)),
        ("You ranked 12 candidates for Senior Data Analyst", "match", timedelta(days=2)),
        ("You shortlisted Priya Nair for BI Developer", "pipeline", timedelta(hours=20)),
        ("You opened BI Developer", "job", timedelta(days=5)),
    ]:
        db.add(RecruiterEvent(owner_id=user.id, kind=kind, text=text, is_demo=True, created_at=t - ago))
    db.commit()
    return f"Added {len(jobs)} sample jobs and {len(cands)} sample candidates. Open the recruiter dashboard to see them."


def main(argv: list[str]) -> str:
    if SessionLocal is None:
        raise SystemExit("DATABASE_URL is not set. Put it in backend/.env first.")
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        raise SystemExit("Usage: python -m app.db.seed_recruiter_demo you@example.com [--clear]")
    init_db()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == args[0].strip().lower()))
        if user is None:
            raise SystemExit(f"No account with the email {args[0]}.")
        if user.role != "recruiter":
            raise SystemExit(f"{user.email} is a {user.role}, not a recruiter. Sign up as a recruiter first (or ask an admin to change the role).")
        return clear(db, user) if "--clear" in argv else seed(db, user)


if __name__ == "__main__":
    print(main(sys.argv[1:]))
