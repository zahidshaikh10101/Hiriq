"""The LLM layer: model fallback, retries, JSON repair, key handling, and the usage log. No network: httpx is mocked."""
import importlib
import json

import httpx
import pytest
from pydantic import BaseModel

RELOAD = ["app.core.config", "app.db.session", "app.db.init_db", "app.services.llm"]


class Out(BaseModel):
    answer: str


class Env:
    pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODELS", "primary/model:free,backup/model:free")
    mods = {n: importlib.reload(importlib.import_module(n)) for n in RELOAD}
    mods["app.db.init_db"].init_db()
    e = Env()
    e.llm, e.session, e.calls, e.sleeps = mods["app.services.llm"], mods["app.db.session"], [], []
    e.llm._sleep = e.sleeps.append  # never really wait

    def serve(handler):
        def transport(request):
            body = json.loads(request.content)
            e.calls.append(body)
            return handler(body["model"], len(e.calls), request)

        e.llm._client_factory = lambda: httpx.Client(transport=httpx.MockTransport(transport))

    e.serve = serve
    return e


def reply(content, usage=None):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5}})


def ask(env, **kw):
    return env.llm.complete_json("sys", "user", Out, purpose="jd", **kw)


def logged(env):
    from sqlalchemy import select
    from app.db.recruiter_models import AiCall

    with env.session.SessionLocal() as db:
        return [(c.model, c.ok, c.error, c.purpose) for c in db.scalars(select(AiCall).order_by(AiCall.id)).all()]


def test_happy_path_uses_the_primary_model_and_logs_it(env):
    env.serve(lambda model, n, req: reply('{"answer": "hi"}'))
    r = ask(env)
    assert r.data.answer == "hi" and r.model == "primary/model:free" and len(env.calls) == 1
    assert logged(env) == [("primary/model:free", True, None, "jd")]
    assert env.calls[0]["messages"][0]["role"] == "system"


def test_json_inside_code_fences_and_chatter_is_accepted(env):
    env.serve(lambda m, n, r: reply('Sure! Here you go:\n```json\n{"answer": "fenced"}\n```\nHope that helps.'))
    assert ask(env).data.answer == "fenced"


def test_rate_limited_primary_falls_back_to_the_backup_at_once(env):
    env.serve(lambda model, n, req: httpx.Response(429) if model.startswith("primary") else reply('{"answer": "from backup"}'))
    r = ask(env)
    assert r.model == "backup/model:free" and r.data.answer == "from backup"
    assert len(env.calls) == 2 and env.sleeps == []  # a 429 is not retried on the same model
    assert [x[:2] for x in logged(env)] == [("primary/model:free", False), ("backup/model:free", True)]


def test_server_error_is_retried_once_on_the_same_model(env):
    env.serve(lambda model, n, req: httpx.Response(503) if n == 1 else reply('{"answer": "second try"}'))
    r = ask(env)
    assert r.model == "primary/model:free" and len(env.calls) == 2 and env.sleeps == [1.0]


def test_a_bad_reply_gets_one_repair_attempt_that_says_what_was_wrong(env):
    env.serve(lambda model, n, req: reply("I cannot do that") if n == 1 else reply('{"answer": "fixed"}'))
    r = ask(env)
    assert r.data.answer == "fixed" and r.model == "primary/model:free"
    repair = env.calls[1]["messages"]
    assert repair[-1]["role"] == "user" and "ONLY the JSON" in repair[-1]["content"] and repair[-2]["role"] == "assistant"


def test_reply_that_misses_a_required_field_counts_as_bad(env):
    env.serve(lambda model, n, req: reply('{"wrong": 1}') if model.startswith("primary") else reply('{"answer": "ok"}'))
    r = ask(env)
    assert r.model == "backup/model:free" and len(env.calls) == 3  # primary twice (repair), then backup


def test_empty_content_from_a_reasoning_model_is_handled(env):
    env.serve(lambda model, n, req: httpx.Response(200, json={"choices": [{"message": {"content": None, "reasoning": "thinking..."}}]}) if n == 1 else reply('{"answer": "ok"}'))
    assert ask(env).data.answer == "ok"


def test_all_models_failing_gives_a_friendly_error_and_logs_every_attempt(env):
    env.serve(lambda m, n, r: httpx.Response(429))
    with pytest.raises(env.llm.LLMError) as e:
        ask(env)
    assert e.value.code == "unavailable" and "busy" in e.value.message
    assert len(logged(env)) == 2 and not any(ok for _, ok, _, _ in logged(env))


def test_garbage_from_every_model_is_bad_output(env):
    env.serve(lambda m, n, r: reply("nope"))
    with pytest.raises(env.llm.LLMError) as e:
        ask(env)
    assert e.value.code == "bad_output"


def test_network_error_falls_back(env):
    def handler(model, n, req):
        if model.startswith("primary"):
            raise httpx.ConnectError("boom")
        return reply('{"answer": "ok"}')

    env.serve(handler)
    assert ask(env).model == "backup/model:free"


def test_missing_key_never_calls_out(env, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    env.serve(lambda m, n, r: pytest.fail("must not call the network"))
    with pytest.raises(env.llm.LLMError) as e:
        ask(env)
    assert e.value.code == "no_key" and "OPENROUTER_API_KEY" in e.value.message


def test_rejected_key_stops_at_once(env):
    env.serve(lambda m, n, r: httpx.Response(401))
    with pytest.raises(env.llm.LLMError) as e:
        ask(env)
    assert e.value.code == "bad_key" and len(env.calls) == 1


def test_key_and_models_are_read_at_call_time(env, monkeypatch):
    env.serve(lambda model, n, req: reply('{"answer": "x"}'))
    monkeypatch.setenv("LLM_MODELS", "other/model:free")
    assert ask(env).model == "other/model:free"
    monkeypatch.delenv("LLM_MODELS")
    assert env.llm._models() == env.llm.DEFAULT_MODELS


def test_authorization_header_carries_the_key(env):
    seen = {}

    def handler(model, n, req):
        seen["auth"] = req.headers["authorization"]
        return reply('{"answer": "x"}')

    env.serve(handler)
    ask(env)
    assert seen["auth"] == "Bearer sk-test"


def test_extract_json_rejects_non_objects(env):
    with pytest.raises(ValueError):
        env.llm.extract_json("[1, 2, 3]")
    with pytest.raises(ValueError):
        env.llm.extract_json("no braces here")


def test_every_model_missing_gives_a_specific_message_and_the_reason_is_logged(env):
    env.serve(lambda m, n, r: httpx.Response(404, json={"error": {"message": "No endpoints found matching your data policy"}}))
    with pytest.raises(env.llm.LLMError) as e:
        ask(env)
    assert e.value.code == "no_model" and "llm_check" in e.value.message and "LLM_MODELS" in e.value.message
    errs = [err for _, _, err, _ in logged(env)]
    assert len(errs) == 2 and all(x.startswith("http 404: No endpoints found") for x in errs)


def test_one_missing_model_still_falls_back(env):
    env.serve(lambda model, n, req: httpx.Response(404) if model.startswith("primary") else reply('{"answer": "ok"}'))
    assert ask(env).model == "backup/model:free"


def test_llm_check_reports_each_model(env, capsys):
    check = importlib.reload(importlib.import_module("app.services.llm_check"))

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "a/free-one:free", "context_length": 8000}, {"id": "paid/model", "context_length": 1}]})
        model = json.loads(req.content)["model"]
        return reply('{"ok": true}') if model.startswith("backup") else httpx.Response(404, json={"error": {"message": "nope"}})

    env.llm._client_factory = lambda: httpx.Client(transport=httpx.MockTransport(handler))
    assert check.main() == 1
    out = capsys.readouterr().out
    assert "a/free-one:free" in out and "paid/model" not in out
    assert "OK    backup/model:free" in out and "FAIL  primary/model:free: http 404: nope" in out and "privacy" in out
