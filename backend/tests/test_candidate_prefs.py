"""Job preferences: cleaning, saving, who can see them, and the small first fetch after a save. The feed's network call is a stand-in."""
import importlib
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from test_candidate import ME, make_user, ready
from test_candidate_discover import RELOAD as BASE, indeed, item

RELOAD = BASE + ["app.services.prefs", "app.routers.candidate_prefs"]
P = f"{ME}/preferences"


class Env:
    pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    monkeypatch.setenv("RAPIDAPI_KEY", "")
    for k in ("EXTERNAL_DAILY_CAP", "EXTERNAL_MONTHLY_CAP", "EXTERNAL_SAVE_FETCH_CALLS"):
        monkeypatch.delenv(k, raising=False)
    mods = {n: importlib.reload(importlib.import_module(n)) for n in RELOAD}
    mods["app.db.init_db"].init_db()
    from fastapi import FastAPI

    e = Env()
    e.mods, e.session, e.security, e.ext, e.prefs = mods, mods["app.db.session"], importlib.import_module("app.core.security"), mods["app.services.externaljobs"], mods["app.services.prefs"]
    app = FastAPI()
    app.include_router(mods["app.routers.candidate"].router, prefix="/api/candidate")
    app.include_router(mods["app.routers.candidate_prefs"].router, prefix="/api/candidate")
    e.client = TestClient(app)
    return e


def feed(env, monkeypatch, body=None):
    monkeypatch.setenv("RAPIDAPI_KEY", "k")
    env.sent = []

    def fake(params):
        env.sent.append(params)
        if isinstance(body, Exception):
            raise body
        return body if body is not None else indeed(item(len(env.sent), f"Job {len(env.sent)}"))

    monkeypatch.setattr(env.ext, "_get", fake)


def put(env, h, **body):
    return env.client.put(P, headers=h, json=body)


def kept(env):
    from app.db.recruiter_models import ExternalJob

    with env.session.SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(ExternalJob))


# ---------------------------------------------------------------- access and reading
def test_only_candidates_can_use_preferences(env):
    _, rect = make_user(env, "r1@example.com", role="recruiter")
    for m in ("get", "delete"):
        assert getattr(env.client, m)(P, headers=rect).status_code == 403
        assert getattr(env.client, m)(P).status_code == 401
    assert env.client.put(P, headers=rect, json={}).status_code == 403 and env.client.put(P, json={}).status_code == 401


def test_a_new_candidate_has_empty_preferences_and_the_limits(env):
    _, h = ready(env)
    b = env.client.get(P, headers=h).json()
    assert b["locations"] == b["roles"] == b["job_types"] == b["work_modes"] == [] and b["last_refreshed_at"] is None
    assert b["limits"] == {"locations": 5, "roles": 5} and b["feed_on"] is False
    assert b["options"] == {"job_types": ["full-time", "part-time", "contract", "internship"], "work_modes": ["onsite", "hybrid", "remote"]}


# ---------------------------------------------------------------- saving and cleaning
def test_save_edit_and_delete_by_sending_the_new_lists(env):
    _, h = ready(env)
    r = put(env, h, locations=["Mumbai", "Pune"], roles=["Data Analyst"], job_types=["part-time", "full-time"], work_modes=["remote", "hybrid"])
    assert r.status_code == 200, r.text
    assert r.json()["job_types"] == ["full-time", "part-time"] and r.json()["work_modes"] == ["hybrid", "remote"]       # always in the same order
    r = put(env, h, locations=["Pune"], roles=["Data Analyst", "BI Analyst"], job_types=["full-time"], work_modes=[])    # edit one, delete others
    assert env.client.get(P, headers=h).json()["locations"] == ["Pune"] and r.json()["roles"] == ["Data Analyst", "BI Analyst"]
    assert put(env, h).json()["roles"] == []                                                                            # an empty body clears the lists
    assert env.client.delete(P, headers=h).status_code == 200


def test_entries_are_trimmed_deduplicated_and_checked(env):
    _, h = ready(env)
    r = put(env, h, locations=["  Navi   Mumbai ", "navi mumbai", "", "Pune"], roles=["Data Analyst", "data analyst", " "])
    assert r.json()["locations"] == ["Navi Mumbai", "Pune"] and r.json()["roles"] == ["Data Analyst"]
    for bad in ({"roles": ["<script>alert(1)</script>"]}, {"roles": ["x"]}, {"locations": ["a" * 81]}, {"roles": [str(i) + "ab" for i in range(6)]},
                {"locations": [f"City {i}" for i in range(6)]}, {"job_types": ["gig"]}, {"work_modes": ["moon"]}, {"roles": "analyst"},
                {"roles": [5]}, {"surprise": 1}):
        assert put(env, h, **bad).status_code == 422, bad
    assert env.client.get(P, headers=h).json()["roles"] == ["Data Analyst"]                                              # a bad save changes nothing


def test_each_candidate_has_their_own_preferences(env):
    _, a = ready(env)
    _, b = make_user(env, "other@example.com")
    put(env, a, roles=["Data Analyst"])
    assert env.client.get(P, headers=b).json()["roles"] == []


def test_delete_clears_everything(env):
    _, h = ready(env)
    put(env, h, roles=["Data Analyst"], locations=["Pune"])
    assert env.client.delete(P, headers=h).json()["roles"] == []
    assert env.client.get(P, headers=h).json()["locations"] == []


def test_saving_does_not_touch_the_refresh_time(env, monkeypatch):
    _, h = ready(env)
    put(env, h, roles=["Data Analyst"])
    from app.db.recruiter_models import CandidatePreference

    stamp = datetime(2026, 11, 1, tzinfo=timezone.utc)
    with env.session.SessionLocal() as db:
        db.scalars(select(CandidatePreference)).one().last_refreshed_at = stamp
        db.commit()
    put(env, h, roles=["Data Analyst", "BI Analyst"])
    assert env.client.get(P, headers=h).json()["last_refreshed_at"].startswith("2026-11-01")


# ---------------------------------------------------------------- the first fetch
def test_feed_off_means_no_fetch(env):
    _, h = ready(env)
    r = put(env, h, roles=["Data Analyst"])
    assert r.json()["fetching"] is False and kept(env) == 0


def test_saving_new_roles_fetches_a_few_jobs_into_the_database(env, monkeypatch):
    feed(env, monkeypatch)
    _, h = ready(env)
    r = put(env, h, roles=["Data Analyst", "BI Analyst"], locations=["Pune", "Mumbai"])
    assert r.json()["fetching"] is True
    assert [(s["query"], s.get("location")) for s in env.sent] == [("Data Analyst", "Pune"), ("BI Analyst", "Pune")]     # at most 2 searches, one per role first
    assert kept(env) == 2


def test_roles_with_no_place_search_everywhere(env, monkeypatch):
    feed(env, monkeypatch)
    _, h = ready(env)
    put(env, h, roles=["Data Analyst"])
    assert env.sent[0]["query"] == "Data Analyst" and "location" not in env.sent[0]


def test_nothing_is_fetched_when_only_job_type_or_work_mode_change_or_nothing_changes(env, monkeypatch):
    feed(env, monkeypatch)
    _, h = ready(env)
    put(env, h, roles=["Data Analyst"], locations=["Pune"])
    n = len(env.sent)
    r = put(env, h, roles=["data analyst"], locations=["PUNE"], job_types=["contract"], work_modes=["remote"])           # same search
    assert r.json()["fetching"] is False and len(env.sent) == n
    assert put(env, h, roles=[], locations=["Pune"]).json()["fetching"] is False and len(env.sent) == n                  # nothing to search for


def test_a_failing_feed_never_breaks_the_save(env, monkeypatch):
    feed(env, monkeypatch, env.ext.ExternalError("unavailable", "down", 502))
    _, h = ready(env)
    r = put(env, h, roles=["Data Analyst"])
    assert r.status_code == 200 and kept(env) == 0 and env.client.get(P, headers=h).json()["roles"] == ["Data Analyst"]


def test_fetched_jobs_are_not_duplicated_by_a_second_save(env, monkeypatch):
    feed(env, monkeypatch, indeed(item(1, "Same"), item(2, "Other")))
    _, h = ready(env)
    put(env, h, roles=["Data Analyst"])
    put(env, h, roles=["BI Analyst"])
    assert kept(env) == 2


# ---------------------------------------------------------------- the monthly allowance
def test_the_monthly_allowance_stops_the_feed_even_after_a_restart(env, monkeypatch):
    feed(env, monkeypatch)
    monkeypatch.setenv("EXTERNAL_MONTHLY_CAP", "2")
    _, h = ready(env)
    put(env, h, roles=["A Role", "B Role", "C Role"])                              # two searches use the allowance
    assert len(env.sent) == 2 and env.ext.used_this_month() == 2
    env.ext._cache.clear()
    env.ext._day.update(date=None, count=0)                                        # as if the server had restarted
    with pytest.raises(env.ext.ExternalError) as e:
        env.ext.search("Another", "")
    assert e.value.code == "monthly_limit" and len(env.sent) == 2


def test_calls_from_last_month_do_not_count(env):
    from app.db.recruiter_models import ExternalCall

    with env.session.SessionLocal() as db:
        db.add(ExternalCall(provider="indeed", ok=True, created_at=datetime(2020, 1, 5, tzinfo=timezone.utc)))
        db.commit()
    assert env.ext.used_this_month() == 0
