# Setup: database, Google sign-in, email codes, AI key and your first admin

Do these once, in order. Everything is free to start.

## 1. Free cloud database (Neon Postgres)

1. Sign up at https://console.neon.tech (no card needed). Create a project; pick the region closest to Mumbai (Singapore if Mumbai is not offered).
2. Open the project, click **Connect**, copy the connection string. It looks like `postgresql://user:pass@ep-xxx.aws.neon.tech/neondb?sslmode=require`.
3. In `backend/` copy `.env.example` to `.env` and paste it as `DATABASE_URL`. The code converts it to the `psycopg` driver form itself.
4. Generate `SESSION_SECRET`: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
5. Install and create the tables:

```bash
cd backend
pip install -r requirements.txt
python -m app.db.init_db          # creates every table and the four plans
```

6. Create your admin (set `ADMIN_EMAIL` and a 12+ character `ADMIN_PASSWORD` in `.env` first):

```bash
python -m app.db.seed_admin       # then delete ADMIN_PASSWORD from .env
```

7. Start the app and check `http://localhost:8000/api/health`: `"database": "ok"` means you are connected.

```bash
uvicorn app.main:app --reload
```

Free-tier behaviour to know: Neon suspends compute after about 5 minutes idle, so the first request after a pause can take a few seconds. The code reconnects automatically. `db/schema.sql` holds the same tables as plain SQL if you prefer the Neon SQL editor.

## 2. Google sign-in

1. https://console.cloud.google.com -> create a project -> **APIs & Services -> OAuth consent screen** (External, add yourself as a test user while in Testing mode).
2. **Credentials -> Create credentials -> OAuth client ID -> Web application**. Under **Authorized JavaScript origins** add `http://localhost:8000` (and `http://127.0.0.1:8000` if you use it). No redirect URI is needed.
3. Copy the client ID into `GOOGLE_CLIENT_ID` in `backend/.env` and into `googleClientId` in `frontend/assets/js/config.js`. It is not a secret.
4. In `config.js` keep `mode: "api"`, then open the site at **http://localhost:8000** (Google refuses `file://` pages).

## 3. Email codes (free) and the optional phone

New accounts verify their **email** with a 6-digit code. Google users are already verified. A phone number is just an optional profile field (page: `complete-profile.html`); no SMS is ever sent.

- `EMAIL_PROVIDER=console` (default): the code is printed in the terminal running uvicorn as `[DEV EMAIL CODE] you@example.com: 123456`. Free, nothing to set up, good for testing.
- `EMAIL_PROVIDER=smtp`: real emails. Free option: Gmail with an app password.
  1. Google Account -> Security -> turn on 2-Step Verification.
  2. Security -> App passwords -> create one called "Hiriq" -> copy the 16 characters.
  3. In `backend/.env`:
     ```
     EMAIL_PROVIDER=smtp
     SMTP_HOST=smtp.gmail.com
     SMTP_PORT=587
     SMTP_USER=you@gmail.com
     SMTP_PASSWORD=<the 16-character app password>
     SMTP_FROM=Hiriq <you@gmail.com>
     ```
  Gmail limits personal accounts to a few hundred emails a day and sends as your own address, so it suits early testing. For launch, switch to a service that sends from your own domain (Brevo, Resend and others all work through the same SMTP settings).
  If email does not arrive, run `python -m app.services.smtp_check you@example.com` from `backend/`. It tries each step and says which one fails.

## 4. AI (the JD writer, resume reader, matching second look and Ask the pool)

All four features go through one place, `app/services/llm.py`, using OpenRouter's free models.

1. Create a key at https://openrouter.ai/keys and put it in `backend/.env`:
   ```
   OPENROUTER_API_KEY=sk-or-...
   ```
2. Optional: `LLM_MODELS=primary-model,backup-model` (comma separated; the first is tried first) and `LLM_TIMEOUT_SECONDS=60`.
3. Restart the server. Without a key every AI feature says it is not set up; matching by rules, search by keywords and everything else still work.

Free models come and go. If "Write with AI" says the models are busy, run `python -m app.services.llm_check` from `backend/`. It lists the free models your key can see, tests the ones Hiriq uses, and prints OpenRouter's own error text. Then change `LLM_MODELS` in `.env`; no code change is needed. Also check https://openrouter.ai/settings/privacy: blocking free-model data policies makes every free model answer 404.

The admin console's **AI usage** page shows how the models are doing: attempts, success rate, speed, tokens, by feature and by model, with the latest failures. A retry, or the backup model after a failure, counts as its own attempt. No prompt or resume text is ever stored.

## 5. Admin accounts, usernames and password reset

- **Admin console:** Overview, Users & roles, AI usage and Audit log read your real database through `/api/admin/*`. You cannot change, suspend or delete your own account, and only a superadmin can make someone an admin or change another admin. Deleting a user cannot be undone. Jobs & sources and Model quality show an empty state until those features exist. To add another admin: they sign up, then a superadmin sets their role to Admin, or run `python -m app.db.promote_admin their@email.com`.
- **Usernames:** password sign-ups ask for a date of birth (16+). When the email is verified the account gets a username: the initials of the name + the date of birth as DDMMYY, e.g. Zahid Salim Shaikh born 10 Jan 2001 gives `zss100101`. If someone has it, a number is added (`zss1001012`). People can log in with the email or the username. Google sign-ups add their date of birth on `complete-profile.html`, which then creates the username. A username never changes afterwards. It contains the birth date.
- **Forgot password:** the login page links to `forgot-password.html`. The user enters their email, gets a 6-digit code, enters it with a new password, and is sent back to log in. The answer is identical whether or not the email has an account, codes expire in 5 minutes, allow 5 tries, and a reset also clears a lockout. Old login tokens stay valid until they expire (8 hours); add token revocation before real users.

## 6. Sample data (optional)

To see the recruiter dashboard filled in for a screenshot or a demo:

```bash
python -m app.db.seed_recruiter_demo your-recruiter@example.com            # add clearly labelled sample data
python -m app.db.seed_recruiter_demo your-recruiter@example.com --clear    # remove exactly that data again
```

The account must have the recruiter role. Sample rows are flagged, the Overview shows a "Sample data" banner while any exist, and `--clear` never touches your real jobs or candidates.

## Upgrading a database

The API upgrades the database itself every time it starts: it creates any missing table (including the recruiter tables), adds `users.date_of_birth`, and lets `otp_codes` hold password-reset codes. It never touches your users, admins or audit log. To run it by hand and see what it did:

```bash
python -m app.db.upgrade
```

If you change a model file, regenerate the plain-SQL copy with `python -m app.db.export_schema`.

## 7. Tests

```bash
pip install -r requirements-dev.txt
pytest -q          # no database or network needed
```

## 8. Before real users

- Rate-limit by IP (per-account lockout, code caps and per-feature AI limits already exist).
- Behind a proxy, read the real client IP from `X-Forwarded-For` for audit logs.
- Add refresh tokens, or move to a JWT library.
- Switch from `init_db` and `upgrade` to Alembic migrations once the schema changes under real data.
- Revoke login tokens on password reset and suspension (today they simply expire after 8 hours; suspension is already checked on every request).
- Rotate `SESSION_SECRET` and your database password if either was ever pasted into a chat, a screenshot or a commit.
