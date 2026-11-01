"""Sending the OTP text. Providers: "console" (log only, free) and "twilio" (paid)."""
from __future__ import annotations

import logging

import httpx

from app.core.config import settings

log = logging.getLogger("hiriq.sms")


class SmsError(RuntimeError):
    pass


def send_otp_sms(phone_e164: str, code: str) -> None:
    body = f"{code} is your Hiriq verification code. It expires in {settings.otp_ttl_seconds // 60} minutes. Do not share it."
    provider = settings.sms_provider

    if provider == "console":
        # Development only: the code appears in the terminal running uvicorn.
        log.warning("DEV OTP for %s: %s", phone_e164, code)
        print(f"[DEV OTP] {phone_e164}: {code}", flush=True)
        return

    if provider == "twilio":
        sid, token, sender = settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_from
        if not (sid and token and sender):
            raise SmsError("Twilio is selected but TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_FROM are not all set.")
        try:
            res = httpx.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                auth=(sid, token),
                data={"To": phone_e164, "From": sender, "Body": body},
                timeout=10,
            )
        except httpx.HTTPError as exc:
            raise SmsError("Could not reach the SMS provider.") from exc
        if res.status_code >= 300:
            log.error("Twilio rejected the message: %s %s", res.status_code, res.text[:300])
            raise SmsError("The SMS provider rejected the message.")
        return

    raise SmsError(f"Unknown SMS_PROVIDER '{provider}'. Use 'console' or 'twilio'.")
