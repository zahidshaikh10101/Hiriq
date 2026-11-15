"""Shared test settings. The Google Jobs scraper opens a real browser, so it is forced off for every test, whatever
backend/.env says; the tests that need it switch it on and replace the browser with saved pages."""
import pytest


@pytest.fixture(autouse=True)
def _no_real_scraper(monkeypatch):
    monkeypatch.setenv("GOOGLE_JOBS_SCRAPER", "0")
    monkeypatch.delenv("JOB_SOURCES", raising=False)
