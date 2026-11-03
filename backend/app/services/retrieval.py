"""Keyword retrieval over resumes: the "find the right passages" half of ask-the-pool.

Pure functions, no database and no network. Given a question and the pool's text, it returns the candidates whose
resumes best answer it, each with the passages that did. The language model only ever sees those passages.

How it works (BM25, the classic keyword ranking, written out so there is no extra dependency):
  * every resume is cut into short passages (a few lines each); the candidate's profile (title, skills, ...) is one more passage
  * the question is turned into "term groups". A skill the engine knows is one group with all its spellings, so
    "PowerBI" finds "Power BI", and a two-word name needs both words together. Any other word is a group of its own.
  * a passage scores the sum of its groups' BM25 weights; a candidate scores their best passages, scaled by how many
    of the question's groups appear anywhere in their resume (so "Python and Tableau" prefers someone with both)
Names are never searched or scored. Nothing here reads gender, age, college or any other identity field.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from app.services import matching

K1, B = 1.5, 0.75
CHUNK_TARGET = 350          # characters a passage grows to before a new one starts
CHUNK_MAX = 650             # a passage never runs longer than this
MAX_PASSAGES = 60           # per candidate
SECOND_PASSAGE_WEIGHT = 0.25
MAX_GROUPS = 12

# Question words that say nothing about the person, plus filler that is on every resume.
STOP = set("""
a about all also am an and any anyone are as at be been but by can could did do does for from get give had has have how i if in into is it its
just list me more most my of on one or our out please show some someone somebody than that the their them then there these they this those to
want was we were what when where which who whom whose why will with would you your find tell who's
candidate candidates resume resumes cv people person profile profiles pool
experience experienced years year work worked working knows know knowledge skills skill good strong
""".split())
_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#]*(?:[.\-][a-z0-9+#]+)*")


def tokens(text: str | None) -> list[str]:
    out = []
    for m in _TOKEN.finditer(str(text or "").lower()):
        w = m.group(0).strip(".-")
        if len(w) < 2 or w in STOP:
            continue
        out.append(matching._stem(w))
    return out


# ---------------------------------------------------------------- cutting resumes up
def passages(text: str | None) -> list[str]:
    """Short passages of a resume, a few lines each, with one line of overlap so a sentence is not cut off from its context."""
    lines = [" ".join(l.split()) for l in str(text or "").splitlines()]
    lines = [l for l in lines if l]
    out, cur = [], []
    for line in lines:
        cur.append(line)
        if sum(len(x) + 1 for x in cur) >= CHUNK_TARGET:
            out.append(" ".join(cur)[:CHUNK_MAX])
            cur = cur[-1:] if len(cur[-1]) < CHUNK_TARGET // 2 else []
    if cur and (not out or " ".join(cur)[:CHUNK_MAX] != out[-1]):
        out.append(" ".join(cur)[:CHUNK_MAX])
    return out[:MAX_PASSAGES]


def profile_passage(title=None, company=None, location=None, qualification=None, years=None, skills=None) -> str:
    """The structured profile as one passage. The name is deliberately not part of it."""
    bits = []
    if title or company:
        bits.append(" at ".join(x for x in (title, company) if x) + ".")
    if years is not None:
        bits.append(f"{years:g} years of experience.")
    if location:
        bits.append(f"Based in {location}.")
    if qualification:
        bits.append(f"{qualification}.")
    if skills:
        bits.append("Skills: " + ", ".join(str(s) for s in skills) + ".")
    return " ".join(bits)


# ---------------------------------------------------------------- the question
def term_groups(question: str) -> list[list[frozenset[str]]]:
    """Each group is a list of alternatives; an alternative is a set of stems that must all appear together."""
    q = str(question or "")
    groups: list[list[frozenset[str]]] = []
    used: set[str] = set()
    for canon_name, names in matching.SYNONYMS.items():
        spellings = [canon_name] + [n for n in names if n != canon_name]
        hit = [a for a in spellings if (p := matching._pattern(a)) is not None and p.search(q)]
        if not hit:
            continue
        alts = []
        for a in spellings:
            toks = frozenset(tokens(a))
            if toks and toks not in alts:
                alts.append(toks)
        groups.append(alts)
        for a in hit:
            used.update(tokens(a))
    seen = set()
    for t in tokens(q):
        if t in used or t in seen:
            continue
        seen.add(t)
        groups.append([frozenset([t])])
    return groups[:MAX_GROUPS]


# ---------------------------------------------------------------- ranking
@dataclass
class Doc:
    id: str
    passages: list[str]


@dataclass
class Hit:
    id: str
    score: float
    coverage: float
    passages: list[str] = field(default_factory=list)


def search(question: str, docs: list[Doc], k: int = 8, per_doc: int = 2) -> list[Hit]:
    groups = term_groups(question)
    if not groups or not docs:
        return []
    stems = {s for g in groups for alt in g for s in alt}
    # passages as token counters, once
    table: list[tuple[str, str, Counter, int]] = []
    for d in docs:
        for text in d.passages:
            toks = tokens(text)
            if toks:
                table.append((d.id, text, Counter(toks), len(toks)))
    if not table:
        return []
    n = len(table)
    avg = sum(t[3] for t in table) / n
    df = {s: sum(1 for t in table if s in t[2]) for s in stems}

    def term(s: str, tf: Counter, dl: int) -> float:
        f = tf.get(s, 0)
        if not f:
            return 0.0
        idf = math.log(1 + (n - df[s] + 0.5) / (df[s] + 0.5))
        return idf * f * (K1 + 1) / (f + K1 * (1 - B + B * dl / avg))

    per: dict[str, list[tuple[float, str]]] = {}
    matched: dict[str, set[int]] = {}
    for did, text, tf, dl in table:
        total = 0.0
        for gi, alts in enumerate(groups):
            best = 0.0
            for alt in alts:
                if all(s in tf for s in alt):
                    best = max(best, sum(term(s, tf, dl) for s in alt))
            if best:
                total += best
                matched.setdefault(did, set()).add(gi)
        if total:
            per.setdefault(did, []).append((total, text))
    hits = []
    for did, scored in per.items():
        scored.sort(key=lambda x: -x[0])
        coverage = len(matched[did]) / len(groups)
        base = scored[0][0] + (SECOND_PASSAGE_WEIGHT * scored[1][0] if len(scored) > 1 else 0.0)
        hits.append(Hit(did, round(base * (0.4 + 0.6 * coverage), 4), round(coverage, 3), [t for _, t in scored[:per_doc]]))
    hits.sort(key=lambda h: (-h.score, h.id))
    return hits[:k]
