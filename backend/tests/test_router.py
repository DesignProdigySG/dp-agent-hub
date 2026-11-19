"""LLM router: routing decisions, fallback chain, credential checks, usage accounting."""

import pytest
from sqlmodel import select

from app.config import Settings
from app.llm.router import (
    Completion,
    LLMRouter,
    missing_credentials,
    plan_route,
    provider_of,
)


def settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_defaults_are_claude_tiers():
    s = settings()
    assert plan_route(s, "fast").models == ["anthropic/claude-haiku-5-5"]
    assert plan_route(s, "standard").models == ["anthropic/claude-sonnet-5-5"]
    assert plan_route(s, "strong").models == ["anthropic/claude-opus-5-5"]
    assert plan_route(s, "reasoning").tier == "standard"  # legacy role name


def test_auto_routing_escalates_and_steps_down():
    s = settings(llm_daily_budget_usd=10)
    assert plan_route(s, "fast", prompt_chars=400_000).tier == "standard"
    assert plan_route(s, "standard", stakes="high").tier == "strong"
    near = plan_route(s, "strong", spent_today=8.5)
    assert near.tier == "standard" and "near daily budget" in near.reasons
    blocked = plan_route(s, "fast", spent_today=10)
    assert blocked.blocked and blocked.models == []


def test_fixed_routing_ignores_heuristics_but_not_budget():
    s = settings(llm_routing="fixed", llm_daily_budget_usd=1)
    assert plan_route(s, "fast", prompt_chars=400_000, stakes="high").tier == "fast"
    assert plan_route(s, "fast", spent_today=2).blocked


def test_fallback_chain_is_deduplicated():
    s = settings(llm_fallback_models="openai/gpt-5-mini, anthropic/claude-sonnet-5-5,,")
    assert plan_route(s, "standard").models == ["anthropic/claude-sonnet-5-5",
                                                "openai/gpt-5-mini"]


def test_provider_parsing_and_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert provider_of("ollama/qwen2.5:14b") == ("ollama", "qwen2.5:14b")
    with pytest.raises(ValueError):
        provider_of("gpt-5")
    s = settings()
    assert missing_credentials(s, "anthropic/claude-opus-5-5") == "no Anthropic API key"
    assert missing_credentials(s, "ollama/llama3") == ""
    assert missing_credentials(settings(openai_api_key="k"), "openai/gpt-5") == ""


async def test_falls_through_to_next_model_and_records_usage(db, monkeypatch):
    from app.config import apply_overrides
    from app.db import LlmUsage, session

    apply_overrides({"anthropic_api_key": "sk-test", "openai_api_key": "sk-oai",
                     "llm_fallback_models": "openai/gpt-5-mini"})
    router = LLMRouter()
    tried = []

    async def fake_call(self, settings, spec, tier, system, messages, tools, max_tokens,
                        tool_choice=None):
        tried.append(spec)
        if spec.startswith("anthropic/"):
            raise RuntimeError("overloaded")
        return Completion("hello", 100, 20, 0.0012)

    monkeypatch.setattr(LLMRouter, "_call", fake_call)
    out = await router.ask("fast", "sys", "hi", agent_id="list_builder", task_id="t1")
    assert out == "hello"
    assert tried == ["anthropic/claude-haiku-5-5", "openai/gpt-5-mini"]
    with session() as s:
        rows = s.exec(select(LlmUsage).order_by(LlmUsage.id)).all()
    assert [(r.model, r.ok) for r in rows] == [("anthropic/claude-haiku-5-5", False),
                                               ("openai/gpt-5-mini", True)]
    assert rows[1].agent_id == "list_builder" and rows[1].cost_usd == pytest.approx(0.0012)
    assert await router.spent_today() == pytest.approx(0.0012)


async def test_returns_none_when_no_model_is_usable(db, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert await LLMRouter().ask("standard", "sys", "hi") is None


async def test_claude_call_shape(db, monkeypatch):
    """Claude goes through the Anthropic SDK with effort per tier and server-side fallback."""
    from types import SimpleNamespace

    from app.config import apply_overrides

    apply_overrides({"anthropic_api_key": "sk-test"})
    captured = {}

    def response(model):
        return SimpleNamespace(
            stop_reason="end_turn", model=model,
            content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text=" hi ")],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=500))

    class Messages:
        async def create(self, **kw):
            captured["plain"] = kw
            return response(kw["model"])

    class BetaMessages:
        async def create(self, **kw):
            captured["beta"] = kw
            return response(kw["model"])

    fake = SimpleNamespace(messages=Messages(), beta=SimpleNamespace(messages=BetaMessages()))
    router = LLMRouter()
    router._anthropic["sk-test"] = fake

    assert await router.ask("fast", "sys", "hi") == "hi"
    assert captured["plain"]["model"] == "claude-haiku-5-5"
    assert captured["plain"]["output_config"] == {"effort": "low"}
    assert "temperature" not in captured["plain"]

    assert await router.ask("strong", "sys", "hi") == "hi"
    assert captured["beta"]["model"] == "claude-opus-5-5"
    assert captured["beta"]["fallbacks"] == "default"
    assert captured["beta"]["betas"] == ["server-side-fallback-2026-07-01"]
    assert captured["beta"]["output_config"] == {"effort": "high"}


async def test_structured_output_sends_a_strict_schema_and_parses_the_reply(monkeypatch):
    """with_structured_output uses output_config.format (forced tool calls 400 on Opus 5.5)."""
    from typing import Literal

    from pydantic import BaseModel, Field

    from app.llm.chat_model import RouterChatModel
    from app.llm.router import Completion, LLMRouter, strict_schema

    class Inner(BaseModel):
        n: int = Field(ge=0, le=25)

    class Verdict(BaseModel):
        label: Literal["ok", "bad"]
        inner: Inner
        note: str = Field(default="", max_length=10)

    seen = {}

    async def fake_chat(self, tier, system, messages, tools, **kw):
        seen.update(tools=tools, schema=kw.get("json_schema"))
        return Completion('{"label": "ok", "inner": {"n": 7}, "note": ""}', 1, 1, 0)

    monkeypatch.setattr(LLMRouter, "chat", fake_chat)
    from app import deps as deps_module

    monkeypatch.setattr("app.llm.chat_model.get_deps",
                        lambda: type("D", (), {"llm": LLMRouter()})())
    out = await RouterChatModel().with_structured_output(Verdict).ainvoke("rate this")
    assert out == Verdict(label="ok", inner=Inner(n=7)) and seen["tools"] == []
    strict = strict_schema(seen["schema"])
    assert strict["additionalProperties"] is False
    assert strict["required"] == ["label", "inner", "note"]
    inner = strict["$defs"]["Inner"]
    assert inner["additionalProperties"] is False and "maximum" not in inner["properties"]["n"]
    assert "maxLength" not in strict["properties"]["note"] and "default" not in str(strict)
    del deps_module
