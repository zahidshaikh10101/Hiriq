"""App settings, read from environment variables (and backend/.env if present)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env")


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _db_url(value: str) -> str:
    """Neon gives postgresql://...; SQLAlchemy needs the psycopg (v3) driver name."""
    value = value.strip()
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://"):]
    if value.startswith("postgresql://"):
        value = "postgresql+psycopg://" + value[len("postgresql://"):]
    return value


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Settings:
    app_name: str = "Hiriq API"
    version: str = "0.2.0"

    # Legacy env-only admin (used only while DATABASE_URL is empty)
    admin_username: str = field(default_factory=lambda: os.getenv("ADMIN_USERNAME", "admin"))
    admin_password: str = field(default_factory=lambda: os.getenv("ADMIN_PASSWORD", ""))

    session_secret: str = field(default_factory=lambda: os.getenv("SESSION_SECRET", ""))
    session_hours: int = field(default_factory=lambda: _int("SESSION_HOURS", 8))
    cors_origins: list[str] = field(
        default_factory=lambda: _csv(os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000,http://localhost:5500,http://127.0.0.1:5500"))
    )
    frontend_dir: Path = REPO_DIR / "frontend"

    # Database
    database_url: str = field(default_factory=lambda: _db_url(os.getenv("DATABASE_URL", "")))

    # Google sign-in
    google_client_id: str = field(default_factory=lambda: os.getenv("GOOGLE_CLIENT_ID", "").strip())

    # Email verification codes. "console" prints the code in the server log (free, development);
    # "smtp" sends a real email (Gmail app password, Brevo, Resend, ... all speak SMTP).
    email_provider: str = field(default_factory=lambda: os.getenv("EMAIL_PROVIDER", "console").strip().lower())
    smtp_host: str = field(default_factory=lambda: os.getenv("SMTP_HOST", "smtp.gmail.com").strip())
    smtp_port: int = field(default_factory=lambda: _int("SMTP_PORT", 587))
    smtp_user: str = field(default_factory=lambda: os.getenv("SMTP_USER", "").strip())
    smtp_password: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""))
    smtp_from: str = field(default_factory=lambda: os.getenv("SMTP_FROM", "").strip())
    otp_ttl_seconds: int = field(default_factory=lambda: _int("OTP_TTL_SECONDS", 300))
    otp_max_attempts: int = field(default_factory=lambda: _int("OTP_MAX_ATTEMPTS", 5))
    otp_resend_seconds: int = field(default_factory=lambda: _int("OTP_RESEND_SECONDS", 30))
    otp_hourly_cap: int = field(default_factory=lambda: _int("OTP_HOURLY_CAP", 5))

    # Password sign-in lockout
    max_failed_logins: int = field(default_factory=lambda: _int("MAX_FAILED_LOGINS", 5))
    lockout_minutes: int = field(default_factory=lambda: _int("LOCKOUT_MINUTES", 15))

    @property
    def db_ready(self) -> bool:
        return bool(self.database_url)

    @property
    def token_ready(self) -> bool:
        return len(self.session_secret) >= 32

    @property
    def auth_ready(self) -> bool:
        """Login works once a long enough secret is set, plus either a DB or the legacy .env admin."""
        if self.db_ready:
            return self.token_ready
        return bool(self.admin_password) and self.token_ready


settings = Settings()
