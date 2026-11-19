"""The data health scan as a LangGraph StateGraph: one node per phase (see scan.py).

    START → leads → activities → values → verify → score → report → END

The Postgres checkpointer records each finished node; inside a node, the phase's own cursor
in health_scan records each finished batch or window. A scan that stopped (error, restart,
the agent switched off) continues from the last of those when its thread is run again.
"""

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.base import Reporter
from app.events.schema import MetricValue, Zone
from app.workflows.data_health import scan
from app.workflows.data_health.config import ScanConfig


class ScanState(TypedDict, total=False):
    task_id: str
    agent_id: str
    zone: str
    metrics: dict[str, MetricValue]
    scan_id: str
    cfg: dict[str, Any]
    model_tier: str
    skills: list[str]
    kpis: dict[str, Any]


def _cfg(state: ScanState) -> ScanConfig:
    return ScanConfig.model_validate(state["cfg"])


def _llm(state: ScanState) -> dict[str, str]:
    return {"agent_id": state["agent_id"], "task_id": state.get("task_id", ""),
            "model_tier": state.get("model_tier", "standard")}


async def leads(state: ScanState) -> dict:
    r = Reporter(state)
    await r.travel(Zone.DATABASE, "Heading to the database...")
    await scan.mirror_leads(state["scan_id"], _cfg(state), r.progress)
    return r.patch()


async def activities(state: ScanState) -> dict:
    r = Reporter(state)
    await scan.mirror_activities(state["scan_id"], _cfg(state), r.progress)
    return r.patch()


async def values(state: ScanState) -> dict:
    r = Reporter(state)
    await scan.resolve_values(state["scan_id"], _cfg(state), r.progress, **_llm(state))
    return r.patch()


async def verify(state: ScanState) -> dict:
    r = Reporter(state)
    await scan.run_verification(state["scan_id"], _cfg(state), state.get("skills", []),
                                r.progress)
    return r.patch()


async def score(state: ScanState) -> dict:
    r = Reporter(state)
    await scan.score(state["scan_id"], _cfg(state), r.progress)
    return r.patch()


async def report(state: ScanState) -> dict:
    r = Reporter(state)
    kpis = await scan.report(state["scan_id"], _cfg(state), r.progress, **_llm(state))
    t = kpis["total"] or 1
    r.metrics.update({
        "health_score": round(kpis["dimensions"]["overall"]["avg"]),
        "leads_scanned": kpis["total"],
        "duplicates_pct": round(100 * kpis["duplicates"]["redundant"] / t, 1),
        "contactable_pct": round(100 * kpis["contactability"]["usable"] / t, 1)})
    await r.finish(f"Scan done: health {kpis['dimensions']['overall']['avg']:.0f}/100 "
                   f"across {kpis['total']:,} leads")
    return r.patch(kpis={"total": kpis["total"]})


def build(checkpointer, store=None):
    g = StateGraph(ScanState)
    order = [("leads", leads), ("activities", activities), ("values", values),
             ("verify", verify), ("score", score), ("report", report)]
    for name, fn in order:
        g.add_node(name, fn)
    g.add_edge(START, order[0][0])
    for (a, _), (b, _) in zip(order, order[1:], strict=False):
        g.add_edge(a, b)
    g.add_edge(order[-1][0], END)
    return g.compile(checkpointer=checkpointer, store=store, name="data_health_scan")
