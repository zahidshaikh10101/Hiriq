"""Google Jobs, scraped with a real browser (Playwright), as a source.

For each role × place × years (the resume's years at floor and ceil, so 3.5 searches 3 and 4) it searches Google for
"<role> in <place> with <N> years of experience jobs", opens the Jobs tab, scrolls the list a few times, reads every card, and
clicks the cards whose apply link or description is not in the page yet. Reading the HTML is in google_jobs_parse.py.

Off unless GOOGLE_JOBS_SCRAPER=1 and Playwright is installed (pip install -r requirements-scraper.txt, then
`playwright install chromium`). It is meant for a machine with a screen: Google does not allow automated searches and shows
a CAPTCHA now and then. With GOOGLE_JOBS_HEADLESS=0 (the default) the window is visible and the scraper waits
GOOGLE_JOBS_CAPTCHA_WAIT seconds (default 120) for you to solve it; otherwise the rest of that save's searches are skipped.
It will not run on Render (no browser, and Google blocks server addresses quickly).

Other settings: GOOGLE_JOBS_SAVE_QUERIES (searches per save, default 4, at most 8), GOOGLE_JOBS_DAILY_CAP (Google searches
the whole server may make per day, default 40, counted from external_calls so a restart cannot reset it),
GOOGLE_JOBS_SCROLLS / GOOGLE_JOBS_SCROLL_PX (default 5 × 220), GOOGLE_JOBS_MAX_CLICKS (per search, default 30),
GOOGLE_JOBS_CHROME=1 to use the installed Chrome (default) and GOOGLE_JOBS_PROFILE_DIR (cookies kept between runs, so a
CAPTCHA solved once is not asked again; default backend/.gjobs_profile, which git ignores).
Only one browser runs at a time: a second save waits for the first to finish.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import random
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import quote_plus

from app.db import session as db_session
from app.services.sources import google_jobs_parse as gp
from app.services.sources.base import Result, Search, SourceError

PROVIDER = "google_jobs"
_lock = threading.Lock()

_PANEL_JS = """
([docid, applySel, panelSel, headSel, tailSel]) => {
  const scoped = [...document.querySelectorAll(`[data-encoded-docid="${docid}"] ${applySel}`)];
  // Fallback: the apply strip of whichever job panel is open right now (visible on screen)
  const open = [...document.querySelectorAll(`${panelSel} ${applySel}`)].filter(a => a.offsetParent !== null);
  const anchors = (scoped.length ? scoped : open).map(a => ({
    title: a.getAttribute("title"), text: a.innerText, href: a.getAttribute("href"), ping: a.getAttribute("ping")}));
  const root = document.querySelector(`[data-encoded-docid="${docid}"] ${headSel}`)?.parentElement;
  const desc = root ? [root.querySelector(headSel), root.querySelector(tailSel)]
      .filter(Boolean).map(e => e.innerText || e.textContent).join("") : "";
  return {anchors, desc};
}
"""


def _int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(int(os.getenv(name, str(default))), hi))
    except ValueError:
        return default


def _on(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def installed() -> bool:
    return importlib.util.find_spec("playwright") is not None


def daily_cap() -> int:
    return _int("GOOGLE_JOBS_DAILY_CAP", 40, 0, 500)


def used_today() -> int:
    """Google searches made today (UTC), from the call log."""
    if db_session.SessionLocal is None:
        return 0
    try:
        from sqlalchemy import func, select

        from app.db.recruiter_models import ExternalCall

        now = datetime.now(timezone.utc)
        start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        with db_session.SessionLocal() as db:
            return int(db.scalar(select(func.count()).select_from(ExternalCall)
                                 .where(ExternalCall.provider == PROVIDER, ExternalCall.created_at >= start)) or 0)
    except Exception:  # noqa: BLE001
        return 0


def _record(ok: bool, started: float, error: str | None = None, results: int | None = None) -> None:
    if db_session.SessionLocal is None:
        return
    try:
        from app.db.recruiter_models import ExternalCall

        with db_session.SessionLocal() as db:
            db.add(ExternalCall(provider=PROVIDER, ok=ok, error=(error or None) and error[:200],
                                latency_ms=int((time.monotonic() - started) * 1000), results=results))
            db.commit()
    except Exception:  # noqa: BLE001
        pass


class _Browser:
    """One Chrome window for a batch of searches."""

    def __init__(self, page):
        self.page = page
        self.headless = _on("GOOGLE_JOBS_HEADLESS")

    # --- page steps ---
    def _blocked(self) -> bool:
        return "/sorry/" in self.page.url or self.page.locator("#captcha-form, form#captcha").count() > 0

    def _wait_if_blocked(self) -> None:
        if not self._blocked():
            return
        if self.headless:
            raise SourceError("blocked", "Google asked for a CAPTCHA. Run the scraper with a visible window to solve it.")
        end = time.time() + _int("GOOGLE_JOBS_CAPTCHA_WAIT", 120, 0, 900)
        while time.time() < end:
            time.sleep(2)
            if not self._blocked():
                return
        raise SourceError("blocked", "Google asked for a CAPTCHA and it was not solved in time.")

    def _consent(self) -> None:
        for name in ("Accept all", "I agree"):
            b = self.page.get_by_role("button", name=name)
            if b.count():
                b.first.click()
                self.page.wait_for_load_state("domcontentloaded")
                return

    def _open_jobs(self, query: str) -> bool:
        from playwright.sync_api import TimeoutError as PWTimeout

        p = self.page
        p.goto(f"https://www.google.com/search?q={quote_plus(query)}&hl=en", wait_until="domcontentloaded")
        self._consent()
        self._wait_if_blocked()
        tab = p.locator('div[role="listitem"] a:has(span:text-is("Jobs"))')
        if not tab.count():
            tab = p.get_by_role("link", name="Jobs", exact=True)
        try:
            if tab.count():
                tab.first.click()
                p.wait_for_selector(gp.SEL["title"], timeout=12000)
                return True
        except PWTimeout:
            pass
        # Fallback: the Jobs view directly (the same link Google shares for a job list)
        p.goto(f"https://www.google.com/search?q={quote_plus(query)}&ibp=htl;jobs&udm=8&hl=en", wait_until="domcontentloaded")
        self._wait_if_blocked()
        try:
            p.wait_for_selector(gp.SEL["title"], timeout=12000)
            return True
        except PWTimeout:
            return False

    def _scroll(self) -> None:
        from playwright.sync_api import TimeoutError as PWTimeout

        px = _int("GOOGLE_JOBS_SCROLL_PX", 220, 50, 2000)
        try:
            self.page.locator(gp.SEL["title"]).first.hover(timeout=3000)   # so the wheel scrolls the job list
        except PWTimeout:
            pass
        for _ in range(_int("GOOGLE_JOBS_SCROLLS", 5, 0, 30)):
            self.page.mouse.wheel(0, px)
            self.page.evaluate(f"window.scrollBy(0, {px})")
            self.page.wait_for_timeout(1500)

    def _fill_missing(self, rows: list[dict]) -> dict:
        """Click cards lacking a description or apply link, and read the open panel right away
        (Google re-uses one panel, so it has to be read before the next click replaces it)."""
        from playwright.sync_api import TimeoutError as PWTimeout

        S, panel = gp.SEL, {}
        for docid in gp.missing(rows)[:_int("GOOGLE_JOBS_MAX_CLICKS", 30, 0, 100)]:
            card = self.page.locator(f'[id="{docid}"] {S["click"]}')
            if not card.count():
                continue
            try:
                card.first.scroll_into_view_if_needed(timeout=3000)
                card.first.click(timeout=4000)
                self.page.wait_for_selector(f'{S["apply_panel"]} {S["apply"]}', state="visible", timeout=6000)
            except PWTimeout:
                continue
            self.page.wait_for_timeout(random.randint(500, 900))
            got = self.page.evaluate(_PANEL_JS, [docid, S["apply"], S["apply_panel"], S["desc_head"], S["desc_tail"]])
            panel[docid] = {"apply_links": gp.apply_links_from(got.get("anchors") or []),
                            "description": gp._clean(got.get("desc") or "")}
        return panel

    def fetch(self, s: Search) -> list[dict]:
        if not self._open_jobs(s.text):
            return []                                   # Google found no jobs for these words
        self._scroll()
        rows = gp.parse_page(self.page.content())
        if gp.missing(rows):
            rows = gp.merge_panel(gp.parse_page(self.page.content()), self._fill_missing(rows))
        return rows


class GoogleJobsSource:
    name = "google_jobs"
    provider = PROVIDER

    def configured(self) -> bool:
        return _on("GOOGLE_JOBS_SCRAPER") and installed()

    def calls_per_save(self) -> int:
        return _int("GOOGLE_JOBS_SAVE_QUERIES", 4, 0, 8)

    def plan(self, roles: list[str], locations: list[str], years: float | None, limit: int) -> list[Search]:
        """Each role and place at the resume's floor and ceil years. Roles go before places, so with a small limit every
        role is searched at least once before a second place is."""
        out = []
        for loc in (locations or [""]):
            for role in roles:
                for y in gp.experience_variants(years):
                    out.append(Search(role=role, location=loc, years=y, text=gp.build_query(role, loc, y)))
        return out[:limit]

    @contextmanager
    def _session(self):
        """The browser. Tests replace this with a stand-in that returns saved pages."""
        if sys.platform == "win32":     # uvicorn --reload uses a loop that cannot start a browser; new loops get this one
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise SourceError("no_browser", "Playwright is not installed. pip install -r requirements-scraper.txt")
        profile = os.getenv("GOOGLE_JOBS_PROFILE_DIR") or str(Path(__file__).resolve().parents[3] / ".gjobs_profile")
        kw = dict(user_data_dir=profile, headless=_on("GOOGLE_JOBS_HEADLESS"), locale="en-IN",
                  viewport={"width": 1366, "height": 900}, args=["--disable-blink-features=AutomationControlled"])
        with sync_playwright() as p:
            ctx = None
            if _on("GOOGLE_JOBS_CHROME", "1"):
                try:
                    ctx = p.chromium.launch_persistent_context(channel="chrome", **kw)
                except Exception:  # noqa: BLE001  (Chrome not installed: use Playwright's own Chromium)
                    ctx = None
            if ctx is None:
                try:
                    ctx = p.chromium.launch_persistent_context(**kw)
                except Exception as exc:  # noqa: BLE001
                    raise SourceError("no_browser", f"Could not start a browser: {str(exc).splitlines()[0][:150]}")
            try:
                yield _Browser(ctx.pages[0] if ctx.pages else ctx.new_page())
            finally:
                ctx.close()

    def run(self, searches: list[Search]) -> Iterator[Result]:
        if not searches:
            return
        if not _lock.acquire(timeout=_int("GOOGLE_JOBS_LOCK_WAIT", 600, 0, 3600)):
            yield Result(searches[0], error=SourceError("feed_busy", "Another Google Jobs fetch is still running."))
            return
        try:
            try:
                with self._session() as browser:
                    for i, s in enumerate(searches):
                        if used_today() >= daily_cap():
                            yield Result(s, error=SourceError("daily_limit", "Google Jobs has reached today's search limit."))
                            return
                        if i:
                            time.sleep(random.uniform(*_delay()))
                        started = time.monotonic()
                        try:
                            jobs = browser.fetch(s)
                        except SourceError as exc:
                            _record(False, started, exc.code)
                            yield Result(s, error=exc)
                            if exc.stop:
                                return
                            continue
                        except Exception as exc:  # noqa: BLE001  (a page that changed shape must not end the save)
                            _record(False, started, f"page: {type(exc).__name__}")
                            yield Result(s, error=SourceError("unavailable", "Google Jobs page could not be read."))
                            continue
                        _record(True, started, results=len(jobs))
                        yield Result(s, jobs=jobs)
            except SourceError as exc:                    # the browser itself could not start
                yield Result(searches[0], error=exc)
        finally:
            _lock.release()


def _delay() -> tuple[float, float]:
    """GOOGLE_JOBS_DELAY='6-12': random pause in seconds between two Google searches."""
    try:
        lo, hi = (float(x) for x in os.getenv("GOOGLE_JOBS_DELAY", "6-12").split("-", 1))
        return (max(0.0, lo), max(lo, hi))
    except ValueError:
        return (6.0, 12.0)
