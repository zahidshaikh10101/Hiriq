"""Outside job sources, and which of them run.

JOB_SOURCES lists them in the order they run after a preferences save (default "google_jobs,indeed"). A listed source that
is not set up (no RAPIDAPI_KEY; GOOGLE_JOBS_SCRAPER off or Playwright missing) is skipped. To add an official API later,
write a class with the Source shape (base.py) and add it to REGISTRY.
"""
from __future__ import annotations

import os

from app.services.sources.base import Result, Search, Source, SourceError  # noqa: F401  (re-exported)
from app.services.sources.google_jobs import GoogleJobsSource
from app.services.sources.rapidapi import RapidApiSource

REGISTRY: dict[str, Source] = {s.name: s for s in (GoogleJobsSource(), RapidApiSource())}
DEFAULT_ORDER = "google_jobs,indeed"


def get(name: str) -> Source | None:
    return REGISTRY.get(name)


def listed() -> list[Source]:
    names = [n.strip().lower() for n in os.getenv("JOB_SOURCES", DEFAULT_ORDER).split(",") if n.strip()]
    return [REGISTRY[n] for n in dict.fromkeys(names) if n in REGISTRY]


def enabled() -> list[Source]:
    """The listed sources that are set up, in order."""
    return [s for s in listed() if s.configured()]


def any_configured() -> bool:
    return bool(enabled())


def status() -> list[dict]:
    return [{"name": s.name, "provider": s.provider, "listed": s in listed(), "configured": s.configured()} for s in REGISTRY.values()]
