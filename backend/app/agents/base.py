"""The event reporter agent runs use to drive the board and the 3D view."""

import asyncio
from typing import Any

from langgraph.config import get_stream_writer

from app.agents import registry
from app.deps import get_deps
from app.events.schema import AgentEvent, AgentState, Handoff, MetricValue, Zone


class Reporter:
    """Turns agent progress into AgentEvents on the LangGraph custom stream.

    Agents keep their current zone in graph state, so build one per node with
    `Reporter(state)` and return `r.patch()` to persist zone + metrics.
    """

    def __init__(self, state: dict[str, Any]):
        self.agent_id = state["agent_id"]
        self.task_id = state.get("task_id")
        self.zone = Zone(state.get("zone", Zone.BREAK_ROOM))
        self.metrics: dict[str, MetricValue] = dict(state.get("metrics", {}))
        self._pace = get_deps().settings.agent_pacing_s

    def _emit(self, action: str, state: AgentState, text: str, target: Zone | None = None,
              **extra: Any):
        get_stream_writer()(AgentEvent(
            agent_id=self.agent_id, task_id=self.task_id, action=action,
            source_zone=self.zone, target_zone=target or self.zone,
            status_text=text, state=state, metrics=self.metrics, **extra,
        ).model_dump(mode="json"))

    def handoff(self, info: Handoff, text: str) -> None:
        """Tell the floor the agent is handing work to a teammate (it stays where it is)."""
        self._emit("handoff", AgentState.BUSY, text, handoff=info)

    async def travel(self, zone: Zone, text: str | None = None) -> None:
        if zone == self.zone:
            return
        self._emit("travel", AgentState.TRAVELING, text or f"Heading to {zone.value}...", zone)
        await asyncio.sleep(self._pace * 2)
        self.zone = zone

    async def work(self, action: str, text: str, **metrics: MetricValue) -> None:
        self.metrics.update(metrics)
        self._emit(action, AgentState.BUSY, text)
        await asyncio.sleep(self._pace)

    async def progress(self, text: str, **metrics: MetricValue) -> None:
        """A status update from a long-running step (no pacing pause)."""
        self.metrics.update(metrics)
        self._emit("progress", AgentState.BUSY, text)

    async def finish(self, text: str) -> None:
        """Walk back to the agent's home zone (where it idles) and go idle."""
        d = registry.get(self.agent_id)
        await self.travel(Zone(d.home_zone) if d else Zone.BREAK_ROOM, "Heading back to my desk...")
        self._emit("idle", AgentState.IDLE, text)

    def patch(self, **extra: Any) -> dict[str, Any]:
        return {"zone": self.zone.value, "metrics": self.metrics, **extra}

