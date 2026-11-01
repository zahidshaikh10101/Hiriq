"""Verify the ID token the browser gets from Google Identity Services ("Sign in with Google")."""
from __future__ import annotations

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.core.config import settings
import logging
log = logging.getLogger("uvicorn.error")

class GoogleAuthError(Exception):
    pass


def verify_google_credential(credential: str) -> dict:
    """Return {sub, email, name} for a valid token issued for our client id, else raise GoogleAuthError."""
    if not settings.google_client_id:
        raise GoogleAuthError("Google sign-in is not configured (set GOOGLE_CLIENT_ID in backend/.env).")
    try:
        info = id_token.verify_oauth2_token(
            credential, google_requests.Request(), settings.google_client_id,
            clock_skew_in_seconds=10,
        )
    except ValueError as exc:
        log.warning("Google token rejected: %s", exc)
        raise GoogleAuthError("Google sign-in could not be verified. Try again.") from exc
    if not info.get("sub") or not info.get("email"):
        raise GoogleAuthError("Google did not return an email address.")
    if not info.get("email_verified"):
        raise GoogleAuthError("Your Google email is not verified.")
    return {"sub": info["sub"], "email": info["email"].lower(), "name": info.get("name") or ""}
