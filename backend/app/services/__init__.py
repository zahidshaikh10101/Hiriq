"""Business logic lives here (one module per area).

Accounts:  phone.py (number cleanup), otp.py (emailed codes), emailer.py, google_auth.py, username.py, audit.py,
           timeutil.py. smtp_check.py is a diagnostic you run by hand.
AI layer:  llm.py is the one place that calls the language model (OpenRouter) and logs each attempt to `ai_calls`.
           llm_check.py is a diagnostic you run by hand.
Recruiter: resume_text.py + resume.py (read a resume into a profile), jd.py (write and check a job description),
           matching.py (the explained score, pure rules), retrieval.py (keyword search behind "Ask the pool").
Outside jobs: sources/ (Google Jobs scraper and Indeed via RapidAPI behind one Source shape, chosen by JOB_SOURCES),
           externaljobs.py (the RapidAPI call and its caps), externalstore.py (saving posts into external_jobs, deduped),
           postingread.py (rules read of skills, years and degree), jobkeys.py (dedupe keys), prefs.py (fetch after a save).
Planned:   alerts and the trained ranker.
"""
