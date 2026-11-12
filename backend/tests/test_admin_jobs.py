"""Admin jobs and sources (create, read, edit, delete for portal and outside jobs) and the RapidAPI usage block."""
import importlib
import uuid

import pytest
from fastapi.testclient import TestClient

RELOAD = ["app.core.config", "app.db.session", "app.db.init_db", "app.core.deps", "app.routers.jobs", "app.routers.admin_jobs",
          "app.routers.admin_ai", "app.services.externaljobs"]


class Env:
    pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    monkeypatch.setenv("RAPIDAPI_KEY", "k")
    monkeypatch.setenv("EXTERNAL_DAILY_CAP", "100")
    mods = {n: importlib.reload(importlib.import_module(n)) for n in RELOAD}
    mods["app.db.init_db"].init_db()
    e = Env()
    e.mods, e.session, e.security = mods, mods["app.db.session"], importlib.import_module("app.core.security")
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(mods["app.routers.admin_jobs"].router, prefix="/api/admin")
    app.include_router(mods["app.routers.admin_ai"].router, prefix="/api/admin")
    e.client = TestClient(app)
    return e


def make_user(env, email, role="admin", company=None):
    from app.db.models import User

    with env.session.SessionLocal() as db:
        u = User(email=email, full_name=email.split("@")[0].title(), role=role, email_verified=True, status="active", company=company)
        db.add(u)
        db.commit()
        uid = str(u.id)
    return uid, {"Authorization": f"Bearer {env.security.create_token(uid, role, 'x' * 40, 8)}"}


JD = ("We are hiring an analyst to build dashboards, own reporting and work with the business every day. " * 2).strip()
BODY = {"title": "Data Analyst", "location": "Mumbai", "skills_required": ["SQL", "Python"], "description": JD}


def test_only_admins(env):
    _, rec = make_user(env, "r@example.com", role="recruiter")
    assert env.client.get("/api/admin/jobs").status_code == 401
    assert env.client.get("/api/admin/jobs", headers=rec).status_code == 403
    assert env.client.post("/api/admin/jobs/portal", headers=rec, json=BODY).status_code == 403
    assert env.client.delete(f"/api/admin/jobs/outside/{uuid.uuid4()}", headers=rec).status_code == 403


def test_portal_job_crud_and_audit(env):
    admin_id, h = make_user(env, "root@example.com")
    rec_id, _ = make_user(env, "rita@example.com", role="recruiter", company="Acme")
    r = env.client.post("/api/admin/jobs/portal", headers=h, json={**BODY, "owner_id": rec_id})
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["status"] == "draft" and job["owner_id"] == rec_id and job["company"] == "Acme" and job["skills_required"] == ["SQL", "Python"]

    # opening needs a description and a skill, like the recruiter's own screen
    bad = env.client.put(f"/api/admin/jobs/portal/{job['id']}", headers=h, json={"title": "Data Analyst", "status": "open"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "need_description"
    opened = env.client.put(f"/api/admin/jobs/portal/{job['id']}", headers=h, json={**BODY, "title": "Senior Data Analyst", "status": "open"})
    assert opened.status_code == 200 and opened.json()["status"] == "open" and opened.json()["title"] == "Senior Data Analyst"

    listed = env.client.get("/api/admin/jobs", headers=h, params={"source": "portal", "status": "open"}).json()
    assert [j["title"] for j in listed["jobs"]] == ["Senior Data Analyst"]
    assert listed["summary"]["portal"] == {"total": 1, "open": 1, "draft": 0, "closed": 0}
    assert any(o["id"] == rec_id for o in listed["owners"])

    closed = env.client.put(f"/api/admin/jobs/portal/{job['id']}", headers=h, json={**BODY, "status": "closed"})
    assert closed.json()["status"] == "closed"

    assert env.client.get(f"/api/admin/jobs/portal/{job['id']}", headers=h).json()["description"] == JD
    assert env.client.delete(f"/api/admin/jobs/portal/{job['id']}", headers=h).json() == {"status": "deleted"}
    assert env.client.get(f"/api/admin/jobs/portal/{job['id']}", headers=h).status_code == 404

    from sqlalchemy import select
    from app.db.models import AuditLog
    with env.session.SessionLocal() as db:
        events = [a.action for a in db.scalars(select(AuditLog).where(AuditLog.category == "Data").order_by(AuditLog.id))]
    assert events[0].startswith("created the job Data Analyst") and events[-1] == "deleted the job Data Analyst"


def test_portal_job_defaults_to_the_admin_and_checks_owner(env):
    admin_id, h = make_user(env, "root@example.com")
    cand_id, _ = make_user(env, "cat@example.com", role="candidate")
    mine = env.client.post("/api/admin/jobs/portal", headers=h, json=BODY).json()
    assert mine["owner_id"] == admin_id
    assert env.client.post("/api/admin/jobs/portal", headers=h, json={**BODY, "owner_id": cand_id}).json()["detail"]["code"] == "bad_owner"
    assert env.client.post("/api/admin/jobs/portal", headers=h, json={"title": "x"}).status_code == 422
    assert env.client.post("/api/admin/jobs/portal", headers=h, json={**BODY, "experience_min": 9, "experience_max": 2}).status_code == 422


def test_outside_job_crud(env):
    _, h = make_user(env, "root@example.com")
    r = env.client.post("/api/admin/jobs/outside", headers=h, json={"title": "BI Analyst", "company": "Zeta", "location": "Pune",
                                                                    "apply_url": "https://example.com/apply", "description": "Reports."})
    assert r.status_code == 201 and r.json()["provider"] == "Added by hand" and r.json()["source"] == "outside"
    jid = r.json()["id"]
    assert env.client.post("/api/admin/jobs/outside", headers=h, json={"title": "BI Analyst", "apply_url": "javascript:alert(1)"}).status_code == 422
    up = env.client.put(f"/api/admin/jobs/outside/{jid}", headers=h, json={"title": "Lead BI Analyst", "remote": True})
    assert up.status_code == 200 and up.json()["title"] == "Lead BI Analyst" and up.json()["remote"] is True and up.json()["apply_url"] is None

    both = env.client.get("/api/admin/jobs", headers=h).json()
    assert both["summary"]["outside"]["total"] == 1 and both["summary"]["outside"]["sources"] == [{"name": "Added by hand", "count": 1}]
    assert env.client.get("/api/admin/jobs", headers=h, params={"source": "outside", "q": "lead"}).json()["jobs"][0]["title"] == "Lead BI Analyst"
    assert env.client.get("/api/admin/jobs", headers=h, params={"source": "outside", "q": "nothing"}).json()["jobs"] == []
    assert env.client.delete(f"/api/admin/jobs/outside/{jid}", headers=h).status_code == 200
    assert env.client.delete(f"/api/admin/jobs/outside/{jid}", headers=h).status_code == 404
    assert env.client.get("/api/admin/jobs/outside/not-a-uuid", headers=h).status_code == 404


def test_list_mixes_both_sources(env):
    _, h = make_user(env, "root@example.com")
    env.client.post("/api/admin/jobs/portal", headers=h, json=BODY)
    env.client.post("/api/admin/jobs/outside", headers=h, json={"title": "Analyst elsewhere"})
    d = env.client.get("/api/admin/jobs", headers=h).json()
    assert {j["source"] for j in d["jobs"]} == {"portal", "outside"}
    assert env.client.get("/api/admin/jobs", headers=h, params={"status": "open"}).json()["jobs"] == []   # outside jobs have no status


def test_rapidapi_usage_is_logged_and_reported(env):
    _, h = make_user(env, "root@example.com")
    ext = env.mods["app.services.externaljobs"]
    item = {"id": "a1", "title": "Analyst", "company": {"name": "Zeta"}, "location": {"location": "Pune"}, "applyUrl": "https://x.example/1"}
    ext._get = lambda params: {"data": [item], "meta": {}}
    assert len(ext.search("analyst", "pune")["jobs"]) == 1
    ext.search("analyst", "pune")                                    # served from the cache: not a request to RapidAPI

    def boom(params):
        raise ext.ExternalError("feed_busy", "busy")
    ext._get = boom
    with pytest.raises(ext.ExternalError):
        ext.search("designer")

    d = env.client.get("/api/admin/ai-usage", headers=h).json()["rapidapi"]
    assert d["configured"] is True and d["calls"] == 2 and d["ok"] == 1 and d["failed"] == 1 and d["success_rate"] == 50
    assert d["posts"] == 1 and d["errors"] == [{"reason": "feed_busy", "count": 1}] and d["used_today"] == 2
    assert d["daily_cap"] == 100 and sum(d["daily"]["values"]) == 2
