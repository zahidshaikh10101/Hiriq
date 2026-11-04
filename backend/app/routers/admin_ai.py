"""Admin AI usage (mounted at /api/admin). Every route needs a signed-in admin.

    GET /ai-usage?range=7d|30d|90d&tz=<minutes ahead of UTC>

Reads the `ai_calls` log that app/services/llm.py writes: one row per model ATTEMPT (a retry, or the backup model after a
failure, is its own row), with purpose, model, success, short error, speed and token counts. No prompt, answer or resume
text is ever stored, so none can be shown here. Numbers come from the database; with no calls every list is empty.
"""
from __future__ import annotations

import os
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.db.models import User
from app.db.recruiter_models import AiCall
from app.db.session import get_db
from app.services.timeutil import aware, now

router = APIRouter(tags=["admin"])

RANGES = {"7d": (7, 1), "30d": (30, 1), "90d": (13, 7)}      # (bars, days per bar), same as the users overview
PURPOSE_LABEL = {"jd": "JD writer", "parse": "Resume reader", "match": "Matching AI check", "ask": "Ask the pool", "other": "Other"}
TOP = 8


def _db(db: Session | None) -> Session:
    if db is None:
        raise HTTPException(503, detail={"code": "no_database", "message": "The database is not configured."})
    return db


def _iso(dt) -> str | None:
    dt = aware(dt)
    return dt.isoformat() if dt else None


def _rate(ok: int, total: int) -> int | None:
    return round(100 * ok / total) if total else None


def _avg(values: list[int]) -> int | None:
    return round(sum(values) / len(values)) if values else None


def _stats(rows: list) -> dict:
    ok = sum(1 for r in rows if r.ok)
    lat = [r.latency_ms for r in rows if r.latency_ms is not None]
    return {"calls": len(rows), "ok": ok, "failed": len(rows) - ok, "success_rate": _rate(ok, len(rows)), "avg_latency_ms": _avg(lat),
            "prompt_tokens": sum(r.prompt_tokens or 0 for r in rows), "completion_tokens": sum(r.completion_tokens or 0 for r in rows)}


def _series(rows: list, buckets: int, step: int, tz_minutes: int) -> tuple[list[int], list[int], list[str]]:
    """Attempts and failures per bucket, bucketed on the viewer's own calendar days."""
    offset = timedelta(minutes=tz_minutes)
    today = (now() + offset).date()
    first = today - timedelta(days=buckets * step - 1)
    total, failed = [0] * buckets, [0] * buckets
    for r in rows:
        idx = ((aware(r.created_at) + offset).date() - first).days // step
        if 0 <= idx < buckets:
            total[idx] += 1
            if not r.ok:
                failed[idx] += 1
    labels = [f"{(first + timedelta(days=i * step)).day} {(first + timedelta(days=i * step)):%b}" for i in range(buckets)]
    return total, failed, labels


def _reason(error: str | None) -> str:
    """'http 429: rate limited' and 'http 429: busy' are one kind of failure."""
    return (error or "unknown").split(":")[0].strip()[:60] or "unknown"


@router.get("/ai-usage")
def ai_usage(range: Literal["7d", "30d", "90d"] = "7d", tz: int = Query(0, ge=-840, le=840),
             actor: User = Depends(require_admin), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    buckets, step = RANGES[range]
    days = buckets * step
    t = now()
    start, prev_start = t - timedelta(days=days), t - timedelta(days=2 * days)
    cols = (AiCall.owner_id, AiCall.purpose, AiCall.model, AiCall.ok, AiCall.error, AiCall.latency_ms, AiCall.prompt_tokens,
            AiCall.completion_tokens, AiCall.created_at)
    every = db.execute(select(*cols).where(AiCall.created_at >= prev_start).order_by(AiCall.created_at.desc())).all()
    rows = [r for r in every if aware(r.created_at) >= start]
    previous = len(every) - len(rows)

    by_purpose = defaultdict(list)
    by_model = defaultdict(list)
    for r in rows:
        by_purpose[r.purpose].append(r)
        by_model[r.model].append(r)
    purposes = sorted(({"purpose": p, "label": PURPOSE_LABEL.get(p, p.title()), **_stats(rs)} for p, rs in by_purpose.items()), key=lambda x: -x["calls"])
    models = sorted(({"model": m, **_stats(rs)} for m, rs in by_model.items()), key=lambda x: (-x["calls"], x["model"]))

    reasons = Counter(_reason(r.error) for r in rows if not r.ok)
    errors = [{"reason": k, "count": v} for k, v in reasons.most_common(TOP)]

    owners = Counter(r.owner_id for r in rows if r.owner_id is not None)
    names = {u.id: u for u in db.scalars(select(User).where(User.id.in_(list(owners)))).all()} if owners else {}
    top_users = [{"name": (names[o].username or names[o].full_name) if o in names else "Deleted account", "calls": n} for o, n in owners.most_common(5)]

    values, failed, labels = _series(rows, buckets, step, tz)
    sub = {"7d": "Attempts per day, last 7 days", "30d": "Attempts per day, last 30 days", "90d": "Attempts per week, last 90 days"}[range]
    recent_failures = [{"at": _iso(r.created_at), "purpose": PURPOSE_LABEL.get(r.purpose, r.purpose), "model": r.model, "error": (r.error or "unknown")[:160]}
                       for r in rows if not r.ok][:TOP]
    key_set = bool(os.getenv("OPENROUTER_API_KEY", "").strip())
    return {
        "range": range, "key_set": key_set,
        "totals": {**_stats(rows), "previous_calls": previous, "users": len(owners)},
        "by_purpose": purposes, "by_model": models, "errors": errors, "top_users": top_users, "recent_failures": recent_failures,
        "daily": {"values": values, "failed": failed, "labels": labels, "sub": sub},
    }
