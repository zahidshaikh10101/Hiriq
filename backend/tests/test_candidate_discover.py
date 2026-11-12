"""Candidate recommendations (open Hiriq jobs ranked by fit) and the outside job feed. The feed's network call is a stand-in."""
import importlib

import pytest
from fastapi.testclient import TestClient

from test_candidate import ME, make_job, make_user, profile_body, ready

RELOAD = ["app.core.config", "app.db.session", "app.db.init_db", "app.db.upgrade", "app.core.deps", "app.services.llm",
          "app.services.resume_text", "app.services.resume", "app.services.matching", "app.services.jobread", "app.services.externaljobs",
          "app.routers.candidates", "app.routers.matches", "app.routers.candidate", "app.routers.candidate_discover"]


class Env:
    pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    monkeypatch.delenv("EXTERNAL_DAILY_CAP", raising=False)
    mods = {n: importlib.reload(importlib.import_module(n)) for n in RELOAD}
    mods["app.db.init_db"].init_db()
    e = Env()
    e.mods, e.session, e.security = mods, mods["app.db.session"], importlib.import_module("app.core.security")
    e.ext, e.discover = mods["app.services.externaljobs"], mods["app.routers.candidate_discover"]
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(mods["app.routers.candidate"].router, prefix="/api/candidate")
    app.include_router(mods["app.routers.candidate_discover"].router, prefix="/api/candidate")
    e.client = TestClient(app)
    return e


def jobs(env):
    rid = make_user(env, "r@example.com", role="recruiter")[0]
    ids = {"Alpha": make_job(env, rid, title="Alpha", skills_required=["SQL", "Python"], skills_nice=[], work_mode="remote"),
           "Beta": make_job(env, rid, title="Beta", skills_required=["SQL", "Python", "Power BI"], skills_nice=[]),
           "Gamma": make_job(env, rid, title="Gamma", skills_required=["Kubernetes", "Terraform", "Figma"], skills_nice=[])}
    make_job(env, rid, title="No skills", skills_required=[], skills_nice=[])
    make_job(env, rid, title="Closed", status="closed")
    make_job(env, rid, title="Draft", status="draft")
    return ids


def rec(env, h, **params):
    return env.client.get(f"{ME}/recommendations", headers=h, params=params)


# ---------------------------------------------------------------- recommendations
def test_only_candidates_and_a_profile_are_needed(env):
    _, rect = make_user(env, "r1@example.com", role="recruiter")
    for path in ("/recommendations", "/external/status", "/external?q=data"):
        assert env.client.get(f"{ME}{path}", headers=rect).status_code == 403, path
        assert env.client.get(f"{ME}{path}").status_code == 401, path
    _, empty = make_user(env, "empty@example.com")
    r = rec(env, empty)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_profile"


def test_open_jobs_are_ranked_by_fit_with_the_reason_and_the_gaps(env):
    ids = jobs(env)
    _, h = ready(env)
    r = rec(env, h, min_score=0)
    assert r.status_code == 200, r.text
    body = r.json()
    titles = [j["title"] for j in body["recommended"]]
    assert titles == ["Alpha", "Beta", "Gamma"] and body["considered"] == 3                         # open jobs with skills only
    a, b, g = body["recommended"]
    assert a["fit"]["score"] > b["fit"]["score"] > g["fit"]["score"]
    assert a["matched"] == ["SQL", "Python"] and a["gaps"] == [] and a["reason"].startswith("You show 2 of 2 required skills")
    assert b["gaps"] == ["Power BI"] and "Missing: Power BI" in b["reason"]
    assert g["matched"] == [] and g["gaps"] == ["Kubernetes", "Terraform", "Figma"]
    for j in body["recommended"]:
        assert "explanation" not in j["fit"] and "owner_id" not in j and "parts" not in j["fit"]
    assert body["strong"] == sum(1 for j in body["recommended"] if j["fit"]["score"] >= 70)


def test_weak_fits_are_hidden_but_counted_and_filters_work(env):
    ids = jobs(env)
    _, h = ready(env)
    all_ = rec(env, h, min_score=0).json()["recommended"]
    beta = next(j for j in all_ if j["title"] == "Beta")["fit"]["score"]
    r = rec(env, h, min_score=beta).json()
    assert [j["title"] for j in r["recommended"]] == ["Alpha", "Beta"] and r["hidden_below"] == 1
    assert [j["title"] for j in rec(env, h, min_score=0, work_mode="remote").json()["recommended"]] == ["Alpha"]
    assert len(rec(env, h, min_score=0, limit=2).json()["recommended"]) == 2
    assert rec(env, h, work_mode="sideways").status_code == 422 and rec(env, h, min_score=101).status_code == 422


def test_scores_refresh_by_themselves_when_you_or_the_job_change(env):
    ids = jobs(env)
    uid, h = ready(env)
    before = {j["title"]: j["fit"]["score"] for j in rec(env, h, min_score=0).json()["recommended"]}
    assert env.client.put(f"{ME}/profile", headers=h, json=profile_body(skills=["SQL", "Python", "Power BI"])).status_code == 200
    after = {j["title"]: j["fit"] for j in rec(env, h, min_score=0).json()["recommended"]}
    assert after["Beta"]["score"] > before["Beta"] and after["Beta"]["stale"] is False


def test_where_you_live_does_not_change_the_ranking(env):
    jobs(env)
    _, h = ready(env)
    a = {j["title"]: j["fit"]["score"] for j in rec(env, h, min_score=0).json()["recommended"]}
    assert env.client.put(f"{ME}/profile", headers=h, json=profile_body(location="Chennai")).status_code == 200
    assert {j["title"]: j["fit"]["score"] for j in rec(env, h, min_score=0).json()["recommended"]} == a


# ---------------------------------------------------------------- the outside feed
def indeed(*items, token=None):
    return {"data": list(items), "meta": {"position": 0, "count": len(items), "nextToken": token}, "errors": [], "hasError": False}


def item(i, title="Data Analyst", desc="We use SQL and Python every day.", **over):
    base = {"id": f"id-{i}", "title": title, "company": {"name": "Acme", "addresses": [], "image": ""},
            "location": {"country": "India", "countryCode": "IN", "location": "Pune, Maharashtra"}, "description": desc,
            "applyUrl": "https://acme.example/apply", "datePublishedTimestamp": 1793577600000, "dateOnIndeedTimestamp": 1793600000000}
    base.update(over)
    return base


def feed(env, monkeypatch, body=None, key="k"):
    monkeypatch.setenv("RAPIDAPI_KEY", key)
    env.sent = []

    def fake(params):
        env.sent.append(params)
        if isinstance(body, Exception):
            raise body
        return body if body is not None else indeed(item(1))

    monkeypatch.setattr(env.ext, "_get", fake)


def test_the_feed_is_off_until_a_key_is_set(env):
    _, h = ready(env)
    assert env.client.get(f"{ME}/external/status", headers=h).json() == {"configured": False}
    r = env.client.get(f"{ME}/external", headers=h, params={"q": "data analyst"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "not_configured"


def test_outside_jobs_show_which_of_your_skills_they_mention(env, monkeypatch):
    _, h = ready(env)                                                    # skills: SQL, Python
    feed(env, monkeypatch, indeed(item(1, "Backend Dev", "We run MySQL and Java."), item(2, "Analyst", "SQL and Python required."),
                                  item(3, "Remote Sneaky", "x", applyUrl="javascript:alert(1)")))
    assert env.client.get(f"{ME}/external/status", headers=h).json() == {"configured": True}
    r = env.client.get(f"{ME}/external", headers=h, params={"q": "analyst", "location": "Pune"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [j["title"] for j in body["jobs"]] == ["Analyst", "Backend Dev", "Remote Sneaky"] and body["your_skills"] == 2
    assert body["jobs"][0]["skills_in_posting"] == ["SQL", "Python"] and body["jobs"][1]["skills_in_posting"] == []   # "MySQL" is not "SQL"
    assert body["jobs"][2]["apply_url"] is None and body["jobs"][0]["apply_url"] == "https://acme.example/apply"
    assert body["jobs"][0]["location"] == "Pune, Maharashtra" and "score" not in body["jobs"][0]
    assert body["jobs"][0]["posted_at"] == "2026-11-02T00:00:00Z" and body["jobs"][0]["source"] == "Indeed" and body["jobs"][0]["remote"] is False
    assert body["jobs"][2]["remote"] is True and body["radius"] == 20 and body["has_more"] is False
    assert env.sent[0] == {"query": "analyst", "location": "Pune", "radius": "20", "radiusType": "km", "sortType": "relevance", "countryCode": "in"}


def test_repeat_searches_are_cached_and_limited(env, monkeypatch):
    _, h = ready(env)
    feed(env, monkeypatch)
    g = lambda q: env.client.get(f"{ME}/external", headers=h, params={"q": q})
    assert g("data analyst").status_code == 200 and g("Data   Analyst").status_code == 200 and len(env.sent) == 1     # same search, one paid call
    monkeypatch.setattr(env.discover, "EXTERNAL_PER_HOUR", 3)
    assert g("sql developer").status_code == 200
    r = g("python developer")
    assert r.status_code == 429 and r.json()["detail"]["code"] == "slow_down"


def test_the_whole_server_has_a_daily_cap(env, monkeypatch):
    _, h = ready(env)
    feed(env, monkeypatch)
    monkeypatch.setenv("EXTERNAL_DAILY_CAP", "1")
    g = lambda q: env.client.get(f"{ME}/external", headers=h, params={"q": q})
    assert g("one search").status_code == 200
    r = g("another search")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "feed_busy" and len(env.sent) == 1


def test_feed_failures_are_explained_not_leaked(env, monkeypatch):
    _, h = ready(env)
    g = lambda q: env.client.get(f"{ME}/external", headers=h, params={"q": q})
    feed(env, monkeypatch, body=env.ext.ExternalError("feed_key", "The job feed key is not accepted.", 502))
    r = g("one")
    assert r.status_code == 502 and r.json()["detail"]["code"] == "feed_key" and "k" != r.json()["detail"]["message"]
    feed(env, monkeypatch, body={"hasError": True, "errors": [{"message": "secret internals"}], "data": []})
    r = g("two")
    assert r.status_code == 502 and "secret" not in r.text
    assert g("x").status_code == 422 and env.client.get(f"{ME}/external", headers=h, params={"q": "ok", "page": 9}).status_code == 422


def test_odd_results_are_cleaned(env, monkeypatch):
    _, h = ready(env)
    feed(env, monkeypatch, indeed({"title": "No id"}, "not a dict", item(1, "<script>x</script>", "y" * 9000, datePublishedTimestamp=-5, dateOnIndeedTimestamp="soon")))
    body = env.client.get(f"{ME}/external", headers=h, params={"q": "odd"}).json()
    assert len(body["jobs"]) == 1 and len(body["jobs"][0]["description"]) == 6000 and body["jobs"][0]["posted_at"] is None


def test_later_pages_follow_the_token_of_the_page_before(env, monkeypatch):
    _, h = ready(env)
    feed(env, monkeypatch, indeed(item(1), token="TOK-2"))
    g = lambda **p: env.client.get(f"{ME}/external", headers=h, params={"q": "data scientist", "location": "Mumbai", **p})
    r = g(page=2)                                                         # nobody has seen page 1 yet: no token to follow
    assert r.status_code == 409 and r.json()["detail"]["code"] == "start_over" and env.sent == []
    first = g(radius=50)
    assert first.status_code == 200 and first.json()["has_more"] is True and env.sent[0]["radius"] == "50"
    assert g(page=2, radius=50).status_code == 200 and env.sent[1] == {"token": "TOK-2"}


def test_a_bad_radius_is_refused(env, monkeypatch):
    _, h = ready(env)
    feed(env, monkeypatch)
    assert env.client.get(f"{ME}/external", headers=h, params={"q": "data", "radius": 1}).status_code == 422
    assert env.client.get(f"{ME}/external", headers=h, params={"q": "data", "radius": 500}).status_code == 422
