"""Database schema: accounts, sign-in methods, OTP codes, and the admin console's tables.

Works on Postgres (Neon) in production and SQLite in tests.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy import (
    JSON, BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, Uuid, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

Json = JSON().with_variant(JSONB(), "postgresql")
BigId = BigInteger().with_variant(Integer(), "sqlite")  # SQLite only autoincrements INTEGER keys

ROLES = ("candidate", "recruiter", "admin")
STATUSES = ("active", "suspended", "invited")
OTP_PURPOSES = ("signup", "reset")
AUDIT_CATEGORIES = ("Auth", "Users", "Model", "Data")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Plan(Base):
    """Free / Basic / Pro / Premium. Only 'free' is live today (matches the admin Users page)."""

    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    live: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.false())


class User(Base):
    """One row per person: candidates, recruiters and admins share this table; `role` tells them apart."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(_in("role", ROLES), name="ck_users_role"),
        CheckConstraint(_in("status", STATUSES), name="ck_users_status"),
        CheckConstraint("email = lower(email)", name="ck_users_email_lower"),
        Index("ix_users_role_status", "role", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    # Login handle. Made automatically as firstname.lastname (e.g. zahid.shaikh); admins can have a custom one.
    username: Mapped[str | None] = mapped_column(String(40), unique=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255))  # NULL for Google-only accounts
    # Optional contact number from "complete your profile". Not verified (SMS costs money), so not unique.
    phone_e164: Mapped[str | None] = mapped_column(String(20), index=True)

    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.false())
    phone_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.false())

    role: Mapped[str] = mapped_column(String(20), nullable=False, server_default="candidate")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id"), nullable=False, server_default="free")

    date_of_birth: Mapped[date | None] = mapped_column(Date)
    designation: Mapped[str | None] = mapped_column(String(120))
    company: Mapped[str | None] = mapped_column(String(120))
    job_alerts: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.false())
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    failed_logins: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Sign-in tokens issued before this moment are refused. Set when the password is reset, so an old session cannot outlive it.
    tokens_valid_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    identities: Mapped[list["AuthIdentity"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    admin_profile: Mapped["AdminProfile | None"] = relationship(
        back_populates="user", foreign_keys="AdminProfile.user_id", cascade="all, delete-orphan", uselist=False
    )


class AuthIdentity(Base):
    """A linked external sign-in (Google today). `subject` is Google's stable user id (the `sub` claim)."""

    __tablename__ = "auth_identities"
    __table_args__ = (UniqueConstraint("provider", "subject", name="uq_identity_provider_subject"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="identities")


class OtpCode(Base):
    """One-time email codes. Only an HMAC of the code is stored, never the code itself."""

    __tablename__ = "otp_codes"
    __table_args__ = (
        CheckConstraint(_in("purpose", OTP_PURPOSES), name="ck_otp_purpose"),
        Index("ix_otp_destination_created", "destination", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    destination: Mapped[str] = mapped_column(String(320), nullable=False)  # the email address
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PendingSignup(Base):
    """A sign-up that has not been verified yet. No `users` row exists until the emailed code is entered.

    The password is kept only as an argon2 hash. `token_hash` binds the sign-up to the browser that started it: the browser
    gets the secret token once, and verifying needs both that token and the emailed code. Someone who restarts a sign-up
    for another person's email cannot read that person's code, and the person cannot guess the new token, so nobody can
    end up verifying an account whose password they did not choose.
    """

    __tablename__ = "pending_signups"
    __table_args__ = (CheckConstraint(_in("role", ("candidate", "recruiter")), name="ck_pending_role"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    phone_e164: Mapped[str | None] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    job_alerts: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.false())
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AdminProfile(Base):
    """Extra admin-only data. A user is an admin when users.role = 'admin'; this row says what they may do."""

    __tablename__ = "admin_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.false())
    # e.g. ["users", "jobs", "model", "audit"]; superadmins ignore this list
    permissions: Mapped[list] = mapped_column(Json, nullable=False, default=list)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="admin_profile", foreign_keys=[user_id])


class AdminInvite(Base):
    """Backs the 'Invite user' form in the admin console. Only a hash of the invite token is stored."""

    __tablename__ = "admin_invites"
    __table_args__ = (CheckConstraint(_in("role", ROLES), name="ck_invite_role"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    full_name: Mapped[str | None] = mapped_column(String(120))
    phone_e164: Mapped[str | None] = mapped_column(String(20))
    designation: Mapped[str | None] = mapped_column(String(120))
    company: Mapped[str | None] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20), nullable=False, server_default="candidate")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AuditLog(Base):
    """Backs the admin 'Audit log' page. Rows are append-only; keep actor_label so history survives user deletion."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint(_in("category", AUDIT_CATEGORIES), name="ck_audit_category"),
        Index("ix_audit_created", "created_at"),
        Index("ix_audit_category_created", "category", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_label: Mapped[str] = mapped_column(String(120), nullable=False, server_default="system")
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    ip: Mapped[str | None] = mapped_column(String(45))
    meta: Mapped[dict | None] = mapped_column(Json)
