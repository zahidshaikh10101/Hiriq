"""The language-model layer. Every AI feature (JD writer, resume parser, matcher, ask-the-pool) calls this one place.

OpenRouter is the provider. It tries the primary model, then the backup. Each call is logged to `ai_calls`
(model, purpose, success, time, tokens; never the prompt or any resume text) for the admin AI-usage panel.

Settings are read when a call is made, not when the module loads, so editing backend/.env and restarting is enough
and import order can never hide the key.

    OPENROUTER_API_KEY   required
    LLM_MODELS           optional, comma separated, first = primary, rest = backups
    LLM_TIMEOUT_SECONDS  optional, default 60
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, ValidationError

from app.core import config  # noqa: F401  (importing it loads backend/.env)
from app.db import session as db_session

log = logging.getLogger("hiriq.llm")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# Free models come and go on OpenRouter (gpt-oss-120b and llama-3.3-70b both stopped being free). If one disappears,
# run `python -m app.services.llm_check` and change LLM_MODELS in .env; no code change needed.
# The first model is tried first. A large model reads resumes and keeps to the JSON format far more reliably than a 2.6B one,
# so the big one leads and the small, fast one is the backup. Check these ids with llm_check: free ids change without notice.
DEFAULT_MODELS = ["nvidia/nemotron-3-ultra-550b-a55b:free", "liquid/lfm-2.5-2.6b:free"]


class LLMError(Exception):
    """`code` is stable for the API and tests; `message` is safe to show the user."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class LLMResult:
    data: BaseModel
    model: str


# ---- settings (read at call time) ----
def _api_key() -> str:
    return os.getenv("OPENROUTER_API_KEY", "").strip()


def _models() -> list[str]:
    raw = os.getenv("LLM_MODELS", "")
    models = [m.strip() for m in raw.split(",") if m.strip()]
    return models or list(DEFAULT_MODELS)


def _timeout() -> float:
    try:
        return float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    except ValueError:
        return 60.0


# ---- seams that tests replace ----
def _make_client() -> httpx.Client:
    return httpx.Client(timeout=_timeout())


_client_factory = _make_client


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


# ---- usage log ----
def _record(owner_id: uuid.UUID | None, purpose: str, model: str, ok: bool, started: float,
            usage: dict | None = None, error: str | None = None) -> None:
    """Never lets a logging problem break the feature."""
    if db_session.SessionLocal is None:
        return
    try:
        from app.db.recruiter_models import AiCall

        usage = usage or {}
        with db_session.SessionLocal() as db:
            db.add(AiCall(
                owner_id=owner_id, purpose=purpose, model=model[:120], ok=ok, error=(error or None) and error[:200],
                latency_ms=int((time.monotonic() - started) * 1000),
                prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"),
            ))
            db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not log AI call: %s", exc)


# ---- parsing the model's reply ----
def extract_json(text: str) -> dict:
    """Pull the JSON object out of a reply that may have code fences or chatter around it."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in the reply")
    obj = json.loads(text[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("the reply is not a JSON object")
    return obj


def _one_request(client: httpx.Client, model: str, messages: list[dict], temperature: float, max_tokens: int) -> tuple[str, dict]:
    resp = client.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json", "X-Title": "Hiriq"},
        json={"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
    )
    if resp.status_code in (401, 403):
        raise LLMError("bad_key", "The AI key was rejected. Check OPENROUTER_API_KEY in backend/.env.")
    if resp.status_code != 200:
        detail = _error_text(resp)
        log.warning("OpenRouter answered %s for %s: %s", resp.status_code, model, detail)
        raise _Transient(f"http {resp.status_code}", retry_same=resp.status_code >= 500, detail=detail)
    try:
        body = resp.json()
        content = body["choices"][0]["message"].get("content")
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise _Transient("unreadable response", retry_same=True)
    return content or "", body.get("usage") or {}


def _error_text(resp: httpx.Response) -> str:
    """OpenRouter explains failures in the body: {"error": {"message": "..."}}. Keep it short."""
    try:
        err = resp.json().get("error")
        text = err.get("message") if isinstance(err, dict) else err
    except (ValueError, AttributeError):
        text = None
    return " ".join(str(text or resp.text or "").split())[:200]


class _Transient(Exception):
    """A failure worth trying the next model for (and, for server errors, this model once more)."""

    def __init__(self, reason: str, retry_same: bool = False, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_same = retry_same
        self.detail = detail


def complete_json(system: str, user: str, schema: type[BaseModel], *, purpose: str, owner_id: uuid.UUID | None = None,
                  temperature: float = 0.2, max_tokens: int = 3000) -> LLMResult:
    """Ask the model for a JSON object that fits `schema`. Raises LLMError with a user-safe message.

    Per model: one retry after a server error, timeout or a reply that does not fit the schema (the retry tells the
    model what was wrong). A rate limit or a missing model moves straight on to the next model.
    max_tokens is generous on purpose: reasoning models spend part of it thinking before they write the answer.
    """
    if not _api_key():
        raise LLMError("no_key", "AI is not set up yet. Add OPENROUTER_API_KEY to backend/.env and restart the server.")

    base = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    last_reason = "no reply"
    bad_output = False
    statuses: list[str] = []
    with _client_factory() as client:
        for model in _models():
            messages = list(base)
            for attempt in (1, 2):
                started = time.monotonic()
                try:
                    text, usage = _one_request(client, model, messages, temperature, max_tokens)
                except LLMError as exc:
                    _record(owner_id, purpose, model, False, started, error=exc.code)
                    raise
                except _Transient as exc:
                    last_reason = exc.reason
                    statuses.append(exc.reason)
                    _record(owner_id, purpose, model, False, started, error=f"{exc.reason}: {exc.detail}" if exc.detail else exc.reason)
                    if attempt == 1 and exc.retry_same:
                        _sleep(1.0)
                        continue
                    break
                except httpx.HTTPError as exc:
                    last_reason = type(exc).__name__
                    _record(owner_id, purpose, model, False, started, error=last_reason)
                    if attempt == 1:
                        _sleep(1.0)
                        continue
                    break
                try:
                    parsed = schema.model_validate(extract_json(text))
                except (ValueError, ValidationError) as exc:
                    last_reason, bad_output = "reply did not fit the format", True
                    _record(owner_id, purpose, model, False, started, usage, error="bad_output")
                    if attempt == 1:
                        messages = base + [
                            {"role": "assistant", "content": text[:1500]},
                            {"role": "user", "content": "That reply could not be used: " + str(exc)[:300] +
                             "\nReply again with ONLY the JSON object, no other text."},
                        ]
                        continue
                    break
                _record(owner_id, purpose, model, True, started, usage)
                return LLMResult(data=parsed, model=model)

    log.warning("All models failed for %s: %s", purpose, last_reason)
    if statuses and all(r == "http 404" for r in statuses) and not bad_output:
        raise LLMError("no_model", "OpenRouter could not find any of the configured models. Run `python -m app.services.llm_check` "
                       "to see which models work for your account, then set LLM_MODELS in backend/.env.")
    if bad_output and last_reason == "reply did not fit the format":
        raise LLMError("bad_output", "The AI reply could not be read. Try again.")
    raise LLMError("unavailable", "The AI is busy right now. Try again in a minute.")