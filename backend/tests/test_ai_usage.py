"""Phase 7: the admin AI-usage panel's API, and the Overview's skills card following the same pool rule as Candidates."""
import importlib
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

RELOAD = ["app.core.config", "app.db.session", "app.db.init_db", "app.core.deps", "app.routers.candidates",
          "app.routers.recruiter", "app.routers.admin_ai"]


class Env:
    pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    mods = {n: importlib.reload(importlib.import_module(n)) for n in RELOAD}
    mods["app.db.init_db"].init_db()
    e = Env()
    e.mods, e.session, e.security = mods, mods["app.db.session"], importlib.import_module("app.core.security")
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(mods["app.routers.admin_ai"].router, prefix="/api/admin")
    app.include_router(mods["app.routers.recruiter"].router, prefix="/api/recruiter")
    e.client = TestClient(app)
    return e


def make_user(env, email, role="admin", status="active", verified=True, username=None, visible=True):
    from app.db.models import User

    with env.session.SessionLocal() as db:
        u = User(email=email, full_name=email.split("@")[0].title(), role=role, email_verified=verified, status=status, username=username)
        db.add(u)
        db.commit()
        uid = str(u.id)
        if role == "candidate" and visible:   # members are hidden from recruiters until they opt in; these tests act as opted-in members
            from app.db.recruiter_models import Candidate

            db.add(Candidate(user_id=u.id, source="platform", full_name=u.full_name, skills=[], visible_to_recruiters=True))
            db.commit()
    return uid, {"Authorization": f"Bearer {env.security.create_token(uid, role, 'x' * 40, 8)}"}


def call(env, owner, purpose="jd", model="m/one:free", ok=True, error=None, latency=1000, pt=10, ct=5, age_days=0.0):
    from app.db.recruiter_models import AiCall
    from app.services.timeutil import now

    with env.session.SessionLocal() as db:
        db.add(AiCall(owner_id=uuid.UUID(owner) if owner else None, purpose=purpose, model=model, ok=ok, error=error, latency_ms=latency,
                      prompt_tokens=pt, completion_tokens=ct, created_at=now() - timedelta(days=age_days, minutes=1)))
        db.commit()


def usage(env, h, **q):
    return env.client.get("/api/admin/ai-usage", headers=h, params=q)


def test_only_admins_may_read_it(env):
    _, rec = make_user(env, "r@example.com", role="recruiter")
    _, cand = make_user(env, "c@example.com", role="candidate")
    assert usage(env, {}).status_code == 401
    assert usage(env, rec).status_code == 403 and usage(env, cand).status_code == 403


def test_with_no_calls_everything_is_empty_not_invented(env):
    _, h = make_user(env, "a@example.com")
    d = usage(env, h).json()
    assert d["totals"]["calls"] == 0 and d["totals"]["success_rate"] is None and d["totals"]["avg_latency_ms"] is None
    assert d["by_purpose"] == [] and d["by_model"] == [] and d["errors"] == [] and d["recent_failures"] == [] and d["top_users"] == []
    assert sum(d["daily"]["values"]) == 0 and len(d["daily"]["values"]) == len(d["daily"]["labels"]) == 7 and d["key_set"] is True


def test_totals_split_by_feature_and_model(env):
    _, h = make_user(env, "a@example.com")
    r1, _ = make_user(env, "r1@example.com", role="recruiter")
    call(env, r1, "jd", "m/one:free", True, latency=1000, pt=100, ct=50)
    call(env, r1, "jd", "m/one:free", False, "http 429: rate limited", latency=200)
    call(env, r1, "parse", "m/two:free", True, latency=3000, pt=400, ct=100)
    call(env, r1, "ask", "m/two:free", True, latency=2000)
    d = usage(env, h).json()
    t = d["totals"]
    assert (t["calls"], t["ok"], t["failed"], t["success_rate"]) == (4, 3, 1, 75) and t["avg_latency_ms"] == 1550
    assert (t["prompt_tokens"], t["completion_tokens"]) == (100 + 10 + 400 + 10, 50 + 5 + 100 + 5)
    by = {p["purpose"]: p for p in d["by_purpose"]}
    assert by["jd"]["label"] == "JD writer" and by["jd"]["calls"] == 2 and by["jd"]["failed"] == 1 and by["jd"]["success_rate"] == 50
    assert by["parse"]["label"] == "Resume reader" and by["ask"]["label"] == "Ask the pool"
    assert [p["purpose"] for p in d["by_purpose"]][0] == "jd"                                   # busiest first
    models = {m["model"]: m for m in d["by_model"]}
    assert models["m/one:free"]["calls"] == 2 and models["m/two:free"]["success_rate"] == 100


def test_failures_are_grouped_by_kind_and_listed_newest_first(env):
    _, h = make_user(env, "a@example.com")
    r, _ = make_user(env, "r@example.com", role="recruiter")
    for msg in ("http 429: rate limited", "http 429: busy", "http 500: oops", "bad_output"):
        call(env, r, "match", "m/x:free", False, msg)
    d = usage(env, h).json()
    assert d["errors"][0] == {"reason": "http 429", "count": 2} and {e["reason"] for e in d["errors"]} == {"http 429", "http 500", "bad_output"}
    assert len(d["recent_failures"]) == 4 and d["recent_failures"][0]["purpose"] == "Matching AI check" and d["recent_failures"][0]["error"]


def test_the_range_decides_what_counts_and_the_previous_period_is_reported(env):
    _, h = make_user(env, "a@example.com")
    r, _ = make_user(env, "r@example.com", role="recruiter")
    call(env, r, age_days=1)
    call(env, r, age_days=10)                                                                   # outside 7 days, inside 30
    call(env, r, age_days=20)
    week, month = usage(env, h, range="7d").json(), usage(env, h, range="30d").json()
    assert week["totals"]["calls"] == 1 and week["totals"]["previous_calls"] == 1
    assert month["totals"]["calls"] == 3 and len(month["daily"]["values"]) == 30
    assert len(usage(env, h, range="90d").json()["daily"]["values"]) == 13
    assert usage(env, h, range="1y").status_code == 422


def test_the_daily_series_counts_attempts_and_failures(env):
    _, h = make_user(env, "a@example.com")
    r, _ = make_user(env, "r@example.com", role="recruiter")
    call(env, r, ok=True)
    call(env, r, ok=False, error="bad_output")
    call(env, r, ok=False, error="bad_output", age_days=3)
    d = usage(env, h, tz=0).json()["daily"]
    assert sum(d["values"]) == 3 and sum(d["failed"]) == 2 and d["values"][-1] == 2 and d["failed"][-1] == 1


def test_who_uses_it_most(env):
    _, h = make_user(env, "a@example.com")
    a, _ = make_user(env, "a1@example.com", role="recruiter", username="alpha")
    b, _ = make_user(env, "b1@example.com", role="recruiter")
    for _ in range(3):
        call(env, a)
    call(env, b)
    call(env, None)                                                                             # a deleted account's call is still counted in totals
    d = usage(env, h).json()
    assert d["top_users"] == [{"name": "alpha", "calls": 3}, {"name": "B1", "calls": 1}] and d["totals"]["calls"] == 5 and d["totals"]["users"] == 2


def test_a_missing_key_is_reported(env, monkeypatch):
    _, h = make_user(env, "a@example.com")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    assert usage(env, h).json()["key_set"] is False


# ---------------------------------------------------------------- Overview: skills in demand follows the pool rule
def test_overview_skills_ignore_suspended_and_unverified_members(env):
    from app.db.recruiter_models import Candidate, Job

    rid, rh = make_user(env, "rec@example.com", role="recruiter")
    with env.session.SessionLocal() as db:
        db.add(Job(owner_id=uuid.UUID(rid), title="Analyst", status="open", skills_required=["SQL"], skills_nice=[]))
        db.add(Candidate(owner_id=uuid.UUID(rid), source="upload", full_name="Mine", skills=["SQL"], file_hash="h1"))
        db.commit()
    ok, _ = make_user(env, "ok@example.com", role="candidate", visible=False)
    bad, _ = make_user(env, "bad@example.com", role="candidate", status="suspended", visible=False)
    new, _ = make_user(env, "new@example.com", role="candidate", verified=False, visible=False)
    with env.session.SessionLocal() as db:
        for uid, name in ((ok, "Ok"), (bad, "Bad"), (new, "New")):
            db.add(Candidate(user_id=uuid.UUID(uid), source="platform", full_name=name, skills=["SQL"], visible_to_recruiters=True))
        db.commit()
    d = env.client.get("/api/recruiter/overview", headers=rh).json()
    assert d["skills_in_demand"] == [{"skill": "SQL", "jobs": 1, "candidates": 2}]                  # my upload + the one active, verified member
    assert d["skills_pool"] == 2
