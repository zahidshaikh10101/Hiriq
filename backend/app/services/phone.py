from __future__ import annotations

import phonenumbers


class PhoneError(ValueError):
    pass


def normalize(raw: str) -> str:
    """Return E.164 (+919876543210). The frontend sends country code + digits, e.g. '+91 98765 43210'."""
    text = (raw or "").strip()
    if not text.startswith("+"):
        raise PhoneError("Enter the number with its country code, like +91 98765 43210.")
    try:
        parsed = phonenumbers.parse(text, None)
    except phonenumbers.NumberParseException:
        raise PhoneError("Enter a valid mobile number.") from None
    if not phonenumbers.is_valid_number(parsed):
        raise PhoneError("Enter a valid mobile number.")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
