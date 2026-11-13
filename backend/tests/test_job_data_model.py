"""The data model behind the personal job feed: duplicate keys, the 30-day rule, preferences, the feed, and the outside-job tracker."""
import importlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.services import jobkeys

RELOAD = ["app.core.config", "app.db.session", "app.db.init_db", "app.db.upgrade", "app.services.postingread", "app.services.externalstore"]


class Env:
    pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    mods = {n: importlib.reload(importlib.import_module(n)) for n in RELOAD}
    e = Env()
    e.mods, e.session, e.store, e.upgrade_mod = mods, mods["app.db.session"], mods["app.services.externalstore"], mods["app.db.upgrade"]
    e.init = mods["app.db.init_db"]
    return e


def fresh_db(env):
    env.init.init_db()
    return env.session.SessionLocal()


def post(i, url="auto", title="Data Analyst", company="Acme", location="Mumbai, India", posted="2026-11-10T00:00:00Z"):
    return {"id": f"id{i}", "title": title, "company": company, "location": location, "remote": False,
            "apply_url": f"https://jobs.example.com/p/{i}" if url == "auto" else url, "description": "x " * 50, "posted_at": posted, "source": "Indeed"}


def candidate(db, n=1):
    from app.db.models import User
    from app.db.recruiter_models import Candidate

    u = User(email=f"c{n}@example.com", full_name=f"Cand {n}", role="candidate", email_verified=True, status="active")
    db.add(u)
    db.flush()
    c = Candidate(user_id=u.id, source="platform", full_name=u.full_name, skills=[])
    db.add(c)
    db.commit()
    return c


# ---------------------------------------------------------------- keys
def test_apply_link_noise_does_not_make_a_new_job():
    base = jobkeys.apply_key("https://jobs.example.com/p/42")
    for same in ("http://www.JOBS.example.com/p/42/", "https://jobs.example.com:443/p/42#apply", "https://jobs.example.com/p/42?utm_source=x&utm_medium=y&gclid=1",
                 "https://jobs.example.com//p/42", "  https://jobs.example.com/p/42  "):
        assert jobkeys.apply_key(same) == base, same
    assert jobkeys.apply_key("https://jobs.example.com/p/43") != base


def test_a_job_id_in_the_query_is_kept_and_order_is_ignored():
    a = jobkeys.apply_key("https://example.com/viewjob?jk=AAA&b=1")
    assert a == jobkeys.apply_key("https://example.com/viewjob?b=1&jk=AAA&utm_campaign=z")
    assert a != jobkeys.apply_key("https://example.com/viewjob?jk=BBB&b=1")
    assert jobkeys.normalize_url("https://Example.com/a/?b=2&a=1&ref=nav") == "example.com/a?a=1&b=2"


def test_bad_links_have_no_key():
    for bad in (None, "", "   ", "javascript:alert(1)", "ftp://example.com/x", "not a url", "https://localhost/x", "https://" + "a" * 2100 + ".com"):
        assert jobkeys.apply_key(bad) is None, bad


def test_title_company_city_key():
    k = jobkeys.dedupe_key("Data  Analyst", "ACME Pvt. Ltd", "Mumbai, Maharashtra")
    assert k == jobkeys.dedupe_key("data analyst", "acme pvt ltd", "mumbai")
    assert k != jobkeys.dedupe_key("Data Analyst", "Acme Pvt Ltd", "Pune")
    assert jobkeys.dedupe_key("Data Analyst", None, "Mumbai") is None          # two anonymous posts must never merge
    assert jobkeys.dedupe_key("", "Acme", "Mumbai") is None


def test_job_key_prefers_the_link():
    assert jobkeys.job_key("https://e.com/1", "T", "C", "L") == jobkeys.apply_key("https://e.com/1")
    assert jobkeys.job_key(None, "T", "C", "L") == jobkeys.dedupe_key("T", "C", "L")
    assert jobkeys.job_key(None, "T", None, "L") is None


# ---------------------------------------------------------------- the 30-day rule
def test_thirty_day_rule():
    now = datetime(2026, 11, 12, tzinfo=timezone.utc)
    assert jobkeys.is_fresh(now - timedelta(days=29, hours=23), now)
    assert jobkeys.is_fresh(now - timedelta(days=30), now)
    assert not jobkeys.is_fresh(now - timedelta(days=30, minutes=1), now)
    assert not jobkeys.is_fresh(None, now)
    assert jobkeys.is_fresh(datetime(2026, 11, 1), now)                           # naive times count as UTC
    seen = datetime(2026, 11, 5, tzinfo=timezone.utc)
    assert jobkeys.listed_at(None, seen) == seen and jobkeys.listed_at(now, seen) == now


# ---------------------------------------------------------------- saving and de-duplicating
def test_save_fills_keys_and_listed_at(env):
    with fresh_db(env) as db:
        rows = env.store.save(db, [post(1)], "data analyst", "in")
        r = rows["id1"]
        assert r.apply_key == jobkeys.apply_key("https://jobs.example.com/p/1") and r.dedupe_key
        assert r.listed_at.replace(tzinfo=None) == datetime(2026, 11, 10)         # the post's own date


def test_listed_at_is_first_seen_when_the_post_has_no_date(env):
    with fresh_db(env) as db:
        r = env.store.save(db, [post(1, posted=None)], "q", "in")["id1"]
        assert abs((datetime.now(timezone.utc) - r.listed_at.replace(tzinfo=timezone.utc)).total_seconds()) < 60


def test_same_apply_link_is_one_job_even_with_other_ids_and_tracking(env):
    with fresh_db(env) as db:
        env.store.save(db, [post(1, url="https://jobs.example.com/p/9")], "q", "in")
        got = env.store.save(db, [post(2, url="https://www.jobs.example.com/p/9/?utm_source=a", title="Data Analyst II")], "q", "in")
        from app.db.recruiter_models import ExternalJob

        rows = db.scalars(select(ExternalJob)).all()
        assert len(rows) == 1 and rows[0].title == "Data Analyst II"             # refreshed, not duplicated
        assert got["id2"].id == rows[0].id                                        # and returned under its own id


def test_same_job_twice_in_one_batch_is_saved_once(env):
    with fresh_db(env) as db:
        got = env.store.save(db, [post(1, url="https://e.com/a"), post(2, url="https://e.com/a?utm_x=1"), post(3, url=None, title="Other")], "q", "in")
        from app.db.recruiter_models import ExternalJob

        assert len(db.scalars(select(ExternalJob)).all()) == 2 and got["id1"].id == got["id2"].id != got["id3"].id


def test_same_title_company_city_under_different_links_is_one_job(env):
    with fresh_db(env) as db:
        env.store.save(db, [post(1, url="https://site-a.com/j/1")], "q", "in")
        env.store.save(db, [post(2, url="https://site-b.com/other/77")], "q", "in")
        from app.db.recruiter_models import ExternalJob

        assert len(db.scalars(select(ExternalJob)).all()) == 1


def test_posts_without_a_link_still_save_and_do_not_merge_when_unnamed(env):
    with fresh_db(env) as db:
        env.store.save(db, [post(1, url=None, company=None), post(2, url=None, company=None, title="Analyst B")], "q", "in")
        from app.db.recruiter_models import ExternalJob

        rows = db.scalars(select(ExternalJob)).all()
        assert len(rows) == 2 and all(r.apply_key is None and r.dedupe_key is None for r in rows)


def test_the_database_itself_refuses_a_second_row_with_the_same_apply_key(env):
    from app.db.recruiter_models import ExternalJob

    with fresh_db(env) as db:
        key = jobkeys.apply_key("https://e.com/z")
        db.add(ExternalJob(provider="a", external_id="1", title="T", apply_key=key))
        db.commit()
        db.add(ExternalJob(provider="b", external_id="2", title="T", apply_key=key))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add_all([ExternalJob(provider="a", external_id="3", title="T"), ExternalJob(provider="a", external_id="4", title="T")])
        db.commit()                                                                # many rows may have no key


# ---------------------------------------------------------------- freshness in queries and the purge
def test_fresh_clause_and_purge(env):
    from app.db.recruiter_models import ExternalJob

    with fresh_db(env) as db:
        now = datetime.now(timezone.utc)
        db.add_all([
            ExternalJob(provider="indeed", external_id="new", title="New", listed_at=now - timedelta(days=3)),
            ExternalJob(provider="indeed", external_id="old", title="Old", listed_at=now - timedelta(days=45)),
            ExternalJob(provider="manual", external_id="m", title="By admin", listed_at=now - timedelta(days=90)),
        ])
        db.commit()
        assert {r.title for r in db.scalars(select(ExternalJob).where(env.store.fresh_clause()))} == {"New"}
        assert env.store.purge_stale(db) == 1
        assert {r.title for r in db.scalars(select(ExternalJob))} == {"New", "By admin"}


# ---------------------------------------------------------------- preferences
def test_preferences_one_row_per_candidate_and_cascade(env):
    from app.db.recruiter_models import Candidate, CandidatePreference

    with fresh_db(env) as db:
        c = candidate(db)
        db.add(CandidatePreference(candidate_id=c.id, locations=["Mumbai", "Pune"], roles=["Data Analyst"], job_types=["full-time"], work_modes=["hybrid", "remote"]))
        db.commit()
        p = db.get(CandidatePreference, c.id)
        assert p.locations == ["Mumbai", "Pune"] and p.last_refreshed_at is None and p.created_at and p.updated_at
        p.roles = ["Data Analyst", "BI Analyst"]
        p.last_refreshed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(p)
        assert p.roles == ["Data Analyst", "BI Analyst"] and p.last_refreshed_at is not None
        db.delete(db.get(Candidate, c.id))
        db.commit()
        db.expire_all()
        assert db.scalars(select(CandidatePreference)).all() == []


# ---------------------------------------------------------------- feed
def test_feed_rows_belong_to_exactly_one_job_kind(env):
    from app.db.recruiter_models import CandidateFeedItem, ExternalJob, Job

    with fresh_db(env) as db:
        c = candidate(db)
        ext = ExternalJob(provider="indeed", external_id="1", title="T")
        job = Job(owner_id=c.user_id, title="Hiriq job", status="open")
        db.add_all([ext, job])
        db.commit()
        db.add_all([CandidateFeedItem(candidate_id=c.id, external_job_id=ext.id, score=71.5, rank=1, breakdown={"rules": 71.5, "ml": None, "genai": None}, model_version="rules-2"),
                    CandidateFeedItem(candidate_id=c.id, job_id=job.id, score=60, rank=2)])
        db.commit()
        rows = db.scalars(select(CandidateFeedItem).where(CandidateFeedItem.candidate_id == c.id).order_by(CandidateFeedItem.rank)).all()
        assert [r.rank for r in rows] == [1, 2] and rows[0].fetched_at is not None and rows[0].breakdown["rules"] == 71.5
        for bad in (dict(external_job_id=ext.id, job_id=job.id), dict()):                  # both, or neither
            db.add(CandidateFeedItem(candidate_id=c.id, score=1, rank=9, **bad))
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()
        db.add(CandidateFeedItem(candidate_id=c.id, external_job_id=ext.id, score=1, rank=3))   # the same job twice for one candidate
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_feed_rows_leave_with_a_purged_job(env):
    from app.db.recruiter_models import CandidateFeedItem, ExternalJob

    with fresh_db(env) as db:
        c = candidate(db)
        old = ExternalJob(provider="indeed", external_id="old", title="Old", listed_at=datetime.now(timezone.utc) - timedelta(days=40))
        db.add(old)
        db.commit()
        db.add(CandidateFeedItem(candidate_id=c.id, external_job_id=old.id, score=50, rank=1))
        db.commit()
        env.store.purge_stale(db)
        assert db.scalars(select(CandidateFeedItem)).all() == []


# ---------------------------------------------------------------- outside-job tracker
def test_tracker_statuses_notes_and_one_entry_per_job(env):
    from app.db.recruiter_models import EXTERNAL_STATUSES, ExternalApplication

    assert EXTERNAL_STATUSES == ("saved", "applied", "interview", "offer", "rejected")
    with fresh_db(env) as db:
        c = candidate(db)
        key = jobkeys.apply_key("https://e.com/1")
        a = ExternalApplication(candidate_id=c.id, job_key=key, title="Data Analyst", company="Acme", apply_url="https://e.com/1")
        db.add(a)
        db.commit()
        assert a.status == "saved" and a.notes is None and a.applied_at is None
        a.status, a.notes = "interview", "Round 1 on Friday"
        db.commit()
        db.refresh(a)
        assert a.status == "interview" and a.notes == "Round 1 on Friday"
        a.status = "ghosted"
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(ExternalApplication(candidate_id=c.id, job_key=key, title="Same job again"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        other = candidate(db, 2)
        db.add(ExternalApplication(candidate_id=other.id, job_key=key, title="Data Analyst"))      # another candidate may track it too
        db.commit()


def test_tracker_entry_survives_its_job_being_purged(env):
    from app.db.recruiter_models import ExternalApplication, ExternalJob

    with fresh_db(env) as db:
        c = candidate(db)
        old = ExternalJob(provider="indeed", external_id="old", title="Old", company="Acme", listed_at=datetime.now(timezone.utc) - timedelta(days=40))
        db.add(old)
        db.commit()
        db.add(ExternalApplication(candidate_id=c.id, external_job_id=old.id, job_key="k" * 40, title="Old", company="Acme", status="applied"))
        db.commit()
        env.store.purge_stale(db)
        row = db.scalars(select(ExternalApplication)).one()
        assert row.external_job_id is None and row.title == "Old" and row.status == "applied"


# ---------------------------------------------------------------- upgrading an existing database
OLD_EXTERNAL_JOBS = """CREATE TABLE external_jobs (
    id CHAR(32) NOT NULL, provider VARCHAR(30) NOT NULL, external_id VARCHAR(200) NOT NULL, title VARCHAR(160) NOT NULL,
    company VARCHAR(160), location VARCHAR(160), country VARCHAR(2), remote BOOLEAN NOT NULL, apply_url VARCHAR(600),
    description TEXT NOT NULL, posted_at TIMESTAMP, "read" JSON NOT NULL, last_query VARCHAR(100),
    first_seen_at TIMESTAMP NOT NULL, last_seen_at TIMESTAMP NOT NULL, PRIMARY KEY (id), UNIQUE (provider, external_id))"""


def test_upgrade_adds_columns_and_fills_keys_for_existing_jobs(env):
    with env.session.engine.begin() as conn:
        conn.execute(text(OLD_EXTERNAL_JOBS))
        ins = text("INSERT INTO external_jobs (id, provider, external_id, title, company, location, remote, apply_url, description, posted_at, \"read\", first_seen_at, last_seen_at) "
                   "VALUES (:id, 'indeed', :e, :t, :c, :l, 0, :u, '', :p, '{}', '2026-10-01 00:00:00', '2026-10-02 00:00:00')")
        conn.execute(ins, {"id": uuid.uuid4().hex, "e": "1", "t": "Analyst", "c": "Acme", "l": "Pune", "u": "https://e.com/j/1", "p": "2026-10-20 00:00:00"})
        conn.execute(ins, {"id": uuid.uuid4().hex, "e": "2", "t": "Analyst B", "c": "Zeta", "l": "Pune", "u": "https://www.e.com/j/1/?utm_source=x", "p": None})   # a duplicate link
        conn.execute(ins, {"id": uuid.uuid4().hex, "e": "3", "t": "Analyst C", "c": None, "l": None, "u": None, "p": None})
    changes = env.upgrade_mod.upgrade()
    assert any("apply_key" in c for c in changes) and any("listed_at" in c for c in changes)
    with env.session.engine.connect() as conn:
        rows = conn.execute(text("SELECT external_id, apply_key, dedupe_key, listed_at FROM external_jobs ORDER BY external_id")).all()
        assert rows[0][1] == jobkeys.apply_key("https://e.com/j/1") and rows[0][2]
        assert rows[1][1] is None and rows[1][2]                          # the later copy of the same link keeps no apply_key
        assert rows[2][1] is None and rows[2][2] is None                  # nothing to key on
        assert str(rows[0][3]).startswith("2026-10-20") and str(rows[2][3]).startswith("2026-10-01")   # posted date, else first seen
        names = {i["name"] for i in __import__("sqlalchemy").inspect(conn).get_indexes("external_jobs")}
        assert {"uq_external_jobs_apply_key", "ix_external_jobs_dedupe_key", "ix_external_jobs_listed_at"} <= names
        tables = set(__import__("sqlalchemy").inspect(conn).get_table_names())
        assert {"candidate_preferences", "candidate_feed", "external_applications"} <= tables
    assert env.upgrade_mod.upgrade() == []                                # running it again changes nothing
