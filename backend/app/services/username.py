"""Automatic usernames: the initials of the full name + the date of birth, e.g.
"Zahid Salim Shaikh", born 10 Jan 2001  ->  zss100101   (initials + DDMMYY).
Lowercase letters and digits only. If someone already has it, a number is added (zss1001012, zss1001013, ...).
"""
from __future__ import annotations

import secrets
import unicodedata
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User

MAX_INITIALS = 4


def initials(full_name: str) -> str:
    """First letter of each part of the name, ASCII only, at most 4. 'Zoë van der Berg' -> 'zvdb'."""
    letters = []
    for part in (full_name or "").split():
        folded = unicodedata.normalize("NFKD", part).encode("ascii", "ignore").decode()
        for ch in folded:
            if ch.isalpha():
                letters.append(ch.lower())
                break
    return "".join(letters[:MAX_INITIALS]) or "u"


def base_username(full_name: str, dob: date) -> str:
    return f"{initials(full_name)}{dob:%d%m%y}"


def make_unique(db: Session, full_name: str, dob: date) -> str:
    base = base_username(full_name, dob)
    taken = set(db.scalars(select(User.username).where(User.username.like(f"{base}%"))))
    if base not in taken:
        return base
    for n in range(2, 100):
        if f"{base}{n}" not in taken:
            return f"{base}{n}"
    return f"{base}{secrets.randbelow(10**4):04d}"


def assign_username(db: Session, user: User) -> str | None:
    """Give the user a username if they have none and we know their date of birth. Never changes an existing one."""
    if user.username or not user.date_of_birth:
        return user.username
    user.username = make_unique(db, user.full_name, user.date_of_birth)
    return user.username
