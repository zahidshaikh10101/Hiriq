"""Reading a Google Jobs results page (pure HTML in, job dicts out). No browser here, so the tests run it on a saved page.

Google's class names are obfuscated and change every few months. They all live in SEL: when the scraper suddenly finds
nothing, open the page in Chrome, inspect one card, and update SEL (ml/notebooks/google_jobs_scraper.ipynb has the same code
for trying a fix quickly). Every value read here is untrusted text from the internet: it is trimmed and limited, and a link
is kept only if it is a plain http(s) address that does not point back at Google.
"""
from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup
from bs4.element import NavigableString, TemplateString

SEL = {
    "title":       "div.tNxQIb",                 # Senior Analyst, Digital Analytics
    "company":     "div.a3jPc",                  # div.wHYlTd.MKCbgd.a3jPc -> Labcorp
    "loc_via":     "div.FqK3wc",                 # "Bengaluru, Karnataka • via Labcorp Careers"
    "chip":        "span.Yf9oye[aria-label]",    # "Posted 1 day ago", "Employment type Full–time"
    "click":       "div[jsname='OCDbef']",       # the clickable part of a card
    "desc_head":   "span.OOyDTc",                # first part of the description
    "desc_tail":   "span[jsname='ij8cu']",       # hidden "Show full description" remainder
    "apply":       "a.brKmxb",                   # "Apply on LinkedIn", "Apply directly on Labcorp Careers"
    "apply_panel": "div.NmXWu",                  # the apply-buttons strip of the open job panel
    "detail_chip": "span.fLsjxc",                # detail chips: "No Degree Mentioned", salary...
}

MAX_DESCRIPTION = 6000
MAX_LINKS = 10
# Google keeps card details inside <template>; BeautifulSoup skips those strings unless asked.
_TEXT_TYPES = (NavigableString, TemplateString)
_TRACKING = re.compile(r"^(utm_|ved$|sa$|usg$|opi$|rct$|source$)")
_SPACE = re.compile(r"\s+")
_REMOTE = re.compile(r"\b(remote|work from home|wfh|anywhere)\b", re.I)


# ---------- the searches ----------

def experience_variants(years) -> list[int | None]:
    """Years from the resume, searched at floor and ceil: 3.5 -> [3, 4]; 3.0 -> [3]; 0.4 -> [0, 1]; None -> [None]."""
    if years is None:
        return [None]
    try:
        y = max(0.0, min(float(years), 50.0))
    except (TypeError, ValueError):
        return [None]
    return sorted({math.floor(y), math.ceil(y)})


def build_query(role: str, location: str, years: int | None) -> str:
    """'Data Analyst in Mumbai with 3 years of experience jobs' (the way a person would type it)."""
    role, location = _clean(role), _clean(location)
    where = f" in {location}" if location else ""
    if years is None:
        return f"{role}{where} jobs"
    if years == 0:
        return f"{role}{where} for freshers jobs"
    return f"{role}{where} with {years} {'year' if years == 1 else 'years'} of experience jobs"


# ---------- small helpers ----------

def _txt(el) -> str:
    return el.get_text(types=_TEXT_TYPES) if el is not None else ""


def _clean(s, limit: int | None = None) -> str:
    out = _SPACE.sub(" ", (s or "").replace("\xa0", " ")).strip()
    return out[:limit] if limit else out


def _strip_tracking(url: str) -> str:
    p = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not _TRACKING.match(k)]
    return urlunparse(p._replace(query=urlencode(q), fragment=""))


def _safe(url: str | None) -> str | None:
    if not url:
        return None
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc or "google." in p.netloc:
        return None
    out = _strip_tracking(url)
    return out if len(out) <= 600 else None


def real_url(href: str | None, ping: str | None = None) -> str | None:
    """Apply anchors carry the real link in href; sometimes it is a /url?url=... redirect instead."""
    for raw in (href, ping):
        if not raw:
            continue
        direct = _safe(raw) if raw.startswith("http") else None
        if direct:
            return direct
        q = dict(parse_qsl(urlparse(raw).query))
        for k in ("url", "q"):
            if q.get(k, "").startswith("http"):
                found = _safe(q[k])
                if found:
                    return found
    return None


def apply_links_from(anchors: list[dict]) -> list[dict]:
    """anchors: dicts with title / text / href / ping, from BeautifulSoup or from the live page. Order is kept."""
    out: list[dict] = []
    for a in anchors:
        label = _clean(a.get("title") or a.get("text") or "")
        if label and not label.lower().startswith("apply"):
            continue
        url = real_url(a.get("href"), a.get("ping"))
        if url and url not in {x["url"] for x in out}:
            site = re.sub(r"^apply (directly )?on\s+", "", label, flags=re.I) or urlparse(url).netloc
            out.append({"site": _clean(site, 80), "url": url, "direct": "directly" in label.lower()})
    return out[:MAX_LINKS]


def _block_text(el) -> str:
    """Text with <br> kept as line breaks."""
    if el is None:
        return ""
    for br in el.find_all("br"):
        br.replace_with("\n")
    return "\n".join(x for x in (_clean(line) for line in _txt(el).split("\n")) if x)


def posted_to_date(text: str | None, now: datetime | None = None) -> datetime | None:
    """'1 day ago' / '3 hours ago' / '2 weeks ago' / 'Just posted' -> an approximate UTC time. Anything else -> None."""
    now = now or datetime.now(timezone.utc)
    t = (text or "").lower()
    if not t:
        return None
    if "just" in t or "today" in t:
        return now
    if "yesterday" in t:
        return now - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*(minute|min|hour|hr|day|week|month)", t)
    if not m:
        return None
    n, unit = min(int(m.group(1)), 365), m.group(2)
    days = {"minute": n / 1440, "min": n / 1440, "hour": n / 24, "hr": n / 24, "day": n, "week": 7 * n, "month": 30 * n}[unit]
    return now - timedelta(days=days)


def _maindata_links(root) -> list[dict]:
    """Backup: Google also lists the apply links as jobs_posting_urls_N inside a data-maindata blob."""
    blob = " ".join(el.get("data-maindata", "") for el in root.select("[data-maindata]"))
    blob = blob.replace("\\u003d", "=").replace("\\u0026", "&")
    return [{"href": u} for u in re.findall(r'jobs_posting_urls_\d+","(https?://[^"]+)"', blob)]


def details(soup, docid: str | None) -> dict:
    """Description, apply links and detail chips of one job: from its <template> next to the card, or the open panel."""
    out = {"description": "", "apply_links": [], "detail_chips": []}
    if not docid:
        return out
    for root in soup.select(f'[data-encoded-docid="{docid}"]'):
        head = root.select_one(SEL["desc_head"])
        if head is not None and not out["description"]:
            out["description"] = (_block_text(head) + _block_text(root.select_one(SEL["desc_tail"]))).strip()
        anchors = [{"title": a.get("title"), "text": _txt(a), "href": a.get("href"), "ping": a.get("ping")}
                   for a in root.select(SEL["apply"])] + _maindata_links(root)
        for link in apply_links_from(anchors):
            if link["url"] not in {x["url"] for x in out["apply_links"]}:
                out["apply_links"].append(link)
        if not out["detail_chips"]:
            out["detail_chips"] = [c for c in (_clean(_txt(x), 80) for x in root.select(SEL["detail_chip"])) if c][:8]
    out["apply_links"] = out["apply_links"][:MAX_LINKS]
    return out


def _card_root(title_el):
    """Walk up from the title to the card container that carries the job id."""
    el = title_el
    while el is not None and el.name:
        if el.get("data-preview-id") or (el.get("id", "").endswith("=") and el.get("jsname") == "y1Aese"):
            return el
        el = el.parent
    return title_el.find_parent("div", class_="EimVGf") or title_el.parent


def _fallback_id(title: str, company: str, location: str) -> str:
    return "h:" + hashlib.sha256(f"{title}|{company}|{location}".lower().encode()).hexdigest()[:40]


# ---------- the page ----------

def parse_page(html: str, now: datetime | None = None) -> list[dict]:
    """Every job card on the page, in the shape externalstore.save takes (plus the Google-only fields)."""
    soup = BeautifulSoup(html or "", "html.parser")
    rows, seen = [], set()
    for t in soup.select(SEL["title"]):
        if t.find_parent("template") is not None:          # titles inside templates are copies
            continue
        title = _clean(_txt(t), 160)
        if not title:
            continue
        card = _card_root(t)
        docid = card.get("id") if card.get("id", "").endswith("=") else None
        share_el = t.find_parent(attrs={"data-share-url": True})
        if not docid and share_el is not None:
            m = re.search(r"htidocid=([^&#]+)", share_el.get("data-share-url", ""))
            docid = m.group(1).replace("%3D", "=") if m else None

        lv = card.select_one(SEL["loc_via"])
        parts = [p.strip() for p in _clean(_txt(lv)).split("•")] if lv is not None else []
        location = _clean(parts[0], 160) if parts else ""
        via = _clean(re.sub(r"^via\s+", "", parts[1], flags=re.I), 80) if len(parts) > 1 else ""
        comp = card.select_one(SEL["company"])
        company = _clean(_txt(comp), 160) if comp is not None else ""

        key = docid or _fallback_id(title, company, location)
        if key in seen:
            continue
        seen.add(key)

        chips: dict = {}
        for c in card.select(SEL["chip"]):
            label, value = _clean(c.get("aria-label", "")).lower(), _clean(_txt(c), 80)
            if label.startswith("posted"):
                chips["posted"] = value
            elif label.startswith("employment type"):
                chips["employment_type"] = _clean(value, 40)
            elif label.startswith("salary"):
                chips["salary"] = value

        d = details(soup, docid)
        posted = posted_to_date(chips.get("posted"), now)
        rows.append({
            "id": key[:200], "title": title, "company": company or None, "location": location or None,
            "remote": bool(_REMOTE.search(f"{title} {location}")), "employment_type": chips.get("employment_type"),
            "salary": chips.get("salary"), "posted_text": chips.get("posted"),
            "posted_at": posted.strftime("%Y-%m-%dT%H:%M:%SZ") if posted else None,
            "source": "Google Jobs", "via": via or None,
            # Google lists the most relevant source first. "Apply directly on" isn't safe to prefer:
            # aggregators sometimes attach a different job under that label.
            "apply_url": d["apply_links"][0]["url"] if d["apply_links"] else None,
            "apply_links": d["apply_links"], "detail_chips": d["detail_chips"],
            "description": d["description"][:MAX_DESCRIPTION],
        })
    return rows


def missing(rows: list[dict]) -> list[str]:
    """Jobs still lacking a description or an apply link (the scraper clicks these). Only real Google ids can be clicked."""
    return [r["id"] for r in rows if not r["id"].startswith("h:") and (not r["description"] or not r["apply_url"])]


def merge_panel(rows: list[dict], panel: dict) -> list[dict]:
    """panel: {docid: {"apply_links": [...], "description": str}} read live after clicking each card."""
    for r in rows:
        p = panel.get(r["id"])
        if not p:
            continue
        if p.get("apply_links") and not r["apply_links"]:
            r["apply_links"] = p["apply_links"][:MAX_LINKS]
        if r["apply_links"] and not r["apply_url"]:
            r["apply_url"] = r["apply_links"][0]["url"]
        if p.get("description") and not r["description"]:
            r["description"] = p["description"][:MAX_DESCRIPTION]
    return rows
