"""Database-backed auth: sign-up with an emailed code, Google, lockout, profile, admin.  Uses a throwaway SQLite file."""
import importlib
from datetime import timedelta

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

EMAIL = "ann@example.com"
PHONE = "+919820011234"
PW = "Correct-horse-9"

RELOAD = [
    "app.core.config", "app.db.session", "app.db.init_db", "app.services.emailer", "app.services.otp",
    "app.services.google_auth", "app.core.deps", "app.routers.health", "app.routers.auth", "app.routers.admin", "app.main",
]


class Env:
    pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k, v in {
        "DATABASE_URL": f"sqlite:///{tmp_path / 'test.db'}", "SESSION_SECRET": "x" * 40, "ADMIN_PASSWORD": "",
        "EMAIL_PROVIDER": "console", "GOOGLE_CLIENT_ID": "test-client", "OTP_RESEND_SECONDS": "0",
        "MAX_FAILED_LOGINS": "5", "OTP_MAX_ATTEMPTS": "3",
    }.items():
        monkeypatch.setenv(k, v)
    mods = {}
    for name in RELOAD:
        mods[name] = importlib.reload(importlib.import_module(name))
    e = Env()
    e.mods = mods
    e.auth = mods["app.routers.auth"]
    e.session = mods["app.db.session"]
    mods["app.db.init_db"].init_db()
    e.codes = {}
    monkeypatch.setattr(e.auth, "send_otp_email", lambda to, code, purpose="signup": e.codes.__setitem__(to, code))
    e.google = {"sub": "g-1", "email": EMAIL, "name": "Ann Lee"}
    monkeypatch.setattr(e.auth, "verify_google_credential", lambda cred: dict(e.google))
    e.client = TestClient(mods["app.main"].app)
    return e


def signup(e, email=EMAIL, password=PW, **kw):
    body = {"name": "Ann Lee", "email": email, "password": password, "role": "candidate", "consent": True, "dob": "2001-01-10"}
    body.update(kw)
    return e.client.post("/api/auth/signup", json=body)


def complete_signup(e, email=EMAIL, **kw):
    assert signup(e, email=email, **kw).status_code == 200
    r = e.client.post("/api/auth/signup/verify-email", json={"email": email, "code": e.codes[email]})
    assert r.status_code == 200, r.text
    return r.json()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def user_row(e, **where):
    from sqlalchemy import select
    from app.db.models import User
    with e.session.SessionLocal() as db:
        return db.scalar(select(User).filter_by(**where))


# ---------- signup + email code ----------
def test_signup_verify_and_me(env):
    out = complete_signup(env)
    assert out["role"] == "candidate" and out["access_token"] and out["needs_phone"] is True
    me = env.client.get("/api/auth/me", headers=auth(out["access_token"])).json()
    assert me["email"] == EMAIL and me["email_verified"] is True and me["plan"] == "free"


def test_signup_with_optional_phone_is_stored_unverified(env):
    out = complete_signup(env, phone="+91 98200 11234")
    assert out["needs_phone"] is False
    u = user_row(env, email=EMAIL)
    assert u.phone_e164 == PHONE and u.phone_verified is False


def test_signup_validation(env):
    assert signup(env, consent=False).json()["detail"]["code"] == "consent_required"
    assert signup(env, password="short").json()["detail"]["code"] == "weak_password"
    assert signup(env, email="nope").json()["detail"]["code"] == "bad_email"
    assert signup(env, phone="+91123").json()["detail"]["code"] == "bad_phone"
    assert signup(env, phone="9820011234").json()["detail"]["code"] == "bad_phone"


def test_cannot_log_in_before_verifying_email(env):
    assert signup(env).status_code == 200
    r = env.client.post("/api/auth/login", json={"username": EMAIL, "password": PW})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "not_verified"


def test_wrong_code_attempts_are_limited(env):
    signup(env)
    good = env.codes[EMAIL]
    wrong = "000000" if good != "000000" else "111111"
    for _ in range(3):
        assert env.client.post("/api/auth/signup/verify-email", json={"email": EMAIL, "code": wrong}).status_code == 400
    r = env.client.post("/api/auth/signup/verify-email", json={"email": EMAIL, "code": good})
    assert r.status_code == 429  # locked out even with the right code


def test_expired_code_rejected(env):
    from sqlalchemy import update
    from app.db.models import OtpCode
    from app.services.timeutil import now
    signup(env)
    with env.session.SessionLocal() as db:
        db.execute(update(OtpCode).values(expires_at=now() - timedelta(seconds=1)))
        db.commit()
    r = env.client.post("/api/auth/signup/verify-email", json={"email": EMAIL, "code": env.codes[EMAIL]})
    assert r.status_code == 400 and "expired" in r.json()["detail"]["message"]


def test_resend_issues_a_fresh_code_and_old_one_stops_working(env):
    signup(env)
    old = env.codes[EMAIL]
    env.codes.clear()
    assert env.client.post("/api/auth/signup/resend", json={"email": EMAIL}).status_code == 200
    new = env.codes[EMAIL]
    if new != old:
        assert env.client.post("/api/auth/signup/verify-email", json={"email": EMAIL, "code": old}).status_code == 400
    assert env.client.post("/api/auth/signup/verify-email", json={"email": EMAIL, "code": new}).status_code == 200


def test_resend_for_unknown_email_reveals_nothing(env):
    r = env.client.post("/api/auth/signup/resend", json={"email": "ghost@example.com"})
    assert r.status_code == 200 and "ghost@example.com" not in env.codes


def test_unverified_signup_can_be_restarted_but_verified_cannot_be_taken(env):
    assert signup(env).status_code == 200
    assert signup(env, password="Another-pass-1").status_code == 200  # abandoned signup restarted
    complete_signup(env)
    r = signup(env)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "account_exists"


def test_password_login_and_lockout(env):
    complete_signup(env)
    ok = env.client.post("/api/auth/login", json={"username": "ANN@example.com", "password": PW})
    assert ok.status_code == 200 and ok.json()["name"] == "Ann Lee"
    for _ in range(5):
        assert env.client.post("/api/auth/login", json={"username": EMAIL, "password": "wrong-pass"}).status_code == 401
    r = env.client.post("/api/auth/login", json={"username": EMAIL, "password": PW})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "locked"
    from sqlalchemy import select
    from app.db.models import AuditLog
    with env.session.SessionLocal() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action.like("was blocked after%"))) is not None


def test_unknown_user_gets_same_error(env):
    r = env.client.post("/api/auth/login", json={"username": "ghost@example.com", "password": "whatever-1"})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "bad_credentials"


def test_same_phone_on_two_accounts_is_allowed_since_it_is_unverified(env):
    complete_signup(env, email="a@example.com", phone=PHONE)
    complete_signup(env, email="b@example.com", phone=PHONE)


# ---------- Google ----------
def test_google_signup_needs_consent_and_login_needs_account(env):
    r = env.client.post("/api/auth/google", json={"credential": "t", "mode": "login"})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "no_account"
    r = env.client.post("/api/auth/google", json={"credential": "t", "mode": "signup", "consent": False})
    assert r.status_code == 422
    r = env.client.post("/api/auth/google", json={"credential": "t", "mode": "signup", "consent": True, "role": "recruiter"})
    assert r.status_code == 200 and r.json()["role"] == "recruiter" and r.json()["needs_phone"] is True
    again = env.client.post("/api/auth/google", json={"credential": "t", "mode": "login"})
    assert again.status_code == 200


def test_google_never_creates_admin(env):
    r = env.client.post("/api/auth/google", json={"credential": "t", "mode": "signup", "consent": True, "role": "admin"})
    assert r.status_code == 422


def test_google_link_wipes_unverified_signup_password(env):
    # attacker signs up with the victim's email (never verifies), victim then uses Google
    assert signup(env).status_code == 200
    r = env.client.post("/api/auth/google", json={"credential": "t", "mode": "login"})
    assert r.status_code == 200
    u = user_row(env, email=EMAIL)
    assert u.password_hash is None and u.email_verified is True
    assert env.client.post("/api/auth/login", json={"username": EMAIL, "password": PW}).status_code == 401


def test_google_failure_is_reported(env, monkeypatch):
    from app.services.google_auth import GoogleAuthError

    def boom(_):
        raise GoogleAuthError("nope")

    monkeypatch.setattr(env.auth, "verify_google_credential", boom)
    assert env.client.post("/api/auth/google", json={"credential": "t"}).status_code == 401


# ---------- complete profile (phone) ----------
def test_google_user_completes_profile_with_phone(env):
    out = env.client.post("/api/auth/google", json={"credential": "t", "mode": "signup", "consent": True}).json()
    assert out["needs_phone"] is True
    r = env.client.put("/api/auth/profile", headers=auth(out["access_token"]),
                       json={"phone": "+91 98200 11234", "designation": " Data Analyst ", "company": "Acme"})
    assert r.status_code == 200
    body = r.json()
    assert body["phone"] == PHONE and body["designation"] == "Data Analyst" and body["company"] == "Acme"
    again = env.client.post("/api/auth/google", json={"credential": "t", "mode": "login"}).json()
    assert again["needs_phone"] is False


def test_profile_validates_and_requires_login(env):
    out = complete_signup(env)
    h = auth(out["access_token"])
    assert env.client.put("/api/auth/profile", headers=h, json={"phone": "12345"}).json()["detail"]["code"] == "bad_phone"
    assert env.client.put("/api/auth/profile", json={"phone": PHONE}).status_code == 401
    cleared = env.client.put("/api/auth/profile", headers=h, json={"phone": ""})
    assert cleared.status_code == 200 and "phone" not in cleared.json()


# ---------- suspension + admin ----------
def test_suspended_user_loses_access_immediately(env):
    out = complete_signup(env)
    h = auth(out["access_token"])
    assert env.client.get("/api/auth/me", headers=h).status_code == 200
    from app.db.models import User
    from sqlalchemy import select
    with env.session.SessionLocal() as db:
        db.scalar(select(User).filter_by(email=EMAIL)).status = "suspended"
        db.commit()
    assert env.client.get("/api/auth/me", headers=h).status_code == 401
    r = env.client.post("/api/auth/login", json={"username": EMAIL, "password": PW})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "suspended"


def test_admin_seed_login_and_guard(env, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "boss@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "a-very-long-admin-pass")
    seed = importlib.reload(importlib.import_module("app.db.seed_admin"))
    assert "created" in seed.seed_admin()
    assert "updated" in seed.seed_admin()  # idempotent

    r = env.client.post("/api/auth/login", json={"username": "admin", "password": "a-very-long-admin-pass"})
    assert r.status_code == 200 and r.json()["role"] == "admin"
    admin_h = auth(r.json()["access_token"])

    deps = env.mods["app.core.deps"]
    app = env.mods["app.main"].app
    app.add_api_route("/api/_admin_only", lambda user=Depends(deps.require_admin): {"ok": True}, methods=["GET"])
    app.router.routes.insert(0, app.router.routes.pop())  # ahead of the static-files mount at "/"
    assert env.client.get("/api/_admin_only", headers=admin_h).status_code == 200

    cand = complete_signup(env)
    assert env.client.get("/api/_admin_only", headers=auth(cand["access_token"])).status_code == 403
    assert env.client.get("/api/_admin_only").status_code == 401


def test_schema_has_expected_tables(env):
    from sqlalchemy import inspect
    names = set(inspect(env.session.engine).get_table_names())
    assert {"users", "auth_identities", "otp_codes", "admin_profiles", "admin_invites", "audit_logs", "plans"} <= names
    cols = {c["name"] for c in inspect(env.session.engine).get_columns("otp_codes")}
    assert "destination" in cols and "phone_e164" not in cols


def test_migration_upgrades_an_old_database(env):
    """Simulate the earlier phone-OTP database, then run the migration."""
    from sqlalchemy import inspect, text
    eng = env.session.engine
    with eng.begin() as c:
        c.execute(text("DROP TABLE otp_codes"))
        c.execute(text("CREATE TABLE otp_codes (id CHAR(32) PRIMARY KEY, purpose VARCHAR(20), phone_e164 VARCHAR(20))"))
    mig = importlib.reload(importlib.import_module("app.db.migrate_email_otp"))
    mig.migrate()
    mig.migrate()  # safe to repeat
    assert "destination" in {c["name"] for c in inspect(eng).get_columns("otp_codes")}


# ================= forgot password =================
def ask_reset(e, email=EMAIL):
    return e.client.post("/api/auth/password/forgot", json={"email": email})


def do_reset(e, code, new="Brand-new-pass-7", email=EMAIL):
    return e.client.post("/api/auth/password/reset", json={"email": email, "code": code, "new_password": new})


def test_forgot_password_full_flow(env):
    complete_signup(env)
    env.codes.clear()
    r = ask_reset(env)
    assert r.status_code == 200 and r.json()["status"] == "code_sent"
    code = env.codes[EMAIL]
    assert do_reset(env, code).status_code == 200
    # old password gone, new one works, code cannot be reused
    assert env.client.post("/api/auth/login", json={"username": EMAIL, "password": PW}).status_code == 401
    assert env.client.post("/api/auth/login", json={"username": EMAIL, "password": "Brand-new-pass-7"}).status_code == 200
    assert do_reset(env, code).status_code == 400


def test_forgot_password_does_not_reveal_which_emails_exist(env):
    complete_signup(env)
    env.codes.clear()
    known = ask_reset(env)
    unknown = ask_reset(env, "ghost@example.com")
    assert known.status_code == unknown.status_code == 200
    assert set(known.json()) == set(unknown.json())
    assert "ghost@example.com" not in env.codes  # nothing is sent to unknown addresses


def test_forgot_password_sends_nothing_for_unverified_or_suspended(env):
    signup(env)  # never verified
    env.codes.clear()
    assert ask_reset(env).status_code == 200 and EMAIL not in env.codes
    complete_signup(env, email="b@example.com")
    from sqlalchemy import select
    from app.db.models import User
    with env.session.SessionLocal() as db:
        db.scalar(select(User).filter_by(email="b@example.com")).status = "suspended"
        db.commit()
    env.codes.clear()
    ask_reset(env, "b@example.com")
    assert "b@example.com" not in env.codes


def test_reset_code_attempts_are_limited_and_weak_password_rejected(env):
    complete_signup(env)
    env.codes.clear()
    ask_reset(env)
    good = env.codes[EMAIL]
    wrong = "000000" if good != "000000" else "111111"
    assert do_reset(env, good, new="short").json()["detail"]["code"] == "weak_password"  # does not burn the code
    for _ in range(3):
        assert do_reset(env, wrong).status_code == 400
    assert do_reset(env, good).status_code == 429  # locked out of this code


def test_reset_clears_a_lockout_and_works_for_google_only_accounts(env):
    complete_signup(env)
    for _ in range(5):
        env.client.post("/api/auth/login", json={"username": EMAIL, "password": "wrong-pass-1"})
    assert env.client.post("/api/auth/login", json={"username": EMAIL, "password": PW}).status_code == 429
    env.codes.clear()
    ask_reset(env)
    assert do_reset(env, env.codes[EMAIL]).status_code == 200
    assert env.client.post("/api/auth/login", json={"username": EMAIL, "password": "Brand-new-pass-7"}).status_code == 200
    # Google-only account can set a password this way
    env.google.update(email="g@example.com", sub="g-9", name="Gina Park")
    env.client.post("/api/auth/google", json={"credential": "x", "mode": "signup", "consent": True})
    env.codes.clear()
    ask_reset(env, "g@example.com")
    assert do_reset(env, env.codes["g@example.com"], email="g@example.com").status_code == 200
    assert env.client.post("/api/auth/login", json={"username": "g@example.com", "password": "Brand-new-pass-7"}).status_code == 200


def test_a_reset_code_cannot_finish_a_signup(env):
    signup(env)
    env.codes.clear()
    # unverified: forgot sends nothing, so there is no reset code at all
    ask_reset(env)
    assert EMAIL not in env.codes
    # even a real reset code (other account) is rejected by the signup verifier
    complete_signup(env, email="c@example.com")
    env.codes.clear()
    ask_reset(env, "c@example.com")
    r = env.client.post("/api/auth/signup/verify-email", json={"email": "c@example.com", "code": env.codes["c@example.com"]})
    assert r.status_code == 400


def test_a_password_reset_signs_out_sessions_opened_before_it(env):
    old = complete_signup(env)["access_token"]
    assert env.client.get("/api/auth/me", headers=auth(old)).status_code == 200
    env.codes.clear()
    ask_reset(env)
    assert do_reset(env, env.codes[EMAIL]).status_code == 200
    assert env.client.get("/api/auth/me", headers=auth(old)).status_code == 401
    fresh = env.client.post("/api/auth/login", json={"username": EMAIL, "password": "Brand-new-pass-7"}).json()["access_token"]
    assert env.client.get("/api/auth/me", headers=auth(fresh)).status_code == 200


def test_the_lockout_reply_is_the_same_for_known_and_unknown_emails(env):
    complete_signup(env)

    def hammer(ident):
        out = []
        for _ in range(7):
            r = env.client.post("/api/auth/login", json={"username": ident, "password": "wrong-pass-1"})
            out.append((r.status_code, r.json()["detail"]["code"]))
        return out

    assert hammer(EMAIL) == hammer("nobody-here@example.com")


# ================= usernames =================
def test_username_is_initials_plus_dob_and_works_for_login(env):
    out = complete_signup(env, name="Zahid Salim Shaikh", dob="2001-01-10")
    me = env.client.get("/api/auth/me", headers=auth(out["access_token"])).json()
    assert me["username"] == "zss100101" and me["dob"] == "2001-01-10"
    assert env.client.post("/api/auth/login", json={"username": "ZSS100101", "password": PW}).status_code == 200


def test_username_collisions_get_a_number(env):
    complete_signup(env, email="a1@example.com", name="Ann Lee", dob="2000-05-04")
    complete_signup(env, email="a2@example.com", name="Amy Lim", dob="2000-05-04")
    complete_signup(env, email="a3@example.com", name="Ava Lo", dob="2000-05-04")
    names = sorted(user_row(env, email=e).username for e in ("a1@example.com", "a2@example.com", "a3@example.com"))
    assert names == ["al040500", "al0405002", "al0405003"]


def test_username_edge_cases():
    import importlib
    u = importlib.import_module("app.services.username")
    assert u.initials("Zoë van der Berg") == "zvdb"
    assert u.initials("  madonna ") == "m"
    assert u.initials("李 雷") == "u"          # no latin letters: neutral fallback
    assert u.initials("A B C D E F") == "abcd"  # at most 4


def test_dob_is_validated(env):
    assert signup(env, dob="not-a-date").json()["detail"]["code"] == "bad_dob"
    assert signup(env, dob="2999-01-01").json()["detail"]["code"] == "bad_dob"
    assert signup(env, dob="1850-01-01").json()["detail"]["code"] == "bad_dob"
    from datetime import date
    too_young = date.today().replace(year=date.today().year - 10).isoformat()
    assert signup(env, dob=too_young).json()["detail"]["code"] == "too_young"


def test_google_user_gets_username_when_they_add_dob_and_it_never_changes(env):
    r = env.client.post("/api/auth/google", json={"credential": "x", "mode": "signup", "consent": True})
    assert r.json()["needs_profile"] is True
    h = auth(r.json()["access_token"])
    assert env.client.get("/api/auth/me", headers=h).json().get("username") is None
    me = env.client.put("/api/auth/profile", headers=h, json={"dob": "1999-12-31"}).json()
    assert me["username"] == "al311299"
    me = env.client.put("/api/auth/profile", headers=h, json={"dob": "1990-01-01"}).json()
    assert me["username"] == "al311299" and me["dob"] == "1990-01-01"  # handle stays stable


def test_needs_profile_until_phone_and_dob_present(env):
    out = complete_signup(env)
    assert out["needs_profile"] is True and out["needs_phone"] is True
    h = auth(out["access_token"])
    env.client.put("/api/auth/profile", headers=h, json={"phone": PHONE})
    again = env.client.post("/api/auth/login", json={"username": EMAIL, "password": PW}).json()
    assert again["needs_profile"] is False


# ================= admin API =================
def make_admin(env, email, username=None, superadmin=True):
    from app.core.security import hash_password
    from app.db.models import AdminProfile, User
    with env.session.SessionLocal() as db:
        u = User(email=email, username=username, full_name=email.split("@")[0], role="admin", email_verified=True,
                 password_hash=hash_password(PW))
        db.add(u)
        db.flush()
        db.add(AdminProfile(user_id=u.id, is_superadmin=superadmin, permissions=[]))
        db.commit()
        return str(u.id)


def token_for(env, ident):
    return env.client.post("/api/auth/login", json={"username": ident, "password": PW}).json()["access_token"]


def test_admin_api_needs_an_admin(env):
    assert env.client.get("/api/admin/users").status_code == 401
    cand = complete_signup(env)
    assert env.client.get("/api/admin/users", headers=auth(cand["access_token"])).status_code == 403
    assert env.client.get("/api/admin/overview", headers=auth(cand["access_token"])).status_code == 403
    assert env.client.get("/api/admin/audit", headers=auth(cand["access_token"])).status_code == 403


def test_admin_lists_real_users(env):
    make_admin(env, "root@example.com", "root")
    complete_signup(env)
    h = auth(token_for(env, "root"))
    data = env.client.get("/api/admin/users", headers=h).json()
    assert {u["email"] for u in data["users"]} == {"root@example.com", EMAIL}
    me_row = next(u for u in data["users"] if u["email"] == "root@example.com")
    assert me_row["you"] is True and me_row["locked"] is True and me_row["role"] == "admin"
    assert next(p for p in data["plans"] if p["id"] == "free")["live"] is True
    assert data["you_are_superadmin"] is True
    assert "password_hash" not in str(data)


def test_admin_changes_role_suspends_and_deletes(env):
    make_admin(env, "root@example.com", "root")
    cand = complete_signup(env)
    uid = user_row(env, email=EMAIL).id
    h = auth(token_for(env, "root"))
    r = env.client.patch(f"/api/admin/users/{uid}", headers=h, json={"role": "recruiter"})
    assert r.status_code == 200 and r.json()["role"] == "recruiter"
    r = env.client.patch(f"/api/admin/users/{uid}", headers=h, json={"status": "suspended"})
    assert r.json()["status"] == "Suspended"
    assert env.client.get("/api/auth/me", headers=auth(cand["access_token"])).status_code == 401  # token dies at once
    env.client.patch(f"/api/admin/users/{uid}", headers=h, json={"status": "active"})
    assert env.client.get("/api/auth/me", headers=auth(cand["access_token"])).status_code == 200
    assert env.client.delete(f"/api/admin/users/{uid}", headers=h).status_code == 200
    assert user_row(env, email=EMAIL) is None
    events = env.client.get("/api/admin/audit", headers=h).json()["events"]
    text = " | ".join(e["actor"] + " " + e["action"] for e in events)
    assert "changed" in text and "suspended" in text and "reactivated" in text and "deleted" in text


def test_admin_cannot_touch_self_and_only_superadmin_manages_admins(env):
    root = make_admin(env, "root@example.com", "root", superadmin=True)
    plain = make_admin(env, "plain@example.com", "plain", superadmin=False)
    h_root, h_plain = auth(token_for(env, "root")), auth(token_for(env, "plain"))
    assert env.client.patch(f"/api/admin/users/{root}", headers=h_root, json={"status": "suspended"}).status_code == 403
    assert env.client.delete(f"/api/admin/users/{root}", headers=h_root).status_code == 403
    # a normal admin cannot manage another admin, nor create admins
    assert env.client.patch(f"/api/admin/users/{root}", headers=h_plain, json={"status": "suspended"}).status_code == 403
    complete_signup(env)
    uid = user_row(env, email=EMAIL).id
    assert env.client.patch(f"/api/admin/users/{uid}", headers=h_plain, json={"role": "admin"}).status_code == 403
    # a superadmin can, and the new admin gets an admin profile
    r = env.client.patch(f"/api/admin/users/{uid}", headers=h_root, json={"role": "admin"})
    assert r.status_code == 200 and r.json()["role"] == "admin"
    assert env.client.patch(f"/api/admin/users/{plain}", headers=h_root, json={"role": "candidate"}).status_code == 200


def test_admin_plan_rules_and_unknown_user(env):
    make_admin(env, "root@example.com", "root")
    complete_signup(env)
    uid = user_row(env, email=EMAIL).id
    h = auth(token_for(env, "root"))
    assert env.client.patch(f"/api/admin/users/{uid}", headers=h, json={"plan": "pro"}).json()["detail"]["code"] == "plan_unavailable"
    assert env.client.patch(f"/api/admin/users/{uid}", headers=h, json={"plan": "free"}).status_code == 200
    import uuid
    assert env.client.patch(f"/api/admin/users/{uuid.uuid4()}", headers=h, json={"status": "active"}).status_code == 404
    assert env.client.patch(f"/api/admin/users/{uid}", headers=h, json={"role": "wizard"}).status_code == 422


def test_admin_overview_and_audit_are_live(env):
    make_admin(env, "root@example.com", "root")
    complete_signup(env, email="x1@example.com")
    complete_signup(env, email="x2@example.com")
    h = auth(token_for(env, "root"))
    for rng, bars in (("7d", 7), ("30d", 30), ("90d", 13)):
        d = env.client.get(f"/api/admin/overview?range={rng}&tz=330", headers=h).json()
        assert len(d["signups"]["values"]) == len(d["signups"]["labels"]) == bars
        assert sum(d["signups"]["values"]) == 3  # exactly the three accounts that exist, nothing invented
    k = {x["label"]: x["value"] for x in d["kpis"]}
    assert k["Total users"] == 3 and k["New sign-ups"] == 3 and k["Suspended accounts"] == 0
    assert dict(d["roles"]) == {"Candidates": 2, "Recruiters": 0, "Admins": 1}
    assert d["health"][0][1] == "good" and d["activity"]
    assert env.client.get("/api/admin/overview?range=1y", headers=h).status_code == 422
    only_auth = env.client.get("/api/admin/audit?category=Auth", headers=h).json()["events"]
    assert only_auth and all(e["category"] == "Auth" for e in only_auth)


# ================= startup upgrade =================
def test_upgrade_adds_missing_column_and_is_repeatable(env):
    from sqlalchemy import inspect, text
    eng = env.session.engine
    with eng.begin() as c:
        c.execute(text("ALTER TABLE users DROP COLUMN date_of_birth"))
    assert "date_of_birth" not in {c["name"] for c in inspect(eng).get_columns("users")}
    up = importlib.reload(importlib.import_module("app.db.upgrade"))
    assert up.upgrade() == ["added users.date_of_birth"]
    assert up.upgrade() == []
    assert "date_of_birth" in {c["name"] for c in inspect(eng).get_columns("users")}


def test_app_start_runs_the_upgrade(env):
    from fastapi.testclient import TestClient
    with TestClient(env.mods["app.main"].app) as c:  # entering the context runs the startup hook
        assert c.get("/api/health").status_code == 200
