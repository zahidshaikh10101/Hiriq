"""Outside job sources: reading a saved Google Jobs page, planning the searches, the source registry, and the fetch after a
preferences save running Google Jobs (with a stand-in browser) and Indeed (with a stand-in network call)."""
import importlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from test_candidate import make_user, ready
from test_candidate_discover import indeed, item
from test_candidate_prefs import RELOAD as PREFS_RELOAD, P, env as prefs_env, put  # noqa: F401  (fixture)

SAMPLE = (Path(__file__).parent / "fixtures" / "google_jobs_sample.html").read_text(encoding="utf-8")
RELOAD = PREFS_RELOAD


@pytest.fixture
def gp():
    return importlib.import_module("app.services.sources.google_jobs_parse")


# ---------------------------------------------------------------- the searches
def test_years_are_searched_at_floor_and_ceil(gp):
    assert gp.experience_variants(3.5) == [3, 4] and gp.experience_variants(3.0) == [3] and gp.experience_variants(4) == [4]
    assert gp.experience_variants(0.4) == [0, 1] and gp.experience_variants(None) == [None] and gp.experience_variants("x") == [None]
    assert gp.experience_variants(-2) == [0]


def test_the_query_reads_like_a_person_typed_it(gp):
    assert gp.build_query("Data Analyst", "Mumbai", 3) == "Data Analyst in Mumbai with 3 years of experience jobs"
    assert gp.build_query("Data Analyst", "Mumbai", 1) == "Data Analyst in Mumbai with 1 year of experience jobs"
    assert gp.build_query("Data Analyst", "Mumbai", 0) == "Data Analyst in Mumbai for freshers jobs"
    assert gp.build_query(" Data  Analyst ", "", None) == "Data Analyst jobs"


def test_google_plans_every_role_before_a_second_place(prefs_env):
    from app.services.sources.google_jobs import GoogleJobsSource

    plan = GoogleJobsSource().plan(["Data Analyst", "BI Analyst"], ["Bengaluru", "Pune"], 4.5, 4)
    assert [s.text for s in plan] == ["Data Analyst in Bengaluru with 4 years of experience jobs",
                                      "Data Analyst in Bengaluru with 5 years of experience jobs",
                                      "BI Analyst in Bengaluru with 4 years of experience jobs",
                                      "BI Analyst in Bengaluru with 5 years of experience jobs"]
    assert plan[0].label == plan[0].text and plan[0].years == 4


# ---------------------------------------------------------------- reading the page
def test_a_saved_page_gives_every_field(gp):
    jobs = gp.parse_page(SAMPLE, now=datetime(2026, 11, 15, tzinfo=timezone.utc))
    assert [(j["title"], j["company"], j["location"], j["via"]) for j in jobs] == [
        ("Senior Data Analyst - AI & Automation", "QualityAI", "Bengaluru, Karnataka", "LinkedIn"),
        ("Senior Analyst, Digital Analytics", "Labcorp", "Bengaluru, Karnataka", "Labcorp Careers")]
    a, b = jobs
    assert a["id"] == "T-eetaF-4AL6IxetAAAAAA==" and a["employment_type"] == "Full–time" and a["posted_text"] == "2 days ago"
    assert a["posted_at"] == "2026-11-13T00:00:00Z" and b["posted_at"] == "2026-11-14T00:00:00Z"
    # the description sits in a hidden <template>; both halves ("..." and "Show full description") are joined
    assert a["description"].startswith("About the Role") and a["description"].endswith("non-technical stakeholders.")
    assert "Adobe Customer Journey Analytics" in b["description"] and "\n" in b["description"]       # <br> kept as line breaks
    # apply links: tracking removed, Google's order kept, the first one is apply_url
    assert a["apply_url"] == "https://in.linkedin.com/jobs/view/senior-data-analyst-ai-automation-at-qualityai-4484985251"
    assert b["apply_url"] == "https://careers.labcorp.com/senior-analyst-digital-analytics/job/2636637"
    assert len(a["apply_links"]) == 8 and all("utm_" not in l["url"] for l in a["apply_links"])
    assert a["apply_links"][2] == {"site": "JobzMall", "url": "https://www.jobzmall.com/amadeus-it-group/job/senior-data-analyst-it-digital-workplace-1", "direct": True}
    assert gp.missing(jobs) == []


def test_apply_links_come_from_the_hidden_list_when_the_buttons_are_missing(gp):
    import re

    no_buttons = re.sub(r'<a class="brKmxb".*?</a>', "", SAMPLE, flags=re.S)
    a, b = gp.parse_page(no_buttons)
    assert a["apply_url"].startswith("https://in.linkedin.com/jobs/view/") and len(a["apply_links"]) == 8
    assert b["apply_url"] is None and gp.missing([a, b]) == [b["id"]]        # this one gets clicked


def test_redirect_and_google_links(gp):
    assert gp.real_url("/url?sa=t&url=https://shine.com/j/1%3Futm_source%3Dx") == "https://shine.com/j/1"
    assert gp.real_url(None, "/url?url=https://naukri.com/a?b=1&utm_medium=y") == "https://naukri.com/a?b=1"
    assert gp.real_url("https://www.google.com/search?q=x") is None and gp.real_url("javascript:alert(1)") is None
    assert gp.apply_links_from([{"title": "Share", "href": "https://x.com"}, {"title": "Apply on Naukri", "href": "https://naukri.com/1"}]) == [
        {"site": "Naukri", "url": "https://naukri.com/1", "direct": False}]


def test_a_card_without_its_details_and_the_open_panel(gp):
    card = ('<div jsname="y1Aese" id="Ok1llf2YurH3jiQfAAAAAA=="><div jsname="OCDbef"><div class="tNxQIb">Healthcare Data Analyst</div>'
            '<div class="a3jPc">SDNA Global</div><div class="FqK3wc">Bengaluru • via Shine</div></div></div>')
    rows = gp.parse_page(card)
    assert rows[0]["apply_url"] is None and gp.missing(rows) == ["Ok1llf2YurH3jiQfAAAAAA=="]
    panel = ('<div class="NmXWu"><span data-encoded-docid="Ok1llf2YurH3jiQfAAAAAA=="><a class="brKmxb" title="Apply directly on Shine" '
             'href="https://www.shine.com/jobs/x/19577603?utm_campaign=google_jobs_apply&amp;utm_source=google_jobs_apply"></a></span></div>')
    assert gp.parse_page(card + panel)[0]["apply_url"] == "https://www.shine.com/jobs/x/19577603"
    merged = gp.merge_panel(rows, {"Ok1llf2YurH3jiQfAAAAAA==": {"apply_links": [{"site": "Shine", "url": "https://shine.com/1", "direct": True}], "description": "Text"}})
    assert merged[0]["apply_url"] == "https://shine.com/1" and merged[0]["description"] == "Text"


def test_junk_pages_give_nothing(gp):
    assert gp.parse_page("") == [] and gp.parse_page("<html><body>No jobs</body></html>") == []


# ---------------------------------------------------------------- the registry
def test_sources_are_off_until_set_up(prefs_env, monkeypatch):
    src = importlib.import_module("app.services.sources")
    assert src.enabled() == [] and src.any_configured() is False
    monkeypatch.setenv("RAPIDAPI_KEY", "k")
    assert [s.name for s in src.enabled()] == ["indeed"]
    monkeypatch.setenv("GOOGLE_JOBS_SCRAPER", "1")
    monkeypatch.setattr(src.google_jobs if hasattr(src, "google_jobs") else importlib.import_module("app.services.sources.google_jobs"), "installed", lambda: True)
    assert [s.name for s in src.enabled()] == ["google_jobs", "indeed"]
    monkeypatch.setenv("JOB_SOURCES", "indeed, nonsense")
    assert [s.name for s in src.enabled()] == ["indeed"]


def test_google_without_playwright_stays_off(prefs_env, monkeypatch):
    g = importlib.import_module("app.services.sources.google_jobs")
    monkeypatch.setenv("GOOGLE_JOBS_SCRAPER", "1")
    monkeypatch.setattr(g, "installed", lambda: False)
    assert g.GoogleJobsSource().configured() is False


# ---------------------------------------------------------------- the fetch after a save
class FakeBrowser:
    def __init__(self, pages, sent, fail=None):
        self.pages, self.sent, self.fail = pages, sent, fail

    def fetch(self, s):
        self.sent.append(s.text)
        if self.fail and len(self.sent) in self.fail:
            raise self.fail[len(self.sent)]
        gp = importlib.import_module("app.services.sources.google_jobs_parse")
        return gp.parse_page(self.pages.get(len(self.sent), ""))


def google_on(env, monkeypatch, pages=None, fail=None):
    g = importlib.import_module("app.services.sources.google_jobs")
    monkeypatch.setenv("GOOGLE_JOBS_SCRAPER", "1")
    monkeypatch.setenv("GOOGLE_JOBS_DELAY", "0-0")
    monkeypatch.setattr(g, "installed", lambda: True)
    env.gsent = []

    @contextmanager
    def session(self):
        yield FakeBrowser(pages if pages is not None else {1: SAMPLE}, env.gsent, fail)

    monkeypatch.setattr(g.GoogleJobsSource, "_session", session)
    return g


def rows(env):
    from app.db.recruiter_models import ExternalJob

    with env.session.SessionLocal() as db:
        return [(r.provider, r.title, r.employment_type, r.source_site, r.apply_url, len(r.apply_links), r.last_query)
                for r in db.scalars(select(ExternalJob).order_by(ExternalJob.title)).all()]


def test_saving_runs_google_with_the_resume_years_and_keeps_the_extra_fields(prefs_env, monkeypatch):
    env = prefs_env
    google_on(env, monkeypatch)
    _, h = ready(env, total_experience_years=3.5)
    r = put(env, h, roles=["Data Analyst"], locations=["Bengaluru"])
    assert r.json()["fetching"] is True
    assert env.gsent == ["Data Analyst in Bengaluru with 3 years of experience jobs", "Data Analyst in Bengaluru with 4 years of experience jobs"]
    assert rows(env) == [
        ("google_jobs", "Senior Analyst, Digital Analytics", "Full–time", "Labcorp Careers", "https://careers.labcorp.com/senior-analyst-digital-analytics/job/2636637", 8,
         "Data Analyst in Bengaluru with 3 years of experience jobs"),
        ("google_jobs", "Senior Data Analyst - AI & Automation", "Full–time", "LinkedIn", "https://in.linkedin.com/jobs/view/senior-data-analyst-ai-automation-at-qualityai-4484985251", 8,
         "Data Analyst in Bengaluru with 3 years of experience jobs")]
    from app.db.recruiter_models import ExternalCall, ExternalJob

    with env.session.SessionLocal() as db:
        job = db.scalars(select(ExternalJob).where(ExternalJob.company == "Labcorp")).one()
        assert job.read["experience_min"] == 4 and job.description.startswith("Labcorp is seeking")
        calls = db.scalars(select(ExternalCall)).all()
        assert [(c.provider, c.ok, c.results) for c in calls] == [("google_jobs", True, 2), ("google_jobs", True, 0)]
    assert env.ext.used_this_month() == 0                       # Google searches never use the RapidAPI allowance


def test_google_runs_first_then_indeed_and_the_same_post_is_not_saved_twice(prefs_env, monkeypatch):
    env = prefs_env
    google_on(env, monkeypatch, pages={1: SAMPLE, 2: SAMPLE})
    monkeypatch.setenv("RAPIDAPI_KEY", "k")
    env.sent = []

    def fake(params):
        env.sent.append(params)
        return indeed(item(1, "Indeed Only"))

    monkeypatch.setattr(env.ext, "_get", fake)
    _, h = ready(env, total_experience_years=4.5)
    put(env, h, roles=["Data Analyst"], locations=["Bengaluru"])
    assert len(env.gsent) == 2 and len(env.sent) == 1
    assert sorted(p for p, *_ in rows(env)) == ["google_jobs", "google_jobs", "indeed"]


def test_a_captcha_stops_google_but_not_indeed_and_never_breaks_the_save(prefs_env, monkeypatch):
    env = prefs_env
    g = google_on(env, monkeypatch, fail={1: importlib.import_module("app.services.sources.base").SourceError("blocked", "captcha")})
    monkeypatch.setenv("RAPIDAPI_KEY", "k")
    monkeypatch.setattr(env.ext, "_get", lambda params: indeed(item(1, "Indeed Only")))
    _, h = ready(env, total_experience_years=2.5)
    r = put(env, h, roles=["Data Analyst"])
    assert r.status_code == 200 and env.gsent == ["Data Analyst with 2 years of experience jobs"]
    assert [p for p, *_ in rows(env)] == ["indeed"]
    from app.db.recruiter_models import ExternalCall

    with env.session.SessionLocal() as db:
        assert [(c.provider, c.ok, c.error) for c in db.scalars(select(ExternalCall).where(ExternalCall.provider == g.PROVIDER))] == [("google_jobs", False, "blocked")]


def test_a_page_that_changed_shape_skips_one_search_only(prefs_env, monkeypatch):
    env = prefs_env
    google_on(env, monkeypatch, pages={2: SAMPLE}, fail={1: KeyError("x")})
    _, h = ready(env, total_experience_years=4.5)
    put(env, h, roles=["Data Analyst"])
    assert len(env.gsent) == 2 and len(rows(env)) == 2


def test_the_daily_google_limit_counts_from_the_log(prefs_env, monkeypatch):
    env = prefs_env
    google_on(env, monkeypatch)
    monkeypatch.setenv("GOOGLE_JOBS_DAILY_CAP", "1")
    _, h = ready(env, total_experience_years=4.5)
    put(env, h, roles=["Data Analyst"])
    assert len(env.gsent) == 1                                  # the second search would pass the limit
    _, h2 = make_user(env, "b@example.com")
    put(env, h2, roles=["BI Analyst"])
    assert len(env.gsent) == 1


def test_no_resume_years_searches_without_them(prefs_env, monkeypatch):
    env = prefs_env
    google_on(env, monkeypatch, pages={})
    _, h = make_user(env, "new@example.com")
    put(env, h, roles=["Data Analyst"], locations=["Pune"])
    assert env.gsent == ["Data Analyst in Pune jobs"]


def test_feed_on_shows_when_google_alone_is_set_up(prefs_env, monkeypatch):
    env = prefs_env
    google_on(env, monkeypatch)
    _, h = make_user(env, "x@example.com")
    assert env.client.get(P, headers=h).json()["feed_on"] is True


def test_upgrade_adds_the_new_columns_to_an_old_table(prefs_env):
    env = prefs_env
    from sqlalchemy import inspect, text

    eng = env.session.engine
    with eng.begin() as c:
        for col in ("employment_type", "salary_text", "source_site", "apply_links"):
            c.execute(text(f"ALTER TABLE external_jobs DROP COLUMN {col}"))
    up = importlib.reload(importlib.import_module("app.db.upgrade"))
    done = up.upgrade()
    assert {"added external_jobs.employment_type", "added external_jobs.apply_links"} <= set(done)
    assert {"employment_type", "salary_text", "source_site", "apply_links"} <= {c["name"] for c in inspect(eng).get_columns("external_jobs")}
    assert not [d for d in up.upgrade() if "external_jobs" in d]
