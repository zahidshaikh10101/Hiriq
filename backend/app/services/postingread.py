"""Reads an outside job post into the same shape a recruiter's job has, with rules only (no AI, no cost, instant).

It finds the skills the engine already knows (matching.SYNONYMS) written in the post, the years of experience asked for, and the
degree asked for. A skill under a "preferred / nice to have / plus" line counts as nice to have, every other skill as required.
This is an estimate from the post's wording: it can miss a skill the post spells in a way the table does not know, and it cannot
tell a skill the job needs from one the company merely mentions. The screen says so. The pasted-job reader (jobread.py,
AI) is the careful version; this one exists so twenty posts can be ranked at once.
"""
from __future__ import annotations

import re

from app.services import matching

MAX_REQUIRED, MAX_NICE = 15, 10
_NICE_WORDS = re.compile(r"\b(preferred|desirable|desired|nice[\s-]to[\s-]have|good[\s-]to[\s-]have|bonus|added advantage|an advantage|a plus|is a plus|optional)\b", re.I)
_REQ_HEAD = re.compile(r"\b(required|requirements?|essential|must[\s-]have|qualifications?|what we look for|what you bring|responsibilities|key skills|skills required|you will need)\b", re.I)
_YEARS = r"(?:years?|yrs?)"
_RANGE = re.compile(rf"(\d{{1,2}})\s*\+?\s*(?:-|–|—|to)\s*(\d{{1,2}})\s*\+?\s*{_YEARS}", re.I)
_MIN = re.compile(rf"(?:(?:minimum|at least|min\.?)\s*(?:of\s*)?(\d{{1,2}})\s*\+?\s*{_YEARS})|(?:(\d{{1,2}})\s*\+\s*{_YEARS})|(?:(\d{{1,2}})\s*{_YEARS}\s*(?:of\s*)?(?:relevant\s*|working\s*|total\s*|hands-on\s*|professional\s*)*experience)", re.I)

_VOCAB: list[tuple[str, re.Pattern]] | None = None


def _vocab() -> list[tuple[str, re.Pattern]]:
    global _VOCAB
    if _VOCAB is None:
        out = []
        for canon, names in matching.SYNONYMS.items():
            pats = [p for p in (matching._pattern(n) for n in [canon] + list(names)) if p is not None]
            if pats:
                out.append((canon, re.compile("|".join(p.pattern for p in pats), re.I)))
        _VOCAB = out
    return _VOCAB


def _near_experience(text: str, a: int, b: int) -> bool:
    return "experience" in text[max(0, a - 45): b + 45].lower()


def _years(text: str) -> tuple[int | None, int | None]:
    for m in _RANGE.finditer(text):
        lo, hi = int(m.group(1)), int(m.group(2))
        if 0 <= lo <= hi <= 40 and _near_experience(text, m.start(), m.end()):
            return lo, hi
    for m in _MIN.finditer(text):
        n = next((int(g) for g in m.groups() if g), None)
        if n is not None and 0 < n <= 40 and _near_experience(text, m.start(), m.end()):
            return n, None
    return None, None


def read(title: str | None, description: str | None) -> dict:
    """-> {skills_required, skills_nice, experience_min, experience_max, qualification}. Never raises."""
    text = str(description or "")[:12000]
    mode = "req"
    required: list[str] = []
    nice: list[str] = []
    qualification = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        short = len(line) <= 70
        if short and _NICE_WORDS.search(line):
            mode = "nice"
        elif short and _REQ_HEAD.search(line):
            mode = "req"
        as_nice = mode == "nice" or bool(_NICE_WORDS.search(line))
        hits = sorted((m.start(), canon) for canon, pat in _vocab() for m in [pat.search(line)] if m)     # in the order they are written
        for _, canon in hits:
            bucket = nice if as_nice else required
            if canon not in bucket:
                bucket.append(canon)
        if qualification is None and matching.degree_levels(line):
            qualification = line[:200]
    nice = [s for s in nice if s not in required]
    lo, hi = _years(text)
    return {"skills_required": required[:MAX_REQUIRED], "skills_nice": nice[:MAX_NICE], "experience_min": lo, "experience_max": hi,
            "qualification": qualification}


def view(title: str | None, description: str | None, location: str | None, found: dict) -> dict:
    """What matching.score_candidate wants: the read, plus the text its keyword check compares."""
    return {**found, "location": location, "work_mode": None, "text": "\n".join(x for x in (title, description) if x)}
