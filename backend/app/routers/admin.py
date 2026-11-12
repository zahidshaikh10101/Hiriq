"""Admin console API (mounted at /api/admin). Every route needs a signed-in admin.

Live data only: users, the overview numbers and the audit log all come from the database. An admin can put any user on any plan.
Safety rules enforced here (not just in the page):
 - nobody can change, suspend or delete their own account;
 - only a superadmin can make someone an admin, or change/suspend/delete another admin.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import require_admin
from app.db.models import AdminProfile, AuditLog, Plan, User
from app.db.session import get_db
from app.services import audit
from app.services.timeutil import aware, now

router = APIRouter(tags=["admin"])

STATUS_LABEL = {"active": "Active", "suspended": "Suspended", "invited": "Invited"}
TONE = {"Auth": "a2", "Users": "a3", "Model": "a1", "Data": "a4"}


def _err(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code, detail={"code": code, "message": message})


def _db(db: Session | None) -> Session:
    if db is None:
        raise _err(503, "no_database", "The database is not configured.")
    return db


def _iso(dt) -> str | None:
    dt = aware(dt)
    return dt.isoformat() if dt else None


def _is_super(db: Session, user: User) -> bool:
    p = db.get(AdminProfile, user.id)
    return bool(p and p.is_superadmin)


def _can_manage(db: Session, actor: User, target: User) -> bool:
    if target.id == actor.id:
        return False
    if target.role == "admin":
        return _is_super(db, actor)
    return True


def _user_row(db: Session, actor: User, u: User, actor_super: bool) -> dict:
    return {
        "id": str(u.id), "name": u.full_name, "email": u.email, "username": u.username, "phone": u.phone_e164,
        "designation": u.designation, "company": u.company, "role": u.role, "plan": u.plan_id,
        "status": STATUS_LABEL.get(u.status, u.status), "joined": _iso(u.created_at), "last": _iso(u.last_login_at),
        "email_verified": u.email_verified, "you": u.id == actor.id,
        "locked": u.id == actor.id or (u.role == "admin" and not actor_super),
    }


def _label(u: User) -> str:
    return u.username or u.full_name


# ---------------- users ----------------
@router.get("/users")
def list_users(actor: User = Depends(require_admin), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    actor_super = _is_super(db, actor)
    users = db.scalars(select(User).order_by(User.created_at.asc())).all()
    plan_order = ["free", "basic", "pro", "premium"]
    plans = sorted(db.scalars(select(Plan)).all(), key=lambda p: plan_order.index(p.id) if p.id in plan_order else 99)
    return {
        "users": [_user_row(db, actor, u, actor_super) for u in users],
        "plans": [{"id": p.id, "name": p.name, "live": p.live} for p in plans],
        "you_are_superadmin": actor_super,
    }


class UserPatch(BaseModel):
    role: Literal["candidate", "recruiter", "admin"] | None = None
    status: Literal["active", "suspended"] | None = None
    plan: str | None = None


@router.patch("/users/{user_id}")
def update_user(user_id: uuid.UUID, body: UserPatch, request: Request, actor: User = Depends(require_admin),
                db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    target = db.get(User, user_id)
    if target is None:
        raise _err(404, "not_found", "That user no longer exists.")
    if target.id == actor.id:
        raise _err(403, "self", "You cannot change your own account here.")
    actor_super = _is_super(db, actor)
    if not _can_manage(db, actor, target):
        raise _err(403, "superadmin_only", "Only a superadmin can change another admin.")

    ip = request.client.host if request.client else None
    who = _label(target)

    if body.role is not None and body.role != target.role:
        if body.role == "admin" and not actor_super:
            raise _err(403, "superadmin_only", "Only a superadmin can make someone an admin.")
        old = target.role
        target.role = body.role
        if body.role == "admin" and db.get(AdminProfile, target.id) is None:
            db.add(AdminProfile(user_id=target.id, is_superadmin=False, permissions=[], invited_by=actor.id))
        if old == "admin":
            profile = db.get(AdminProfile, target.id)
            if profile is not None:
                db.delete(profile)
        audit.record(db, "Users", f"changed {who} from {old.title()} to {body.role.title()}", actor_id=actor.id,
                     actor_label=_label(actor), target_user_id=target.id, ip=ip)

    if body.status is not None and body.status != target.status:
        if target.status == "invited":
            raise _err(409, "invited", "This person has not accepted their invite yet.")
        target.status = body.status
        audit.record(db, "Users", f"{'suspended' if body.status == 'suspended' else 'reactivated'} {who}",
                     actor_id=actor.id, actor_label=_label(actor), target_user_id=target.id, ip=ip)

    if body.plan is not None and body.plan != target.plan_id:
        plan = db.get(Plan, body.plan)
        if plan is None:
            raise _err(422, "plan_unavailable", "That plan does not exist.")
        old_plan = target.plan_id
        target.plan_id = plan.id
        audit.record(db, "Users", f"moved {who} from the {old_plan} plan to the {plan.id} plan", actor_id=actor.id,
                     actor_label=_label(actor), target_user_id=target.id, ip=ip)

    db.commit()
    return _user_row(db, actor, target, actor_super)


@router.delete("/users/{user_id}")
def delete_user(user_id: uuid.UUID, request: Request, actor: User = Depends(require_admin),
                db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    target = db.get(User, user_id)
    if target is None:
        raise _err(404, "not_found", "That user no longer exists.")
    if target.id == actor.id:
        raise _err(403, "self", "You cannot delete your own account.")
    if not _can_manage(db, actor, target):
        raise _err(403, "superadmin_only", "Only a superadmin can delete another admin.")
    who = f"{_label(target)} ({target.email})"
    db.delete(target)
    audit.record(db, "Users", f"deleted {who}", actor_id=actor.id, actor_label=_label(actor),
                 ip=request.client.host if request.client else None)
    db.commit()
    return {"status": "deleted"}


# ---------------- overview ----------------
RANGES = {"7d": (7, 1), "30d": (30, 1), "90d": (13, 7)}  # (number of bars, days per bar)


def _bucket_series(created: list, buckets: int, step: int, tz_minutes: int) -> tuple[list[int], list[str]]:
    offset = timedelta(minutes=tz_minutes)
    today = (now() + offset).date()
    first = today - timedelta(days=buckets * step - 1)
    counts = [0] * buckets
    for dt in created:
        d = (aware(dt) + offset).date()
        idx = (d - first).days // step
        if 0 <= idx < buckets:
            counts[idx] += 1
    labels = []
    for i in range(buckets):
        start = first + timedelta(days=i * step)
        labels.append(f"{start.day} {start:%b}")
    return counts, labels


def _delta(current: int, previous: int) -> tuple[str, bool]:
    diff = current - previous
    if diff == 0:
        return "no change", True
    return (f"+{diff}" if diff > 0 else f"−{abs(diff)}"), diff > 0


@router.get("/overview")
def overview(range: Literal["7d", "30d", "90d"] = "7d", tz: int = Query(0, ge=-840, le=840),
             actor: User = Depends(require_admin), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    buckets, step = RANGES[range]
    days = buckets * step
    t = now()
    start, prev_start = t - timedelta(days=days), t - timedelta(days=2 * days)

    total = db.scalar(select(func.count()).select_from(User)) or 0
    role_counts = dict(db.execute(select(User.role, func.count()).group_by(User.role)).all())
    suspended = db.scalar(select(func.count()).select_from(User).where(User.status == "suspended")) or 0
    created = db.scalars(select(User.created_at).where(User.created_at >= prev_start)).all()
    new_now = sum(1 for c in created if aware(c) >= start)
    new_prev = len(created) - new_now
    active = db.scalar(select(func.count()).select_from(User).where(User.last_login_at >= start)) or 0

    series_values, series_labels = _bucket_series([c for c in created if aware(c) >= start], buckets, step, tz)
    delta_text, delta_up = _delta(new_now, new_prev)
    sub = {"7d": "Per day, last 7 days", "30d": "Per day, last 30 days", "90d": "Per week, last 90 days"}[range]

    email_live = settings.email_provider == "smtp" and bool(settings.smtp_user and settings.smtp_password)
    health = [
        ["Database", "good", "Healthy"],
        ["Email codes", "good" if email_live else "warn",
         f"Sending real email from {settings.smtp_user}" if email_live else "Console mode: codes print in the server window"],
        ["Google sign-in", "good" if settings.google_client_id else "warn",
         "Configured" if settings.google_client_id else "No client ID set"],
    ]

    recent = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(6)).all()
    return {
        "you_are_superadmin": _is_super(db, actor),
        "kpis": [
            {"label": "Total users", "value": total, "delta": f"+{new_now} new" if new_now else None, "up": True},
            {"label": "New sign-ups", "value": new_now, "delta": delta_text, "up": delta_up},
            {"label": "Signed in this period", "value": active, "delta": None, "up": True},
            {"label": "Suspended accounts", "value": suspended, "delta": None, "up": True},
        ],
        "signups": {"values": series_values, "labels": series_labels, "sub": sub},
        "roles": [["Candidates", role_counts.get("candidate", 0)], ["Recruiters", role_counts.get("recruiter", 0)],
                  ["Admins", role_counts.get("admin", 0)]],
        "health": health,
        "activity": [{"text": f"{a.actor_label} {a.action}", "at": _iso(a.created_at), "tone": TONE.get(a.category, "a1")}
                     for a in recent],
    }


# ---------------- audit log ----------------
@router.get("/audit")
def audit_log(category: Literal["all", "Auth", "Users", "Model", "Data"] = "all", limit: int = Query(100, ge=1, le=500),
              actor: User = Depends(require_admin), db: Session | None = Depends(get_db)) -> dict:
    db = _db(db)
    q = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)
    if category != "all":
        q = q.where(AuditLog.category == category)
    rows = db.scalars(q).all()
    return {"events": [{"at": _iso(a.created_at), "category": a.category, "actor": a.actor_label, "action": a.action}
                       for a in rows]}
