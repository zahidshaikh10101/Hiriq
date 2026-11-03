"""The matching engine on its own: skill knowledge, the five parts, weights, honesty about gaps, and the AI-judge guards."""
import pytest

from app.services import matching as m

JD = ("We are hiring a Senior Data Analyst to own reporting for the retail business. You will build dashboards for the sales team, "
      "automate weekly reporting, clean messy sales data and present insights to the leadership team every month. "
      "Strong reporting and dashboard storytelling with retail stakeholders is essential.")
JOB = {"skills_required": ["SQL", "Python", "Power BI"], "skills_nice": ["Tableau", "dbt"], "experience_min": 3, "experience_max": 5,
       "location": "Mumbai", "work_mode": "hybrid", "qualification": "Bachelor's degree in Computer Science or a related field",
       "text": "Senior Data Analyst\n" + JD}
TEXT = "\n".join([
    "Senior Data Analyst, Northwind Retail   Mar 2020 - Dec 2023",
    "Built Power BI dashboards and SQL pipelines for the sales team.",
    "Cleaned data in Python and wrote weekly reporting packs in Excel for the retail business.",
    "Presented insights to the leadership team every month.",
    "SKILLS: SQL, Python, Power BI, Excel",
])
CAND = {"skills": ["SQL", "Python", "Power BI", "Excel"], "years": 4.0, "location": "Mumbai, Maharashtra", "text": TEXT,
        "qualification": "B.Tech in Computer Science", "education": ["B.Tech in Computer Science"]}


def score(job=None, cand=None, **kw):
    return m.score_candidate({**JOB, **(job or {})}, {**CAND, **(cand or {})}, **kw)


def req(result, name):
    return next(r for r in result["explanation"]["skills"]["required"] + result["explanation"]["skills"]["nice"] if r["skill"] == name)


def part(result, name):
    return result["breakdown"]["parts"][name]["score"]


# ---------------------------------------------------------------- skill names
@pytest.mark.parametrize("a,b", [("PowerBI", "power bi"), ("Microsoft Power BI", "POWER BI"), ("Node.js", "nodejs"), ("NodeJS", "node js"),
                                 ("Postgres", "PostgreSQL"), ("k8s", "Kubernetes"), ("sklearn", "scikit-learn"), ("C Sharp", "c#"), ("T-SQL", "sql server")])
def test_spellings_of_one_skill_are_one_skill(a, b):
    assert m.canon(a) == m.canon(b)


def test_unknown_skills_are_kept_as_written_but_normalised():
    assert m.canon("  Prompt   Engineering ") == "prompt engineering"
    assert m.canon("C") != m.canon("C#") != m.canon("C++")


# ---------------------------------------------------------------- the skills part
def test_a_full_match_scores_full_marks_on_skills_and_shows_evidence():
    r = score()
    assert part(r, "skills") == pytest.approx(100 * (3 + 0.4 * 0.5) / 3.8, abs=0.1)   # Tableau is only "related" to Power BI
    sql = req(r, "SQL")
    assert sql["status"] == "listed" and sql["credit"] == 1 and "SQL pipelines" in sql["evidence"]      # a real experience line, not the SKILLS line
    assert req(r, "Power BI")["evidence"] == "Built Power BI dashboards and SQL pipelines for the sales team."


def test_nice_to_haves_count_less_than_must_haves():
    r = score(job={"skills_nice": ["Terraform", "dbt"]})
    # all 3 required met, none of the 2 nice: 3 / (3 + 0.4*2)
    assert part(r, "skills") == pytest.approx(100 * 3 / 3.8, abs=0.1)
    only_nice_missing = part(r, "skills")
    one_required_missing = part(score(cand={"skills": ["SQL", "Python"], "text": "SQL and Python daily work every week."}), "skills")
    assert only_nice_missing > one_required_missing


def test_a_specific_skill_satisfies_the_generic_one_but_not_the_reverse():
    pg = score(job={"skills_required": ["SQL"], "skills_nice": []}, cand={"skills": ["PostgreSQL"], "text": "Tuned PostgreSQL queries for reporting."})
    assert req(pg, "SQL")["status"] == "implied" and req(pg, "SQL")["via"] == "PostgreSQL" and req(pg, "SQL")["credit"] == 1
    rev = score(job={"skills_required": ["PostgreSQL"], "skills_nice": []}, cand={"skills": ["SQL"], "text": "Wrote SQL for reports and dashboards."})
    assert req(rev, "PostgreSQL")["status"] == "related" and req(rev, "PostgreSQL")["credit"] == 0.5


def test_similar_tools_earn_half_credit_and_say_which_tool():
    r = score(job={"skills_required": ["Power BI"], "skills_nice": []}, cand={"skills": ["Tableau"], "text": "Built Tableau dashboards for sales leaders."})
    s = req(r, "Power BI")
    assert (s["status"], s["credit"], s["via"]) == ("related", 0.5, "Tableau") and "Tableau dashboards" in s["evidence"]
    assert part(r, "skills") == 50.0


def test_a_skill_in_the_text_but_not_in_the_skills_list_still_counts():
    r = score(job={"skills_required": ["Airflow"], "skills_nice": []}, cand={"skills": [], "text": "Scheduled nightly jobs with Apache Airflow and monitored retries."})
    s = req(r, "Airflow")
    assert s["status"] == "text" and s["credit"] == 1 and "Airflow" in s["evidence"]


def test_missing_skills_say_missing_and_have_no_evidence():
    r = score(job={"skills_required": ["Kubernetes"], "skills_nice": []})
    s = req(r, "Kubernetes")
    assert (s["status"], s["credit"], s["evidence"], s["via"]) == ("missing", 0, None, None)
    assert part(r, "skills") == 0


@pytest.mark.parametrize("wanted,text", [
    ("REST API", "Took the rest of the team through the roadmap"),       # an everyday word is not a skill
    ("SQL", "Worked at Oracle Corporation on retail projects"),          # an employer name is not a skill
    ("Java", "Built dashboards in JavaScript"), ("Git", "Hosted code on GitHub"), ("R", "R&D team lead"), ("C", "Used C++ daily"),
    ("Spark", "Ran PySpark jobs nightly"),
])
def test_no_false_matches_from_lookalike_words(wanted, text):
    r = score(job={"skills_required": [wanted], "skills_nice": []}, cand={"skills": [], "text": text + " every day of the week."})
    assert req(r, wanted)["credit"] < 1 or req(r, wanted)["status"] == "implied"
    assert req(r, wanted)["status"] in ("missing", "related", "implied")


def test_spelling_variants_in_free_text_are_found():
    for variant in ("PowerBI", "power-bi", "Microsoft Power BI", "power bi"):
        r = score(job={"skills_required": ["Power BI"], "skills_nice": []}, cand={"skills": [], "text": f"Created reports in {variant} for finance."})
        assert req(r, "Power BI")["status"] == "text", variant


def test_c_plus_plus_and_c_sharp_are_not_c():
    r = score(job={"skills_required": ["C#"], "skills_nice": []}, cand={"skills": ["C++"], "text": "Wrote C++ services for trading systems."})
    assert req(r, "C#")["status"] != "listed" and req(r, "C#")["credit"] < 1


# ---------------------------------------------------------------- qualification
@pytest.mark.parametrize("text,levels", [
    ("B.Tech in Computer Science", {3}), ("BTech", {3}), ("B.E. in IT", {3}), ("BE in Information Technology", {3}), ("Bachelor of Science", {3}),
    ("M.Tech in Data Science", {4}), ("MTech", {4}), ("MBA", {4}), ("MCA", {4}), ("M.Sc. Statistics", {4}), ("Master's in Analytics", {4}), ("MS in Data Science", {4}),
    ("Post graduate diploma in management", {4}), ("PhD in Machine Learning", {5}), ("Doctorate", {5}),
    ("Diploma in Computer Engineering", {2}), ("12th Science", {1}), ("Bachelor's or Master's degree", {3, 4}),
    ("B.E. / B.Tech / M.Tech", {3, 4}), ("Any graduate", {3}),
    ("MS Excel", set()), ("IIT Bombay", set()), ("to be or not to be", set()), ("", set()), (None, set()),
])
def test_degree_levels(text, levels):
    assert m.degree_levels(text) == levels


def test_meeting_or_beating_the_asked_level_is_full_marks():
    assert score()["explanation"]["qualification"]["state"] == "meets" and part(score(), "qualification") == 100.0
    higher = score(cand={"qualification": "M.Tech in Data Science", "education": ["B.E.", "M.Tech in Data Science"]})
    assert part(higher, "qualification") == 100.0 and higher["explanation"]["qualification"]["level"] == "master's"


def test_one_level_short_earns_half_and_more_than_one_earns_nothing():
    master_job = {"qualification": "Master's degree in a quantitative field"}
    assert part(score(job=master_job), "qualification") == 50.0
    assert score(job=master_job)["explanation"]["qualification"]["state"] == "below"
    phd_job = {"qualification": "PhD"}
    assert part(score(job=phd_job, cand={"qualification": "M.Tech", "education": []}), "qualification") == 50.0   # a master's is one level under a doctorate
    assert part(score(job=phd_job), "qualification") == 0.0                                                     # a bachelor's is two
    assert part(score(job=master_job, cand={"qualification": "Diploma in Computer Engineering", "education": []}), "qualification") == 0.0


def test_a_job_asking_bachelors_or_masters_needs_only_the_lower_one():
    assert part(score(job={"qualification": "B.E./B.Tech or M.Tech"}), "qualification") == 100.0


def test_the_degree_can_come_from_the_education_list_when_qualification_is_blank():
    r = score(cand={"qualification": None, "education": ["M.Sc in Statistics"]}, job={"qualification": "Master's degree"})
    assert part(r, "qualification") == 100.0


def test_qualification_is_not_assessed_or_unknown_rather_than_zero():
    none = score(job={"qualification": None})
    assert none["explanation"]["qualification"]["state"] == "not_assessed" and none["breakdown"]["parts"]["qualification"]["assessed"] is False
    vague = score(job={"qualification": "Relevant discipline"})
    assert vague["explanation"]["qualification"]["state"] == "not_assessed"
    unknown = score(cand={"qualification": None, "education": []})
    assert unknown["explanation"]["qualification"]["state"] == "unknown" and unknown["assessed_weight"] == 80
    assert unknown["score"] > score(cand={"qualification": "12th Science", "education": []}, job={"qualification": "Master's degree"})["score"]


def test_the_institution_never_changes_the_qualification_score():
    a = score(cand={"qualification": "B.Tech in Computer Science", "education": ["B.Tech in Computer Science"]})
    b = score(cand={"qualification": "B.Tech in Computer Science", "education": ["B.Tech in Computer Science"], "institution": "IIT Bombay", "college": "IIT Bombay"})
    assert a["score"] == b["score"] and a["explanation"]["qualification"] == b["explanation"]["qualification"]
    assert score(cand={"qualification": "IIT Bombay", "education": []})["explanation"]["qualification"]["state"] == "unknown"


# ---------------------------------------------------------------- keywords
def test_keywords_come_from_the_job_text_and_exclude_skill_names():
    k = score()["explanation"]["keywords"]
    assert k["state"] == "assessed" and 0 < k["score"] <= 100 and k["total"] >= m.MIN_KEYWORDS
    everything = set(k["matched"]) | set(k["missing"])
    assert not everything & {"sql", "python", "power", "tableau", "dbt"}       # skills have their own part
    assert not everything & {"the", "and", "strong", "essential", "will", "team"} or "team" not in everything     # filler is dropped


def test_a_resume_that_echoes_the_job_scores_higher_than_one_that_does_not():
    echo = score()
    off_topic = score(cand={"text": "Managed a warehouse and drove forklifts across three depots for many years, training new loaders and "
                                    "keeping stock records tidy while coordinating deliveries with regional suppliers."})
    assert part(echo, "keywords") > part(off_topic, "keywords")
    assert off_topic["explanation"]["keywords"]["missing"]


def test_plurals_and_endings_do_not_hide_a_match():
    job = {"text": "dashboards reporting analysis retail stakeholders insights " * 6, "skills_required": ["Zzz"], "skills_nice": []}
    r = score(job=job, cand={"text": "I built a dashboard and reported on retail stakeholder insight every week for the finance and sales groups of the business unit, then shared the analysis with managers during monthly reviews."})
    assert part(r, "keywords") >= 60


def test_keywords_are_not_assessed_for_a_thin_job_text_and_unknown_for_a_thin_resume():
    assert score(job={"text": "Data analyst wanted."})["explanation"]["keywords"]["state"] == "not_assessed"
    assert score(job={"text": None})["explanation"]["keywords"]["state"] == "not_assessed"
    thin = score(cand={"text": "SQL Python"})
    assert thin["explanation"]["keywords"]["state"] == "unknown" and thin["breakdown"]["parts"]["keywords"]["assessed"] is False


# ---------------------------------------------------------------- experience
@pytest.mark.parametrize("years,state,score_", [(4, "within", 100.0), (3, "within", 100.0), (5, "within", 100.0), (1.5, "below", 50.0), (0, "below", 0.0),
                                                (7, "above", 90.0), (30, "above", 80.0)])
def test_experience_against_the_range(years, state, score_):
    p = score(cand={"years": years})["explanation"]["experience"]
    assert (p["state"], p["score"]) == (state, score_)


def test_experience_with_only_a_minimum_or_only_a_maximum():
    assert score(job={"experience_min": 3, "experience_max": None}, cand={"years": 12})["explanation"]["experience"]["state"] == "within"
    assert score(job={"experience_min": None, "experience_max": 2}, cand={"years": 1})["explanation"]["experience"]["state"] == "within"
    assert score(job={"experience_min": 4, "experience_max": 4}, cand={"years": 4})["explanation"]["experience"]["reason"].endswith("within 4 years.")


def test_unknown_years_are_left_out_not_zeroed():
    r = score(cand={"years": None})
    assert r["explanation"]["experience"]["state"] == "unknown" and r["breakdown"]["parts"]["experience"]["assessed"] is False
    assert r["assessed_weight"] == 70
    # the other four parts are re-weighted among themselves, so a missing field does not drag the score down
    w, p = r["breakdown"]["weights"], r["breakdown"]["parts"]
    expected = sum(w[k] * p[k]["score"] for k in m.PARTS if k != "experience") / 70
    assert r["score"] == pytest.approx(expected, abs=0.1)
    assert r["score"] > score(cand={"years": 0})["score"]            # unknown is treated better than known-to-be-zero
    assert any(n["part"] == "experience" for n in r["explanation"]["not_assessed"])
    assert "70% of the criteria" in r["explanation"]["summary"]


def test_no_experience_range_on_the_job_is_not_assessed():
    r = score(job={"experience_min": None, "experience_max": None})
    assert r["explanation"]["experience"]["state"] == "not_assessed" and r["assessed_weight"] == 70


# ---------------------------------------------------------------- location
@pytest.mark.parametrize("job,cand,state", [
    ("Mumbai", "Mumbai, Maharashtra", "match"), ("Bangalore", "Bengaluru, Karnataka", "match"), ("Bengaluru", "Bangalore", "match"),
    ("Mumbai", "Navi Mumbai", "match"), ("Delhi NCR", "Noida, Uttar Pradesh", "different"), ("Gurgaon", "New Delhi", "match"),
    ("Pune", "Mumbai", "different"), ("Mumbai, Maharashtra", "Greater Mumbai Area", "match"), ("Hyderabad", "Secunderabad, Telangana", "different"),
])
def test_location_matching(job, cand, state):
    assert score(job={"location": job}, cand={"location": cand})["explanation"]["location"]["state"] == state


def test_remote_jobs_and_unknown_places_are_not_scored():
    assert score(job={"work_mode": "remote"})["explanation"]["location"]["state"] == "not_assessed"
    assert score(job={"location": None})["explanation"]["location"]["state"] == "not_assessed"
    unknown = score(cand={"location": None})
    assert unknown["explanation"]["location"]["state"] == "unknown" and unknown["assessed_weight"] == 95


def test_a_different_city_scores_zero_on_location_and_says_relocation_is_not_assessed():
    p = score(cand={"location": "Chennai"})["explanation"]["location"]
    assert p["score"] == 0 and "relocate" in p["reason"]


# ---------------------------------------------------------------- weights and totals
def test_the_default_weights_are_40_20_30_5_5():
    assert m.DEFAULT_WEIGHTS == {"skills": 40, "qualification": 20, "experience": 30, "location": 5, "keywords": 5}
    assert sum(m.DEFAULT_WEIGHTS.values()) == 100 and m.PARTS == ("skills", "qualification", "experience", "location", "keywords")


def test_default_weights_and_the_total():
    r = score()
    p = r["breakdown"]["parts"]
    expected = (40 * p["skills"]["score"] + 20 * 100 + 30 * 100 + 5 * 100 + 5 * p["keywords"]["score"]) / 100
    assert r["breakdown"]["weights"] == m.DEFAULT_WEIGHTS and r["score"] == pytest.approx(expected, abs=0.1)
    assert r["assessed_weight"] == 100 and r["breakdown"]["version"] == "rules-2"


def test_changing_weights_changes_the_ranking_the_way_you_would_expect():
    senior_unskilled = {"skills": ["Excel"], "years": 4, "text": "Excel reports for the finance team every month."}
    skilled_junior = {"skills": ["SQL", "Python", "Power BI"], "years": 1, "text": "SQL Python Power BI dashboards for sales every week."}
    skills_first = {"skills": 90, "qualification": 0, "experience": 5, "location": 5, "keywords": 0}
    exp_first = {"skills": 5, "qualification": 0, "experience": 90, "location": 5, "keywords": 0}
    assert score(cand=skilled_junior, weights=skills_first)["score"] > score(cand=senior_unskilled, weights=skills_first)["score"]
    assert score(cand=skilled_junior, weights=exp_first)["score"] < score(cand=senior_unskilled, weights=exp_first)["score"]


def test_a_zero_weight_part_is_ignored_and_listed_as_not_assessed():
    r = score(cand={"location": "Chennai"}, weights={"skills": 50, "experience": 50, "location": 0, "qualification": 0, "keywords": 0})
    assert r["breakdown"]["parts"]["location"]["assessed"] is False and r["assessed_weight"] == 100
    assert r["score"] > score(cand={"location": "Chennai"})["score"] or r["score"] > 90


@pytest.mark.parametrize("raw,needle", [
    ({"skills": -1}, "0 to 100"), ({"skills": 101}, "0 to 100"), ({"skills": "60"}, "number"), ({"skills": True}, "number"),
    ({"skills": 0, "qualification": 0, "experience": 0, "location": 0, "keywords": 0}, "above zero"), ({"colour": 5}, "Unknown weight"), ("lots", "object"),
    ({"skills": float("nan")}, "number"), ({"keywords": -5}, "keywords weight"),
])
def test_bad_weights_are_refused_with_a_clear_message(raw, needle):
    with pytest.raises(m.WeightError) as e:
        m.normalize_weights(raw)
    assert needle in str(e.value)


def test_weights_are_filled_in_and_rounded():
    assert m.normalize_weights(None) == m.DEFAULT_WEIGHTS
    assert m.normalize_weights({"skills": 70.4}) == {**m.DEFAULT_WEIGHTS, "skills": 70}
    assert m.normalize_weights({"qualification": 0})["qualification"] == 0


def test_a_job_with_nothing_assessable_scores_zero_without_crashing():
    r = score(job={"skills_required": [], "skills_nice": [], "experience_min": None, "experience_max": None, "work_mode": "remote",
                   "qualification": None, "text": ""})
    assert r["score"] == 0 and r["assessed_weight"] == 0 and len(r["explanation"]["not_assessed"]) == 5


# ---------------------------------------------------------------- fairness
def test_identity_fields_cannot_change_a_score():
    """score_candidate only reads skills, years, location, qualification, education and text. Anything else on the candidate is ignored."""
    base = score()
    noisy = score(cand={"full_name": "Zoya Khan", "gender": "female", "dob": "1990-01-01", "photo": "x.png",
                        "institution": "IIT Bombay", "college": "IIT Bombay", "email": "z@example.org", "age": 57})
    assert noisy["score"] == base["score"] and noisy["explanation"]["skills"] == base["explanation"]["skills"]


def test_ranking_is_by_score_then_required_coverage_never_by_name():
    a = score(cand={"skills": ["SQL"], "text": "SQL reports every week for the team."})
    b = score(cand={"skills": ["SQL", "Python", "Power BI"], "text": "SQL Python Power BI every week."})
    assert sorted([a, b], key=m.rank_key)[0] is b
    tie1, tie2 = score(), score()
    assert m.rank_key(tie1) == m.rank_key(tie2)


# ---------------------------------------------------------------- the AI judge's guard rails
def test_a_verified_related_verdict_gives_half_credit_and_is_marked_ai():
    job = {"skills_required": ["Airflow"], "skills_nice": []}
    c = {"skills": [], "text": "Scheduled nightly pipelines with Luigi and monitored retries."}
    rules = score(job=job, cand=c)
    judged = score(job=job, cand=c, verdicts={"airflow": {"verdict": "related", "quote": "Scheduled nightly pipelines with Luigi"}})
    s = req(judged, "Airflow")
    assert req(rules, "Airflow")["status"] == "missing"
    assert (s["status"], s["credit"], s["ai"]) == ("ai_related", 0.5, True) and judged["score"] > rules["score"]


def test_a_verdict_can_never_give_more_than_half_credit_or_beat_a_real_match():
    job = {"skills_required": ["Airflow"], "skills_nice": []}
    c = {"skills": ["Airflow"], "text": "Ran Apache Airflow in production for two years."}
    r = score(job=job, cand=c, verdicts={"airflow": {"verdict": "related", "quote": "something"}})
    assert req(r, "Airflow")["status"] == "listed" and req(r, "Airflow")["ai"] is False
    assert score(job=job, cand={"skills": [], "text": "nothing relevant here at all"}, verdicts={"airflow": {"verdict": "none"}})["score"] == score(job=job, cand={"skills": [], "text": "nothing relevant here at all"})["score"]


def test_quote_verification():
    text = "Scheduled nightly pipelines with   Luigi and monitored retries."
    assert m.verify_quote("scheduled nightly pipelines with luigi", text)
    assert not m.verify_quote("Orchestrated Airflow DAGs", text)       # invented
    assert not m.verify_quote("", text) and not m.verify_quote(None, text) and not m.verify_quote("abc", text) and not m.verify_quote("x" * 400, "x" * 500)


def test_gaps_lists_required_first_and_skips_covered_skills():
    r = score(job={"skills_required": ["Kubernetes", "SQL"], "skills_nice": ["Terraform"]})
    assert m.gaps(r) == ["Kubernetes", "Terraform"]
    assert m.gaps(score(job={"skills_required": ["A1", "B1", "C1", "D1", "E1", "F1"], "skills_nice": ["G1", "H1", "I1"]}), limit=4) == ["A1", "B1", "C1", "D1"]


def test_redaction_removes_identity_before_text_leaves_the_server():
    text = "Aarav Mehta\naarav.mehta@example.org | +91 98765 43210\nhttps://www.linkedin.com/in/aarav-mehta  github.com/aaravm\nMehta Analytics Ltd\nBuilt Power BI dashboards."
    out = m.redact(text, name="Aarav Mehta", email="aarav.mehta@example.org", phone="+919876543210", links=("https://www.linkedin.com/in/aarav-mehta",))
    for secret in ("Aarav", "aarav.mehta", "98765", "linkedin.com", "github.com/aaravm"):
        assert secret.lower() not in out.lower(), secret
    assert "Built Power BI dashboards." in out and "[candidate]" in out


def test_text_hash_changes_when_the_resume_changes():
    assert m.text_hash("a") == m.text_hash("a") != m.text_hash("b") and m.text_hash(None) == m.text_hash("")
