"""Auth endpoints.

With DATABASE_URL set: real accounts (email + password with an emailed code, or Google) stored in Postgres.
Without it: the single admin from .env (kept so the project still runs with no database).
A phone number is an optional profile field (PUT /profile); it is not verified, because SMS costs money.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import current_user, user_from_authorization
from app.core.security import create_token, hash_password, same_secret, verify_password, verify_token
from app.db.models import AuthIdentity, User
from app.db.session import get_db
from app.services import audit, otp
from app.services.username import assign_username
from app.services.emailer import EmailError, mask_email, send_otp_email
from app.services.google_auth import GoogleAuthError, verify_google_credential
from app.services.phone import PhoneError, normalize
from app.services.timeutil import aware, now

router = APIRouter(tags=["auth"])
log = logging.getLogger("hiriq.auth")

MIN_AGE_YEARS = 16

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------- schemas ----------------
class LoginIn(BaseModel):
    username: str  # email or username
    password: str


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    name: str | None = None
    expires_in: int | None = None  # seconds
    needs_phone: bool | None = None  # true until the user saves a phone number in "complete your profile"
    needs_profile: bool | None = None  # true while the phone or the date of birth is missing
    username: str | None = None


class Me(BaseModel):
    user: str
    role: str
    id: str | None = None
    username: str | None = None
    email: str | None = None
    dob: str | None = None
    phone: str | None = None
    email_verified: bool | None = None
    designation: str | None = None
    company: str | None = None
    plan: str | None = None


class SignupIn(BaseModel):
    name: str
    email: str
    password: str
    dob: str  # date of birth, YYYY-MM-DD; used with the name's initials to make the username
    phone: str = ""  # optional, +<country code><digits>
    role: Literal["candidate", "recruiter"] = "candidate"
    alerts: bool = True
    consent: bool = False


class EmailIn(BaseModel):
    email: str


class EmailCodeIn(BaseModel):
    email: str
    code: str


class GoogleIn(BaseModel):
    credential: str
    mode: Literal["login", "signup"] = "login"
    role: Literal["candidate", "recruiter"] = "candidate"
    consent: bool = False


class ProfileIn(BaseModel):
    dob: str | None = None  # YYYY-MM-DD; creates the username if the account has none
    phone: str | None = None  # "" clears it
    designation: str | None = None
    company: str | None = None
    alerts: bool | None = None


class ResetIn(BaseModel):
    email: str
    code: str
    new_password: str


class CodeSent(BaseModel):
    status: str = "code_sent"
    email_masked: str | None = None
    resend_in: int | None = None


# ---------------- helpers ----------------
def _err(code_status: int, code: str, message: str) -> HTTPException:
    return HTTPException(code_status, detail={"code": code, "message": message})


def _need_db(db: Session | None) -> Session:
    if db is None:
        raise _err(503, "no_database", "The database is not configured. Set DATABASE_URL in backend/.env.")
    if not settings.token_ready:
        raise _err(503, "no_secret", "Set SESSION_SECRET (32+ characters) in backend/.env.")
    return db


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _email(raw: str) -> str:
    email = (raw or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise _err(422, "bad_email", "Add a valid email address.")
    return email


def _phone(raw: str) -> str:
    try:
        return normalize(raw)
    except PhoneError as exc:
        raise _err(422, "bad_phone", str(exc)) from None


def _dob(raw: str) -> date:
    try:
        d = date.fromisoformat((raw or "").strip())
    except ValueError:
        raise _err(422, "bad_dob", "Enter your date of birth.") from None
    today = date.today()
    age = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
    if d > today or d.year < 1900:
        raise _err(422, "bad_dob", "Enter a valid date of birth.")
    if age < MIN_AGE_YEARS:
        raise _err(422, "too_young", f"You must be at least {MIN_AGE_YEARS} to use Hiriq.")
    return d


def _session(user: User) -> LoginOut:
    token = create_token(str(user.id), user.role, settings.session_secret, settings.session_hours)
    return LoginOut(
        access_token=token, role=user.role, name=user.full_name, expires_in=settings.session_hours * 3600,
        needs_phone=not user.phone_e164, needs_profile=not user.phone_e164 or not user.date_of_birth,
        username=user.username,
    )


def _mark_signed_in(user: User) -> None:
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now()


def _send_code(db: Session, email: str, user_id) -> None:
    """Create + email a code. Any failure rolls the whole request back so nothing half-saved remains."""
    try:
        code = otp.issue(db, email, "signup", user_id)
        send_otp_email(email, code)
    except otp.OtpError as exc:
        db.rollback()
        raise _err(exc.status, "otp_rate_limited", exc.message) from None
    except EmailError:
        db.rollback()
        raise _err(502, "email_failed", "We could not send the email. Try again in a moment.") from None


def _check_active(user: User) -> None:
    if user.status == "suspended":
        raise _err(403, "suspended", "This account is suspended. Contact support.")
    if user.status != "active":
        raise _err(403, "not_active", "This account is not active yet.")


def _me(user: User) -> Me:
    return Me(
        user=user.username or user.full_name, role=user.role, id=str(user.id), username=user.username, email=user.email,
        dob=user.date_of_birth.isoformat() if user.date_of_birth else None, phone=user.phone_e164,
        email_verified=user.email_verified, designation=user.designation, company=user.company, plan=user.plan_id,
    )


# ---------------- sign up (email + password, then an emailed code) ----------------
@router.post("/signup", response_model=CodeSent)
def signup(body: SignupIn, request: Request, db: Session | None = Depends(get_db)) -> CodeSent:
    db = _need_db(db)
    name = body.name.strip()
    email = _email(body.email)
    if len(name) < 2:
        raise _err(422, "bad_name", "Add your full name.")
    if len(body.password) < 8 or len(body.password) > 128:
        raise _err(422, "weak_password", "Use a password of 8 to 128 characters.")
    if not body.consent:
        raise _err(422, "consent_required", "Accept the Terms and Privacy Policy to continue.")
    dob = _dob(body.dob)
    phone = _phone(body.phone) if body.phone.strip() else None

    user = db.scalar(select(User).where(User.email == email))
    # A half-finished signup (email never verified) can be restarted; a real account cannot be taken over.
    if user and (user.email_verified or user.identities or user.role == "admin"):
        raise _err(409, "account_exists", "An account with this email already exists. Log in instead.")

    if user is None:
        user = User(email=email, full_name=name)
        db.add(user)
    user.full_name = name
    user.date_of_birth = dob
    user.phone_e164 = phone
    user.password_hash = hash_password(body.password)
    user.role = body.role
    user.job_alerts = body.alerts if body.role == "candidate" else False
    user.consented_at = now()
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise _err(409, "account_exists", "An account with this email already exists. Log in instead.") from None

    _send_code(db, email, user.id)
    audit.record(db, "Auth", "started sign-up", actor_id=user.id, actor_label=name, target_user_id=user.id, ip=_ip(request))
    db.commit()
    return CodeSent(email_masked=mask_email(email), resend_in=settings.otp_resend_seconds)


@router.post("/signup/resend", response_model=CodeSent)
def signup_resend(body: EmailIn, db: Session | None = Depends(get_db)) -> CodeSent:
    db = _need_db(db)
    email = _email(body.email)
    user = db.scalar(select(User).where(User.email == email, User.email_verified.is_(False)))
    if user and user.password_hash:  # same reply whether or not there is a pending signup
        _send_code(db, email, user.id)
        db.commit()
    return CodeSent(email_masked=mask_email(email), resend_in=settings.otp_resend_seconds)


@router.post("/signup/verify-email", response_model=LoginOut, response_model_exclude_none=True)
def signup_verify(body: EmailCodeIn, request: Request, db: Session | None = Depends(get_db)) -> LoginOut:
    db = _need_db(db)
    email = _email(body.email)
    try:
        row = otp.verify(db, email, "signup", body.code)
    except otp.OtpError as exc:
        raise _err(exc.status, "otp_invalid", exc.message) from None
    user = db.get(User, row.user_id) if row.user_id else None
    if user is None or user.email != email:
        db.rollback()
        raise _err(400, "otp_invalid", "That code is no longer valid. Start sign-up again.")
    user.email_verified = True
    assign_username(db, user)
    _mark_signed_in(user)
    audit.record(db, "Auth", "verified their email and signed up", actor_id=user.id, actor_label=user.full_name,
                 target_user_id=user.id, ip=_ip(request))
    db.commit()
    return _session(user)


# ---------------- log in with email/username + password ----------------
# Real accounts lock after repeated failures. If an unknown email never locked, the "too many attempts" reply would tell an
# attacker the account exists. So unknown identifiers are counted and locked the same way (in memory, per process).
_ghosts: dict[str, list] = {}   # identifier -> [failed count, locked until]
_GHOST_LIMIT = 5000


def _ghost_wait(ident: str) -> int:
    entry = _ghosts.get(ident)
    if entry and entry[1] and entry[1] > now():
        return max(1, int((entry[1] - now()).total_seconds() // 60) + 1)
    return 0


def _ghost_fail(ident: str) -> None:
    if len(_ghosts) >= _GHOST_LIMIT and ident not in _ghosts:
        t = now()
        for key in [k for k, v in _ghosts.items() if not v[1] or v[1] <= t]:
            del _ghosts[key]
        if len(_ghosts) >= _GHOST_LIMIT:
            return
    entry = _ghosts.setdefault(ident, [0, None])
    entry[0] += 1
    if entry[0] >= settings.max_failed_logins:
        entry[1] = now() + timedelta(minutes=settings.lockout_minutes)
        entry[0] = 0


def _login_legacy(body: LoginIn) -> LoginOut:
    if not settings.auth_ready:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Login is not configured. Set DATABASE_URL, or ADMIN_PASSWORD, plus SESSION_SECRET (32+ characters) in backend/.env.",
        )
    user_ok = same_secret(body.username.strip().lower(), settings.admin_username.lower())
    pass_ok = same_secret(body.password, settings.admin_password)
    if not (user_ok and pass_ok):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "That username and password do not match.")
    token = create_token(settings.admin_username, "admin", settings.session_secret, settings.session_hours)
    return LoginOut(access_token=token, role="admin")


@router.post("/login", response_model=LoginOut, response_model_exclude_none=True)
def login(body: LoginIn, request: Request, db: Session | None = Depends(get_db)) -> LoginOut:
    if not settings.db_ready:
        return _login_legacy(body)
    db = _need_db(db)

    ident = body.username.strip().lower()
    user = db.scalar(select(User).where(or_(User.email == ident, User.username == ident)))
    bad = _err(401, "bad_credentials", "That email and password do not match.")

    if user is None:
        wait = _ghost_wait(ident)
        if wait:
            raise _err(429, "locked", f"Too many failed attempts. Try again in {wait} minutes.")
    elif user.locked_until and aware(user.locked_until) > now():
        mins = max(1, int((aware(user.locked_until) - now()).total_seconds() // 60) + 1)
        raise _err(429, "locked", f"Too many failed attempts. Try again in {mins} minutes.")

    if not verify_password(body.password, user.password_hash if user else None) or user is None:
        if user:
            user.failed_logins += 1
            if user.failed_logins >= settings.max_failed_logins:
                user.locked_until = now() + timedelta(minutes=settings.lockout_minutes)
                audit.record(db, "Auth", f"was blocked after {user.failed_logins} failed sign-ins", actor_id=user.id,
                             actor_label=user.full_name, target_user_id=user.id, ip=_ip(request))
                user.failed_logins = 0
            db.commit()
        else:
            _ghost_fail(ident)
        raise bad

    _check_active(user)
    if not user.email_verified:
        raise _err(403, "not_verified", "Verify your email to finish creating your account. Sign up again with the same email to get a new code.")
    _mark_signed_in(user)
    audit.record(db, "Auth", "signed in", actor_id=user.id, actor_label=user.username or user.full_name,
                 target_user_id=user.id, ip=_ip(request))
    db.commit()
    return _session(user)


# ---------------- forgot password (emailed code, then a new password) ----------------
def _deliver_reset_code(email: str, code: str) -> None:
    """Runs after the response is sent, so the reply takes the same time whether or not the account exists."""
    try:
        send_otp_email(email, code, "reset")
    except EmailError:
        log.error("Could not send the password reset code to %s", mask_email(email))


@router.post("/password/forgot", response_model=CodeSent)
def password_forgot(body: EmailIn, request: Request, background: BackgroundTasks,
                    db: Session | None = Depends(get_db)) -> CodeSent:
    """Always answers the same way, so nobody can use this to find out which emails have accounts."""
    db = _need_db(db)
    email = _email(body.email)
    user = db.scalar(select(User).where(User.email == email))
    if user and user.email_verified and user.status == "active":
        try:
            code = otp.issue(db, email, "reset", user.id)
        except otp.OtpError:
            db.rollback()  # too many codes lately: quietly send nothing, same reply
        else:
            audit.record(db, "Auth", "asked for a password reset code", actor_id=user.id,
                         actor_label=user.username or user.full_name, target_user_id=user.id, ip=_ip(request))
            db.commit()
            background.add_task(_deliver_reset_code, email, code)
    return CodeSent(email_masked=mask_email(email), resend_in=settings.otp_resend_seconds)


@router.post("/password/reset")
def password_reset(body: ResetIn, request: Request, db: Session | None = Depends(get_db)) -> dict:
    db = _need_db(db)
    email = _email(body.email)
    if len(body.new_password) < 8 or len(body.new_password) > 128:
        raise _err(422, "weak_password", "Use a password of 8 to 128 characters.")
    try:
        row = otp.verify(db, email, "reset", body.code)
    except otp.OtpError as exc:
        raise _err(exc.status, "otp_invalid", exc.message) from None
    user = db.get(User, row.user_id) if row.user_id else None
    if user is None or user.email != email or user.status != "active":
        db.rollback()
        raise _err(400, "otp_invalid", "That code is no longer valid. Ask for a new one.")
    user.password_hash = hash_password(body.new_password)
    user.failed_logins = 0
    user.locked_until = None  # they proved they own the email, so a lockout no longer applies
    user.tokens_valid_after = now()  # and any session opened with the old password stops working
    audit.record(db, "Auth", "reset their password", actor_id=user.id, actor_label=user.username or user.full_name,
                 target_user_id=user.id, ip=_ip(request))
    db.commit()
    return {"status": "password_changed"}


# ---------------- Google ----------------
@router.post("/google", response_model=LoginOut, response_model_exclude_none=True)
def google_sign_in(body: GoogleIn, request: Request, db: Session | None = Depends(get_db)) -> LoginOut:
    db = _need_db(db)
    try:
        info = verify_google_credential(body.credential)
    except GoogleAuthError as exc:
        raise _err(401, "google_failed", str(exc)) from None

    link = db.scalar(select(AuthIdentity).where(AuthIdentity.provider == "google", AuthIdentity.subject == info["sub"]))
    if link:
        user = link.user
    else:
        user = db.scalar(select(User).where(User.email == info["email"]))
        if user:
            if not user.email_verified:
                # Google has now proven who owns this email. A password attached by an earlier, unverified
                # signup could belong to someone else, so drop it.
                user.password_hash = None
                user.email_verified = True
        else:
            if body.mode == "login":
                raise _err(404, "no_account", "No Hiriq account uses that Google email yet. Sign up first.")
            if not body.consent:
                raise _err(422, "consent_required", "Accept the Terms and Privacy Policy to continue.")
            user = User(
                email=info["email"], full_name=(info["name"] or info["email"].split("@")[0])[:120],
                role=body.role, email_verified=True, consented_at=now(), job_alerts=body.role == "candidate",
            )
            db.add(user)
            db.flush()
            audit.record(db, "Users", "signed up with Google", actor_id=user.id, actor_label=user.full_name,
                         target_user_id=user.id, ip=_ip(request))
        db.add(AuthIdentity(user_id=user.id, provider="google", subject=info["sub"], email=info["email"]))

    _check_active(user)
    _mark_signed_in(user)
    audit.record(db, "Auth", "signed in with Google", actor_id=user.id, actor_label=user.full_name,
                 target_user_id=user.id, ip=_ip(request))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _err(409, "account_exists", "That Google account is already linked. Try again.") from None
    return _session(user)


# ---------------- complete your profile (phone etc.), signed in ----------------
@router.put("/profile", response_model=Me, response_model_exclude_none=True)
def update_profile(body: ProfileIn, request: Request, user: User = Depends(current_user),
                   db: Session | None = Depends(get_db)) -> Me:
    db = _need_db(db)
    if body.dob is not None and body.dob.strip():
        user.date_of_birth = _dob(body.dob)
        assign_username(db, user)  # only when there is none yet; an existing username never changes
    if body.phone is not None:
        user.phone_e164 = _phone(body.phone) if body.phone.strip() else None
    if body.designation is not None:
        user.designation = body.designation.strip()[:120] or None
    if body.company is not None:
        user.company = body.company.strip()[:120] or None
    if body.alerts is not None and user.role == "candidate":
        user.job_alerts = body.alerts
    audit.record(db, "Users", "updated their profile", actor_id=user.id, actor_label=user.full_name,
                 target_user_id=user.id, ip=_ip(request))
    db.commit()
    return _me(user)


# ---------------- who am I ----------------
@router.get("/me", response_model=Me, response_model_exclude_none=True)
def me(authorization: str | None = Header(default=None), db: Session | None = Depends(get_db)) -> Me:
    if settings.db_ready:
        user = user_from_authorization(authorization, db)
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in.")
        return _me(user)
    token = (authorization or "").removeprefix("Bearer ").strip()
    payload = verify_token(token, settings.session_secret) if token and settings.auth_ready else None
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in.")
    return Me(user=payload["sub"], role=payload["role"])
