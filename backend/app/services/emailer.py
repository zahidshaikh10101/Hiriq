"""Sending the verification email. Providers: "console" (log only, free) and "smtp" (real email)."""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import settings

log = logging.getLogger("hiriq.email")


class EmailError(RuntimeError):
    pass


def mask_email(email: str) -> str:
    """zahid@gmail.com -> z•••@gmail.com"""
    local, _, domain = email.partition("@")
    return f"{local[:1]}•••@{domain}"


def open_smtp() -> smtplib.SMTP:
    """Connect the way the port expects: 465 = TLS from the first byte, anything else = STARTTLS."""
    ctx = ssl.create_default_context()
    if settings.smtp_port == 465:
        return smtplib.SMTP_SSL(settings.smtp_host, 465, timeout=15, context=ctx)
    server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
    try:
        server.starttls(context=ctx)
    except Exception:
        server.close()
        raise
    return server


def send_otp_email(to: str, code: str, purpose: str = "signup") -> None:
    minutes = max(1, settings.otp_ttl_seconds // 60)
    provider = settings.email_provider

    if provider == "console":
        # Development only: the code appears in the terminal running uvicorn.
        log.warning("DEV email code for %s: %s", to, code)
        print(f"[DEV EMAIL CODE] {to}: {code}" + (" (password reset)" if purpose == "reset" else ""), flush=True)
        return

    if provider == "smtp":
        if not (settings.smtp_user and settings.smtp_password):
            raise EmailError("EMAIL_PROVIDER=smtp needs SMTP_USER and SMTP_PASSWORD in backend/.env.")
        msg = EmailMessage()
        msg["Subject"] = f"{code} is your Hiriq {'password reset' if purpose == 'reset' else 'verification'} code"
        msg["From"] = settings.smtp_from or settings.smtp_user
        msg["To"] = to
        if purpose == "reset":
            intro = f"Your Hiriq password reset code is {code}."
            ignore = "If you did not ask to reset your password, ignore this email. Your password has not changed."
        else:
            intro = f"Your Hiriq verification code is {code}."
            ignore = "If you did not try to create a Hiriq account, ignore this email."
        msg.set_content(f"{intro}\n\nIt expires in {minutes} minutes. {ignore}\nNever share this code with anyone.")
        try:
            with open_smtp() as server:
                server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            log.error("SMTP send failed: %s", exc)
            raise EmailError("Could not send the email.") from exc
        return

    raise EmailError(f"Unknown EMAIL_PROVIDER '{provider}'. Use 'console' or 'smtp'.")