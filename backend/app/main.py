"""Hiriq API entry point.

Run from the backend folder:
    uvicorn app.main:app --reload
Then open http://localhost:8000 (the frontend) or http://localhost:8000/docs (API docs).
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.db import session as db_session
from app.routers import admin, auth, health

log = logging.getLogger("hiriq")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Bring the database schema up to date (idempotent). Never stop the API from starting if it cannot.
    if db_session.engine is not None:
        try:
            from app.db.upgrade import upgrade

            for change in upgrade():
                log.warning("Database upgrade: %s", change)
        except Exception as exc:  # noqa: BLE001
            log.error("Database upgrade failed (run `python -m app.db.upgrade` to see why): %s", exc)
    yield


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api/auth")
app.include_router(admin.router, prefix="/api/admin")

# Upcoming routers (see backend/README.md):
#   /api/resumes  - upload + structured extraction (GenAI)
#   /api/match    - score a resume against a job, with explanation
#   /api/jobs     - ingested postings, search
#   /api/admin    - users, sources, model metrics (users, overview and audit are live)

# Serve the plain HTML/CSS/JS frontend from the same server, so one URL runs everything.
# Mounted last so /api routes take priority.
if settings.frontend_dir.exists():
    app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
