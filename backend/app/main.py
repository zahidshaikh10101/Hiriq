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
from app.routers import admin, admin_ai, ask, auth, candidates, health, jobs, matches, pipeline, recruiter

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

@app.middleware("http")
async def no_cache_static(request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache"
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Filename"],
)

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api/auth")
app.include_router(admin.router, prefix="/api/admin")
app.include_router(admin_ai.router, prefix="/api/admin")
app.include_router(recruiter.router, prefix="/api/recruiter")
app.include_router(jobs.router, prefix="/api/recruiter")
app.include_router(candidates.router, prefix="/api/recruiter")
app.include_router(matches.router, prefix="/api/recruiter")
app.include_router(pipeline.router, prefix="/api/recruiter")
app.include_router(ask.router, prefix="/api/recruiter")

# Upcoming routers (see backend/README.md):
#   /api/recruiter - all recruiter routers are live (jobs, candidates, matcher, pipeline, ask-the-pool)
#   /api/resumes   - candidate-side upload + structured extraction (GenAI)
#   /api/match     - score a resume against a job, with explanation
#   /api/admin     - users, sources, model metrics (users, overview, audit and AI usage are live)

# Serve the plain HTML/CSS/JS frontend from the same server, so one URL runs everything.
# Mounted last so /api routes take priority.
if settings.frontend_dir.exists():
    app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
