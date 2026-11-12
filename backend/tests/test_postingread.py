"""The rules-only reader of outside job posts: skills (required vs nice), years, degree. Pure functions, no database."""
from app.services import postingread


def test_skills_are_found_in_the_order_written_and_whole_words_only():
    r = postingread.read("Analyst", "You will use Python, SQL and PowerBI daily.\nWe run MySQL and Java; not JavaScript here.")
    assert r["skills_required"] == ["python", "sql", "power bi", "mysql", "java", "javascript"]
    assert postingread.read("x", "We love excellent teamwork and the Hive of activity at GitLab.")["skills_required"] == ["hive"]   # not Excel, not Git


def test_preferred_sections_and_lines_are_nice_to_have_and_never_also_required():
    text = "Requirements\nPython and SQL\nPreferred Qualifications\nTableau and Docker\nRequired Skills\nGit\nKafka is a plus"
    r = postingread.read("x", text)
    assert r["skills_required"] == ["python", "sql", "git"] and r["skills_nice"] == ["tableau", "docker", "kafka"]
    assert postingread.read("x", "Python required.\nPython is a plus.")["skills_nice"] == []


def test_years_are_read_only_when_they_are_about_experience():
    assert postingread.read("x", "Experience Required: 2-4 Years")["experience_min"] == 2
    assert (postingread.read("x", "Experience: 6 - 8 years")["experience_min"], postingread.read("x", "Experience: 6 - 8 years")["experience_max"]) == (6, 8)
    r = postingread.read("x", "Minimum 3 years of relevant working experience.")
    assert (r["experience_min"], r["experience_max"]) == (3, None)
    assert postingread.read("x", "5+ years of experience building models")["experience_min"] == 5
    assert postingread.read("x", "18+ years of online journey and 2008 digital presence")["experience_min"] is None


def test_the_degree_line_is_kept_for_the_qualification_check():
    r = postingread.read("x", "About us\nB.E./B.Tech/M.Tech in Data Science, Statistics, or Computer Science\nMore text")
    assert r["qualification"].startswith("B.E./B.Tech/M.Tech in Data Science")
    assert postingread.read("x", "Nothing about school here")["qualification"] is None


def test_odd_input_never_raises():
    for bad in (None, "", "   \n\n", "x" * 50000):
        r = postingread.read(None, bad)
        assert r["skills_required"] == [] and r["skills_nice"] == [] and r["experience_min"] is None
