"""The LLM router as a LangChain chat model, so agents use standard LangChain messages,
`bind_tools` and middleware while the router keeps tier routing, the daily budget,
cross-provider fallback and per-call cost tracking.

    model = RouterChatModel(tier="standard", agent_id="data-doctor", task_id="tsk_1")
    reply = await model.bind_tools(tools).ainvoke([SystemMessage(...), HumanMessage(...)])
"""

from typing import Any, Literal

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel

from app.deps import get_deps
from app.llm.router import ToolDef


class NoModelAvailable(RuntimeError):
    """Every model in the route failed, lacked credentials, or the budget was spent."""


NO_MODEL = ("No LLM could answer. Add an API key in Settings > LLM router, or check the "
            "daily budget.")


def to_router_messages(messages: list[BaseMessage]) -> tuple[str, list[dict[str, Any]]]:
    """LangChain messages -> (system prompt, the router's provider-neutral messages)."""
    system: list[str] = []
    out: list[dict[str, Any]] = []
    for m in messages:
        if isinstance(m, SystemMessage):
            system.append(m.text)
        elif isinstance(m, AIMessage):
            out.append({"role": "assistant", "content": m.text,
                        "tool_calls": [{"id": c["id"], "name": c["name"], "args": c["args"]}
                                       for c in m.tool_calls]})
        elif isinstance(m, ToolMessage):
            out.append({"role": "tool", "tool_call_id": m.tool_call_id, "name": m.name or "",
                        "content": m.text, "is_error": m.status == "error"})
        else:
            out.append({"role": "user", "content": m.text})
    return "\n\n".join(system), out


class RouterChatModel(BaseChatModel):
    tier: str = "standard"
    agent_id: str | None = None
    task_id: str | None = None
    stakes: Literal["normal", "high"] = "normal"
    max_tokens: int = 16_000

    @property
    def _llm_type(self) -> str:
        return "hub-router"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"tier": self.tier, "agent_id": self.agent_id}

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        # Forcing a tool call (tool_choice) is rejected by Claude Opus 5.5 / Sonnet 5.5, so it
        # isn't passed on; use with_structured_output for a guaranteed shape.
        defs = [convert_to_openai_tool(t)["function"] for t in tools]
        return self.bind(tools=[ToolDef(d["name"], d.get("description", ""),
                                        d.get("parameters") or {"type": "object",
                                                                "properties": {}})
                                for d in defs], **kwargs)

    def with_structured_output(self, schema, *, include_raw: bool = False, **kwargs):
        """Structured outputs (output_config.format): the reply is JSON matching the pydantic
        model's schema, validated into the model. Raises on an invalid reply."""
        if include_raw or not (isinstance(schema, type) and issubclass(schema, BaseModel)):
            raise NotImplementedError("RouterChatModel structured output takes a pydantic model")

        def parse(message: AIMessage) -> BaseModel:
            return schema.model_validate_json(message.text)

        return self.bind(json_schema=schema.model_json_schema()) | RunnableLambda(parse)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        raise NotImplementedError("RouterChatModel is async-only; use ainvoke")

    async def _agenerate(self, messages: list[BaseMessage], stop: list[str] | None = None,
                         run_manager: AsyncCallbackManagerForLLMRun | None = None,
                         tools: list[ToolDef] | None = None,
                         json_schema: dict[str, Any] | None = None,
                         **kwargs: Any) -> ChatResult:
        system, chat = to_router_messages(messages)
        reply = await get_deps().llm.chat(self.tier, system, chat, tools or [],
                                          agent_id=self.agent_id, task_id=self.task_id,
                                          stakes=self.stakes, max_tokens=self.max_tokens,
                                          json_schema=json_schema)
        if reply is None:
            raise NoModelAvailable(NO_MODEL)
        message = AIMessage(
            content=reply.text,
            tool_calls=[{"id": c["id"], "name": c["name"], "args": c["args"],
                         "type": "tool_call"} for c in reply.tool_calls],
            usage_metadata={"input_tokens": reply.input_tokens,
                            "output_tokens": reply.output_tokens,
                            "total_tokens": reply.input_tokens + reply.output_tokens},
            response_metadata={"model_name": reply.model, "cost_usd": reply.cost_usd},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])
