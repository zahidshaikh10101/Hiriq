"""Job-description writer.

The recruiter's form is the source of truth. The model only writes the prose (summary, duties, requirements);
the facts a candidate relies on (location, experience, qualification, salary) are put into the text by code, so the
AI can never change a number or invent a perk.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.services import llm

CURRENCY_SYMBOL = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}
WORK_MODE_LABEL = {"onsite": "On-site", "hybrid": "Hybrid", "remote": "Remote"}

SYSTEM = """You write clear, honest job descriptions for hiring teams.

Rules:
- Use ONLY the details you are given. Never invent the company, its size, products, perks, benefits, culture, salary, location or any number.
- Plain, specific language. One sentence per bullet, at most 25 words. No buzzwords such as rockstar, ninja, guru, dynamic, passionate.
- Be inclusive: no gendered wording, no age limits, no preference for particular colleges, no "native speaker" requirements.
- Requirements must follow from the skills, experience and qualification given. Do not add extra must-have tools.
- "suggested_skills" are up to 6 skills a strong candidate for this role often has that are NOT already listed. Short names only (for example "Tableau").

Reply with ONLY a JSON object with exactly these keys:
{"summary": "2-3 sentences about the role",
 "responsibilities": ["5 to 9 bullets, drawn from the day-to-day notes"],
 "requirements": ["4 to 9 bullets for the must-have skills, experience and qualification"],
 "nice_to_have": ["0 to 5 bullets for the nice-to-have skills"],
 "suggested_skills": ["up to 6 short skill names"]}"""


class JDSections(BaseModel):
    summary: str = Field(min_length=20, max_length=1200)
    responsibilities: list[str] = Field(min_length=2, max_length=14)
    requirements: list[str] = Field(min_length=2, max_length=14)
    nice_to_have: list[str] = Field(default_factory=list, max_length=10)
    suggested_skills: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("responsibilities", "requirements", "nice_to_have", "suggested_skills", mode="before")
    @classmethod
    def _clean_list(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        out = []
        for item in value:
            text = re.sub(r"^\s*[-•*\d.)]+\s*", "", str(item)).strip()
            if text:
                out.append(text[:240])
        return out


# ---------- facts, written by code ----------
def format_money(amount: int, currency: str) -> str:
    sym = CURRENCY_SYMBOL.get(currency)
    if currency == "INR":
        if amount >= 10_000_000:
            return f"₹{amount / 10_000_000:g} crore"
        if amount >= 100_000:
            return f"₹{amount / 100_000:g} lakh"
        return f"₹{amount:,}"
    return f"{sym}{amount:,}" if sym else f"{currency} {amount:,}"


def salary_text(job: dict) -> str | None:
    lo, hi, cur = job.get("salary_min"), job.get("salary_max"), job.get("salary_currency") or "INR"
    if lo is None and hi is None:
        return None
    if lo is not None and hi is not None:
        body = format_money(lo, cur) if lo == hi else f"{format_money(lo, cur)} to {format_money(hi, cur)}"
    else:
        body = f"from {format_money(lo, cur)}" if lo is not None else f"up to {format_money(hi, cur)}"
    return f"{body} per year"


def experience_text(job: dict) -> str | None:
    lo, hi = job.get("experience_min"), job.get("experience_max")
    if lo is None and hi is None:
        return None
    if lo is not None and hi is not None:
        return f"{lo} years" if lo == hi else f"{lo} to {hi} years"
    return f"{lo}+ years" if lo is not None else f"up to {hi} years"


def location_text(job: dict) -> str | None:
    parts = [p for p in (job.get("location"), WORK_MODE_LABEL.get(job.get("work_mode") or "")) if p]
    return " · ".join(parts) if parts else None


def render(job: dict, s: JDSections) -> str:
    """Final JD text: facts block from the form, prose from the model. Plain text with '## ' headings and '- ' bullets."""
    facts = [
        ("Department", job.get("department")),
        ("Location", location_text(job)),
        ("Employment", (job.get("employment_type") or "").replace("-", " ").capitalize() or None),
        ("Experience", experience_text(job)),
        ("Qualification", job.get("qualification")),
        ("Salary", salary_text(job)),
    ]
    lines = [f"{label}: {value}" for label, value in facts if value]
    out = []
    if lines:
        out.append("\n".join(lines))
    out.append("## About the role\n" + s.summary.strip())
    out.append("## What you will do\n" + "\n".join(f"- {b}" for b in s.responsibilities))
    out.append("## What you bring\n" + "\n".join(f"- {b}" for b in s.requirements))
    if s.nice_to_have:
        out.append("## Nice to have\n" + "\n".join(f"- {b}" for b in s.nice_to_have))
    return "\n\n".join(out) + "\n"


# ---------- wording check (deterministic, no AI) ----------
RISKY = [
    (r"\b(rock ?star|ninja|guru|wizard)\b", "rockstar-style titles put some people off"),
    (r"\b(young|youthful|energetic team|digital native|recent graduate)\b", "can read as an age preference"),
    (r"\b(he|she|his|her|manpower|salesman|chairman)\b", "gendered wording"),
    (r"\bnative (english )?speaker\b", "excludes strong non-native speakers; say the level you need instead"),
    (r"\b(top[- ]tier|premier|elite|iit|nit|ivy league)\b.{0,20}\b(college|university|institute|graduate)", "college prestige is not a skill"),
]


def check_wording(text: str | None) -> list[str]:
    """Phrases in the JD that may put off good candidates or break fair-hiring norms. Advice only; nothing is blocked."""
    found = []
    for pattern, why in RISKY:
        m = re.search(pattern, text or "", flags=re.IGNORECASE)
        if m:
            found.append(f"“{m.group(0).strip()}”: {why}")
    return found


# ---------- generation ----------
def _brief(job: dict) -> str:
    def line(label: str, value: Any) -> str | None:
        return f"{label}: {value}" if value not in (None, "", []) else None

    parts = [
        line("Job title", job.get("title")), line("Department", job.get("department")),
        line("Experience", experience_text(job)), line("Qualification", job.get("qualification")),
        line("Employment type", job.get("employment_type")), line("Work mode", job.get("work_mode")),
        line("Must-have skills", ", ".join(job.get("skills_required") or [])),
        line("Nice-to-have skills", ", ".join(job.get("skills_nice") or [])),
        line("Day-to-day work (the recruiter's notes)", job.get("responsibilities")),
    ]
    return "\n".join(p for p in parts if p)


def generate(job: dict, owner_id: uuid.UUID | None = None) -> dict:
    """Returns {description, suggested_skills, model}. Raises llm.LLMError."""
    result = llm.complete_json(SYSTEM, _brief(job), JDSections, purpose="jd", owner_id=owner_id, temperature=0.4)
    sections: JDSections = result.data  # type: ignore[assignment]
    have = {s.strip().lower() for s in (job.get("skills_required") or []) + (job.get("skills_nice") or [])}
    seen: set[str] = set()
    suggested = []
    for s in sections.suggested_skills:
        key = s.strip().lower()
        if key and key not in have and key not in seen and len(s) <= 60:
            seen.add(key)
            suggested.append(s.strip())
    return {"description": render(job, sections), "suggested_skills": suggested[:6], "model": result.model}
