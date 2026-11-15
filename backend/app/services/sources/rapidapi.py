"""Indeed through the RapidAPI "Jobs API" (jobs-api14), as a source. The call, cache, daily and monthly caps stay in
externaljobs.py (the live search on the Find work page uses it too); this only adapts it to the Source shape."""
from __future__ import annotations

import os
from typing import Iterator

from app.services import externaljobs
from app.services.sources.base import Result, Search, SourceError


class RapidApiSource:
    name = "indeed"
    provider = "indeed"

    def configured(self) -> bool:
        return externaljobs.configured()

    def calls_per_save(self) -> int:
        """EXTERNAL_SAVE_FETCH_CALLS (default 2, at most 5): the plan is 250 requests a month for the whole server."""
        try:
            return max(0, min(int(os.getenv("EXTERNAL_SAVE_FETCH_CALLS", "2")), 5))
        except ValueError:
            return 2

    def plan(self, roles: list[str], locations: list[str], years: float | None, limit: int) -> list[Search]:
        """Indeed is asked the role only (years in the words make its results worse). Each role before a role repeats."""
        places = locations or [""]
        return [Search(role=r, location=l) for l in places for r in roles][:limit]

    def run(self, searches: list[Search]) -> Iterator[Result]:
        for s in searches:
            try:
                found = externaljobs.search(s.role, s.location)
            except externaljobs.ExternalError as exc:
                yield Result(s, error=SourceError(exc.code, exc.message, exc.status))
                continue
            yield Result(s, jobs=[dict(j) for j in found["jobs"]])
