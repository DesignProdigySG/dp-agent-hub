"""Code-defined LangGraph workflows that hub agents can run instead of the configurable
agent loop: fixed StateGraphs for processes that need deterministic steps and guardrails
enforced in code (see app/workflows/data_health for a worked example).

An agent runs one as its whole job (`agent_def.workflow`), or a task runs one on an ordinary
agent through `params.workflow`, when one of the agent's task templates names it (e.g. the
Data Doctor's full data health scan).

The hub drives them through `WorkflowSpec`: it starts a batch for a task, streams each
thread (forwarding progress events to the board and 3D view), turns interrupts into
approvals with the workflow's own choices, and resumes threads when a reviewer decides.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass
class ThreadOutcome:
    status: Literal["done", "interrupted"]
    values: dict[str, Any] = field(default_factory=dict)
    interrupt: Any = None


class BatchContext(Protocol):
    """What the hub gives a workflow's batch runner."""

    task_id: str
    run_key: str  # unique per run of the task: use it in thread ids
    agent_id: str
    agent_name: str
    enabled: bool
    model_tier: str
    knowledge_ids: list[str]
    skill_names: list[str]
    template_params: dict[str, Any]
    task_params: dict[str, Any]

    async def stream(self, thread_id: str, inputs: Any) -> ThreadOutcome: ...
    async def state(self, thread_id: str) -> dict[str, Any]: ...  # a thread's latest values
    async def pause(self, thread_id: str, request: dict[str, Any]) -> str: ...  # approval id
    def log(self, **row: Any) -> None: ...
    def report(self, headline: str, kpis: dict[str, Any]) -> None: ...  # app/reporting.py
    async def hand_off(self, to: str, title: str, brief: str,
                       lead_ids: list[int] | None = None) -> Any: ...  # app/handoff.py -> Task


@dataclass(frozen=True)
class WorkflowSpec:
    id: str
    name: str
    description: str
    build: Callable[..., Any]  # (checkpointer, store) -> compiled graph
    run_batch: Callable[[BatchContext], Awaitable[tuple[str, int]]]  # (result text, paused)
    resume_value: Callable[[str, str, str], Any]  # (choice, approver, note) -> Command.resume
    after_resume: Callable[[BatchContext, str, ThreadOutcome], Awaitable[str]]  # -> result line
    choice_labels: dict[str, str] = field(default_factory=dict)
    # A task interrupted by a restart is queued again (the workflow continues where it
    # stopped) instead of failing.
    resumable: bool = False
    kpis: tuple = ()  # app.reporting.KpiDef: what the workflow reports after each run


def registry() -> dict[str, WorkflowSpec]:
    from app.workflows.data_health.runner import SPEC as data_health

    return {s.id: s for s in (data_health,)}
