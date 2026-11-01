"""Recruiter module, phase 1: the role guard, the empty overview, real numbers, data scoping, and the sample-data seeder.

Uses a throwaway SQLite file. Users are created directly, so these tests do not depend on the sign-up flow.
"""
import importlib
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

RELOAD = ["app.core.config", "app.db.session", "app.db.init_db", "app.core.deps", "app.routers.recruiter"]


class Env:
    pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    mods = {}
    for name in RELOAD:
        mods[name] = importlib.reload(importlib.import_module(name))
    mods["app.db.init_db"].init_db()
    e = Env()
    e.mods, e.session, e.security = mods, mods["app.db.session"], importlib.import_module("app.core.security")
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(mods["app.routers.recruiter"].router, prefix="/api/recruiter")
    e.client = TestClient(app)
    return e


def make_user(env, email, role="recruiter", name=None):
    from app.db.models import User

    with env.session.SessionLocal() as db:
        u = User(email=email, full_name=name or email.split("@")[0].title(), role=role, email_verified=True,
                 company="Acme", designation="Talent Lead")
        db.add(u)
        db.commit()
        uid = str(u.id)
    token = env.security.create_token(uid, role, "x" * 40, 8)
    return uid, {"Authorization": f"Bearer {token}"}


def add(env, *rows):
    with env.session.SessionLocal() as db:
        db.add_all(rows)
        db.commit()


def overview(env, headers):
    r = env.client.get("/api/recruiter/overview", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- who may call ----------
def test_overview_needs_a_signed_in_recruiter(env):
    assert env.client.get("/api/recruiter/overview").status_code == 401
    _, cand = make_user(env, "c@example.com", role="candidate")
    _, admin = make_user(env, "a@example.com", role="admin")
    assert env.client.get("/api/recruiter/overview", headers=cand).status_code == 403
    assert env.client.get("/api/recruiter/overview", headers=admin).status_code == 403


def test_suspended_recruiter_is_locked_out(env):
    from app.db.models import User

    uid, h = make_user(env, "r@example.com")
    assert env.client.get("/api/recruiter/overview", headers=h).status_code == 200
    with env.session.SessionLocal() as db:
        db.get(User, __import__("uuid").UUID(uid)).status = "suspended"
        db.commit()
    assert env.client.get("/api/recruiter/overview", headers=h).status_code == 401


# ---------- empty state: nothing invented ----------
def test_new_recruiter_sees_honest_zeros(env):
    _, h = make_user(env, "r@example.com", name="Riya Kapoor")
    d = overview(env, h)
    assert d["empty"] is True and d["has_demo"] is False
    assert d["me"] == {"name": "Riya Kapoor", "company": "Acme", "designation": "Talent Lead"}
    assert [k["value"] for k in d["kpis"]] == [0, 0, 0, 0, 0, 0]
    assert [f["count"] for f in d["funnel"]] == [0] * 5
    assert all(f["drop"] is None for f in d["funnel"])
    assert d["job_health"] == [] and d["match_quality"] == [] and d["skills_in_demand"] == [] and d["activity"] == []
    assert d["needs_action"]["waiting_total"] == 0 and d["needs_action"]["stale_jobs"] == []


# ---------- real numbers ----------
def test_counts_funnel_health_skills_and_needs_action(env):
    from app.db.recruiter_models import Candidate, Job, JobMatch, PipelineEntry, RecruiterEvent
    from app.services.timeutil import now

    uid, h = make_user(env, "r@example.com")
    import uuid

    owner = uuid.UUID(uid)
    t = now()
    j_ok = Job(owner_id=owner, title="Data Analyst", status="open", skills_required=["SQL", "Python", "sql"], opened_at=t - timedelta(days=3))
    j_dead = Job(owner_id=owner, title="Ghost Role", status="open", skills_required=["Rust"], opened_at=t - timedelta(days=45))
    j_weak = Job(owner_id=owner, title="Weak Role", status="open", skills_required=["SQL"], opened_at=t - timedelta(days=2))
    j_closed = Job(owner_id=owner, title="Old", status="closed")
    j_draft = Job(owner_id=owner, title="Draft", status="draft")
    add(env, j_ok, j_dead, j_weak, j_closed, j_draft)

    cands = [
        Candidate(owner_id=owner, full_name=f"Cand {i}", skills=sk, file_hash=f"h{i}", created_at=t - timedelta(days=d),
                  current_title="Analyst")
        for i, (sk, d) in enumerate([(["SQL", "Python"], 1), (["python"], 2), (["Excel"], 3), (["SQL"], 10)])
    ]
    add(env, *cands)
    c0, c1, c2, c3 = cands
    add(env,
        JobMatch(job_id=j_ok.id, candidate_id=c0.id, score=91), JobMatch(job_id=j_ok.id, candidate_id=c1.id, score=72),
        JobMatch(job_id=j_ok.id, candidate_id=c2.id, score=35), JobMatch(job_id=j_weak.id, candidate_id=c3.id, score=40),
        PipelineEntry(job_id=j_ok.id, candidate_id=c0.id, stage="interview", reached=2),
        PipelineEntry(job_id=j_ok.id, candidate_id=c1.id, stage="shortlisted", reached=1),
        PipelineEntry(job_id=j_ok.id, candidate_id=c2.id, stage="sourced", reached=0),
        PipelineEntry(job_id=j_weak.id, candidate_id=c3.id, stage="rejected", reached=1),
        RecruiterEvent(owner_id=owner, kind="job", text="You created the job Data Analyst"))

    d = overview(env, h)
    k = {x["key"]: x for x in d["kpis"]}
    assert (k["open"]["value"], k["closed"]["value"], k["pool"]["value"]) == (3, 1, 4)
    assert k["open"]["sub"] == "5 in total" and k["closed"]["sub"] == "1 drafts"
    assert k["parsed"]["value"] == 3 and k["parsed"]["delta"] == "+2"  # 3 this week vs 1 the week before
    assert k["shortlisted"]["value"] == 1 and k["interview"]["value"] == 1

    # reached: sourced 4, shortlisted 3, interview 1, offer 0, hired 0
    assert [f["count"] for f in d["funnel"]] == [4, 3, 1, 0, 0]
    assert [f["drop"] for f in d["funnel"]] == [None, 25, 67, 100, None]

    health = {x["title"]: x for x in d["job_health"]}
    assert health["Ghost Role"]["state"] == "bad" and health["Weak Role"]["state"] == "warn"
    assert health["Data Analyst"]["state"] == "good" and health["Data Analyst"]["strong"] == 2
    assert d["job_health"][0]["state"] == "bad" and d["job_health"][-1]["state"] == "good"  # worst first

    mq = next(x for x in d["match_quality"] if x["title"] == "Data Analyst")
    assert mq["bands"] == [0, 1, 0, 1, 1] and mq["total"] == 3
    assert [t["name"] for t in mq["top"]] == ["Cand 0", "Cand 1", "Cand 2"] and mq["top"][0]["score"] == 91

    sk = {s["skill"]: s for s in d["skills_in_demand"]}
    assert sk["SQL"] == {"skill": "SQL", "jobs": 2, "candidates": 2}   # duplicate "sql" in one job counts once
    assert sk["Python"]["candidates"] == 2 and sk["Rust"]["candidates"] == 0  # case-insensitive match

    na = d["needs_action"]
    assert na["waiting_total"] == 1 and na["waiting"][0]["name"] == "Cand 2" and na["waiting"][0]["job"] == "Data Analyst"
    assert [s["title"] for s in na["stale_jobs"]] == ["Ghost Role"] and na["stale_jobs"][0]["days"] >= 45
    assert d["activity"][0]["text"] == "You created the job Data Analyst"
    assert d["empty"] is False


def test_closed_jobs_count_in_the_funnel_but_not_in_right_now_numbers(env):
    from app.db.recruiter_models import Candidate, Job, PipelineEntry
    import uuid

    uid, h = make_user(env, "r@example.com")
    closed = Job(owner_id=uuid.UUID(uid), title="Filled role", status="closed", skills_required=["SQL"])
    cand = Candidate(owner_id=uuid.UUID(uid), full_name="Hired Hana", file_hash="hh", skills=["SQL"])
    add(env, closed, cand)
    add(env, PipelineEntry(job_id=closed.id, candidate_id=cand.id, stage="sourced", reached=0),
        )
    d = overview(env, h)
    k = {x["key"]: x for x in d["kpis"]}
    assert d["funnel"][0]["count"] == 1            # history keeps it
    assert d["needs_action"]["waiting_total"] == 0  # but nobody is "waiting" on a closed job
    assert k["shortlisted"]["value"] == 0 and k["interview"]["value"] == 0


# ---------- scoping ----------
def test_a_recruiter_never_sees_another_recruiters_data(env):
    from app.db.recruiter_models import Candidate, Job, PipelineEntry
    import uuid

    a_id, a = make_user(env, "a@example.com")
    b_id, b = make_user(env, "b@example.com")
    job_b = Job(owner_id=uuid.UUID(b_id), title="B's secret job", status="open", skills_required=["Go"])
    cand_b = Candidate(owner_id=uuid.UUID(b_id), full_name="B Upload", file_hash="x", skills=["Go"])
    add(env, job_b, cand_b)
    add(env, PipelineEntry(job_id=job_b.id, candidate_id=cand_b.id, stage="sourced", reached=0))

    d = overview(env, a)
    assert d["empty"] is True
    assert [k["value"] for k in d["kpis"]] == [0] * 6
    assert d["job_health"] == [] and d["skills_in_demand"] == [] and d["needs_action"]["waiting_total"] == 0
    assert "secret" not in str(d) and "B Upload" not in str(d)


def test_platform_candidates_are_visible_to_every_recruiter(env):
    from app.db.recruiter_models import Candidate

    _, h = make_user(env, "r@example.com")
    cand_user_id, _ = make_user(env, "member@example.com", role="candidate")
    import uuid

    add(env, Candidate(user_id=uuid.UUID(cand_user_id), source="platform", full_name="Platform Pat", skills=["SQL"]))
    d = overview(env, h)
    k = {x["key"]: x for x in d["kpis"]}
    assert k["pool"]["value"] == 1 and k["parsed"]["value"] == 0  # in the pool, but not an upload of theirs
    assert d["skills_pool"] == 1  # and their skills are on file


def test_members_count_in_the_pool_as_soon_as_they_join(env):
    """A verified, active candidate account is a member even before it has a profile row."""
    from app.db.models import User

    _, h = make_user(env, "r@example.com")
    make_user(env, "m1@example.com", role="candidate")
    make_user(env, "m2@example.com", role="candidate")
    _, _ = make_user(env, "other-recruiter@example.com")  # recruiters are not candidates
    with env.session.SessionLocal() as db:
        db.add(User(email="unverified@example.com", full_name="Un Verified", role="candidate", email_verified=False))
        db.add(User(email="gone@example.com", full_name="Sus Pended", role="candidate", email_verified=True, status="suspended"))
        db.commit()
    d = overview(env, h)
    k = {x["key"]: x for x in d["kpis"]}
    assert k["pool"]["value"] == 2 and k["pool"]["sub"] == "0 uploaded · 2 Hiriq members"
    assert d["empty"] is True and d["skills_pool"] == 0  # members alone do not make the recruiter's own account non-empty


# ---------- sample-data seeder ----------
def test_seed_adds_labelled_sample_data_and_clear_removes_only_that(env):
    from app.db.recruiter_models import Candidate, Job
    import uuid

    seed = importlib.import_module("app.db.seed_recruiter_demo")
    seed = importlib.reload(seed)
    uid, h = make_user(env, "r@example.com")
    _, other = make_user(env, "o@example.com", role="candidate")
    real_job = Job(owner_id=uuid.UUID(uid), title="My real job", status="open", skills_required=["Excel"])
    add(env, real_job, Candidate(owner_id=uuid.UUID(uid), full_name="Real Person", file_hash="real", skills=["Excel"]))

    assert "Added 5 sample jobs and 12 sample candidates" in seed.main(["r@example.com"])
    assert "already there" in seed.main(["r@example.com"])
    d = overview(env, h)
    assert d["has_demo"] is True and d["empty"] is False
    k = {x["key"]: x for x in d["kpis"]}
    assert k["open"]["value"] == 4 and k["closed"]["value"] == 1 and k["pool"]["value"] == 14  # 13 uploads + 1 member
    assert d["funnel"][0]["count"] > 0 and d["activity"] and d["match_quality"]
    assert any(s["jobs"] >= 1 for s in d["skills_in_demand"])

    assert "Removed 5 sample jobs and 12 sample candidates" in seed.main(["r@example.com", "--clear"])
    d = overview(env, h)
    assert d["has_demo"] is False
    k = {x["key"]: x for x in d["kpis"]}
    assert k["open"]["value"] == 1 and k["pool"]["value"] == 2  # the real job and upload survived (+1 member)
    assert d["funnel"][0]["count"] == 0 and d["activity"] == []


def test_seed_refuses_non_recruiters_and_unknown_emails(env):
    seed = importlib.reload(importlib.import_module("app.db.seed_recruiter_demo"))
    make_user(env, "c@example.com", role="candidate")
    with pytest.raises(SystemExit, match="not a recruiter"):
        seed.main(["c@example.com"])
    with pytest.raises(SystemExit, match="No account"):
        seed.main(["nobody@example.com"])


def test_tables_exist(env):
    from sqlalchemy import inspect

    names = set(inspect(env.session.engine).get_table_names())
    assert {"jobs", "candidates", "job_matches", "pipeline_entries", "match_feedback", "recruiter_events"} <= names
