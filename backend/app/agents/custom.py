"""The LangChain `create_agent` graph every agent runs, configured by its agent_def row.

One graph is compiled at startup and shared; everything per-agent comes from the config
pinned into the run's state (`registry.run_config`) and is applied by middleware:

  * AutonomyApproval  — LangChain's HumanInTheLoopMiddleware; pauses a turn's tool calls
                         for review when their risk needs approval under the agent's
                         autonomy setting. Reviewers can approve, edit the arguments, or reject.
  * StepLimit         — ModelCallLimitMiddleware with the agent's max_steps.
  * ToolErrorMiddleware — tool failures go back to the model as error results.
  * HubRuntime        — the agent's prompt (instructions, skills, knowledge, memories),
                         model tier and tool set, plus the 3D/board progress events.

Tools are resolved per run (LangChain's dynamic-tools pattern: `wrap_model_call` picks them,
`wrap_tool_call` binds them), so MCP tools loaded at runtime work the same as the hub's own.
Long-term memory lives in the LangGraph store under ("agents", <agent_id>, "memories").
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, NotRequired

from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    HumanInTheLoopMiddleware,
    InterruptOnConfig,
    ModelCallLimitMiddleware,
    ToolErrorMiddleware,
    hook_config,
)
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from app import handoff
from app.agents.base import Reporter
from app.agents.context import custom_system_prompt
from app.agents.tools import memory_namespace, needs_approval, risk_of, tools_for, zone_of
from app.db import Task, session
from app.events.schema import Handoff, MetricValue, Zone
from app.llm.chat_model import RouterChatModel
from app.marketo import links

log = logging.getLogger(__name__)
TOOL_TIMEOUT_S = 120
RESULT_CHARS = 12_000  # per tool result sent back to the model
DEFAULT_MAX_STEPS = 12


class CustomState(AgentState):
    task_id: NotRequired[str]
    agent_id: NotRequired[str]
    params: NotRequired[dict[str, Any]]
    zone: NotRequired[str]
    metrics: NotRequired[dict[str, MetricValue]]
    config: NotRequired[dict[str, Any]]  # pinned agent config (registry.run_config)
    brief: NotRequired[dict[str, Any]]  # task title / description
    system: NotRequired[str]
    toolset: NotRequired[dict[str, str]]  # tool name -> risk, fixed at the start of the run
    result: NotRequired[str]


def brief_text(title: str, description: str = "", params: dict | None = None) -> str:
    lines = [f"Task: {title}"]
    if description:
        lines.append(description)
    shown = {k: v for k, v in (params or {}).items() if k != "revisions"}  # bookkeeping
    if shown:
        lines.append("Parameters:\n" + json.dumps(shown, indent=2))
    return "\n\n".join(lines)


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > RESULT_CHARS:
        return value[:RESULT_CHARS] + "… [truncated]"
    return value


@dataclass
class _Live:
    """In-process bookkeeping for a running task: tool calls run one at a time (the avatar
    walks between zones, and Marketo calls stay sequential) and the current zone."""
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    zone: str | None = None


_live: dict[str, _Live] = {}


def _reporter(state: dict) -> Reporter:
    r = Reporter(state)
    if (live := _live.get(r.task_id or "")) and live.zone:
        r.zone = Zone(live.zone)
    return r


def _link_changes(tool_name: str, args: dict, content: Any, state: dict) -> Any:
    """Record what a Marketo write changed (with links) and tell the agent the links."""
    try:
        found = links.changes_from_tool(tool_name, args, content)
        recorded = [links.record(task_id=state.get("task_id"), agent_id=state["agent_id"],
                                 kind=c["kind"], object_id=c["object_id"], action=c["action"],
                                 name=c.get("name", ""), detail=c.get("detail", ""))
                    for c in found]
    except Exception:  # links are a convenience: never fail the tool call over them
        log.exception("recording Marketo changes for %s failed", tool_name)
        return content
    return f"{content}{links.note(recorded)}" if recorded and isinstance(content, str) \
        else content


def _announce_handoff(r: Reporter, content: Any) -> None:
    """A hand-off went through: send the avatar over to the receiver (the floor event)."""
    data = links.parse(content)
    task_id = data.get("task_id") if isinstance(data, dict) else None
    if not task_id:
        return  # the tool refused (its error is in the content)
    with session() as s:
        task = s.get(Task, task_id)
    if task is None:
        return
    line_from, line_to = handoff.lines(task)
    r.handoff(Handoff(to_agent_id=task.agent_id, task_id=task.id, line_from=line_from,
                      line_to=line_to), f"Handing off to {task.params.get('to_agent_name')}")


class HubRuntime(AgentMiddleware):
    state_schema = CustomState

    async def abefore_agent(self, state, runtime) -> dict | None:
        r = _reporter(state)
        cfg = state["config"]
        memories: list[dict[str, str]] = []
        if cfg.get("memory_enabled") and runtime.store is not None:
            items = await runtime.store.asearch(memory_namespace(r.agent_id), limit=200)
            items.sort(key=lambda i: i.updated_at, reverse=True)
            memories = [{"id": i.key, "text": i.value.get("text", "")} for i in items[:30]]
        tools, _ = await tools_for(cfg)
        await r.travel(Zone(cfg.get("home_zone", Zone.BREAK_ROOM)), "Heading to my desk...")
        return r.patch(system=await custom_system_prompt(cfg, memories),
                       toolset={name: risk_of(t) for name, t in tools.items()})

    async def abefore_model(self, state, runtime) -> dict | None:
        r = _reporter(state)
        steps = sum(isinstance(m, AIMessage) for m in state["messages"])
        await r.work("think", "Planning..." if steps == 0 else "Reviewing results...",
                     steps=steps, tool_calls=sum(isinstance(m, ToolMessage)
                                                 and m.status != "error"
                                                 for m in state["messages"]))
        return r.patch()

    async def awrap_model_call(self, request, handler):
        state, cfg = request.state, request.state["config"]
        tools, _ = await tools_for(cfg)
        return await handler(request.override(
            model=RouterChatModel(tier=cfg.get("model_tier", "standard"),
                                  agent_id=state["agent_id"], task_id=state.get("task_id")),
            tools=[tools[n] for n in state.get("toolset", {}) if n in tools],
            system_message=SystemMessage(state.get("system", "")),
        ))

    async def awrap_tool_call(self, request, handler):
        call, state = request.tool_call, request.state
        tools, _ = await tools_for(state["config"])
        t = tools.get(call["name"]) if call["name"] in state.get("toolset", {}) else None
        if t is None:
            return ToolMessage(f"Tool {call['name']!r} is not available to you.",
                               tool_call_id=call["id"], name=call["name"], status="error")
        live = _live.setdefault(state.get("task_id", ""), _Live())
        async with live.lock:
            r = _reporter(state)
            if zone := zone_of(t):
                await r.travel(zone)
                live.zone = r.zone.value
            await r.work(t.name, f"Running {t.name}...")
            result = await asyncio.wait_for(handler(request.override(tool=t)), TOOL_TIMEOUT_S)
        if isinstance(result, ToolMessage):
            result.content = links.rewrite(_clip(result.content))  # links that open for you
            if result.status != "error" and state.get("toolset", {}).get(t.name) in (
                    "write", "destructive"):
                result.content = _link_changes(t.name, call.get("args") or {}, result.content,
                                               state)
            if t.name in ("hand_off", "plan_tasks", "plan_fixes") and result.status != "error":
                _announce_handoff(r, result.content)
        return result

    async def aafter_agent(self, state, runtime) -> dict | None:
        r = _reporter(state)
        last = next((m for m in reversed(state["messages"]) if isinstance(m, AIMessage)), None)
        await r.finish("Task complete")
        _live.pop(r.task_id or "", None)
        return r.patch(result=links.rewrite(last.text if last else "")
                       or "Finished without a summary.")


class _EveryTool(dict):
    """`interrupt_on` that applies one policy to every tool name, including MCP tools
    discovered at runtime; the policy's `when` predicate decides per call."""

    def __init__(self, policy: InterruptOnConfig):
        super().__init__()
        self.policy = policy

    def get(self, key, default=None):
        return self.policy

    def __getitem__(self, key):
        return self.policy


def _gated(request) -> bool:
    state = request.state
    risk = state.get("toolset", {}).get(request.tool_call["name"])
    if risk is None:  # not one of the agent's tools: HubRuntime refuses it without running
        return False
    return needs_approval(risk, state.get("config", {}).get("autonomy", "approve_writes"))


def _describe(tool_call, state, runtime) -> str:
    risk = state.get("toolset", {}).get(tool_call["name"], "write")
    return f"{risk.title()} action: {tool_call['name']}"


class AutonomyApproval(HumanInTheLoopMiddleware):
    """Human review of tool calls, driven by tool risk and the agent's autonomy setting."""

    def __init__(self):
        super().__init__(interrupt_on={})
        self.interrupt_on = _EveryTool(InterruptOnConfig(
            allowed_decisions=["approve", "edit", "reject"], description=_describe,
            when=_gated))


class StepLimit(ModelCallLimitMiddleware):
    """ModelCallLimitMiddleware with each agent's own max_steps (one thread per task, so
    the thread count spans resumes after approvals)."""

    def __init__(self):
        super().__init__(thread_limit=DEFAULT_MAX_STEPS)

    @hook_config(can_jump_to=["end"])
    def before_model(self, state, runtime) -> dict | None:
        limit = state.get("config", {}).get("max_steps", DEFAULT_MAX_STEPS)
        count = state.get("thread_model_call_count", 0)
        if count < limit:
            return None
        last = next((m.text for m in reversed(state["messages"])
                     if isinstance(m, AIMessage) and m.text), "")
        note = f"Stopped after {count} steps without finishing." + (
            f" Last notes: {last}" if last else "")
        return {"jump_to": "end", "messages": [AIMessage(note)]}

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state, runtime) -> dict | None:
        return self.before_model(state, runtime)


def _tool_error(exc: Exception, request) -> str:
    return f"{type(exc).__name__}: {exc}"[:2000]


def build(checkpointer, store=None):
    return create_agent(
        RouterChatModel(),
        tools=[],
        middleware=[AutonomyApproval(), StepLimit(), ToolErrorMiddleware(_tool_error),
                    HubRuntime()],
        checkpointer=checkpointer,
        store=store,
        name="custom_agent",
    )
