"""The matching engine: how well does a candidate fit a job, and why.

Pure functions, no database and no network, so every score can be reproduced from the same inputs.

What decides a score (and nothing else), with the default weight of each part:
  skills         40%  the job's required and nice-to-have skills against the candidate's skills and resume text
  qualification  20%  the candidate's highest degree level against the level the job asks for
  experience     30%  the candidate's years against the job's range
  location        5%  the candidate's city against the job's city (skipped for remote jobs)
  keywords        5%  how many of the job description's key terms also appear in the resume
Name, gender, photo, college and date of birth are never inputs. `score_candidate` does not even receive them.
Qualification looks at the degree LEVEL only (diploma, bachelor's, master's, doctorate), never at the institution.

Honesty rules:
  * A part that cannot be assessed (the job has no range, the resume has no dates, ...) is left out and the other
    parts are re-weighted. The result says which parts were not assessed instead of guessing a number.
  * Every skill verdict carries its evidence: the line of the resume that shows it.
  * The optional AI judge can only lift a missing skill to "related" (half credit), and only with a quote that is
    verified to exist in the resume text. It can never invent a full match.
"""
from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from typing import Any

VERSION = "rules-2"
DEFAULT_WEIGHTS = {"skills": 40, "qualification": 20, "experience": 30, "location": 5, "keywords": 5}
PARTS = tuple(DEFAULT_WEIGHTS)
NICE_WEIGHT = 0.4          # a nice-to-have skill counts this much of a required one
RELATED_CREDIT = 0.5       # a related skill (Tableau for Power BI) earns half
ABOVE_RANGE_FLOOR = 0.8    # being over the experience range costs at most 20%
ONE_LEVEL_BELOW = 50.0     # a master's asked for and a bachelor's held (or a bachelor's asked for and a diploma held)
KEYWORD_LIMIT = 25         # how many key terms of the job description are looked for
MIN_JD_WORDS = 25          # a shorter job text says too little to compare
MIN_KEYWORDS = 5
MIN_RESUME_WORDS = 25

# ---------------------------------------------------------------- skill knowledge
# canonical name -> other ways people write it. Extend freely: nothing else needs to change.
SYNONYMS: dict[str, list[str]] = {
    "sql": ["sql", "structured query language"],
    "power bi": ["power bi", "powerbi", "microsoft power bi", "ms power bi"],
    "excel": ["excel", "ms excel", "microsoft excel", "advanced excel"],
    "tableau": ["tableau"], "looker": ["looker", "looker studio", "data studio"], "qlik": ["qlik", "qlikview", "qlik sense"],
    "metabase": ["metabase"], "superset": ["superset", "apache superset"], "quicksight": ["quicksight", "amazon quicksight"],
    "python": ["python", "python3", "python 3"], "r": ["r", "r language"], "java": ["java"],
    "javascript": ["javascript", "js", "ecmascript"], "typescript": ["typescript", "ts"],
    "node.js": ["node.js", "nodejs", "node js"], "react": ["react", "react.js", "reactjs"], "angular": ["angular", "angularjs"],
    "vue": ["vue", "vue.js", "vuejs"], "c#": ["c#", "csharp", "c sharp"], "c++": ["c++", "cpp"], ".net": [".net", "dotnet", "dot net", ".net core", "asp.net"],
    "go": ["golang", "go language"], "scala": ["scala"], "kotlin": ["kotlin"], "php": ["php"], "ruby": ["ruby", "ruby on rails"],
    "postgresql": ["postgresql", "postgres", "psql"], "mysql": ["mysql"], "sql server": ["sql server", "mssql", "ms sql", "microsoft sql server", "t-sql", "tsql"],
    "oracle": ["oracle", "oracle db", "oracle database", "pl/sql", "plsql"], "sqlite": ["sqlite"], "mariadb": ["mariadb"],
    "mongodb": ["mongodb", "mongo"], "redis": ["redis"], "cassandra": ["cassandra"], "dynamodb": ["dynamodb"],
    "snowflake": ["snowflake"], "bigquery": ["bigquery", "big query"], "redshift": ["redshift", "amazon redshift"], "databricks": ["databricks"],
    "apache spark": ["apache spark", "spark"], "pyspark": ["pyspark"], "hadoop": ["hadoop"], "hive": ["hive", "apache hive"], "flink": ["flink", "apache flink"],
    "kafka": ["kafka", "apache kafka"], "rabbitmq": ["rabbitmq"], "kinesis": ["kinesis"],
    "airflow": ["airflow", "apache airflow"], "dagster": ["dagster"], "prefect": ["prefect"], "dbt": ["dbt", "data build tool"],
    "etl": ["etl", "etl pipelines", "data pipelines"], "data warehousing": ["data warehouse", "data warehousing", "dwh"],
    "aws": ["aws", "amazon web services"], "azure": ["azure", "microsoft azure"], "gcp": ["gcp", "google cloud", "google cloud platform"],
    "docker": ["docker"], "kubernetes": ["kubernetes", "k8s"], "terraform": ["terraform"], "git": ["git"],
    "ci/cd": ["ci/cd", "cicd", "continuous integration"], "jenkins": ["jenkins"], "github actions": ["github actions"],
    "machine learning": ["machine learning", "ml"], "deep learning": ["deep learning"], "nlp": ["nlp", "natural language processing"],
    "llm": ["llm", "llms", "large language models", "large language model"], "scikit-learn": ["scikit-learn", "sklearn", "scikit learn"],
    "tensorflow": ["tensorflow"], "pytorch": ["pytorch"], "keras": ["keras"], "pandas": ["pandas"], "numpy": ["numpy"],
    "statistics": ["statistics", "statistical analysis"], "a/b testing": ["a/b testing", "ab testing", "a/b tests"],
    "fastapi": ["fastapi"], "flask": ["flask"], "django": ["django"], "spring boot": ["spring boot", "springboot"],
    "rest api": ["rest api", "rest apis", "restful api", "restful apis", "restful"],
    "dax": ["dax"], "power query": ["power query"], "pyspark sql": ["spark sql"],
}
# a specific skill that proves a generic one: PostgreSQL experience satisfies "SQL"
IMPLIES: dict[str, list[str]] = {
    "postgresql": ["sql"], "mysql": ["sql"], "sql server": ["sql"], "sqlite": ["sql"], "mariadb": ["sql"],
    "pyspark": ["apache spark"], "pyspark sql": ["apache spark", "sql"], "node.js": ["javascript"], "react": ["javascript"], "vue": ["javascript"],
    "angular": ["javascript"], "typescript": ["javascript"], "spring boot": ["java"], "django": ["python"], "flask": ["python"],
    "fastapi": ["python"], "pandas": ["python"], "numpy": ["python"], "scikit-learn": ["python", "machine learning"],
    "tensorflow": ["machine learning", "deep learning"], "pytorch": ["machine learning", "deep learning"], "keras": ["machine learning", "deep learning"],
    "dbt": ["sql"], "dax": ["power bi"], "power query": ["power bi"],
}
# tools that do the same kind of job: close, not the same
FAMILIES: list[set[str]] = [
    {"power bi", "tableau", "looker", "qlik", "metabase", "superset", "quicksight"},
    {"aws", "azure", "gcp"},
    {"sql", "mysql", "postgresql", "sql server", "oracle", "sqlite", "mariadb"},
    {"apache spark", "pyspark", "hadoop", "hive", "flink"},
    {"react", "angular", "vue"}, {"django", "flask", "fastapi"}, {"tensorflow", "pytorch", "keras"},
    {"airflow", "dagster", "prefect"}, {"mongodb", "cassandra", "dynamodb", "redis"}, {"kafka", "rabbitmq", "kinesis"},
    {"snowflake", "bigquery", "redshift", "databricks"}, {"jenkins", "github actions", "ci/cd"},
]
LINE_HEADERS = ("skills", "technical skills", "key skills", "core skills", "tools", "technologies", "core competencies")


def _key(text: str) -> str:
    return re.sub(r"[\s._\-]+", "", str(text).lower().strip())


ALIAS_KEY: dict[str, str] = {}
for _canon, _names in SYNONYMS.items():
    for _n in [_canon] + _names:
        ALIAS_KEY.setdefault(_key(_n), _canon)
IMPLIERS: dict[str, set[str]] = {}
for _spec, _gens in IMPLIES.items():
    for _g in _gens:
        IMPLIERS.setdefault(_g, set()).add(_spec)


def canon(skill: str) -> str:
    """One name for one skill: 'PowerBI', 'power bi' and 'Microsoft Power BI' are all 'power bi'."""
    return ALIAS_KEY.get(_key(skill)) or " ".join(str(skill).lower().split())


def aliases_of(c: str) -> list[str]:
    return [c] + [a for a in SYNONYMS.get(c, []) if a != c]


def family_of(c: str) -> set[str]:
    out: set[str] = set()
    for fam in FAMILIES:
        if c in fam:
            out |= fam
    out.discard(c)
    return out


@lru_cache(maxsize=2048)
def _pattern(alias: str) -> re.Pattern | None:
    """Whole-word, case-insensitive pattern. 'power bi' also matches 'PowerBI' and 'power-bi'.
    Names shorter than 3 letters ('js', 'r', 'ml') are too ambiguous to search for in free text."""
    a = alias.strip().lower()
    if len(re.sub(r"[^a-z0-9]", "", a)) < 3 and a not in ("c#", "c++"):
        return None
    pieces = re.split(r"(?<=[a-z0-9])[\s._\-]+(?=[a-z0-9])", a)
    body = r"[\s._\-]?".join(re.escape(p) for p in pieces)
    tail = "" if a[-1] in "+#" else r"(?![+#])"
    return re.compile(r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])" + tail, re.I)


def find_line(lines: list[str], names: list[str]) -> str | None:
    """The line of the resume that shows one of these skills. A skills-list line is used only when nothing better exists."""
    pats = [p for p in (_pattern(n) for n in names) if p]
    fallback = None
    for line in lines:
        if any(p.search(line) for p in pats):
            clean = line.strip()[:220]
            if clean.lower().lstrip("•-* ").startswith(LINE_HEADERS):
                fallback = fallback or clean
            else:
                return clean
    return fallback


# ---------------------------------------------------------------- skills
def assess_skill(wanted: str, listed: dict[str, str], lines: list[str], verdict: dict | None = None) -> dict:
    """listed: canonical -> the candidate's own spelling. Returns the verdict for one wanted skill."""
    cw = canon(wanted)
    out = {"skill": wanted, "status": "missing", "credit": 0.0, "via": None, "evidence": None, "ai": False}

    def done(status, credit, via=None, evidence=None, ai=False):
        out.update(status=status, credit=credit, via=via, evidence=evidence, ai=ai)
        return out

    if cw in listed:
        return done("listed", 1.0, listed[cw], find_line(lines, aliases_of(cw)))
    for spec in IMPLIERS.get(cw, ()):
        if spec in listed:
            return done("implied", 1.0, listed[spec], find_line(lines, aliases_of(spec)))
    line = find_line(lines, aliases_of(cw))
    if line:
        return done("text", 1.0, None, line)
    for spec in IMPLIERS.get(cw, ()):
        line = find_line(lines, aliases_of(spec))
        if line:
            return done("implied", 1.0, spec, line)
    fam = family_of(cw)
    for member in sorted(fam):
        if member in listed:
            return done("related", RELATED_CREDIT, listed[member], find_line(lines, aliases_of(member)))
    for member in sorted(fam):
        line = find_line(lines, aliases_of(member))
        if line:
            return done("related", RELATED_CREDIT, member, line)
    if verdict and verdict.get("verdict") == "related" and verdict.get("quote"):
        return done("ai_related", RELATED_CREDIT, None, verdict["quote"], ai=True)
    return out


def _skills_part(job: dict, cand: dict, verdicts: dict) -> tuple[dict, dict]:
    lines = [l for l in str(cand.get("text") or "").splitlines() if l.strip()]
    listed: dict[str, str] = {}
    for s in cand.get("skills") or []:
        listed.setdefault(canon(s), str(s))
    req = [assess_skill(s, listed, lines, verdicts.get(canon(s))) for s in job.get("skills_required") or []]
    nice = [assess_skill(s, listed, lines, verdicts.get(canon(s))) for s in job.get("skills_nice") or []]
    total = len(req) + NICE_WEIGHT * len(nice)
    if not total:
        return {"score": None, "state": "not_assessed", "reason": "The job lists no skills."}, {"required": req, "nice": nice}
    got = sum(r["credit"] for r in req) + NICE_WEIGHT * sum(r["credit"] for r in nice)
    return {"score": round(100 * got / total, 1), "state": "assessed"}, {"required": req, "nice": nice}


# ---------------------------------------------------------------- qualification
# Degree LEVEL only. The institution is never read. Order matters: higher levels are found first and blanked out, so
# "post graduate" is not also read as "graduate".
LEVEL_NAME = {5: "a doctorate", 4: "a master's degree", 3: "a bachelor's degree", 2: "a diploma", 1: "a school certificate"}
LEVEL_SHORT = {5: "doctorate", 4: "master's", 3: "bachelor's", 2: "diploma", 1: "school certificate"}
_LEVEL_PATTERNS: list[tuple[int, re.Pattern]] = [
    (5, re.compile(r"\bph\.?\s?d\b|\bdoctorate\b|\bdoctoral\b", re.I)),
    (4, re.compile(r"\bm\.?\s?tech\b|\bmaster(?:'?s)?\b|\bm\.?\s?sc\b|\bm\.?\s?c\.?\s?a\b|\bmba\b|\bpgdm\b|\bpgdba\b|\bpgdca\b|\bpost[\s-]?graduat\w*(?:\s+(?:diploma|degree|certificate))?|\bm\.?\s?com\b|\bm\.?\s?phil\b|\bm\.?\s?stat\b|\bm\.?\s?arch\b|\bll\.?m\b", re.I)),
    # two-letter forms are matched in capitals only, and "MS Excel" is not "MS": they need dots or a following "in", "/", "," or ")"
    (4, re.compile(r"\bM\.[SAE]\b|\b(?:MS|MA|ME)\b(?=\s*(?:in\b|degree|[(/,\-]|$))")),
    (3, re.compile(r"\bb\.?\s?tech\b|\bbachelor(?:'?s)?\b|\bb\.?\s?sc\b|\bb\.?\s?c\.?\s?a\b|\bbba\b|\bb\.?\s?com\b|\bb\.?\s?arch\b|\bb\.?\s?pharm\b|\bundergraduate\b|\bllb\b", re.I)),
    (3, re.compile(r"\bB\.[SAE]\b|\b(?:BS|BA|BE)\b(?=\s*(?:in\b|degree|[(/,\-]|$))")),
    (2, re.compile(r"\bdiploma\b|\bpolytechnic\b", re.I)),
    (1, re.compile(r"\b12th\b|\b10th\b|\bhsc\b|\bssc\b|\bhigher secondary\b|\bhigh school\b|\bintermediate\b", re.I)),
]


# "degree" or "graduate" on their own only say "a bachelor's or better"; they count only when nothing more specific is named,
# so "Master's degree" is a master's and not also a bachelor's.
_WEAK_BACHELOR = re.compile(r"\bdegree\b|\bgraduat(?:e|es|ion)\b", re.I)


def degree_levels(text: str | None) -> set[int]:
    """The degree levels named in a piece of text: {3} for 'B.Tech in CS', {3, 4} for 'Bachelor's or Master's'."""
    t, found = str(text or ""), set()
    for level, pat in _LEVEL_PATTERNS:
        hits = list(pat.finditer(t))
        if hits:
            found.add(level)
            for h in reversed(hits):
                t = t[:h.start()] + " " * (h.end() - h.start()) + t[h.end():]
    if not found and _WEAK_BACHELOR.search(t):
        found.add(3)
    return found


def _qualification_part(job: dict, cand: dict) -> dict:
    asked = (job.get("qualification") or "").strip()
    if not asked:
        return {"score": None, "state": "not_assessed", "reason": "The job lists no qualification."}
    wanted = degree_levels(asked)
    if not wanted:
        return {"score": None, "state": "not_assessed", "reason": f"The job's qualification (“{asked[:80]}”) does not name a degree level."}
    need = min(wanted)          # "Bachelor's or Master's" asks for a bachelor's
    texts = [cand.get("qualification")] + list(cand.get("education") or [])
    held = [lv for t in texts for lv in degree_levels(t)]
    shown = (cand.get("qualification") or "").strip() or next((str(t) for t in texts[1:] if t and degree_levels(t)), "")
    base = {"required_level": LEVEL_SHORT[need], "job": asked}
    if not held:
        return {**base, "score": None, "state": "unknown", "reason": "No degree was found in the resume, so qualification is left out of this score."}
    have = max(held)
    base.update(candidate=shown, level=LEVEL_SHORT[have])
    if have >= need:
        return {**base, "score": 100.0, "state": "meets", "reason": f"{shown or 'Highest degree'} is {LEVEL_NAME[have]}; the job asks for {LEVEL_NAME[need]}."}
    if need - have == 1:
        return {**base, "score": ONE_LEVEL_BELOW, "state": "below", "reason": f"{shown or 'Highest degree'} is {LEVEL_NAME[have]}; the job asks for {LEVEL_NAME[need]} (half credit)."}
    return {**base, "score": 0.0, "state": "below", "reason": f"{shown or 'Highest degree'} is {LEVEL_NAME[have]}; the job asks for {LEVEL_NAME[need]}."}


# ---------------------------------------------------------------- keywords (job description against resume)
# Words that appear in nearly every job post and say nothing about the work.
_STOP = set("""
a about above across after again all also am an and any are as at be because been before being below between both but by can could did do does doing
down during each either else etc even every few for from further had has have having he her here hers him his how i if in into is it its just may me
more most much must my no nor not now of off on once only or other our out over own per same she should so some such than that the their them then
there these they this those through to too under until up upon us very via was we were what when where which while who whom why will with within
without would yet you your yours able ability about across additional also applicant applicants apply based best better candidate candidates
company companies compensation culture day daily demonstrated depth desired desirable detail details develop duties duty effective employer
employment equal environment essential excellent exposure familiar familiarity fast field focus following full good great grow growth hands
help hiring ideal impact include includes including industry join joining knowledge large learn level like location looking make making
manage many meet member members multiple need needs new offer offers office onsite hybrid remote opportunity opportunities part people
perform performing plus position positive preferred prior proven provide providing pursue qualification qualifications qualified range
related relevant require required requirement requirements responsibilities responsibility responsible role roles salary seeking senior
junior set several skill skills solid something strong successful support supporting take team teams their things time together tools
understand understanding use used using value variety various want ways well while willing work working works world year years
""".split())
_WORD = re.compile(r"[a-z][a-z0-9+#]*(?:[.\-][a-z0-9+#]+)*")


def _stem(word: str) -> str:
    w = word
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            if suf == "s" and w.endswith(("ss", "is", "us")):
                continue
            w = w[:-len(suf)]
            break
    if w.endswith("e") and len(w) > 4:
        w = w[:-1]
    return w


def _terms(text: str) -> list[tuple[str, str]]:
    """(stem, the word as written) for every meaningful word, in order."""
    out = []
    for m in _WORD.finditer(str(text or "").lower()):
        w = m.group(0).strip(".-")
        if len(w) < 3 or w in _STOP or w.isdigit():
            continue
        out.append((_stem(w), w))
    return out


def _skill_stems(job: dict) -> set[str]:
    """Stems of the skill names themselves: skills already have their own part, so they are not counted twice here."""
    stems: set[str] = set()
    for s in list(job.get("skills_required") or []) + list(job.get("skills_nice") or []):
        for alias in aliases_of(canon(s)) + [str(s)]:
            for stem, _ in _terms(alias):
                stems.add(stem)
    return stems


def _keywords_part(job: dict, cand: dict) -> dict:
    jd = str(job.get("text") or "")
    if len(jd.split()) < MIN_JD_WORDS:
        return {"score": None, "state": "not_assessed", "reason": "The job description is too short to compare keywords."}
    skip = _skill_stems(job)
    freq: dict[str, int] = {}
    first: dict[str, tuple[int, str]] = {}
    for i, (stem, word) in enumerate(_terms(jd)):
        if stem in skip:
            continue
        freq[stem] = freq.get(stem, 0) + 1
        first.setdefault(stem, (i, word))
    ranked = sorted(freq, key=lambda s: (-freq[s], first[s][0]))[:KEYWORD_LIMIT]
    if len(ranked) < MIN_KEYWORDS:
        return {"score": None, "state": "not_assessed", "reason": "The job description has too few distinctive terms to compare."}
    text = str(cand.get("text") or "")
    if len(text.split()) < MIN_RESUME_WORDS:
        return {"score": None, "state": "unknown", "reason": "The resume has too little text to compare keywords, so they are left out of this score."}
    have = {stem for stem, _ in _terms(text)}
    hit = [s for s in ranked if s in have]
    miss = [s for s in ranked if s not in have]
    return {
        "score": round(100 * len(hit) / len(ranked), 1), "state": "assessed", "total": len(ranked), "found": len(hit),
        "matched": [first[s][1] for s in hit][:10], "missing": [first[s][1] for s in miss][:10],
        "reason": f"{len(hit)} of {len(ranked)} key terms from the job description also appear in the resume.",
    }


# ---------------------------------------------------------------- experience
def _yrs(n: float) -> str:
    return f"{n:g} {'year' if n == 1 else 'years'}"


def _experience_part(job: dict, cand: dict) -> dict:
    lo, hi, y = job.get("experience_min"), job.get("experience_max"), cand.get("years")
    if lo is None and hi is None:
        return {"score": None, "state": "not_assessed", "reason": "The job has no experience range."}
    rng = f"{lo} to {hi} years" if lo is not None and hi is not None and lo != hi else (f"{lo}+ years" if hi is None else (f"up to {hi} years" if lo is None else _yrs(lo)))
    if y is None:
        return {"score": None, "state": "unknown", "range": rng, "reason": "No usable job dates were found in the resume, so experience is left out of this score."}
    base = {"years": y, "range": rng}
    if lo is not None and y < lo:
        return {**base, "score": round(100 * max(0.0, y / lo), 1), "state": "below", "reason": f"{_yrs(y)} against a minimum of {_yrs(lo)}."}
    if hi is not None and y > hi:
        return {**base, "score": round(100 * max(ABOVE_RANGE_FLOOR, 1 - 0.05 * (y - hi)), 1), "state": "above", "reason": f"{_yrs(y)} is above the {rng} range (a small deduction, never a rejection)."}
    return {**base, "score": 100.0, "state": "within", "reason": f"{_yrs(y)} is within {rng}."}


# ---------------------------------------------------------------- location
CITY_ALIASES = {"bangalore": "bengaluru", "bombay": "mumbai", "gurgaon": "gurugram", "madras": "chennai", "calcutta": "kolkata",
                "poona": "pune", "trivandrum": "thiruvananthapuram", "cochin": "kochi", "baroda": "vadodara", "hyd": "hyderabad"}
METROS = [{"mumbai", "navi mumbai", "thane"}, {"delhi", "new delhi", "noida", "gurugram", "ghaziabad", "faridabad", "greater noida"}]


def _city(name: str) -> str:
    n = " ".join(re.sub(r"[^a-z ]", " ", name.lower()).split())
    return CITY_ALIASES.get(n, n)


def _same_place(job_loc: str, cand_loc: str) -> str | None:
    """The shared city (or metro area) if there is one."""
    job_city = _city(re.split(r"[,/|(]", job_loc)[0])
    if not job_city:
        return None
    names = {job_city} | {m for metro in METROS if job_city in metro for m in metro}
    names |= {a for a, c in CITY_ALIASES.items() if c in names}
    text = " " + " ".join(_city(p) for p in re.split(r"[,/|()]", cand_loc)) + " " + _city(cand_loc) + " "
    for n in sorted(names):
        if n and f" {n} " in text:
            return n.title()
    return None


def _location_part(job: dict, cand: dict) -> dict:
    jl, cl, mode = (job.get("location") or "").strip(), (cand.get("location") or "").strip(), job.get("work_mode")
    if mode == "remote":
        return {"score": None, "state": "not_assessed", "reason": "This is a remote job, so location is not scored."}
    if not jl:
        return {"score": None, "state": "not_assessed", "reason": "The job has no location."}
    if not cl:
        return {"score": None, "state": "unknown", "reason": "No location in the resume, so location is left out of this score."}
    same = _same_place(jl, cl)
    if same:
        return {"score": 100.0, "state": "match", "candidate": cl, "job": jl, "reason": f"Based in {cl}; the job is in {jl}."}
    return {"score": 0.0, "state": "different", "candidate": cl, "job": jl, "reason": f"Based in {cl}; the job is in {jl}. Willingness to relocate is not assessed."}


# ---------------------------------------------------------------- weights and totals
class WeightError(ValueError):
    """The weights were not usable. The message is safe to show."""


def normalize_weights(raw: Any) -> dict[str, int]:
    names = ", ".join(PARTS[:-1]) + " and " + PARTS[-1]
    if raw is None:
        return dict(DEFAULT_WEIGHTS)
    if not isinstance(raw, dict):
        raise WeightError(f"Weights must be an object with {names}.")
    unknown = [k for k in raw if k not in PARTS]
    if unknown:
        raise WeightError(f"Unknown weight: {unknown[0]}. Use {names}.")
    out = {}
    for key in PARTS:
        v = raw.get(key, DEFAULT_WEIGHTS[key])
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not 0 <= v <= 100:
            raise WeightError(f"The {key} weight must be a number from 0 to 100.")
        out[key] = int(round(v))
    if sum(out.values()) <= 0:
        raise WeightError("At least one weight must be above zero.")
    return out


def _summary(parts: dict, skills: dict, assessed_weight: int) -> str:
    bits = []
    req = skills["required"]
    if req:
        met = sum(1 for r in req if r["credit"] >= 1)
        related = sum(1 for r in req if 0 < r["credit"] < 1)
        gap = [r["skill"] for r in req if r["credit"] == 0]
        s = f"{met} of {len(req)} required skills found"
        if related:
            s += f", {related} related"
        if gap:
            s += f". Missing: {', '.join(gap[:4])}" + ("…" if len(gap) > 4 else "")
        bits.append(s)
    for key in ("qualification", "experience", "location", "keywords"):
        p = parts[key]
        if p.get("weight") == 0:      # a part switched off is not talked about
            continue
        bits.append(p["reason"] if p.get("reason") else "")
    text = ". ".join(b.rstrip(".") for b in bits if b) + "."
    if assessed_weight < 100:
        text += f" This score is based on {assessed_weight}% of the criteria; the rest could not be assessed."
    return text


def score_candidate(job: dict, cand: dict, weights: dict[str, int] | None = None, verdicts: dict | None = None) -> dict:
    """job: skills_required, skills_nice, qualification, experience_min, experience_max, location, work_mode, text (title + description).
       cand: skills, years, location, qualification, education (a list of degree names), text.   Nothing else is read, by design."""
    w = normalize_weights(weights)
    skills_part, skill_detail = _skills_part(job, cand, verdicts or {})
    parts = {"skills": skills_part, "qualification": _qualification_part(job, cand), "experience": _experience_part(job, cand),
             "location": _location_part(job, cand), "keywords": _keywords_part(job, cand)}
    num = den = 0.0
    for key in PARTS:
        p = parts[key]
        p["weight"] = w[key]
        p["assessed"] = p["score"] is not None and w[key] > 0
        if p["assessed"]:
            num += w[key] * p["score"]
            den += w[key]
    total_w = sum(w.values())
    assessed_weight = round(100 * den / total_w)
    score = round(num / den, 1) if den else 0.0
    not_assessed = [{"part": k, "reason": parts[k].get("reason") or "Weight is zero."} for k in PARTS if not parts[k]["assessed"]]
    return {
        "score": score, "assessed_weight": assessed_weight,
        "breakdown": {"version": VERSION, "weights": w, "assessed_weight": assessed_weight,
                      "parts": {k: {"score": parts[k]["score"], "weight": w[k], "assessed": parts[k]["assessed"], "state": parts[k]["state"]} for k in PARTS}},
        "explanation": {"summary": _summary(parts, skill_detail, assessed_weight), "skills": skill_detail,
                        "qualification": parts["qualification"], "experience": parts["experience"], "location": parts["location"],
                        "keywords": parts["keywords"], "not_assessed": not_assessed},
    }


def rank_key(result: dict) -> tuple:
    """Highest score first; ties go to whoever covers more required skills. Never by name."""
    req = result["explanation"]["skills"]["required"]
    return (-result["score"], -sum(r["credit"] for r in req))


# ---------------------------------------------------------------- AI judge helpers (the call itself lives in the router)
def text_hash(text: str | None) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


def gaps(result: dict, limit: int = 8) -> list[str]:
    """Skills still missing after the rules, required ones first: what the AI judge is asked about."""
    sk = result["explanation"]["skills"]
    return [r["skill"] for r in sk["required"] + sk["nice"] if r["credit"] == 0][:limit]


def redact(text: str, name: str | None = None, email: str | None = None, phone: str | None = None, links: tuple = ()) -> str:
    """The resume text with identity removed before it goes to an AI model: name, email, phone, links."""
    t = str(text or "")
    t = re.sub(r"[\w.+\-]+@[\w\-]+(\.[\w\-]+)+", "[email]", t)
    t = re.sub(r"https?://\S+|(?:www\.)?(?:linkedin|github)\.com/\S*", "[link]", t, flags=re.I)
    t = re.sub(r"(?<!\w)\+?\d[\d\s().\-]{7,}\d(?!\w)", "[number]", t)
    for ident in (name, phone, email, *links):
        if ident and len(str(ident)) >= 3:
            t = re.sub(re.escape(str(ident)), "[candidate]", t, flags=re.I)
    for part in str(name or "").split():
        if len(part) >= 3:
            t = re.sub(r"(?<![A-Za-z])" + re.escape(part) + r"(?![A-Za-z])", "[candidate]", t, flags=re.I)
    return t


def verify_quote(quote: str | None, text: str) -> bool:
    """A quote counts only if it really appears in the text (ignoring case and spacing)."""
    norm = lambda s: " ".join(str(s).lower().split())
    q = norm(quote or "")
    return 4 <= len(q) <= 300 and q in norm(text)
