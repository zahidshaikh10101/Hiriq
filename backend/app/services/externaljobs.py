"""Jobs from outside Hiriq, through the "Jobs API" (jobs-api14) on RapidAPI: Indeed search.

Switched on only when RAPIDAPI_KEY is set in backend/.env (never in code or in git). Optional: EXTERNAL_COUNTRY (two letters,
default "in"), EXTERNAL_DAILY_CAP (searches the whole server may make per day, default 100: the free plan is small).
Everything that comes back is untrusted text from the internet: titles and descriptions are shown escaped, never run, and an
apply link is kept only if it is a plain http(s) address. Results are cached for 15 minutes.

The feed pages by token, not by number. We keep the token each page returns so that ?page=2 can follow page 1 of the same search.
It sends no job-type, salary or remote flag, so those are not guessed: only what the post itself says is passed on.
"""
from __future__ import annotations

import os
import re
import time
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.db import session as db_session

HOST = "jobs-api14.p.rapidapi.com"
URL = f"https://{HOST}/v2/indeed/search"
CACHE_SECONDS = 15 * 60
MAX_DESCRIPTION = 6000

_cache: dict[tuple, tuple[float, dict]] = {}
_tokens: dict[tuple, tuple[float, str]] = {}    # (search, page) -> token that fetches that page
_day = {"date": None, "count": 0}


class ExternalError(Exception):
    def __init__(self, code: str, message: str, status: int = 503):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def configured() -> bool:
    return bool(os.getenv("RAPIDAPI_KEY", "").strip())


def country() -> str:
    """The two-letter country searches use (EXTERNAL_COUNTRY, default in)."""
    return (os.getenv("EXTERNAL_COUNTRY", "in").strip().lower() or "in")[:2]


def _cap() -> int:
    try:
        return int(os.getenv("EXTERNAL_DAILY_CAP", "100"))
    except ValueError:
        return 100


def _record(ok: bool, started: float, error: str | None = None, results: int | None = None) -> None:
    """Log one request to the feed for the admin RapidAPI panel. Never lets a logging problem break a search."""
    if db_session.SessionLocal is None:
        return
    try:
        from app.db.recruiter_models import ExternalCall

        with db_session.SessionLocal() as db:
            db.add(ExternalCall(provider="indeed", ok=ok, error=(error or None) and error[:200],
                                latency_ms=int((time.monotonic() - started) * 1000), results=results))
            db.commit()
    except Exception:  # noqa: BLE001
        pass


def _text(v: Any, limit: int) -> str:
    return " ".join(str(v or "").split())[:limit]


def _safe_url(v: Any) -> str | None:
    u = str(v or "").strip()
    p = urlparse(u)
    return u[:600] if p.scheme in ("http", "https") and p.netloc and len(u) <= 600 else None


def _get(params: dict) -> dict:
    """The one network call (tests replace it)."""
    headers = {"x-rapidapi-key": os.getenv("RAPIDAPI_KEY", "").strip(), "x-rapidapi-host": HOST}
    try:
        r = httpx.get(URL, params=params, headers=headers, timeout=15.0)
    except httpx.HTTPError:
        raise ExternalError("unavailable", "The outside job feed did not answer. Try again in a minute.")
    if r.status_code in (401, 403):
        raise ExternalError("feed_key", "The job feed key is not accepted. Check RAPIDAPI_KEY and your subscription to the Jobs API.", 502)
    if r.status_code == 429:
        raise ExternalError("feed_busy", "The outside job feed is out of searches for now. Try again later.")
    if r.status_code >= 400:
        raise ExternalError("unavailable", "The outside job feed had a problem. Try again in a minute.", 502)
    try:
        return r.json()
    except ValueError:
        raise ExternalError("unavailable", "The outside job feed sent something unreadable.", 502)


def _when(ms: Any) -> str | None:
    """Indeed sends milliseconds since 1970. Anything odd becomes None rather than a wrong date."""
    try:
        t = float(ms) / 1000
        if not 946684800 <= t <= time.time() + 86400 * 2:      # 2000 .. two days from now
            return None
        return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def normalize(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    title, jid = _text(item.get("title"), 160), _text(item.get("id"), 200)
    if not title or not jid:
        return None
    company = item.get("company") if isinstance(item.get("company"), dict) else {}
    loc = item.get("location") if isinstance(item.get("location"), dict) else {}
    place = _text(loc.get("location"), 160)
    return {
        "id": jid, "title": title, "company": _text(company.get("name"), 160) or None, "location": place or None,
        "remote": bool(re.search(r"\bremote\b", f"{title} {place}", re.I)), "employment_type": None,
        "posted_at": _when(item.get("datePublishedTimestamp")) or _when(item.get("dateOnIndeedTimestamp")), "source": "Indeed",
        "apply_url": _safe_url(item.get("applyUrl")), "description": str(item.get("description") or "")[:MAX_DESCRIPTION],
    }


def _expire(table: dict) -> None:
    if len(table) > 200:                         # keep the tables small
        for k in sorted(table, key=lambda k: table[k][0])[:100]:
            table.pop(k, None)


def search(query: str, location: str = "", page: int = 1, radius_km: int = 20) -> dict:
    """Raises ExternalError. Returns {"jobs": [...normalised, at most 20], "has_more": bool}."""
    if not configured():
        raise ExternalError("not_configured", "The outside job feed is not set up on this server.", 503)
    cc = country()
    base = (query.lower(), location.lower(), radius_km, cc)
    key = base + (page,)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    params = {"query": query, "radius": str(radius_km), "radiusType": "km", "sortType": "relevance", "countryCode": cc}
    if location:
        params["location"] = location
    if page > 1:                                  # later pages are fetched with the token the page before gave us
        tok = _tokens.get(base + (page,))
        if not tok or time.time() - tok[0] >= CACHE_SECONDS:
            raise ExternalError("start_over", "Run the search again from the first page.", 409)
        params = {"token": tok[1]}
    today = date.today().isoformat()
    if _day["date"] != today:
        _day.update(date=today, count=0)
    if _day["count"] >= _cap():
        raise ExternalError("feed_busy", "The outside job feed has reached today's limit. Try again tomorrow.")
    _day["count"] += 1
    started = time.monotonic()
    try:
        body = _get(params)
    except ExternalError as exc:
        _record(False, started, exc.code)
        raise
    if not isinstance(body, dict) or body.get("hasError") or not isinstance(body.get("data"), list):
        _record(False, started, "bad_reply")
        raise ExternalError("unavailable", "The outside job feed had a problem. Try again in a minute.", 502)
    jobs = [j for j in (normalize(i) for i in body["data"][:20]) if j]
    _record(True, started, results=len(jobs))
    meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
    nxt = meta.get("nextToken")
    if isinstance(nxt, str) and 0 < len(nxt) <= 2000 and jobs:
        _tokens[base + (page + 1,)] = (time.time(), nxt)
        _expire(_tokens)
    result = {"jobs": jobs, "has_more": bool(isinstance(nxt, str) and nxt and jobs)}
    _cache[key] = (time.time(), result)
    _expire(_cache)
    return result
