# backend/

FastAPI service for Hiriq. It also serves `../frontend`, so http://localhost:8000 runs the whole app.
Interactive docs: http://localhost:8000/docs. Setup (database, Google, email, AI key, admin): see `SETUP-DB.md`.

## Endpoints

Errors come back as `{"detail": {"code": "...", "message": "..."}}`. Someone else's job or candidate answers **404**, as if it did not exist.

**Public and account** (`/api`)

| Method | Path | What |
|---|---|---|
| GET | `/api/health` | status, version, database state, Google and email configuration |
| POST | `/api/auth/signup` | name, email, password, date of birth; emails a 6-digit code and returns a one-time `signup_token`. No account exists yet (the details wait in `pending_signups`) |
| POST | `/api/auth/signup/resend`, `/signup/verify-email` | resend the code; verify with `{email, code, token}` (the token from `/signup`), which creates the account and signs in |
| POST | `/api/auth/login` | email or username + password |
| POST | `/api/auth/password/forgot`, `/password/reset` | emailed code, then a new password |
| POST | `/api/auth/google` | sign in or sign up with a Google credential |
| PUT | `/api/auth/profile` | date of birth (creates the username), phone, designation, company |
| GET | `/api/auth/me` | who is signed in |

**Recruiter** (`/api/recruiter`, recruiter role)

| Method | Path | What |
|---|---|---|
| GET | `/overview` | every number on the Overview page |
| GET, POST | `/jobs` | list (`?status=`), create a draft |
| POST | `/jobs/generate` | write a JD from the form (nothing saved) |
| GET, PUT, DELETE | `/jobs/{id}` | read, edit (not while closed), delete a draft |
| POST | `/jobs/{id}/publish`, `/close`, `/clone` | open or reopen, close, copy |
| POST, GET | `/candidates` | upload one resume (raw file body, name in `X-Filename`); list the pool (`?q=&source=`) |
| GET, PUT, DELETE | `/candidates/{id}` | one candidate; correct the reader; remove your own upload |
| POST | `/jobs/{id}/match` | rank the pool against the job (rules only, instant; optional `weights`) |
| POST | `/jobs/{id}/match/review` | AI second look at the top candidates' skill gaps |
| GET | `/jobs/{id}/matches`, `/matches/{candidate_id}` | the stored ranking; one full explanation |
| GET, POST | `/jobs/{id}/pipeline` | the stage board; add candidates |
| PATCH, DELETE | `/jobs/{id}/pipeline/{candidate_id}` | move or annotate; take off the board |
| PUT | `/jobs/{id}/matches/{candidate_id}/feedback` | thumbs up (1), down (-1) or clear (0) |
| GET | `/applicants` | your jobs with how many people applied |
| GET | `/jobs/{id}/applicants` | who applied to one job (`?sort=new\|fit`), with fit score and pipeline stage |
| GET | `/jobs/{id}/applicants/{application_id}` | one application in full: contact details, the resume and letter sent, their message. Add them to the pipeline with `POST /jobs/{id}/pipeline` |
| POST | `/ask` | question about the pool, answered from the resumes with checked quotes |

**Candidate** (`/api/candidate`, candidate role)

| Method | Path | What |
|---|---|---|
| GET | `/me` | your profile, resume status and visibility |
| POST, DELETE | `/resume` | upload your resume (raw body, name in `X-Filename`; 10 AI reads/hour); remove it and your scores |
| PUT | `/profile` | correct what the reader got wrong |
| PUT | `/visibility` | `{visible}`: let recruiters find you (off by default) |
| GET | `/insights` | completeness, skills with evidence, experience, skills open jobs ask for |
| GET | `/jobs`, `/jobs/{id}` | open jobs only (`?q=`), with your stored fit |
| POST | `/jobs/match`, `/jobs/{id}/match` | score all open jobs / one job (rules only, standard weights) |
| POST | `/match/paste` | `{text}`: match a pasted job description (15 AI reads/hour, not stored) |
| POST | `/rewrite` | `{job_id}` or `{text}`: tailor your resume to a job. Only rewords your own lines; invented numbers or skills are dropped (rewrites, prep sets and letters share 12 a hour) |
| GET | `/versions`, `/versions/{id}` | your saved tailored resumes (up to 20) |
| PATCH, DELETE | `/versions/{id}` | rename, edit the text, or delete one |
| POST | `/prep` | `{job_id}` or `{text}`: likely interview questions tied to your resume lines, stories, gaps, questions to ask |
| GET, DELETE | `/preps`, `/preps/{id}` | saved prep sets (up to 20) |
| POST | `/letters` | `{job_id}` or `{text}`, `tone`: a cover letter from your resume (invented numbers or skills are dropped) |
| GET, PATCH, DELETE | `/letters`, `/letters/{id}` | saved letters (up to 20); rename or edit the text |
| GET | `/letters/{id}/pdf` | the letter as a PDF download |
| GET | `/recommendations` | open jobs ranked by your fit, with why and what is missing (`?min_score=&work_mode=&limit=`) |
| POST | `/jobs/{id}/apply` | `{version_id?, letter_id?, message?}`: apply to an open job. The recruiter gets a copy of the resume text you pick (uploaded or a tailored version), the letter, your message, your contact details and your fit score. 409 if you already applied |
| GET | `/applications` | your applications, newest first |
| DELETE | `/applications/{id}` | withdraw: the copy the recruiter had is deleted (removing your resume withdraws them all) |
| GET | `/external/status`, `/external` | outside job feed (JSearch): `?q=&location=&page=`; needs `RAPIDAPI_KEY`; shows which of your skills each post mentions |

**Admin** (`/api/admin`, admin role)

| Method | Path | What |
|---|---|---|
| GET | `/users` | all accounts and plans |
| PATCH, DELETE | `/users/{id}` | change role, status or plan; delete. Never your own account; only a superadmin touches admins |
| GET | `/overview?range=7d\|30d\|90d` | sign-ups, roles, system health, recent activity |
| GET | `/ai-usage?range=7d\|30d\|90d` | model attempts, success rate, speed, tokens, by feature and model, failures, top users |
| GET | `/audit` | the audit log (`?category=`) |

## Layout

- `app/routers/` - thin: validate input, call a service, return. One file per area.
- `app/services/` - the logic. See `app/services/__init__.py` for a map.
- `app/core/` - settings, token and password helpers, the `require_recruiter` / `require_admin` dependencies.
- `app/db/` - `models.py` (accounts), `recruiter_models.py` (jobs, candidates, matches, pipeline, AI log), `upgrade.py`
  (runs on every start), `init_db.py`, and the admin and demo scripts.
- `db/schema.sql` - generated by `python -m app.db.export_schema`. Re-run it whenever a model file changes.
- `tests/` - one test file per router or service. Run `pytest -q` from this folder.

## Useful commands (run from `backend/`)

```bash
python -m app.db.init_db                         # create tables
python -m app.db.upgrade                         # bring an existing database up to date (the API also does this on start)
python -m app.db.seed_admin                      # create the first admin
python -m app.db.promote_admin someone@x.com     # make an existing account an admin
python -m app.db.seed_recruiter_demo me@x.com    # sample jobs and candidates (add --clear to remove)
python -m app.db.export_schema                   # regenerate db/schema.sql
python -m app.services.smtp_check [to@x.com]     # find out why email is not sending
python -m app.services.llm_check                 # find out which AI models work for your key
```

## Before going live

- Rate-limit by IP (per-account lockout, code caps and per-feature AI limits already exist).
- Behind a proxy, read the real client IP from `X-Forwarded-For` for audit logs.
- Add refresh tokens, or move to a JWT library. (A password reset already signs out older sessions.)
- Move from `init_db` and `upgrade` to Alembic migrations once the schema changes under real data.
