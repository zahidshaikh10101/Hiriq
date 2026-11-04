"""Business logic lives here (one module per area).

Accounts:  phone.py (number cleanup), otp.py (emailed codes), emailer.py, google_auth.py, username.py, audit.py,
           timeutil.py. smtp_check.py is a diagnostic you run by hand.
AI layer:  llm.py is the one place that calls the language model (OpenRouter) and logs each attempt to `ai_calls`.
           llm_check.py is a diagnostic you run by hand.
Recruiter: resume_text.py + resume.py (read a resume into a profile), jd.py (write and check a job description),
           matching.py (the explained score, pure rules), retrieval.py (keyword search behind "Ask the pool").
Planned:   job ingestion, alerts, and the trained ranker.
"""
