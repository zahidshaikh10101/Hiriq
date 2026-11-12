"""Applying to a job: the candidate sends a copy of a resume (and optionally a letter) to the job's owner; the recruiter
sees it under Applicants and may add the person to the pipeline; withdrawing or removing the resume ends the recruiter's access."""
import importlib
import uuid

import pytest
from fastapi.testclient import TestClient

from test_candidate import ME, add, make_job, make_user, ready

RELOAD = ["app.core.config", "app.db.session", "app.db.init_db", "app.db.upgrade", "app.core.deps", "app.services.llm",
          "app.services.resume_text", "app.services.resume", "app.services.matching", "app.services.jobread",
          "app.routers.candidates", "app.routers.matches", "app.routers.candidate", "app.routers.candidate_apply",
          "app.routers.pipeline", "app.routers.applicants"]
REC = "/api/recruiter"
TAILORED = "Asha Rao\nTAILORED: Built SQL reports and Python scripts that leadership uses every week.\nSKILLS: SQL, Python"
LETTER = "Dear Hiring Team,\n\nI would love to join you.\n\nAsha Rao"


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
    for name in ("candidate", "candidate_apply"):
        app.include_router(mods[f"app.routers.{name}"].router, prefix="/api/candidate")
    for name in ("candidates", "pipeline", "applicants"):
        app.include_router(mods[f"app.routers.{name}"].router, prefix=REC)
    e.client = TestClient(app)
    return e


def world(env):
    """A recruiter with one open job, and a ready candidate. Returns (recruiter headers, job id, candidate headers, candidate id)."""
    rid, rec = make_user(env, "r@example.com", role="recruiter", company="Acme")
    job = make_job(env, rid)
    _, cand = ready(env)
    cid = env.client.get(f"{ME}/me", headers=cand).json()["id"]
    return rec, job, cand, cid


def apply(env, h, job, **body):
    return env.client.post(f"{ME}/jobs/{job}/apply", headers=h, json=body)


def test_access_rules(env):
    rec, job, cand, _ = world(env)
    assert env.client.post(f"{ME}/jobs/{job}/apply", json={}).status_code == 401
    assert apply(env, rec, job).status_code == 403                                   # a recruiter cannot apply
    assert env.client.get(f"{ME}/applications", headers=rec).status_code == 403
    assert env.client.get(f"{REC}/applicants", headers=cand).status_code == 403      # a candidate cannot read applicants
    assert env.client.get(f"{REC}/jobs/{job}/applicants", headers=cand).status_code == 403
    assert env.client.get(f"{REC}/applicants").status_code == 401


def test_apply_and_the_recruiter_sees_a_copy(env):
    rec, job, cand, cid = world(env)
    r = apply(env, cand, job, message="  I can start   in  a month.  ")
    assert r.status_code == 201
    a = r.json()
    assert a["job_title"] == "Senior Data Analyst" and a["company"] == "Acme" and a["job_status"] == "open"
    assert a["resume_label"] == "Your uploaded resume" and a["letter_label"] is None and a["has_message"] is True

    again = apply(env, cand, job)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_applied"
    mine = env.client.get(f"{ME}/applications", headers=cand).json()
    assert [x["id"] for x in mine["applications"]] == [a["id"]]

    summary = env.client.get(f"{REC}/applicants", headers=rec).json()
    assert summary["total"] == 1 and summary["jobs"][0]["applicants"] == 1
    lst = env.client.get(f"{REC}/jobs/{job}/applicants", headers=rec).json()
    assert lst["total"] == 1
    row = lst["applicants"][0]
    assert row["candidate_id"] == cid and row["name"] == "Asha Rao" and row["stage"] is None and row["has_letter"] is False
    assert isinstance(row["fit_score"], int) and 0 <= row["fit_score"] <= 100

    full = env.client.get(f"{REC}/jobs/{job}/applicants/{a['id']}", headers=rec).json()
    assert full["contact"]["email"] == "asha@example.com" and "SQL reports" in full["resume_text"]
    assert full["message"] == "I can start in a month." and full["letter_text"] is None


def test_apply_with_a_tailored_version_and_a_letter(env):
    from app.db.recruiter_models import CoverLetter, ResumeVersion

    rec, job, cand, cid = world(env)
    version = add(env, ResumeVersion(candidate_id=uuid.UUID(cid), job_title="Senior Data Analyst", label="For Senior Data Analyst", content={}, text=TAILORED))
    letter = add(env, CoverLetter(candidate_id=uuid.UUID(cid), job_title="Senior Data Analyst", label="Letter one", text=LETTER, content={}))
    a = apply(env, cand, job, version_id=version, letter_id=letter).json()
    assert a["resume_label"] == "For Senior Data Analyst" and a["letter_label"] == "Letter one"
    full = env.client.get(f"{REC}/jobs/{job}/applicants/{a['id']}", headers=rec).json()
    assert full["resume_text"] == TAILORED and full["letter_text"] == LETTER

    # the recruiter's copy does not change when the member edits the original
    env.client.patch(f"{ME}/versions/{version}", headers=cand, json={"text": "something else"})
    again = env.client.get(f"{REC}/jobs/{job}/applicants/{a['id']}", headers=rec).json()
    assert again["resume_text"] == TAILORED


def test_someone_elses_version_or_letter_is_refused(env):
    from app.db.recruiter_models import CoverLetter, ResumeVersion

    rec, job, cand, _ = world(env)
    _, other = ready(env, "ben@example.com")
    other_id = env.client.get(f"{ME}/me", headers=other).json()["id"]
    version = add(env, ResumeVersion(candidate_id=uuid.UUID(other_id), label="Ben", content={}, text=TAILORED))
    letter = add(env, CoverLetter(candidate_id=uuid.UUID(other_id), label="Ben", text=LETTER, content={}))
    assert apply(env, cand, job, version_id=version).status_code == 404
    assert apply(env, cand, job, letter_id=letter).status_code == 404
    assert apply(env, cand, job, version_id="not-a-uuid").status_code == 404
    assert env.client.get(f"{ME}/applications", headers=cand).json()["applications"] == []


def test_input_rules(env):
    rec, job, cand, _ = world(env)
    _, empty = make_user(env, "new@example.com")
    assert apply(env, empty, job).json()["detail"]["code"] == "no_resume"            # no resume yet
    assert apply(env, cand, str(uuid.uuid4())).status_code == 404 and apply(env, cand, "nope").status_code == 404
    assert apply(env, cand, job, message="x" * 1001).status_code == 422
    assert apply(env, cand, job, extra="field").status_code == 422
    rid2, _ = make_user(env, "r2@example.com", role="recruiter")
    draft = make_job(env, rid2, status="draft")
    closed = make_job(env, rid2, status="closed")
    assert apply(env, cand, draft).status_code == 404 and apply(env, cand, closed).status_code == 404   # only open jobs


def test_recruiters_only_see_applicants_to_their_own_jobs(env):
    rec, job, cand, _ = world(env)
    a = apply(env, cand, job).json()
    _, rec2 = make_user(env, "r2@example.com", role="recruiter")
    assert env.client.get(f"{REC}/jobs/{job}/applicants", headers=rec2).status_code == 404
    assert env.client.get(f"{REC}/jobs/{job}/applicants/{a['id']}", headers=rec2).status_code == 404
    assert env.client.get(f"{REC}/applicants", headers=rec2).json() == {"jobs": [], "total": 0}


def test_an_application_is_only_found_under_its_own_job(env):
    from app.db.recruiter_models import Job

    rec, job, cand, _ = world(env)
    a = apply(env, cand, job).json()
    with env.session.SessionLocal() as db:
        owner = str(db.get(Job, uuid.UUID(job)).owner_id)
    second = make_job(env, owner, title="Another role")      # a second job of the same recruiter
    assert env.client.get(f"{REC}/jobs/{second}/applicants/{a['id']}", headers=rec).status_code == 404
    assert env.client.get(f"{REC}/jobs/{second}/applicants", headers=rec).json()["total"] == 0


def test_applicant_can_be_added_to_the_pipeline_but_only_by_that_recruiter(env):
    rec, job, cand, cid = world(env)
    # not visible to recruiters, so before applying the recruiter cannot add them
    assert env.client.post(f"{REC}/jobs/{job}/pipeline", headers=rec, json={"candidate_ids": [cid]}).status_code == 404
    apply(env, cand, job)
    added = env.client.post(f"{REC}/jobs/{job}/pipeline", headers=rec, json={"candidate_ids": [cid]})
    assert added.status_code == 201 and added.json()["added"] == 1
    board = env.client.get(f"{REC}/jobs/{job}/pipeline", headers=rec).json()
    assert [c["candidate_id"] for c in board["stages"][0]["cards"]] == [cid]
    assert env.client.get(f"{REC}/jobs/{job}/applicants", headers=rec).json()["applicants"][0]["stage"] == "sourced"
    # still hidden from every other recruiter
    rid2, rec2 = make_user(env, "r2@example.com", role="recruiter")
    job2 = make_job(env, rid2)
    assert env.client.post(f"{REC}/jobs/{job2}/pipeline", headers=rec2, json={"candidate_ids": [cid]}).status_code == 404


def test_withdrawing_ends_the_recruiters_access(env):
    rec, job, cand, cid = world(env)
    a = apply(env, cand, job).json()
    env.client.post(f"{REC}/jobs/{job}/pipeline", headers=rec, json={"candidate_ids": [cid]})
    _, other = ready(env, "ben@example.com")
    assert env.client.delete(f"{ME}/applications/{a['id']}", headers=other).status_code == 404       # not theirs to withdraw
    assert env.client.delete(f"{ME}/applications/{a['id']}", headers=cand).json() == {"deleted": True}
    assert env.client.delete(f"{ME}/applications/{a['id']}", headers=cand).status_code == 404
    assert env.client.get(f"{ME}/applications", headers=cand).json()["applications"] == []
    assert env.client.get(f"{REC}/jobs/{job}/applicants", headers=rec).json()["total"] == 0
    assert env.client.get(f"{REC}/jobs/{job}/applicants/{a['id']}", headers=rec).status_code == 404
    board = env.client.get(f"{REC}/jobs/{job}/pipeline", headers=rec).json()
    assert board["counts"]["total"] == 0 and board["stages"][0]["cards"] == []                        # the person is hidden from the board
    assert apply(env, cand, job).status_code == 201                                                    # they may apply again
    back = env.client.get(f"{REC}/jobs/{job}/pipeline", headers=rec).json()
    assert [c["candidate_id"] for c in back["stages"][0]["cards"]] == [cid]                           # and the earlier board entry comes back with them


def test_removing_the_resume_withdraws_every_application(env):
    rec, job, cand, _ = world(env)
    apply(env, cand, job)
    assert env.client.delete(f"{ME}/resume", headers=cand).status_code == 200
    assert env.client.get(f"{ME}/applications", headers=cand).json()["applications"] == []
    assert env.client.get(f"{REC}/jobs/{job}/applicants", headers=rec).json()["total"] == 0


def test_sort_by_fit(env):
    from test_candidate import set_text

    rec, job, cand, _ = world(env)
    uid, weak = ready(env, "weak@example.com", full_name="Weak Match", skills=["Cooking"])
    set_text(env, uid, "Cooked meals for large events.")
    assert apply(env, weak, job).status_code == 201
    assert apply(env, cand, job).status_code == 201
    rows = env.client.get(f"{REC}/jobs/{job}/applicants?sort=fit", headers=rec).json()["applicants"]
    assert [r["name"] for r in rows] == ["Asha Rao", "Weak Match"] and rows[0]["fit_score"] > rows[1]["fit_score"]
    assert env.client.get(f"{REC}/jobs/{job}/applicants?sort=new", headers=rec).json()["total"] == 2
    assert env.client.get(f"{REC}/jobs/{job}/applicants?sort=bogus", headers=rec).status_code == 422
