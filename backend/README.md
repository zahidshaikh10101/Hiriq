# backend/

FastAPI service for Hiriq. It also serves `../frontend`, so http://localhost:8000 runs the whole app.

## Endpoints today

| Method | Path | What |
|---|---|---|
| GET | `/api/health` | status, version, whether login is configured |
| POST | `/api/auth/login` | `{username, password}` → `{access_token, role}` (admin from `.env`) |
| GET | `/api/auth/me` | `Authorization: Bearer <token>` → `{user, role}` |

Interactive docs: http://localhost:8000/docs

## Where new code goes

- `app/routers/` — one file per area (`resumes.py`, `match.py`, `jobs.py`, `admin.py`). Thin: validate input, call a service, return.
- `app/services/` — the real logic (see the plan in `app/services/__init__.py`).
- `app/core/` — settings and security helpers.
- `tests/` — one test file per router.

## Before going live

- Store users in a database with bcrypt/argon2 password hashes (not `.env`).
- Rate-limit `/api/auth/login`.
- Move to a JWT library and short-lived tokens with refresh.
