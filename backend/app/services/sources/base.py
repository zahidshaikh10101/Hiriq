"""What every outside job source looks like to the rest of Hiriq.

A source turns a candidate's preferences (roles, places, years of experience) into a few searches (`plan`), and runs them
(`run`), yielding one result per search as it goes, so each batch can be saved before the next search starts. Each job comes
back in the shape externalstore.save takes:

    {"id", "title", "company", "location", "remote", "employment_type", "posted_at" ("YYYY-MM-DDTHH:MM:SSZ" or None),
     "source", "apply_url", "description"}  and optionally  {"via", "salary", "apply_links"}

Nothing about the candidate travels with a search except the role, place and rounded years in it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Protocol

# Codes after which the rest of this source's searches are skipped (asking again would fail the same way).
STOP_CODES = frozenset({"not_configured", "feed_busy", "monthly_limit", "daily_limit", "blocked", "no_browser"})


class SourceError(Exception):
    def __init__(self, code: str, message: str, status: int = 503):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status

    @property
    def stop(self) -> bool:
        return self.code in STOP_CODES


@dataclass(frozen=True)
class Search:
    role: str
    location: str = ""
    years: int | None = None
    text: str = ""          # what is actually typed into the source (e.g. the Google query); empty = role

    @property
    def label(self) -> str:
        """Kept in external_jobs.last_query (at most 100 characters)."""
        return (self.text or self.role)[:100]


@dataclass
class Result:
    search: Search
    jobs: list[dict] = field(default_factory=list)
    error: SourceError | None = None


class Source(Protocol):
    name: str          # registry name, used in JOB_SOURCES
    provider: str      # external_jobs.provider and external_calls.provider

    def configured(self) -> bool: ...
    def calls_per_save(self) -> int: ...
    def plan(self, roles: list[str], locations: list[str], years: float | None, limit: int) -> list[Search]: ...
    def run(self, searches: list[Search]) -> Iterator[Result]: ...
