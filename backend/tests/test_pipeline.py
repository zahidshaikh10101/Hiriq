"""Pipeline routes (phase 5): scope, the board, moving, notes, rejection, the Overview funnel, and thumbs up/down."""
import importlib
import uuid

import pytest
from fastapi.testclient import TestClient

RELOAD = ["app.core.config", "app.db.session", "app.db.init_db", "app.core.deps", "app.routers.candidates",
          "app.routers.pipeline", "app.routers.recruiter"]


class Env:
    pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    mods = {n: importlib.reload(importlib.import_module(n)) for n in RELOAD}
    mods["app.db.init_db"].init_db()
    e = Env()
    e.mods, e.session, e.security = mods, mods["app.db.session"], importlib.import_module("app.core.security")
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(mods["app.routers.pipeline"].router, prefix="/api/recruiter")
    app.include_router(mods["app.routers.recruiter"].router, prefix="/api/recruiter")
    e.client = TestClient(app)
    return e


def make_user(env, email, role="recruiter", status="active", verified=True):
    from app.db.models import User

    with env.session.SessionLocal() as db:
        u = User(email=email, full_name=email.split("@")[0].title(), role=role, email_verified=verified, status=status)
        db.add(u)
        db.commit()
        uid = str(u.id)
    return uid, {"Authorization": f"Bearer {env.security.create_token(uid, role, 'x' * 40, 8)}"}


def add(env, obj):
    with env.session.SessionLocal() as db:
        db.add(obj)
        db.commit()
        return str(obj.id)


def make_job(env, owner, **over):
    from app.db.recruiter_models import Job

    f = dict(owner_id=uuid.UUID(owner), title="Senior Data Analyst", status="open", skills_required=["SQL"], skills_nice=[])
    f.update(over)
    return add(env, Job(**f))


def add_cand(env, owner, name, **fields):
    from app.db.recruiter_models import Candidate

    base = dict(owner_id=uuid.UUID(owner), source="upload", full_name=name, skills=["SQL"], file_hash=uuid.uuid4().hex)
    base.update(fields)
    return add(env, Candidate(**base))


def rank(env, job, cand, score):
    from app.db.recruiter_models import JobMatch

    return add(env, JobMatch(job_id=uuid.UUID(job), candidate_id=uuid.UUID(cand), score=score))


@pytest.fixture
def scene(env):
    uid, h = make_user(env, "r@example.com")
    job = make_job(env, uid)
    ids = {"ana": add_cand(env, uid, "Ana", current_title="Analyst", current_company="Northwind"),
           "ben": add_cand(env, uid, "Ben"), "cal": add_cand(env, uid, "Cal")}
    return env, uid, h, job, ids


def board(env, h, job):
    r = env.client.get(f"/api/recruiter/jobs/{job}/pipeline", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def put_on(env, h, job, *cands):
    r = env.client.post(f"/api/recruiter/jobs/{job}/pipeline", headers=h, json={"candidate_ids": list(cands)})
    assert r.status_code == 201, r.text
    return r.json()


def move(env, h, job, cand, **body):
    return env.client.patch(f"/api/recruiter/jobs/{job}/pipeline/{cand}", headers=h, json=body)


def column(b, stage):
    return [c["name"] for c in (b["rejected"] if stage == "rejected" else next(s for s in b["stages"] if s["stage"] == stage))["cards"]]


def overview(env, h):
    r = env.client.get("/api/recruiter/overview", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- access and scope
def test_every_route_needs_a_recruiter(env):
    _, cand = make_user(env, "c@example.com", role="candidate")
    _, adm = make_user(env, "a@example.com", role="admin")
    j, c = str(uuid.uuid4()), str(uuid.uuid4())
    calls = [("get", f"/jobs/{j}/pipeline", None), ("post", f"/jobs/{j}/pipeline", {"candidate_ids": [c]}),
             ("patch", f"/jobs/{j}/pipeline/{c}", {"note": "x"}), ("delete", f"/jobs/{j}/pipeline/{c}", None),
             ("put", f"/jobs/{j}/matches/{c}/feedback", {"label": 1})]
    for method, path, body in calls:
        url = "/api/recruiter" + path
        kw = {"json": body} if body is not None else {}
        assert getattr(env.client, method)(url, **kw).status_code == 401, path
        assert getattr(env.client, method)(url, headers=cand, **kw).status_code == 403, path
        assert getattr(env.client, method)(url, headers=adm, **kw).status_code == 403, path


def test_another_recruiters_job_is_a_404_everywhere(scene):
    env, uid, h, job, ids = scene
    _, other = make_user(env, "o@example.com")
    c = ids["ana"]
    calls = [("get", f"/jobs/{job}/pipeline", None), ("post", f"/jobs/{job}/pipeline", {"candidate_ids": [c]}),
             ("patch", f"/jobs/{job}/pipeline/{c}", {"note": "x"}), ("delete", f"/jobs/{job}/pipeline/{c}", None),
             ("put", f"/jobs/{job}/matches/{c}/feedback", {"label": 1})]
    for method, path, body in calls:
        kw = {"json": body} if body is not None else {}
        r = getattr(env.client, method)("/api/recruiter" + path, headers=other, **kw)
        assert r.status_code == 404 and r.json()["detail"]["code"] == "not_found", path
    assert env.client.get("/api/recruiter/jobs/not-a-uuid/pipeline", headers=h).status_code == 404


def test_someone_elses_upload_cannot_be_added_and_nothing_is_added_with_it(scene):
    env, uid, h, job, ids = scene
    oid, _ = make_user(env, "o@example.com")
    theirs = add_cand(env, oid, "Secret Sam")
    r = env.client.post(f"/api/recruiter/jobs/{job}/pipeline", headers=h, json={"candidate_ids": [ids["ana"], theirs]})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "not_found"
    assert board(env, h, job)["counts"]["total"] == 0                         # all or nothing
    assert "Secret Sam" not in str(board(env, h, job))


def test_the_board_never_lists_someone_elses_candidates_as_addable(scene):
    env, uid, h, job, ids = scene
    oid, _ = make_user(env, "o@example.com")
    add_cand(env, oid, "Secret Sam")
    assert sorted(a["name"] for a in board(env, h, job)["available"]) == ["Ana", "Ben", "Cal"]


# ---------------------------------------------------------------- the empty board and adding
def test_a_new_board_is_empty_with_everyone_available(scene):
    env, uid, h, job, ids = scene
    b = board(env, h, job)
    assert [s["stage"] for s in b["stages"]] == ["sourced", "shortlisted", "interview", "offer", "hired"]
    assert b["counts"] == {"sourced": 0, "shortlisted": 0, "interview": 0, "offer": 0, "hired": 0, "rejected": 0, "total": 0}
    assert b["available_total"] == 3 and b["can_add"] is True and b["rejected"]["count"] == 0
    assert b["job"]["title"] == "Senior Data Analyst"


def test_available_lists_ranked_people_first_best_score_first(scene):
    env, uid, h, job, ids = scene
    rank(env, job, ids["cal"], 88)
    rank(env, job, ids["ben"], 41.6)
    names = [(a["name"], a["score"]) for a in board(env, h, job)["available"]]
    assert names == [("Cal", 88), ("Ben", 42), ("Ana", None)]


def test_adding_puts_people_in_sourced_and_is_idempotent(scene):
    env, uid, h, job, ids = scene
    r = put_on(env, h, job, ids["ana"], ids["ben"])
    assert r["added"] == 2 and r["already_there"] == 0 and r["counts"]["sourced"] == 2 and r["available_total"] == 1
    assert sorted(column(r, "sourced")) == ["Ana", "Ben"]
    again = put_on(env, h, job, ids["ana"], ids["cal"], ids["cal"])           # a repeat and a duplicate in the same request
    assert again["added"] == 1 and again["already_there"] == 1 and again["counts"]["sourced"] == 3
    assert again["available_total"] == 0


def test_adding_only_people_already_there_answers_200(scene):
    env, uid, h, job, ids = scene
    put_on(env, h, job, ids["ana"])
    r = env.client.post(f"/api/recruiter/jobs/{job}/pipeline", headers=h, json={"candidate_ids": [ids["ana"]]})
    assert r.status_code == 200 and r.json()["added"] == 0 and r.json()["already_there"] == 1


def test_adding_needs_at_least_one_and_not_too_many(scene):
    env, uid, h, job, ids = scene
    url = f"/api/recruiter/jobs/{job}/pipeline"
    assert env.client.post(url, headers=h, json={"candidate_ids": []}).status_code == 422
    assert env.client.post(url, headers=h, json={"candidate_ids": [ids["ana"]] * 51}).status_code == 422
    assert env.client.post(url, headers=h, json={"candidate_ids": [ids["ana"]], "stage": "hired"}).status_code == 422
    assert env.client.post(url, headers=h, json={"candidate_ids": ["nope"]}).status_code == 404


def test_a_closed_job_takes_no_new_candidates_but_still_shows_its_board(scene):
    env, uid, h, job, ids = scene
    put_on(env, h, job, ids["ana"])
    closed = make_job(env, uid, title="Filled", status="closed")
    r = env.client.post(f"/api/recruiter/jobs/{closed}/pipeline", headers=h, json={"candidate_ids": [ids["ana"]]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "closed"
    assert board(env, h, closed)["can_add"] is False
    from app.db.recruiter_models import Job

    with env.session.SessionLocal() as db:
        db.get(Job, uuid.UUID(job)).status = "closed"
        db.commit()
    assert column(board(env, h, job), "sourced") == ["Ana"]                     # history stays readable and movable
    assert move(env, h, job, ids["ana"], stage="hired").status_code == 200


def test_members_can_be_added_but_not_suspended_or_unverified_ones(scene):
    env, uid, h, job, ids = scene
    make_user(env, "meera@example.com", role="candidate")
    make_user(env, "bad@example.com", role="candidate", status="suspended")
    make_user(env, "new@example.com", role="candidate", verified=False)
    b = board(env, h, job)
    names = sorted(a["name"] for a in b["available"])
    assert names == ["Ana", "Ben", "Cal", "Meera"]
    meera = next(a for a in b["available"] if a["name"] == "Meera")
    assert meera["source"] == "platform" and meera["has_profile"] is False
    assert put_on(env, h, job, meera["candidate_id"])["added"] == 1


def test_a_candidate_who_leaves_the_pool_disappears_from_the_board(scene):
    from app.db.models import User

    env, uid, h, job, ids = scene
    mid, _ = make_user(env, "meera@example.com", role="candidate")
    meera = next(a["candidate_id"] for a in board(env, h, job)["available"] if a["name"] == "Meera")
    put_on(env, h, job, meera)
    with env.session.SessionLocal() as db:
        db.get(User, uuid.UUID(mid)).status = "suspended"
        db.commit()
    b = board(env, h, job)
    assert "Meera" not in str(b) and b["counts"]["total"] == 0


# ---------------------------------------------------------------- moving
def test_moving_changes_the_column_and_keeps_scores_sorted(scene):
    env, uid, h, job, ids = scene
    rank(env, job, ids["ana"], 90)
    rank(env, job, ids["ben"], 55)
    put_on(env, h, job, ids["ana"], ids["ben"], ids["cal"])
    r = move(env, h, job, ids["ana"], stage="shortlisted")
    assert r.status_code == 200
    card = r.json()["card"]
    assert card["stage"] == "shortlisted" and card["score"] == 90 and card["name"] == "Ana" and card["headline"] == "Analyst at Northwind"
    assert r.json()["counts"] == {"sourced": 2, "shortlisted": 1, "interview": 0, "offer": 0, "hired": 0, "rejected": 0, "total": 3}
    b = board(env, h, job)
    assert column(b, "shortlisted") == ["Ana"] and column(b, "sourced") == ["Ben", "Cal"]   # scored first, unscored last


def test_a_move_can_skip_stages_and_any_direction_is_allowed(scene):
    env, uid, h, job, ids = scene
    put_on(env, h, job, ids["ana"])
    assert move(env, h, job, ids["ana"], stage="offer").json()["card"]["stage"] == "offer"
    assert move(env, h, job, ids["ana"], stage="shortlisted").json()["card"]["stage"] == "shortlisted"


def test_bad_stages_are_refused_and_change_nothing(scene):
    env, uid, h, job, ids = scene
    put_on(env, h, job, ids["ana"])
    for stage in ("promoted", "", "HIRED", None):
        r = move(env, h, job, ids["ana"], stage=stage)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_stage", stage
    assert column(board(env, h, job), "sourced") == ["Ana"]
    assert move(env, h, job, ids["ana"], colour="red").status_code == 422        # unknown fields are refused


def test_moving_someone_who_is_not_on_the_board_is_a_404(scene):
    env, uid, h, job, ids = scene
    r = move(env, h, job, ids["ana"], stage="hired")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "not_on_board"
    assert env.client.delete(f"/api/recruiter/jobs/{job}/pipeline/{ids['ana']}", headers=h).json()["detail"]["code"] == "not_on_board"


def test_moving_to_the_same_stage_changes_nothing_and_logs_nothing(scene):
    from sqlalchemy import select
    from app.db.recruiter_models import RecruiterEvent

    env, uid, h, job, ids = scene
    put_on(env, h, job, ids["ana"])
    assert move(env, h, job, ids["ana"], stage="sourced").status_code == 200
    with env.session.SessionLocal() as db:
        texts = [e.text for e in db.scalars(select(RecruiterEvent))]
    assert texts == ["You added Ana to the Senior Data Analyst pipeline"]


# ---------------------------------------------------------------- notes
def test_notes_are_saved_trimmed_cleared_and_independent_of_stage(scene):
    env, uid, h, job, ids = scene
    put_on(env, h, job, ids["ana"])
    r = move(env, h, job, ids["ana"], note="  Strong on SQL. Ask about dbt.  ")
    assert r.json()["card"]["note"] == "Strong on SQL. Ask about dbt." and r.json()["card"]["stage"] == "sourced"
    move(env, h, job, ids["ana"], stage="interview")
    assert board(env, h, job)["stages"][2]["cards"][0]["note"] == "Strong on SQL. Ask about dbt."   # a move keeps the note
    assert move(env, h, job, ids["ana"], note="   ").json()["card"]["note"] is None
    assert move(env, h, job, ids["ana"], note="x" * 2001).status_code == 422


# ---------------------------------------------------------------- rejection
def test_rejecting_keeps_the_reason_and_the_furthest_stage(scene):
    from app.db.recruiter_models import PipelineEntry
    from sqlalchemy import select

    env, uid, h, job, ids = scene
    put_on(env, h, job, ids["ana"])
    move(env, h, job, ids["ana"], stage="interview")
    r = move(env, h, job, ids["ana"], stage="rejected", rejection_reason="  Salary expectations too high  ")
    assert r.json()["card"]["stage"] == "rejected" and r.json()["card"]["rejection_reason"] == "Salary expectations too high"
    b = board(env, h, job)
    assert column(b, "rejected") == ["Ana"] and b["rejected"]["count"] == 1 and b["counts"]["rejected"] == 1 and b["counts"]["interview"] == 0
    with env.session.SessionLocal() as db:
        assert db.scalars(select(PipelineEntry)).one().reached == 2          # reached interview before the rejection


def test_the_reason_can_be_edited_while_rejected_and_is_dropped_when_reinstated(scene):
    env, uid, h, job, ids = scene
    put_on(env, h, job, ids["ana"])
    move(env, h, job, ids["ana"], stage="rejected")
    assert move(env, h, job, ids["ana"]).json()["card"]["rejection_reason"] is None
    assert move(env, h, job, ids["ana"], rejection_reason="Not a fit").json()["card"]["rejection_reason"] == "Not a fit"
    r = move(env, h, job, ids["ana"], stage="shortlisted")                       # taken back
    assert r.json()["card"]["stage"] == "shortlisted" and r.json()["card"]["rejection_reason"] is None
    assert move(env, h, job, ids["ana"], rejection_reason="late").json()["card"]["rejection_reason"] is None   # only a rejection has a reason
    assert move(env, h, job, ids["ana"], stage="rejected", rejection_reason="x" * 201).status_code == 422


def test_a_reason_sent_together_with_the_rejection_is_kept(scene):
    env, uid, h, job, ids = scene
    put_on(env, h, job, ids["ana"])
    assert move(env, h, job, ids["ana"], stage="rejected", rejection_reason="Withdrew").json()["card"]["rejection_reason"] == "Withdrew"


# ---------------------------------------------------------------- removing
def test_removing_takes_someone_off_and_makes_them_addable_again(scene):
    env, uid, h, job, ids = scene
    put_on(env, h, job, ids["ana"], ids["ben"])
    r = env.client.delete(f"/api/recruiter/jobs/{job}/pipeline/{ids['ana']}", headers=h)
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["counts"]["total"] == 1
    b = board(env, h, job)
    assert "Ana" in [a["name"] for a in b["available"]] and column(b, "sourced") == ["Ben"]


# ---------------------------------------------------------------- the Overview reads this
def test_the_overview_funnel_needs_action_and_activity_follow_the_board(scene):
    env, uid, h, job, ids = scene
    put_on(env, h, job, ids["ana"], ids["ben"], ids["cal"])
    move(env, h, job, ids["ana"], stage="interview")
    move(env, h, job, ids["ben"], stage="shortlisted")
    move(env, h, job, ids["cal"], stage="rejected", rejection_reason="Not a fit")          # never got past sourced
    d = overview(env, h)
    k = {x["key"]: x["value"] for x in d["kpis"]}
    assert k["shortlisted"] == 1 and k["interview"] == 1
    assert [f["count"] for f in d["funnel"]] == [3, 2, 1, 0, 0]
    assert d["needs_action"]["waiting_total"] == 0
    assert d["activity"][0]["text"] == f"You rejected Cal for Senior Data Analyst" and d["activity"][0]["tone"] == "a4"

    move(env, h, job, ids["ben"], stage="sourced")                                         # moved back a step
    d = overview(env, h)
    assert [f["count"] for f in d["funnel"]] == [3, 2, 1, 0, 0]                           # history keeps where he got to
    assert d["needs_action"]["waiting_total"] == 1 and d["needs_action"]["waiting"][0]["name"] == "Ben"
    assert d["needs_action"]["waiting"][0]["job_id"] == job

    move(env, h, job, ids["ana"], stage="hired")
    assert [f["count"] for f in overview(env, h)["funnel"]] == [3, 2, 1, 1, 1]


def test_events_use_plain_wording(scene):
    from sqlalchemy import select
    from app.db.recruiter_models import RecruiterEvent

    env, uid, h, job, ids = scene
    put_on(env, h, job, ids["ana"], ids["ben"])
    move(env, h, job, ids["ana"], stage="shortlisted")
    move(env, h, job, ids["ana"], stage="rejected")
    move(env, h, job, ids["ana"], stage="interview")
    env.client.delete(f"/api/recruiter/jobs/{job}/pipeline/{ids['ben']}", headers=h)
    with env.session.SessionLocal() as db:
        events = [(e.kind, e.text) for e in db.scalars(select(RecruiterEvent).order_by(RecruiterEvent.id))]
    assert events == [("pipeline", "You added 2 candidates to the Senior Data Analyst pipeline"),
                      ("pipeline", "You moved Ana to Shortlisted for Senior Data Analyst"),
                      ("pipeline", "You rejected Ana for Senior Data Analyst"),
                      ("pipeline", "You moved Ana back to Interview for Senior Data Analyst"),
                      ("pipeline", "You took Ben off the Senior Data Analyst pipeline")]


# ---------------------------------------------------------------- thumbs
def thumb(env, h, job, cand, label):
    return env.client.put(f"/api/recruiter/jobs/{job}/matches/{cand}/feedback", headers=h, json={"label": label})


def test_thumbs_need_a_ranking_first(scene):
    env, uid, h, job, ids = scene
    r = thumb(env, h, job, ids["ana"], 1)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "not_ranked"


def test_thumbs_up_down_change_and_clear(scene):
    from sqlalchemy import select
    from app.db.recruiter_models import MatchFeedback

    env, uid, h, job, ids = scene
    rank(env, job, ids["ana"], 80)
    assert thumb(env, h, job, ids["ana"], 1).json() == {"candidate_id": ids["ana"], "label": 1}
    assert thumb(env, h, job, ids["ana"], -1).json()["label"] == -1                 # changing your mind replaces, never doubles
    with env.session.SessionLocal() as db:
        rows = db.scalars(select(MatchFeedback)).all()
        assert len(rows) == 1 and rows[0].label == -1 and str(rows[0].recruiter_id) == uid
    assert thumb(env, h, job, ids["ana"], 0).json()["label"] is None
    assert thumb(env, h, job, ids["ana"], 0).status_code == 200                      # clearing nothing is fine
    with env.session.SessionLocal() as db:
        assert db.scalars(select(MatchFeedback)).all() == []


@pytest.mark.parametrize("label", [2, -2, 5])
def test_bad_labels_are_refused(scene, label):
    env, uid, h, job, ids = scene
    rank(env, job, ids["ana"], 80)
    r = thumb(env, h, job, ids["ana"], label)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_label"
    assert env.client.put(f"/api/recruiter/jobs/{job}/matches/{ids['ana']}/feedback", headers=h, json={"label": "up"}).status_code == 422
    assert env.client.put(f"/api/recruiter/jobs/{job}/matches/{ids['ana']}/feedback", headers=h, json={"label": 1, "score": 100}).status_code == 422


def test_thumbs_show_on_the_board_and_belong_to_one_recruiter(scene):
    env, uid, h, job, ids = scene
    rank(env, job, ids["ana"], 80)
    put_on(env, h, job, ids["ana"])
    thumb(env, h, job, ids["ana"], 1)
    assert board(env, h, job)["stages"][0]["cards"][0]["feedback"] == 1
    assert move(env, h, job, ids["ana"], note="hi").json()["card"]["feedback"] == 1
    # a different recruiter with the same member in their pool has their own, separate thumbs
    mid, _ = make_user(env, "meera@example.com", role="candidate")
    oid, other = make_user(env, "o@example.com")
    ojob = make_job(env, oid)
    meera = next(a["candidate_id"] for a in board(env, h, job)["available"] if a["name"] == "Meera")
    rank(env, job, meera, 60)
    rank(env, ojob, meera, 70)
    thumb(env, h, job, meera, -1)
    assert thumb(env, other, ojob, meera, 1).json()["label"] == 1
    assert next(a for a in board(env, h, job)["available"] if a["name"] == "Meera")["feedback"] == -1
    assert next(a for a in board(env, other, ojob)["available"] if a["name"] == "Meera")["feedback"] == 1


def test_thumbs_never_change_a_score(scene):
    env, uid, h, job, ids = scene
    rank(env, job, ids["ana"], 80)
    put_on(env, h, job, ids["ana"])
    thumb(env, h, job, ids["ana"], -1)
    assert board(env, h, job)["stages"][0]["cards"][0]["score"] == 80


def test_thumbs_on_someone_elses_candidate_are_a_404(scene):
    env, uid, h, job, ids = scene
    oid, _ = make_user(env, "o@example.com")
    theirs = add_cand(env, oid, "Secret Sam")
    rank(env, job, theirs, 50)
    assert thumb(env, h, job, theirs, 1).status_code == 404
    assert thumb(env, h, job, "nope", 1).status_code == 404


# ---------------------------------------------------------------- the matching page gets thumbs and stage too
def test_the_matches_list_carries_thumbs_and_stage(scene):
    from app.db.recruiter_models import PipelineEntry

    for name in ("app.routers.matches",):
        importlib.reload(importlib.import_module(name))
    env, uid, h, job, ids = scene
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(importlib.import_module("app.routers.matches").router, prefix="/api/recruiter")
    client = TestClient(app)
    rank(env, job, ids["ana"], 80)
    rank(env, job, ids["ben"], 40)
    put_on(env, h, job, ids["ana"])
    move(env, h, job, ids["ana"], stage="shortlisted")
    thumb(env, h, job, ids["ana"], 1)
    rows = client.get(f"/api/recruiter/jobs/{job}/matches", headers=h).json()["results"]
    by = {r["name"]: r for r in rows}
    assert (by["Ana"]["feedback"], by["Ana"]["stage"]) == (1, "shortlisted")
    assert (by["Ben"]["feedback"], by["Ben"]["stage"]) == (None, None)
