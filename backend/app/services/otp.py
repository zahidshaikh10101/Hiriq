"""Issue and check 6-digit email codes. Codes are stored only as an HMAC, expire, and allow few attempts."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import OtpCode
from app.services.timeutil import aware, now


class OtpError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _digest(code: str, destination: str, purpose: str) -> str:
    key = settings.session_secret.encode()
    return hmac.new(key, f"{purpose}:{destination}:{code}".encode(), hashlib.sha256).hexdigest()


def issue(db: Session, destination: str, purpose: str, user_id: uuid.UUID | None) -> str:
    """Create a code (and retire older ones for this address). Caller sends it, then commits."""
    t = now()
    last = db.scalar(select(OtpCode).where(OtpCode.destination == destination).order_by(OtpCode.created_at.desc()).limit(1))
    if last and (t - aware(last.created_at)).total_seconds() < settings.otp_resend_seconds:
        raise OtpError(f"Please wait {settings.otp_resend_seconds} seconds before asking for another code.", 429)
    recent = db.scalar(
        select(func.count()).select_from(OtpCode).where(OtpCode.destination == destination, OtpCode.created_at > t - timedelta(hours=1))
    )
    if recent >= settings.otp_hourly_cap:
        raise OtpError("Too many codes requested for this address. Try again in an hour.", 429)

    db.execute(update(OtpCode).where(OtpCode.destination == destination, OtpCode.consumed_at.is_(None)).values(consumed_at=t))
    code = f"{secrets.randbelow(10**6):06d}"
    db.add(OtpCode(
        purpose=purpose, destination=destination, user_id=user_id, code_hash=_digest(code, destination, purpose),
        expires_at=t + timedelta(seconds=settings.otp_ttl_seconds), created_at=t,
    ))
    db.flush()
    return code


def verify(db: Session, destination: str, purpose: str, code: str) -> OtpCode:
    """Return the consumed OtpCode row, or raise OtpError. A wrong guess is counted and saved."""
    t = now()
    row = db.scalar(
        select(OtpCode)
        .where(OtpCode.destination == destination, OtpCode.purpose == purpose, OtpCode.consumed_at.is_(None))
        .order_by(OtpCode.created_at.desc())
        .limit(1)
    )
    if row is None or aware(row.expires_at) < t:
        raise OtpError("That code has expired. Ask for a new one.")
    if row.attempts >= settings.otp_max_attempts:
        raise OtpError("Too many wrong attempts. Ask for a new code.", 429)
    row.attempts += 1
    if not hmac.compare_digest(row.code_hash, _digest((code or "").strip(), destination, purpose)):
        db.commit()  # keep the attempt count even though the request fails
        raise OtpError("That code is not correct.")
    row.consumed_at = t
    return row
