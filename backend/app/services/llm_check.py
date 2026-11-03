"""Check your OpenRouter setup from the backend folder:

    python -m app.services.llm_check

It lists the free models your key can see, then sends one tiny request to each model in LLM_MODELS (or the defaults)
and prints what came back, including OpenRouter's own error text. Use it when "Write with AI" says the models are busy.
"""
from __future__ import annotations

import sys

import httpx

from app.services import llm

MODELS_URL = "https://openrouter.ai/api/v1/models"


def main() -> int:
    key = llm._api_key()
    if not key:
        print("OPENROUTER_API_KEY is empty. Add it to backend/.env and run this again.")
        return 1
    with llm._client_factory() as client:
        listing = client.get(MODELS_URL, headers={"Authorization": f"Bearer {key}"})
        if listing.status_code == 200:
            free = sorted(
                (m for m in listing.json().get("data", []) if str(m.get("id", "")).endswith(":free")),
                key=lambda m: -(m.get("context_length") or 0),
            )
            print(f"Free models your key can see ({len(free)}):")
            for m in free:
                print(f"  {m['id']}   context {m.get('context_length')}")
        else:
            print(f"Could not list models: http {listing.status_code} {llm._error_text(listing)}")

        print("\nTesting the models Hiriq will use (LLM_MODELS or the defaults):")
        worst = 0
        for model in llm._models():
            try:
                resp = client.post(
                    llm.OPENROUTER_URL,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Title": "Hiriq"},
                    json={"model": model, "messages": [{"role": "user", "content": 'Reply with exactly: {"ok": true}'}], "max_tokens": 200},
                )
            except httpx.HTTPError as exc:
                print(f"  FAIL  {model}: {type(exc).__name__}")
                worst = 1
                continue
            if resp.status_code == 200:
                print(f"  OK    {model}")
            else:
                worst = 1
                print(f"  FAIL  {model}: http {resp.status_code}: {llm._error_text(resp)}")
        if worst:
            print("\nA 404 usually means the model id no longer exists, or your OpenRouter privacy settings block free models "
                  "(openrouter.ai/settings/privacy). Pick ids from the list above and set LLM_MODELS in backend/.env.")
        return worst


if __name__ == "__main__":
    sys.exit(main())
