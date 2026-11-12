"""Automatic usernames: first name + last name, lowercase, joined by a dot.

"Zahid Salim Shaikh"  ->  zahid.shaikh        (first and last part of the name; middle names are skipped)
"Zoë van der Berg"    ->  zoe.berg             (accents are folded to plain letters)
"Madonna"             ->  madonna              (a single name stays single)

If someone already has it, a number is added: zahid.shaikh2, zahid.shaikh3, ...
Lowercase ASCII letters, digits and one dot only. A name with no ASCII letters at all becomes "user".
Nothing here reads the date of birth: a username is easy to remember and reveals nothing private.
"""
from __future__ import annotations

import secrets
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User

MAX_PART = 15        # characters kept from the first and from the last name (the column holds 40)


def _letters(part: str) -> str:
    """Accents folded, ASCII letters only, lowercase. "O'Brien" -> "obrien", "Zoë" -> "zoe"."""
    folded = unicodedata.normalize("NFKD", part).encode("ascii", "ignore").decode()
    return "".join(ch for ch in folded if ch.isalpha()).lower()


def base_username(full_name: str) -> str:
    parts = [p for p in (_letters(p) for p in (full_name or "").split()) if p]
    if not parts:
        return "user"
    if len(parts) == 1:
        return parts[0][:MAX_PART * 2]
    return f"{parts[0][:MAX_PART]}.{parts[-1][:MAX_PART]}"


def make_unique(db: Session, full_name: str) -> str:
    base = base_username(full_name)
    taken = set(db.scalars(select(User.username).where(User.username.like(f"{base}%"))))
    if base not in taken:
        return base
    for n in range(2, 100):
        if f"{base}{n}" not in taken:
            return f"{base}{n}"
    return f"{base}{secrets.randbelow(10**4):04d}"


def assign_username(db: Session, user: User) -> str | None:
    """Give the user a username if they have none. Never changes an existing one."""
    if user.username:
        return user.username
    user.username = make_unique(db, user.full_name)
    return user.username
