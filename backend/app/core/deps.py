"""Shared FastAPI dependencies: who is calling, and are they an admin or a recruiter."""
from __future__ import annotations

import uuid

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import verify_token
from app.db.models import User
from app.db.session import get_db
from app.services.timeutil import aware


def bearer(authorization: str | None) -> str:
    return (authorization or "").removeprefix("Bearer ").strip()


def user_from_authorization(authorization: str | None, db: Session | None) -> User | None:
    """The active user a bearer token belongs to, or None. A suspended user's old token stops working at once."""
    if db is None or not settings.token_ready:
        return None
    token = bearer(authorization)
    payload = verify_token(token, settings.session_secret) if token else None
    if not payload:
        return None
    try:
        user = db.get(User, uuid.UUID(str(payload.get("sub"))))
    except ValueError:
        return None
    if user is None or user.status != "active":
        return None
    if user.tokens_valid_after is not None:
        try:
            issued = float(payload.get("iat", 0))        # tokens made before this check existed have no iat: refused after a reset
        except (TypeError, ValueError):
            return None
        if issued < aware(user.tokens_valid_after).timestamp():
            return None
    return user


def current_user(authorization: str | None = Header(default=None), db: Session | None = Depends(get_db)) -> User:
    if db is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database is not configured.")
    user = user_from_authorization(authorization, db)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in.")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admins only.")
    return user


def require_recruiter(user: User = Depends(current_user)) -> User:
    """Recruiter data belongs to recruiters. Admins manage accounts from the admin console instead."""
    if user.role != "recruiter":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Recruiters only.")
    return user
