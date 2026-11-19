"""LLM router: agents ask for a tier, the router picks and calls a model.

Tiers are fast / standard / strong, each mapped to a "provider/model" in Settings (Claude by
default). With routing set to "auto" the router escalates large or high-stakes prompts and
steps down a tier as the daily budget runs out. Every attempt — including failed ones that
fall through to the next model — is recorded in llm_usage with tokens and cost.

Claude models are called through the official Anthropic SDK; every other provider goes
through LiteLLM. `ask` returns plain text, or None when no model could answer. `chat` runs
one turn of a tool-calling conversation; agents reach it through LangChain as `RouterChatModel`
(app/llm/chat_model.py). It uses a provider-neutral message format:

    {"role": "user", "content": str}
    {"role": "assistant", "content": str, "tool_calls": [{"id", "name", "args"}]}
    {"role": "tool", "tool_call_id": str, "name": str, "content": str, "is_error": bool}

so a conversation can fall back from Claude to another provider mid-run.
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import anthropic
from sqlalchemy import func
from sqlmodel import select

from app.config import Settings, get_settings
from app.db import LlmUsage, session

log = logging.getLogger(__name__)

Tier = Literal["fast", "standard", "strong"]
TIERS: tuple[Tier, ...] = ("fast", "standard", "strong")
EFFORT: dict[Tier, str] = {"fast": "low", "standard": "medium", "strong": "high"}

# USD per million tokens (input, output), Anthropic first-party pricing.
CLAUDE_PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.0, 5.0),
}
# Models that accept Anthropic's server-side refusal fallback (`fallbacks: "default"`).
SERVER_FALLBACK = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
LARGE_PROMPT_TOKENS = 50_000


class NoAnswer(RuntimeError):
    pass


@dataclass
class Route:
    tier: Tier
    models: list[str]
    reasons: list[str] = field(default_factory=list)
    blocked: str = ""


def normalize_tier(tier: str) -> Tier:
    return "standard" if tier == "reasoning" else tier if tier in TIERS else "standard"


def _step(tier: Tier, delta: int) -> Tier:
    return TIERS[max(0, min(len(TIERS) - 1, TIERS.index(tier) + delta))]


def provider_of(spec: str) -> tuple[str, str]:
    provider, sep, model = spec.strip().partition("/")
    if not sep or not provider or not model:
        raise ValueError(f"model {spec!r} must look like provider/model")
    return provider, model


def plan_route(settings: Settings, tier: str, *, prompt_chars: int = 0,
               stakes: Literal["normal", "high"] = "normal",
               spent_today: float = 0.0) -> Route:
    """Pure routing decision (no I/O) so it can be tested and shown in the UI."""
    t = normalize_tier(tier)
    route = Route(tier=t, models=[])
    budget = settings.llm_daily_budget_usd
    if budget > 0 and spent_today >= budget:
        route.blocked = f"daily LLM budget of ${budget:.2f} reached"
        return route
    if settings.llm_routing == "auto":
        if prompt_chars // 4 > LARGE_PROMPT_TOKENS and t == "fast":
            t = "standard"
            route.reasons.append("large prompt")
        if stakes == "high" and t != "strong":
            t = _step(t, +1)
            route.reasons.append("high stakes")
        if budget > 0 and spent_today >= 0.8 * budget and t != "fast":
            t = _step(t, -1)
            route.reasons.append("near daily budget")
    route.tier = t
    primary = getattr(settings, f"llm_{t}_model")
    fallbacks = [m.strip() for m in settings.llm_fallback_models.split(",")]
    for spec in [primary, *fallbacks]:
        if spec and spec not in route.models:
            route.models.append(spec)
    return route


def missing_credentials(settings: Settings, spec: str) -> str:
    """Why a model can't be called with the current settings ('' if it can)."""
    try:
        provider, _ = provider_of(spec)
    except ValueError as e:
        return str(e)
    if provider == "anthropic":
        return "" if settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY") else \
            "no Anthropic API key"
    if provider == "openai" and not settings.openai_api_key:
        return "no OpenAI API key"
    if provider == "gemini" and not settings.gemini_api_key:
        return "no Gemini API key"
    if provider == "azure" and not (settings.azure_openai_api_key
                                    and settings.azure_openai_endpoint):
        return "no Azure OpenAI key/endpoint"
    return ""


@dataclass
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)  # [{id, name, args}]
    model: str = ""


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema for the arguments


# --- message format conversion (pure, tested) ----------------------------------------------


def to_anthropic(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            blocks: list[dict] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            blocks += [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["args"]}
                       for c in m.get("tool_calls", [])]
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "…"}]})
        elif m["role"] == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"],
                     "content": m["content"], "is_error": bool(m.get("is_error"))}
            # Results for one assistant turn go back together in a single user message.
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return out


def to_openai(system: str, messages: list[dict]) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}]
    for m in messages:
        if m["role"] == "assistant":
            msg: dict = {"role": "assistant", "content": m.get("content") or None}
            if m.get("tool_calls"):
                msg["tool_calls"] = [{"id": c["id"], "type": "function",
                                      "function": {"name": c["name"],
                                                   "arguments": json.dumps(c["args"])}}
                                     for c in m["tool_calls"]]
            out.append(msg)
        elif m["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"],
                        "content": m["content"]})
        else:
            out.append({"role": "user", "content": m["content"]})
    return out


def _parse_args(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except ValueError:
        return {"_unparsed": str(raw)}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


# Structured outputs accept a subset of JSON Schema: every object closed, and no numeric or
# length constraints (callers validate those after parsing, e.g. with pydantic).
_UNSUPPORTED = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
                "minLength", "maxLength", "minItems", "maxItems", "pattern", "default", "title"}


def strict_schema(schema: Any) -> Any:
    """A copy of `schema` that structured outputs accept: objects get
    additionalProperties=false and require every property; unsupported keywords go."""
    if isinstance(schema, list):
        return [strict_schema(x) for x in schema]
    if not isinstance(schema, dict):
        return schema
    out = {k: strict_schema(v) for k, v in schema.items() if k not in _UNSUPPORTED}
    if out.get("type") == "object" or "properties" in out:
        out["additionalProperties"] = False
        out["required"] = list(out.get("properties", {}))
    return out


class LLMRouter:
    def __init__(self) -> None:
        self._anthropic: dict[str, anthropic.AsyncAnthropic] = {}
        self._spend_cache: tuple[float, float] = (0.0, 0.0)  # (monotonic ts, usd)

    # --- public -----------------------------------------------------------------------------

    async def ask(self, tier: str, system: str, prompt: str, *, agent_id: str | None = None,
                  task_id: str | None = None, stakes: Literal["normal", "high"] = "normal",
                  max_tokens: int = 16_000) -> str | None:
        messages = [{"role": "user", "content": prompt}]
        result = await self._route(tier, system, messages, [], agent_id=agent_id,
                                   task_id=task_id, stakes=stakes, max_tokens=max_tokens)
        return result.text if result else None

    async def chat(self, tier: str, system: str, messages: list[dict], tools: list[ToolDef], *,
                   agent_id: str | None = None, task_id: str | None = None,
                   stakes: Literal["normal", "high"] = "normal",
                   max_tokens: int = 16_000,
                   json_schema: dict[str, Any] | None = None) -> Completion | None:
        """One assistant turn of a tool-calling conversation (None if no model answered).
        `json_schema` asks for a JSON reply that matches it (structured outputs)."""
        return await self._route(tier, system, messages, tools, agent_id=agent_id,
                                 task_id=task_id, stakes=stakes, max_tokens=max_tokens,
                                 json_schema=json_schema)

    async def _route(self, tier, system, messages, tools, *, agent_id, task_id, stakes,
                     max_tokens, json_schema=None) -> Completion | None:
        settings = get_settings()
        chars = len(system) + sum(len(str(m.get("content", ""))) for m in messages)
        route = plan_route(settings, tier, prompt_chars=chars, stakes=stakes,
                           spent_today=await self.spent_today())
        if route.blocked:
            log.warning("LLM call skipped: %s", route.blocked)
            return None
        for spec in route.models:
            if why := missing_credentials(settings, spec):
                log.info("skipping %s: %s", spec, why)
                continue
            started = time.monotonic()
            try:
                result = await self._call(settings, spec, route.tier, system, messages, tools,
                                          max_tokens, json_schema)
            except Exception as e:  # provider error, refusal, timeout... try the next model
                await self._record(agent_id, task_id, route.tier, spec, False, started,
                                   error=f"{type(e).__name__}: {e}"[:500])
                log.warning("LLM %s failed: %s", spec, e)
                continue
            await self._record(agent_id, task_id, route.tier, spec, True, started, result)
            result.model = spec
            return result
        return None

    async def test(self, spec: str) -> dict:
        """Tiny round-trip used by the Settings page's Test button."""
        settings = get_settings()
        if why := missing_credentials(settings, spec):
            return {"ok": False, "model": spec, "error": why}
        started = time.monotonic()
        try:
            r = await self._call(settings, spec, "fast", "Reply with exactly: OK",
                                 [{"role": "user", "content": "ping"}], [], 32)
        except Exception as e:
            return {"ok": False, "model": spec, "error": f"{type(e).__name__}: {e}"[:300]}
        await self._record(None, None, "test", spec, True, started, r)
        return {"ok": True, "model": spec, "reply": r.text[:60],
                "latency_ms": int((time.monotonic() - started) * 1000)}

    async def spent_today(self) -> float:
        ts, usd = self._spend_cache
        if time.monotonic() - ts < 15:
            return usd
        usd = await asyncio.to_thread(_spend_since, _utc_midnight())
        self._spend_cache = (time.monotonic(), usd)
        return usd

    # --- providers --------------------------------------------------------------------------

    async def _call(self, settings: Settings, spec: str, tier: str, system: str,
                    messages: list[dict], tools: list[ToolDef], max_tokens: int,
                    json_schema: dict[str, Any] | None = None) -> Completion:
        provider, model = provider_of(spec)
        effort = EFFORT.get(tier, "medium")  # type: ignore[arg-type]
        if provider == "anthropic":
            return await self._call_anthropic(settings, model, effort, system, messages, tools,
                                              max_tokens, json_schema)
        return await self._call_litellm(settings, spec, provider, system, messages, tools,
                                        max_tokens, json_schema)

    async def _call_anthropic(self, settings: Settings, model: str, effort: str, system: str,
                              messages: list[dict], tools: list[ToolDef],
                              max_tokens: int,
                              json_schema: dict[str, Any] | None = None) -> Completion:
        key = settings.anthropic_api_key or ""
        client = self._anthropic.get(key)
        if client is None:
            client = anthropic.AsyncAnthropic(api_key=key or None, timeout=180.0)
            self._anthropic[key] = client
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            # Cache the system prompt (and the tool list before it): agent loops resend both
            # on every turn.
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": to_anthropic(messages),
            "output_config": {"effort": effort},
        }
        if json_schema:  # structured outputs: the reply's text is JSON matching the schema
            params["output_config"]["format"] = {"type": "json_schema",
                                                 "schema": strict_schema(json_schema)}
        if tools:
            params["tools"] = [{"name": t.name, "description": t.description,
                                "input_schema": t.parameters} for t in tools]
        if model in SERVER_FALLBACK:
            # If the model declines on safety grounds, the API retries on a suitable model
            # within the same call instead of returning a refusal.
            response = await client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params)
        else:
            response = await client.messages.create(**params)
        if response.stop_reason == "refusal":
            raise NoAnswer(f"{model} declined the request")
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        calls = [{"id": b.id, "name": b.name, "args": dict(b.input or {})}
                 for b in response.content if b.type == "tool_use"]
        usage = response.usage
        served = getattr(response, "model", model) or model
        price = CLAUDE_PRICES.get(served) or CLAUDE_PRICES.get(model)
        cached_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cached_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cost = ((usage.input_tokens + 1.25 * cached_write + 0.1 * cached_read) * price[0]
                + usage.output_tokens * price[1]) / 1e6 if price else None
        return Completion(text, usage.input_tokens + cached_read + cached_write,
                          usage.output_tokens, cost, calls)

    async def _call_litellm(self, settings: Settings, spec: str, provider: str, system: str,
                            messages: list[dict], tools: list[ToolDef],
                            max_tokens: int,
                            json_schema: dict[str, Any] | None = None) -> Completion:
        import litellm  # heavy import; only load when a non-Anthropic model is used

        litellm.telemetry = False
        kwargs: dict = provider_kwargs(settings, provider)
        if tools:
            kwargs["tools"] = [{"type": "function",
                                "function": {"name": t.name, "description": t.description,
                                             "parameters": t.parameters}} for t in tools]
        if json_schema:
            kwargs["response_format"] = {"type": "json_schema", "json_schema": {
                "name": json_schema.get("title", "output"), "strict": True,
                "schema": strict_schema(json_schema)}}
        response = await litellm.acompletion(
            model=spec,
            messages=to_openai(system, messages),
            max_tokens=max_tokens,
            drop_params=True,
            timeout=180,
            **kwargs,
        )
        message = response.choices[0].message
        text = (message.content or "").strip()
        calls = [{"id": c.id, "name": c.function.name, "args": _parse_args(c.function.arguments)}
                 for c in (getattr(message, "tool_calls", None) or [])]
        usage = getattr(response, "usage", None)
        try:
            cost = float(litellm.completion_cost(completion_response=response))
        except Exception:
            cost = None
        return Completion(text, getattr(usage, "prompt_tokens", 0) or 0,
                          getattr(usage, "completion_tokens", 0) or 0, cost, calls)

    async def _record(self, agent_id, task_id, tier, spec, ok, started, result=None, error=""):
        row = LlmUsage(
            agent_id=agent_id, task_id=task_id, tier=tier, model=spec, ok=ok,
            input_tokens=result.input_tokens if result else 0,
            output_tokens=result.output_tokens if result else 0,
            cost_usd=result.cost_usd if result else None,
            latency_ms=int((time.monotonic() - started) * 1000), error=error,
        )
        try:
            await asyncio.to_thread(_insert, row)
        except Exception:
            log.exception("could not record LLM usage")
        if result and result.cost_usd:
            ts, usd = self._spend_cache
            self._spend_cache = (ts, usd + result.cost_usd)


def provider_kwargs(settings: Settings, provider: str) -> dict[str, Any]:
    """Credentials LiteLLM needs for a provider (shared by chat and embeddings)."""
    if provider == "openai":
        return {"api_key": settings.openai_api_key}
    if provider == "gemini":
        return {"api_key": settings.gemini_api_key}
    if provider == "azure":
        return {"api_key": settings.azure_openai_api_key,
                "api_base": settings.azure_openai_endpoint,
                "api_version": os.environ.get("AZURE_API_VERSION", "2024-10-21")}
    if provider == "ollama":
        return {"api_base": settings.ollama_base_url}
    if provider == "voyage":
        return {"api_key": settings.voyage_api_key}
    return {}


def _utc_midnight() -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def _spend_since(since: datetime) -> float:
    with session() as s:
        total = s.exec(select(func.coalesce(func.sum(LlmUsage.cost_usd), 0.0))
                       .where(LlmUsage.ts >= since)).one()
    return float(total or 0.0)


def _insert(row: LlmUsage) -> None:
    with session() as s:
        s.add(row)
        s.commit()
