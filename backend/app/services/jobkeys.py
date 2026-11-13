"""Keys that tell two copies of the same outside job apart, and the freshness rule for outside jobs.

Outside jobs reach Hiriq from several places (the Indeed feed today, more sources later), so the same post can arrive twice
under different ids or with different tracking junk on its link. Two keys catch that:

  apply_key   sha-256 of the NORMALIZED apply link. This is the main key: one apply link is one job, and the database refuses a
              second row with the same apply_key. Normalizing drops what does not change the page: upper/lower case in the host,
              "www.", a trailing slash, the #fragment, default ports, and tracking parameters (utm_*, gclid, ref ...). Any other
              parameter is kept, because some sites keep the job id in the query (for example ?jk=...). The rest are sorted.
  dedupe_key  sha-256 of title + company + city. The backup, for the same job posted under two different links. It needs both a
              title and a company, so two anonymous posts are never merged by accident.

Freshness: a post older than FRESH_DAYS (30) is not shown, because it is probably filled. "Older" counts from `listed_at`, which is
the date the post says it was published, or the day Hiriq first saw it when the post gives no date.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit

FRESH_DAYS = 30

_TRACKING_EXACT = {
    "gclid", "fbclid", "msclkid", "dclid", "yclid", "mc_cid", "mc_eid", "igshid", "ref", "referrer", "referer", "src", "source",
    "trk", "trkid", "trackingid", "tracking", "from", "campaign", "cmp", "ad", "adid", "sid", "spm", "_ga", "_gl", "vjs",
}
_TRACKING_PREFIX = ("utm_", "utm-", "hsa_", "mkt_", "pk_", "ga_")
_DEFAULT_PORT = {"http": 80, "https": 443}


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_url(url: str | None) -> str | None:
    """The same link with the noise removed, or None when it is not a plain http(s) address."""
    raw = (url or "").strip()
    if not raw or len(raw) > 2000:
        return None
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in ("http", "https") or not host or "." not in host:
        return None
    if host.startswith("www."):
        host = host[4:]
    netloc = host if port in (None, _DEFAULT_PORT[scheme]) else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if len(path) > 1:
        path = path.rstrip("/")
    query = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_EXACT and not k.lower().startswith(_TRACKING_PREFIX)
    )
    # http and https of the same page are one job
    return f"{netloc}{path}" + (f"?{urlencode(query)}" if query else "")


def apply_key(url: str | None) -> str | None:
    norm = normalize_url(url)
    return _digest("url:" + norm) if norm else None


def _words(text: str | None) -> str:
    return " ".join(re.findall(r"[a-z0-9+#]+", (text or "").lower()))


def dedupe_key(title: str | None, company: str | None, location: str | None) -> str | None:
    t, c = _words(title), _words(company)
    if not t or not c:
        return None
    city = _words((location or "").split(",")[0])
    return _digest(f"post:{t}|{c}|{city}")


def job_key(url: str | None, title: str | None, company: str | None, location: str | None) -> str | None:
    """One stable key for "this job": the apply-link key when there is a link, else the title-company-city key."""
    return apply_key(url) or dedupe_key(title, company, location)


# ---------------------------------------------------------------- freshness
def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def cutoff(now: datetime | None = None, days: int = FRESH_DAYS) -> datetime:
    return _aware(now or datetime.now(timezone.utc)) - timedelta(days=days)


def listed_at(posted_at: datetime | None, first_seen_at: datetime | None) -> datetime:
    """The date a post counts from: when it says it was published, else the day Hiriq first saw it."""
    return posted_at or first_seen_at or datetime.now(timezone.utc)


def is_fresh(listed: datetime | None, now: datetime | None = None, days: int = FRESH_DAYS) -> bool:
    return listed is not None and _aware(listed) >= cutoff(now, days)
