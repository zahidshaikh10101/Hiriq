# Hiriq

Resume-to-job matching that explains itself: matched skills, gaps, and the next fix.
Three workspaces (candidate, recruiter, admin) on one matching engine.

> Stage: **initial**. The frontend design is built. The Python backend has a working admin login; the GenAI and ML parts come next.

## Repository layout

```
hiriq/
├── frontend/            Plain HTML, CSS and JavaScript. No build step, no Node.js.
│   ├── index.html       Landing page
│   ├── login.html       Google / email / phone (OTP) login
│   ├── signup.html      Candidate or recruiter sign-up
│   ├── admin.html       Admin console: overview, users, jobs, model, audit
│   └── assets/
│       ├── css/         base.css (tokens, fonts, animations), components.css, one file per page
│       ├── js/          config.js (mode switch), auth-client.js, effects.js, page scripts, mock-data.js
│       ├── img/         logos
│       └── fonts/       bundled fonts (work offline)
├── backend/             Python (FastAPI) API — also serves the frontend
│   ├── app/
│   │   ├── main.py      app entry point
│   │   ├── core/        settings, tokens
│   │   ├── routers/     HTTP endpoints (/api/health, /api/auth)
│   │   └── services/    business logic (parsing, matching, ranking … to build)
│   ├── tests/
│   └── requirements.txt
├── ml/                  evaluation set, notebooks, experiments for the ranker
└── data/                local data (git-ignored)
```

## 1. Run the frontend (nothing to install)

Double-click `frontend/index.html`. It opens in your browser and everything works offline.

**Demo admin login:** open `login.html` → Email tab → username `admin` and the password you chose.
In demo mode the check runs in the browser against a hash in `frontend/assets/js/config.js`.
That is a stand-in so the UI works today; it is not real security.

To change the demo password, put the SHA-256 hash of the new one in `config.js`. One way to make the hash
without installing anything: open any Hiriq page, press F12 → Console, and run
`HiriqAuth.sha256("your-new-password")` (on `login.html`, which loads the auth script).

## 2. Run the backend (needs Python 3.10+)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
copy .env.example .env          # Windows  (cp on macOS / Linux) — then edit .env
uvicorn app.main:app --reload
```

Open http://localhost:8000. The backend serves the frontend too, so one address runs everything.
API docs: http://localhost:8000/docs

To make the frontend use the backend for login, set `mode: "api"` in `frontend/assets/js/config.js`.

Run the tests: `pip install -r requirements-dev.txt` then `pytest -q`.

**Laptop won't let you install Python?** GitHub Codespaces gives you a full Linux environment with Python in the browser (free monthly allowance on personal accounts). Push this repo to GitHub, open it in a Codespace and run the backend steps there.

## Roadmap

| Phase | What | Where |
|---|---|---|
| 1 ✅ | Design: landing, auth, admin console | `frontend/` |
| 2 ✅ | Backend skeleton, admin login, health check | `backend/` |
| 3 | Resume + JD extraction with an LLM, validated by a Pydantic schema | `backend/app/services/parsing.py` |
| 4 | Matching engine: baseline → TF-IDF → embeddings → explanation | `services/matching.py`, `ml/` |
| 5 | Labeled evaluation set (100–150 resume–job pairs) and NDCG@5 table | `ml/` |
| 6 | Candidate dashboard: upload, score, skill gap, matched jobs | `frontend/candidate.html` |
| 7 | Job ingestion from sources, de-duplication, morning alerts | `services/jobs.py`, `services/alerts.py` |
| 8 | Recruiter dashboard + trained ranker (LightGBM) | `frontend/recruiter.html`, `services/ranking.py` |
| 9 | Replace mock data in the admin console with real API calls | `frontend/assets/js/admin.js` |

## Principles

- **Explain every score:** matched skills, missing skills, experience gap.
- **Sensitive fields stay out of scoring:** name, gender, photo and college are never features.
- **People decide:** Hiriq ranks and explains, and nothing is auto-rejected.
- **Honest numbers:** every metric shown comes from a real evaluation, or is labelled as a placeholder.
