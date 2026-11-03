"""Jobs and the JD writer: ownership, validation, status rules, and the AI step (mocked)."""
import importlib
import uuid

import pytest
from fastapi.testclient import TestClient

RELOAD = ["app.core.config", "app.db.session", "app.db.init_db", "app.core.deps", "app.services.llm", "app.services.jd",
          "app.routers.jobs", "app.routers.recruiter"]


class Env:
    pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    mods = {n: importlib.reload(importlib.import_module(n)) for n in RELOAD}
    mods["app.db.init_db"].init_db()
    e = Env()
    e.mods, e.session, e.security, e.llm = mods, mods["app.db.session"], importlib.import_module("app.core.security"), mods["app.services.llm"]
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(mods["app.routers.recruiter"].router, prefix="/api/recruiter")
    app.include_router(mods["app.routers.jobs"].router, prefix="/api/recruiter")
    e.client = TestClient(app)
    return e


def make_user(env, email, role="recruiter"):
    from app.db.models import User

    with env.session.SessionLocal() as db:
        u = User(email=email, full_name=email.split("@")[0].title(), role=role, email_verified=True)
        db.add(u)
        db.commit()
        uid = str(u.id)
    return uid, {"Authorization": f"Bearer {env.security.create_token(uid, role, 'x' * 40, 8)}"}


FORM = {
    "title": "Senior Data Analyst", "department": "Analytics", "location": "Mumbai", "work_mode": "hybrid",
    "employment_type": "full-time", "experience_min": 3, "experience_max": 5, "qualification": "B.E. in IT or similar",
    "salary_min": 1200000, "salary_max": 1800000, "salary_currency": "INR",
    "skills_required": ["SQL", "Python", "sql"], "skills_nice": ["Tableau", "python"],
    "responsibilities": "Build dashboards for the sales team. Clean data in SQL. Present findings weekly.",
}
GOOD_AI = {
    "summary": "You will turn raw sales data into clear decisions for the business team.",
    "responsibilities": ["- Build weekly sales dashboards", "2) Write SQL to clean and join data", "Present findings to managers"],
    "requirements": ["3 to 5 years of analytics experience", "Strong SQL and Python"],
    "nice_to_have": ["Tableau"], "suggested_skills": ["dbt", "SQL", "Excel", "excel"],
}


def mock_ai(env, monkeypatch, payload=GOOD_AI, model="primary/model:free"):
    calls = []

    def fake(system, user, schema, **kw):
        calls.append((system, user, kw))
        return env.llm.LLMResult(data=schema.model_validate(payload), model=model)

    monkeypatch.setattr(env.llm, "complete_json", fake)
    return calls


def create(env, h, **over):
    r = env.client.post("/api/recruiter/jobs", headers=h, json={**FORM, **over})
    assert r.status_code == 201, r.text
    return r.json()


JD_TEXT = "x" * 120


def ready_job(env, h, **over):
    job = create(env, h, **over)
    r = env.client.put(f"/api/recruiter/jobs/{job['id']}", headers=h, json={**FORM, **over, "description": JD_TEXT})
    assert r.status_code == 200, r.text
    return r.json()


# ---------- access ----------
def test_every_jobs_route_needs_a_recruiter(env):
    _, cand = make_user(env, "c@example.com", role="candidate")
    _, adm = make_user(env, "a@example.com", role="admin")
    some = str(uuid.uuid4())
    calls = [("get", "/jobs"), ("post", "/jobs"), ("post", "/jobs/generate"), ("get", f"/jobs/{some}"), ("put", f"/jobs/{some}"),
             ("post", f"/jobs/{some}/publish"), ("post", f"/jobs/{some}/close"), ("post", f"/jobs/{some}/clone"), ("delete", f"/jobs/{some}")]
    for method, path in calls:
        url = "/api/recruiter" + path
        kw = {"json": FORM} if method in ("post", "put") else {}
        assert getattr(env.client, method)(url, **kw).status_code == 401, (method, path)
        assert getattr(env.client, method)(url, headers=cand, **kw).status_code == 403, (method, path)
        assert getattr(env.client, method)(url, headers=adm, **kw).status_code == 403, (method, path)


def test_a_recruiter_cannot_see_or_touch_anothers_job(env):
    _, a = make_user(env, "a@example.com")
    _, b = make_user(env, "b@example.com")
    job = ready_job(env, a)
    jid = job["id"]
    assert env.client.get("/api/recruiter/jobs", headers=b).json()["jobs"] == []
    for method, path, kw in [("get", "", {}), ("put", "", {"json": FORM}), ("post", "/publish", {}), ("post", "/close", {}),
                             ("post", "/clone", {}), ("delete", "", {})]:
        r = getattr(env.client, method)(f"/api/recruiter/jobs/{jid}{path}", headers=b, **kw)
        assert r.status_code == 404 and r.json()["detail"]["code"] == "not_found", (method, path)
    assert env.client.get(f"/api/recruiter/jobs/{jid}", headers=a).status_code == 200  # untouched


def test_bad_or_unknown_ids_are_404(env):
    _, h = make_user(env, "r@example.com")
    assert env.client.get("/api/recruiter/jobs/not-a-uuid", headers=h).status_code == 404
    assert env.client.get(f"/api/recruiter/jobs/{uuid.uuid4()}", headers=h).status_code == 404


# ---------- create / read / update ----------
def test_create_cleans_the_form_and_starts_as_a_draft(env):
    _, h = make_user(env, "r@example.com")
    job = create(env, h, title="  Senior   Data   Analyst ", department="   ")
    assert job["status"] == "draft" and job["title"] == "Senior Data Analyst" and job["department"] is None
    assert job["skills_required"] == ["SQL", "Python"]            # "sql" duplicate dropped
    assert job["skills_nice"] == ["Tableau"]                      # "python" removed: already a must-have
    assert job["opened_at"] is None and job["has_description"] is False and job["wording_flags"] == []


@pytest.mark.parametrize("over,needle", [
    ({"title": "ab"}, "at least 3"),
    ({"work_mode": "moon"}, "Work mode"),
    ({"employment_type": "gig"}, "Employment type"),
    ({"salary_currency": "XYZ"}, "Currency"),
    ({"experience_min": 8, "experience_max": 2}, "Minimum experience"),
    ({"salary_min": 5, "salary_max": 1}, "Minimum salary"),
    ({"experience_min": -1}, "greater than or equal"),
])
def test_validation_messages(env, over, needle):
    _, h = make_user(env, "r@example.com")
    r = env.client.post("/api/recruiter/jobs", headers=h, json={**FORM, **over})
    assert r.status_code == 422 and needle in r.text


def test_update_edits_fields_and_keeps_description_when_not_sent(env):
    _, h = make_user(env, "r@example.com")
    job = ready_job(env, h)
    body = {**FORM, "title": "Lead Analyst"}
    r = env.client.put(f"/api/recruiter/jobs/{job['id']}", headers=h, json=body)  # no description key
    assert r.status_code == 200 and r.json()["title"] == "Lead Analyst" and r.json()["description"] == JD_TEXT
    r = env.client.put(f"/api/recruiter/jobs/{job['id']}", headers=h, json={**body, "description": "new text"})
    assert r.json()["description"] == "new text"


def test_list_filters_counts_and_order(env):
    _, h = make_user(env, "r@example.com")
    first = ready_job(env, h, title="First")
    create(env, h, title="Second draft")
    env.client.post(f"/api/recruiter/jobs/{first['id']}/publish", headers=h)
    d = env.client.get("/api/recruiter/jobs", headers=h).json()
    assert d["counts"] == {"all": 2, "open": 1, "draft": 1, "closed": 0} and len(d["jobs"]) == 2
    assert [j["title"] for j in env.client.get("/api/recruiter/jobs?status=open", headers=h).json()["jobs"]] == ["First"]
    assert env.client.get("/api/recruiter/jobs?status=nope", headers=h).status_code == 422
    assert "description" not in d["jobs"][0]  # the list stays light


# ---------- status rules ----------
def test_publish_needs_a_description_and_a_skill(env):
    _, h = make_user(env, "r@example.com")
    bare = create(env, h)
    r = env.client.post(f"/api/recruiter/jobs/{bare['id']}/publish", headers=h)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "need_description"
    no_skill = ready_job(env, h, skills_required=[])
    r = env.client.post(f"/api/recruiter/jobs/{no_skill['id']}/publish", headers=h)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "need_skills"


def test_publish_close_reopen_lifecycle_and_overview_follows(env):
    _, h = make_user(env, "r@example.com")
    job = ready_job(env, h)
    jid = job["id"]
    opened = env.client.post(f"/api/recruiter/jobs/{jid}/publish", headers=h).json()
    assert opened["status"] == "open" and opened["opened_at"]
    ov = env.client.get("/api/recruiter/overview", headers=h).json()
    assert {k["key"]: k["value"] for k in ov["kpis"]}["open"] == 1 and ov["empty"] is False
    assert ov["job_health"][0]["title"] == "Senior Data Analyst"
    assert ov["skills_in_demand"][0]["jobs"] == 1
    assert ov["activity"][0]["text"] == "You opened the job Senior Data Analyst"

    again = env.client.post(f"/api/recruiter/jobs/{jid}/publish", headers=h)
    assert again.status_code == 200 and again.json()["opened_at"] == opened["opened_at"]  # idempotent

    closed = env.client.post(f"/api/recruiter/jobs/{jid}/close", headers=h).json()
    assert closed["status"] == "closed" and closed["closed_at"]
    kp = {k["key"]: k["value"] for k in env.client.get("/api/recruiter/overview", headers=h).json()["kpis"]}
    assert (kp["open"], kp["closed"]) == (0, 1)

    assert env.client.put(f"/api/recruiter/jobs/{jid}", headers=h, json=FORM).json()["detail"]["code"] == "closed"
    back = env.client.post(f"/api/recruiter/jobs/{jid}/publish", headers=h).json()
    assert back["status"] == "open" and back["closed_at"] is None
    texts = [a["text"] for a in env.client.get("/api/recruiter/overview", headers=h).json()["activity"]]
    assert "You reopened the job Senior Data Analyst" in texts and "You closed the job Senior Data Analyst" in texts


def test_a_draft_cannot_be_closed(env):
    _, h = make_user(env, "r@example.com")
    job = create(env, h)
    r = env.client.post(f"/api/recruiter/jobs/{job['id']}/close", headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_open"


def test_clone_makes_an_independent_draft(env):
    _, h = make_user(env, "r@example.com")
    job = ready_job(env, h)
    env.client.post(f"/api/recruiter/jobs/{job['id']}/publish", headers=h)
    r = env.client.post(f"/api/recruiter/jobs/{job['id']}/clone", headers=h)
    copy = r.json()
    assert r.status_code == 201 and copy["id"] != job["id"] and copy["status"] == "draft" and copy["opened_at"] is None
    assert copy["title"] == "Senior Data Analyst (copy)" and copy["description"] == JD_TEXT and copy["skills_required"] == ["SQL", "Python"]
    long = ready_job(env, h, title="T" * 160)
    assert len(env.client.post(f"/api/recruiter/jobs/{long['id']}/clone", headers=h).json()["title"]) <= 160


def test_only_drafts_can_be_deleted(env):
    _, h = make_user(env, "r@example.com")
    draft, live = create(env, h, title="Draft one"), ready_job(env, h, title="Live one")
    env.client.post(f"/api/recruiter/jobs/{live['id']}/publish", headers=h)
    assert env.client.delete(f"/api/recruiter/jobs/{draft['id']}", headers=h).json() == {"ok": True}
    assert env.client.get(f"/api/recruiter/jobs/{draft['id']}", headers=h).status_code == 404
    r = env.client.delete(f"/api/recruiter/jobs/{live['id']}", headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_draft"
    assert env.client.get(f"/api/recruiter/jobs/{live['id']}", headers=h).status_code == 200


# ---------- the JD writer ----------
def test_generate_builds_the_jd_and_puts_the_facts_in_by_code(env, monkeypatch):
    _, h = make_user(env, "r@example.com")
    calls = mock_ai(env, monkeypatch)
    r = env.client.post("/api/recruiter/jobs/generate", headers=h, json=FORM)
    assert r.status_code == 200, r.text
    d = r.json()
    text = d["description"]
    assert "Location: Mumbai · Hybrid" in text and "Experience: 3 to 5 years" in text
    assert "Salary: ₹12 lakh to ₹18 lakh per year" in text and "Qualification: B.E. in IT or similar" in text
    assert "## About the role" in text and "## What you will do" in text and "## What you bring" in text and "## Nice to have" in text
    assert "- Build weekly sales dashboards" in text and "- Write SQL to clean and join data" in text   # list markers stripped
    assert d["suggested_skills"] == ["dbt", "Excel"]   # SQL is already a must-have, "excel" duplicate dropped
    assert d["model"] == "primary/model:free" and d["wording_flags"] == []
    system, user, kw = calls[0]
    assert kw["purpose"] == "jd" and "Senior Data Analyst" in user and "SQL, Python" in user and "Build dashboards" in user
    assert "1200000" not in user and "salary" not in user.lower()   # salary never goes to the model


def test_generate_does_not_save_anything(env, monkeypatch):
    _, h = make_user(env, "r@example.com")
    mock_ai(env, monkeypatch)
    env.client.post("/api/recruiter/jobs/generate", headers=h, json=FORM)
    assert env.client.get("/api/recruiter/jobs", headers=h).json()["jobs"] == []


def test_generate_needs_something_to_write_about(env, monkeypatch):
    _, h = make_user(env, "r@example.com")
    mock_ai(env, monkeypatch)
    r = env.client.post("/api/recruiter/jobs/generate", headers=h, json={"title": "Analyst"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "need_details"


@pytest.mark.parametrize("code,status", [("no_key", 503), ("bad_key", 503), ("no_model", 503), ("unavailable", 503), ("bad_output", 502)])
def test_generate_maps_ai_failures_to_friendly_errors(env, monkeypatch, code, status):
    _, h = make_user(env, "r@example.com")

    def boom(*a, **k):
        raise env.llm.LLMError(code, f"message for {code}")

    monkeypatch.setattr(env.llm, "complete_json", boom)
    r = env.client.post("/api/recruiter/jobs/generate", headers=h, json=FORM)
    assert r.status_code == status and r.json()["detail"] == {"code": code, "message": f"message for {code}"}


def test_wording_flags_are_advice_only(env, monkeypatch):
    _, h = make_user(env, "r@example.com")
    bad = {**GOOD_AI, "summary": "We want a rockstar who is a young, energetic go-getter to join us today."}
    mock_ai(env, monkeypatch, bad)
    d = env.client.post("/api/recruiter/jobs/generate", headers=h, json=FORM).json()
    assert len(d["wording_flags"]) == 2 and any("rockstar" in f for f in d["wording_flags"]) and any("young" in f for f in d["wording_flags"])
    job = ready_job(env, h)
    env.client.put(f"/api/recruiter/jobs/{job['id']}", headers=h, json={**FORM, "description": "Ideal for a recent graduate. " + JD_TEXT})
    got = env.client.get(f"/api/recruiter/jobs/{job['id']}", headers=h).json()
    assert got["wording_flags"] and env.client.post(f"/api/recruiter/jobs/{job['id']}/publish", headers=h).status_code == 200  # not blocked


def test_generate_is_rate_limited_per_recruiter_per_hour(env, monkeypatch):
    from app.db.recruiter_models import AiCall

    uid, h = make_user(env, "r@example.com")
    _, other = make_user(env, "o@example.com")
    mock_ai(env, monkeypatch)
    with env.session.SessionLocal() as db:
        db.add_all([AiCall(owner_id=uuid.UUID(uid), purpose="jd", model="m", ok=True) for _ in range(30)])
        db.commit()
    r = env.client.post("/api/recruiter/jobs/generate", headers=h, json=FORM)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "slow_down"
    assert env.client.post("/api/recruiter/jobs/generate", headers=other, json=FORM).status_code == 200


def test_end_to_end_with_the_real_llm_layer_mocked_at_http(env, monkeypatch):
    """Form -> llm.py (HTTP mocked) -> JD text, and the call shows up in ai_calls."""
    import json
    import httpx
    from sqlalchemy import select
    from app.db.recruiter_models import AiCall

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODELS", "primary/model:free")
    env.llm._client_factory = lambda: httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={"choices": [{"message": {"content": "```json\n" + json.dumps(GOOD_AI) + "\n```"}}], "usage": {"prompt_tokens": 40, "completion_tokens": 120}})))
    uid, h = make_user(env, "r@example.com")
    r = env.client.post("/api/recruiter/jobs/generate", headers=h, json=FORM)
    assert r.status_code == 200 and "## What you will do" in r.json()["description"]
    with env.session.SessionLocal() as db:
        row = db.scalars(select(AiCall)).one()
    assert (str(row.owner_id), row.purpose, row.ok, row.prompt_tokens, row.completion_tokens) == (uid, "jd", True, 40, 120)


# ---------- money / text helpers ----------
def test_money_and_experience_text(env):
    jd = env.mods["app.services.jd"]
    assert jd.format_money(1200000, "INR") == "₹12 lakh" and jd.format_money(15000000, "INR") == "₹1.5 crore"
    assert jd.format_money(850000, "INR") == "₹8.5 lakh" and jd.format_money(50000, "INR") == "₹50,000"
    assert jd.format_money(120000, "USD") == "$120,000" and jd.format_money(90000, "GBP") == "£90,000"
    assert jd.salary_text({"salary_min": 1000000, "salary_max": None}) == "from ₹10 lakh per year"
    assert jd.salary_text({"salary_min": None, "salary_max": None}) is None
    assert jd.experience_text({"experience_min": 2, "experience_max": 2}) == "2 years"
    assert jd.experience_text({"experience_min": 4, "experience_max": None}) == "4+ years"
    assert jd.experience_text({"experience_min": None, "experience_max": 3}) == "up to 3 years"
