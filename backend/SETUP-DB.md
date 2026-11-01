# Database, Google sign-in, email codes and admin: setup

Merge the files from this update into your repo (same relative paths), then follow these steps.

## 1. Free cloud database (Neon Postgres)

1. Sign up at https://console.neon.tech (no card needed). Create a project; pick the region closest to Mumbai (Singapore if Mumbai is not offered).
2. Open the project, click **Connect**, copy the connection string. It looks like `postgresql://user:pass@ep-xxx.aws.neon.tech/neondb?sslmode=require`.
3. In `backend/` copy `.env.example` to `.env` and paste it as `DATABASE_URL`. The code converts it to the `psycopg` driver form itself.
4. Generate `SESSION_SECRET`: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
5. Install and create the tables:

```bash
cd backend
pip install -r requirements.txt
python -m app.db.init_db          # creates tables + the four plans
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
4. In `config.js` set `mode: "api"`, then open the site at **http://localhost:8000** (Google refuses `file://` pages).

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

## Forgot password, usernames and the live admin console

- **Forgot password:** the login page links to `forgot-password.html`. The user enters their email, gets a 6-digit code (same email setup as sign-up), enters it with a new password, and is sent back to log in. The answer is identical whether or not the email has an account, codes expire in 5 minutes, allow 5 tries, and a reset also clears a lockout. Old login tokens stay valid until they expire (8 hours); add token revocation before real users.
- **Usernames:** password sign-ups now ask for a date of birth (16+). When the email is verified the account gets a username: the initials of the name + the date of birth as DDMMYY, e.g. Zahid Salim Shaikh born 10 Jan 2001 gives `zss100101`. If someone has it, a number is added (`zss1001012`). People can log in with the email or the username. Google sign-ups add their date of birth on `complete-profile.html`, which then creates the username. A username never changes afterwards. Note that it contains the birth date.
- **Admin console:** Overview, Users & roles and Audit log read your real database through `/api/admin/*`. You cannot change, suspend or delete your own account, and only a superadmin can make someone an admin or change another admin. Deleting a user cannot be undone. Jobs & sources and Model quality show an empty state until those features exist. To add another admin: they sign up, then a superadmin sets their role to Admin, or run `python -m app.db.promote_admin their@email.com`.

## Upgrading a database

The API now upgrades the database itself every time it starts (it adds `users.date_of_birth` and lets `otp_codes` hold password-reset codes). It never touches your users, admins or audit log. To run it by hand and see what it did:

```bash
python -m app.db.upgrade
```

## Upgrading a database created by the very first (phone OTP) version

Your Neon database already has the old `otp_codes` table (phone based) and a unique phone constraint. Run once from `backend/`:

```bash
python -m app.db.migrate_email_otp
```

It keeps your users, admin and audit log. It is safe to run twice. Then delete the unused `app/services/sms.py`.

## 4. Tests

```bash
pip install -r requirements-dev.txt
pytest -q          # 47 tests, no database or network needed
```

## 5. Before real users

- Rate-limit by IP (per-account lockout and OTP caps already exist).
- Behind a proxy, read the real client IP from `X-Forwarded-For` for audit logs.
- Add refresh tokens, or move to a JWT library.
- Switch from `init_db` to Alembic migrations once the schema changes under real data.
- Revoke login tokens on password reset and suspension (today they simply expire after 8 hours; suspension is already checked on every request).
