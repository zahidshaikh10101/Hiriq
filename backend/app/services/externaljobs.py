"""Jobs from outside Hiriq, through the JSearch API on RapidAPI (Google for Jobs and many boards behind one search).

Switched on only when RAPIDAPI_KEY is set in backend/.env. Optional: EXTERNAL_COUNTRY (two letters, default "in"),
EXTERNAL_DAILY_CAP (searches the whole server may make per day, default 100: the free plan is small).
Everything that comes back is untrusted text from the internet: titles and descriptions are shown escaped, never run,
and an apply link is kept only if it is a plain http(s) address. Results are cached for 15 minutes.
"""
from __future__ import annotations

import os
import time
from datetime import date
from typing import Any
from urllib.parse import urlparse

import httpx

HOST = "jsearch.p.rapidapi.com"
URL = f"https://{HOST}/search"
CACHE_SECONDS = 15 * 60
MAX_DESCRIPTION = 6000

_cache: dict[tuple, tuple[float, list[dict]]] = {}
_day = {"date": None, "count": 0}


class ExternalError(Exception):
    def __init__(self, code: str, message: str, status: int = 503):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def configured() -> bool:
    return bool(os.getenv("RAPIDAPI_KEY", "").strip())


def _cap() -> int:
    try:
        return int(os.getenv("EXTERNAL_DAILY_CAP", "100"))
    except ValueError:
        return 100


def _text(v: Any, limit: int) -> str:
    return " ".join(str(v or "").split())[:limit]


def _safe_url(v: Any) -> str | None:
    u = str(v or "").strip()
    p = urlparse(u)
    return u[:600] if p.scheme in ("http", "https") and p.netloc and len(u) <= 600 else None


def _get(params: dict) -> dict:
    """The one network call (tests replace it)."""
    headers = {"X-RapidAPI-Key": os.getenv("RAPIDAPI_KEY", "").strip(), "X-RapidAPI-Host": HOST}
    try:
        r = httpx.get(URL, params=params, headers=headers, timeout=15.0)
    except httpx.HTTPError:
        raise ExternalError("unavailable", "The outside job feed did not answer. Try again in a minute.")
    if r.status_code in (401, 403):
        raise ExternalError("feed_key", "The job feed key is not accepted. Check RAPIDAPI_KEY and your JSearch subscription.", 502)
    if r.status_code == 429:
        raise ExternalError("feed_busy", "The outside job feed is out of searches for now. Try again later.")
    if r.status_code >= 400:
        raise ExternalError("unavailable", "The outside job feed had a problem. Try again in a minute.", 502)
    try:
        return r.json()
    except ValueError:
        raise ExternalError("unavailable", "The outside job feed sent something unreadable.", 502)


def normalize(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    title, jid = _text(item.get("job_title"), 160), _text(item.get("job_id"), 200)
    if not title or not jid:
        return None
    place = ", ".join(x for x in (_text(item.get("job_city"), 60), _text(item.get("job_state"), 60), _text(item.get("job_country"), 20)) if x)
    return {
        "id": jid, "title": title, "company": _text(item.get("employer_name"), 160) or None, "location": place or None,
        "remote": bool(item.get("job_is_remote")), "employment_type": _text(item.get("job_employment_type"), 30) or None,
        "posted_at": _text(item.get("job_posted_at_datetime_utc"), 40) or None, "source": _text(item.get("job_publisher"), 80) or None,
        "apply_url": _safe_url(item.get("job_apply_link")), "description": str(item.get("job_description") or "")[:MAX_DESCRIPTION],
    }


def search(query: str, location: str = "", page: int = 1) -> list[dict]:
    """Raises ExternalError. Returns normalised jobs (never more than 10 per page)."""
    if not configured():
        raise ExternalError("not_configured", "The outside job feed is not set up on this server.", 503)
    q = f"{query} in {location}" if location else query
    country = (os.getenv("EXTERNAL_COUNTRY", "in").strip().lower() or "in")[:2]
    key = (q.lower(), country, page)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    today = date.today().isoformat()
    if _day["date"] != today:
        _day.update(date=today, count=0)
    if _day["count"] >= _cap():
        raise ExternalError("feed_busy", "The outside job feed has reached today's limit. Try again tomorrow.")
    _day["count"] += 1
    body = _get({"query": q, "page": str(page), "num_pages": "1", "country": country, "date_posted": "month"})
    if not isinstance(body, dict) or body.get("status") == "ERROR":
        raise ExternalError("unavailable", "The outside job feed had a problem. Try again in a minute.", 502)
    jobs = [j for j in (normalize(i) for i in (body.get("data") or [])[:10]) if j]
    _cache[key] = (time.time(), jobs)
    if len(_cache) > 200:                       # keep the cache small
        for k in sorted(_cache, key=lambda k: _cache[k][0])[:100]:
            _cache.pop(k, None)
    return jobs
