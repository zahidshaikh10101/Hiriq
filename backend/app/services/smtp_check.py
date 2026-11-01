"""Find out why email is not sending.  Run from the backend folder:

    python -m app.services.smtp_check             # tries your .env settings, step by step
    python -m app.services.smtp_check you@x.com   # ...and sends a real test email to that address
"""
from __future__ import annotations

import sys

from app.core.config import settings
from app.services import emailer


def main(to: str = "") -> int:
    print(f"provider={settings.email_provider}  host={settings.smtp_host}  port={settings.smtp_port}  user={settings.smtp_user or '<empty>'}")
    print(f"password set: {'yes, ' + str(len(settings.smtp_password)) + ' characters' if settings.smtp_password else 'NO'}")
    if settings.smtp_password and len(settings.smtp_password) != 16 and "gmail" in settings.smtp_host:
        print("  note: a Gmail app password is exactly 16 characters with no spaces")
    if settings.email_provider != "smtp":
        print("EMAIL_PROVIDER is not 'smtp' in backend/.env, so no real email will be sent.")
        return 1
    step = "connecting"
    try:
        server = emailer.open_smtp()
        step = "logging in"
        server.login(settings.smtp_user, settings.smtp_password)
        print("OK: connected and logged in.")
        if to:
            step = "sending"
            from email.message import EmailMessage
            m = EmailMessage()
            m["Subject"], m["From"], m["To"] = "Hiriq SMTP test", settings.smtp_from or settings.smtp_user, to
            m.set_content("If you can read this, Hiriq can send email.")
            server.send_message(m)
            print(f"OK: test email sent to {to}.")
        server.quit()
        return 0
    except Exception as exc:  # noqa: BLE001 - this is a diagnostic tool
        print(f"FAILED while {step}: {type(exc).__name__}: {exc}")
        hints = {
            "SMTPAuthenticationError": "Google refused the login. Re-create the app password and paste the 16 characters with no spaces. 2-Step Verification must be ON.",
            "SMTPServerDisconnected": "The server hung up. Try SMTP_PORT=465 in .env. If that fails too, your antivirus or network is blocking mail ports (turn off 'mail shield' / 'email scanning' and retry).",
            "TimeoutError": "No answer. A firewall, VPN or network is blocking the mail port. Try another network or SMTP_PORT=465.",
            "gaierror": "Could not find the host. Check SMTP_HOST (smtp.gmail.com) and your internet.",
            "SSLError": "TLS problem. If you use 465, make sure SMTP_PORT=465; antivirus HTTPS/mail scanning can also cause this.",
        }
        print("Hint:", hints.get(type(exc).__name__, "See the error above."))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))