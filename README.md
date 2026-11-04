# Hiriq

Resume-to-job matching that explains itself: matched skills, gaps, and the next fix.
Three workspaces (candidate, recruiter, admin) on one matching engine.

> Stage: **recruiter workspace and admin console are built and run on real data.** The candidate workspace, job
> ingestion with morning alerts, and the trained ranker are still to come (see the roadmap).

## What works today

| Area | What you can do |
|---|---|
| Accounts | Sign up with email + emailed code, or Google. Forgot password. Usernames. Admin-only roles. |
| Recruiter: Overview | Open jobs, pool size, funnel, match quality and skills in demand, all from your own data. |
| Recruiter: Jobs | Create jobs, write the JD with AI (editable), publish, close, clone. |
| Recruiter: Candidates | Upload resumes (PDF, DOCX); the AI reads them into editable profiles. The pool is your uploads plus active Hiriq members. |
| Recruiter: Matching | Rank the pool against a job. Five weighted parts (skills 40, qualification 20, experience 30, location 5, keywords 5 by default, adjustable per run), each explained. Optional AI second look at skill gaps. |
| Recruiter: Pipeline | Stage board per job (sourced to hired, plus a rejected lane), notes, thumbs up/down on a match. |
| Recruiter: Ask the pool | Ask a question in plain English, get an answer quoted from the resumes. Questions that filter by gender, age, religion, caste, nationality, marital status or disability are refused. |
| Admin | Overview, Users and roles, AI usage (attempts, success rate, speed, tokens, by feature and model), Audit log. |

## Repository layout

```
hiriq/
├── frontend/            Plain HTML, CSS and JavaScript. No build step, no Node.js.
│   ├── index.html, login.html, signup.html, forgot-password.html, complete-profile.html
│   ├── recruiter.html   Recruiter workspace (Overview, Jobs, Candidates, Matching, Pipeline, Ask)
│   ├── admin.html       Admin console (Overview, Users, AI usage, Jobs, Model quality, Audit log)
│   └── assets/
│       ├── css/         base.css (tokens, fonts), components.css, one file per page or workspace
│       ├── js/          config.js, auth-client.js, effects.js, one script per page or recruiter section
│       ├── img/         logos
│       └── fonts/       bundled fonts (work offline)
├── backend/             Python (FastAPI) API. It also serves the frontend.
│   ├── app/
│   │   ├── main.py      app entry point
│   │   ├── core/        settings, tokens, auth dependencies
│   │   ├── db/          models, sessions, upgrade, seed and admin scripts
│   │   ├── routers/     HTTP endpoints (see backend/README.md)
│   │   └── services/    the logic: resume reader, matching, retrieval, LLM layer, email, audit
│   ├── db/schema.sql    the same tables as plain SQL (generated)
│   └── tests/
├── ml/                  evaluation plan and experiments for the ranker
└── data/                local data (git-ignored)
```

## Run it (needs Python 3.10+)

The frontend talks to the backend for login, the recruiter workspace and the admin console, so run both together:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
copy .env.example .env          # Windows  (cp on macOS / Linux) - then edit .env
python -m app.db.init_db        # creates the tables
uvicorn app.main:app --reload
```

Open http://localhost:8000. One address runs everything. API docs: http://localhost:8000/docs.

Database (Neon), Google sign-in, email codes, the AI key and your first admin are explained step by step in
[`backend/SETUP-DB.md`](backend/SETUP-DB.md).

Run the tests: `pip install -r requirements-dev.txt`, then `pytest -q` from `backend/`. No database or network is needed.

`frontend/assets/js/config.js` has a `mode` switch. Leave it on `"api"`. The old `"demo"` mode only previews the login
and sign-up pages without a backend; the workspaces need the API.

**Laptop won't let you install Python?** GitHub Codespaces gives you a Linux environment with Python in the browser.
Push this repo to GitHub, open it in a Codespace and run the steps above there.

## Roadmap

| Step | What | Status |
|---|---|---|
| Design | Landing, auth, admin console, recruiter workspace | done |
| Accounts | Database, Google and email-code sign-up, admin console on real data | done |
| Recruiter workspace | Overview, jobs and JD writer, candidates and resume reader, matching, pipeline, ask the pool | done |
| Admin AI usage | Cost and reliability of the free models, by feature and model | done |
| Candidate workspace | Upload a resume, score it against a job, skill gaps, relevant jobs | next |
| Job ingestion and alerts | Postings from sources, de-duplication, morning alerts | planned |
| Evaluation set | 100-150 labelled resume-job pairs and an NDCG@5 table (see `ml/README.md`) | planned |
| Trained ranker | Learn from recruiter thumbs and the labelled set | planned |

## Principles

- **Explain every score:** matched skills, missing skills, experience gap, with the evidence quoted.
- **Sensitive fields stay out of scoring:** name, gender, photo and college are never features.
- **People decide:** Hiriq ranks and explains, and nothing is auto-rejected or auto-moved.
- **Honest numbers:** every metric shown comes from real data, or the page shows an empty state. No invented figures.
- **No resume text in logs:** the AI usage log keeps model, time and token counts only.
