"""Make an email address an admin.  Run from the backend folder:

    python -m app.db.promote_admin hiriqoff@gmail.com            # normal admin
    python -m app.db.promote_admin hiriqoff@gmail.com --super    # superadmin (ignores the permission list)
    python -m app.db.promote_admin hiriqoff@gmail.com --username hiriqoff --set-password   # also allow username + password login

If the person already signed up, their account is promoted. If not, an account is created with no
password: they sign in with the Google button on login.html using that Gmail address.
"""
from __future__ import annotations

import argparse
import getpass

from sqlalchemy import select

from app.core.security import hash_password
from app.db import models
from app.db.session import SessionLocal


def promote(email: str, superadmin: bool = False, name: str = "", username: str = "", password: str = "") -> str:
    if SessionLocal is None:
        raise SystemExit("DATABASE_URL is not set. Put it in backend/.env first.")
    email = email.strip().lower()
    if "@" not in email:
        raise SystemExit("Give a valid email address.")

    with SessionLocal() as db:
        user = db.scalar(select(models.User).where(models.User.email == email))
        created = user is None
        if created:
            user = models.User(email=email, full_name=(name or email.split("@")[0])[:120])
            db.add(user)
        username = username.strip().lower()
        if username:
            taken = db.scalar(select(models.User).where(models.User.username == username, models.User.id != user.id))
            if taken is not None:
                raise SystemExit(f"The username '{username}' already belongs to {taken.email}. Pick another.")
            user.username = username
        if password:
            if len(password) < 12:
                raise SystemExit("Use a password of 12 or more characters.")
            user.password_hash = hash_password(password)
        user.role = "admin"
        user.status = "active"
        user.email_verified = True  # sign-in still needs Google (or a password they set), so this proves nothing alone
        user.failed_logins = 0
        user.locked_until = None
        db.flush()
        profile = db.get(models.AdminProfile, user.id)
        if profile is None:
            db.add(models.AdminProfile(user_id=user.id, is_superadmin=superadmin, permissions=[]))
        elif superadmin:
            profile.is_superadmin = True
        db.add(models.AuditLog(
            category="Users", actor_label="system",
            action=f"{'created' if created else 'promoted'} {'superadmin' if superadmin else 'admin'} {email}",
            target_user_id=user.id,
        ))
        user_login = user.username or email
        db.commit()
    if password:
        how = f"Log in with '{user_login}' and your password, or with the Google button."
    else:
        how = "Sign in with the Google button on login.html." if created else "Sign out and back in to get an admin session."
    return f"{email} is now {'a superadmin' if superadmin else 'an admin'} ({'created' if created else 'existing account promoted'}). {how}"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Make an email address an admin.")
    ap.add_argument("email")
    ap.add_argument("--super", dest="superadmin", action="store_true", help="make them a superadmin")
    ap.add_argument("--name", default="", help="display name (only used when the account is new)")
    ap.add_argument("--username", default="", help="username for password login")
    ap.add_argument("--set-password", dest="set_password", action="store_true", help="prompt for a password (12+ characters)")
    a = ap.parse_args()
    pw = ""
    if a.set_password:
        pw = getpass.getpass("New password (12+ characters, hidden): ")
        if pw != getpass.getpass("Repeat it: "):
            raise SystemExit("The two passwords differ. Nothing was changed.")
    print(promote(a.email, a.superadmin, a.name, a.username, pw))