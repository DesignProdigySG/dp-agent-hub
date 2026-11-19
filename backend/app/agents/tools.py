"""Tools custom agents can be given: standard LangChain tools tagged with a risk level.

Three sources:
  * hub tools: stored activity, engagement and KPI history (Postgres, no Marketo quota),
    and the Designer's brand images and deliverables (app/design.py)
  * Marketo REST helpers (`rest_*`), governed like every other call
  * Marketo MCP tools, loaded from the MCP server in live mode (a stand-in subset in demo)

plus context tools added automatically from an agent's config: `search_knowledge`,
`load_skill`, the memory tools `remember` / `recall` / `forget`, and `read_attachment` /
`search_attachments` when the task has files attached. Those read the run's
pinned config and the LangGraph store through the injected `ToolRuntime`.

Each tool's `metadata` holds {"risk", "group", "zone"}. Risk is "read", "write" or
"destructive" for Marketo-facing tools and "internal" for the agent's own knowledge,
skills and memory; an agent's autonomy setting turns risk into "needs approval" (see
`needs_approval`, applied by the human-in-the-loop middleware in `custom.py`).
"""

import asyncio
import functools
import logging
from dataclasses import dataclass
from typing import Any, Literal

from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, StructuredTool, tool
from pydantic import BaseModel, Field
from sqlmodel import select

from app import analytics, attachments, design, handoff, knowledge
from app.db import Skill, Task, session
from app.deps import get_deps
from app.events.schema import TaskUpdatedMsg, Zone, utcnow
from app.marketo import asset_api

log = logging.getLogger(__name__)

Risk = Literal["read", "write", "destructive", "internal"]
Autonomy = Literal["approve_writes", "approve_destructive", "autonomous"]


def needs_approval(risk: Risk, autonomy: str) -> bool:
    if risk in ("read", "internal") or autonomy == "autonomous":
        return False
    if autonomy == "approve_destructive":
        return risk == "destructive"
    return True  # approve_writes (default), or anything unrecognized


def _tag(t: BaseTool, risk: Risk, group: str, zone: Zone | None) -> BaseTool:
    t.metadata = {"risk": risk, "group": group, "zone": zone.value if zone else None}
    return t


def risk_of(t: BaseTool) -> Risk:
    return (t.metadata or {}).get("risk", "write")  # untagged: fail safe


def zone_of(t: BaseTool) -> Zone | None:
    z = (t.metadata or {}).get("zone")
    return Zone(z) if z else None


def public(t: BaseTool) -> dict[str, Any]:
    meta = t.metadata or {}
    return {"name": t.name, "description": t.description, "risk": risk_of(t),
            "group": meta.get("group", ""), "zone": meta.get("zone")}


# --- hub data tools ---------------------------------------------------------------------------


@tool
async def activity_summary(days: int = 7) -> dict:
    """Summarize Marketo activity stored in the hub over the last N days (1-365): totals,
    engaged leads, counts by activity type, top assets and a per-day series."""
    return await asyncio.to_thread(analytics.activity_summary, max(1, min(days, 365)))


@tool
async def recent_activities(limit: int = 25) -> list:
    """Most recent stored Marketo activities, newest first (up to 200)."""
    return await asyncio.to_thread(analytics.recent_activities, max(1, min(limit, 200)))


@tool
async def lead_engagement(lead_ids: list[int], days: int = 30) -> dict:
    """Engagement score (count of recent activities) for each lead ID."""
    scores = await asyncio.to_thread(analytics.lead_engagement, lead_ids[:1000], days)
    return {str(k): v for k, v in scores.items()}


@tool
async def kpi_history(days: int = 30,
                      scope: Literal["agent", "tasks", "approvals", "activities", "llm"]
                      | None = None,
                      metric: str | None = None) -> list:
    """Daily KPI snapshots (agent KPIs, task throughput, activity volume, LLM spend)."""
    rows = await asyncio.to_thread(analytics.kpi_series, days, scope)
    if metric:
        rows = [r for r in rows if r.get("metric") == metric]
    return rows[:500]


# --- Marketo REST tools -----------------------------------------------------------------------

DEFAULT_LEAD_FIELDS = ["id", "email", "firstName", "lastName", "company", "title"]


@tool
async def rest_get_leads(filter_type: str, values: list[str],
                         fields: list[str] | None = None) -> list:
    """Look up Marketo leads by a field (REST), e.g. filter_type "email" or "id".
    Returns up to 300 leads."""
    leads = await get_deps().marketo.get_leads(filter_type, values[:300],
                                               fields or DEFAULT_LEAD_FIELDS)
    return leads[:300]


@tool
async def rest_update_leads(leads: list[dict[str, Any]]) -> Any:
    """Update Marketo lead fields (REST). Each lead needs its id plus the fields to change."""
    return await get_deps().marketo.update_leads(leads[:300])


@tool
async def rest_add_leads_to_list(list_id: int, lead_ids: list[int]) -> Any:
    """Add leads to a Marketo static list (REST)."""
    return await get_deps().marketo.add_leads_to_list(list_id, lead_ids[:300])


async def _asset_call(op_name: str, **args: Any) -> list[dict[str, Any]]:
    op = asset_api.by_name()[op_name]
    body = await get_deps().marketo.asset(asset_api.split_args(op, args))
    return list((body or {}).get("result") or [])


@tool
async def create_program_list(program_id: int, name: str, copy_from_list_id: int) -> dict:
    """Create a static list inside a program (a local list) with the members of another
    static list, e.g. an event's invite list copied from its candidates list. Safe to call
    again: a list of that name already in the program is reused and topped up. Smart list
    rules ("Member of List") must name a program's list as `smart_list_value`
    ("<Program>.<List>"); its bare name isn't found."""
    program = (await _asset_call("asset_get_program_by_id", id=program_id) or [{}])[0]
    found = [x for x in await _asset_call("asset_get_static_list_by_name", name=name)
             if (x.get("folder") or {}).get("id") == program_id]
    made = found[0] if found else (await _asset_call(
        "asset_create_static_list", name=name, folder={"id": program_id, "type": "Program"},
        description=f"Copied from static list {copy_from_list_id}"))[0]
    list_id = int(made["id"])
    m = get_deps().marketo
    source = [int(x["id"]) for x in await m.list_leads(copy_from_list_id, 300, ["id"])]
    have = {int(x["id"]) for x in await m.list_leads(list_id, 300, ["id"])}
    if add := [i for i in source if i not in have]:
        await m.add_leads_to_list(list_id, add)
    return {"list_id": list_id, "name": name, "program_id": program_id,
            "smart_list_value": f"{program.get('name', '')}.{name}",
            "members": len(have) + len(add), "copied_from": copy_from_list_id,
            "created": not found}


@tool
async def rest_merge_leads(winner_id: int, loser_ids: list[int]) -> dict:
    """Merge duplicate leads into a winner (REST). Losers are permanently deleted."""
    await get_deps().marketo.merge_leads(winner_id, loser_ids)
    return {"merged": len(loser_ids), "winner_id": winner_id}


# --- the team -------------------------------------------------------------------------------


@tool
async def hand_off(to_agent: str, title: str, brief: str, runtime: ToolRuntime,
                   lead_ids: list[int] | None = None,
                   attachment_ids: list[str] | None = None) -> dict:
    """Hand the next step to another agent on the team by creating a task for them. Use it
    when their job covers what comes next (e.g. the Qualifier scores and routes leads, the
    Designer builds pages and emails). to_agent: their id or name. brief: what you need done
    and why, in Markdown; it becomes their task description. lead_ids: the Marketo leads
    it's about. attachment_ids: files attached to your task to pass along (id or filename).
    Cite the returned confirmation line in your summary."""
    state = runtime.state
    try:
        task = await asyncio.to_thread(
            handoff.create, from_task_id=state.get("task_id"), from_agent_id=state["agent_id"],
            to=to_agent, title=title, brief=brief, lead_ids=lead_ids,
            attachment_ids=attachment_ids)
    except handoff.HandoffError as e:
        return {"error": str(e)}
    await get_deps().bus.broadcast(TaskUpdatedMsg(task=task.out()))
    return handoff.tool_result(task)


class PlanStep(BaseModel):
    to_agent: str = Field(description="The agent whose job this is: id or name")
    title: str = Field(description="Short task title, e.g. 'Design the invitation emails'")
    brief: str = Field(description="What to do, in Markdown: deliverables, names, where in "
                                   "Marketo, what to hand back")
    after: list[int] = Field(default_factory=list,
                             description="Steps (by position, 0-based) that must finish first")


@tool
async def plan_tasks(steps: list[PlanStep], runtime: ToolRuntime) -> dict:
    """Turn a piece of work into a plan on the task board: one task per step, each for the
    agent whose job it is, in order. A step with `after` waits until those steps are done;
    then it starts with their results in its brief. Steps without `after` start right away.
    Use it once, with the whole plan, including a last step for yourself to report back."""
    return await _plan(steps, runtime.state)


MAX_FIX_ROUNDS = 2


@tool
async def plan_fixes(steps: list[PlanStep], runtime: ToolRuntime) -> dict:
    """When a check says the work isn't ready: plan a round of fixes, the same way as
    plan_tasks. One step per agent who can fix a blocking problem (what to fix, with the
    Marketo IDs), then the check again after them, then yourself to report after the check.
    The requester approves the plan before anything starts. At most two rounds per run."""
    state = runtime.state
    with session() as s:
        origin = s.get(Task, state.get("task_id")) if state.get("task_id") else None
        if origin is None:
            return {"error": "plan_fixes works from a task"}
        shared = dict((origin.params or {}).get("shared") or {})
        done = int(shared.get("fix_round", 0))
        if done >= MAX_FIX_ROUNDS:
            return {"error": f"This run has had {done} fix rounds already: report what's still "
                             "open and ask the requester how to go on. Don't plan more."}
        shared["fix_round"] = done + 1  # the new tasks inherit it, so the count carries on
        origin.params = {**origin.params, "shared": shared}
        s.add(origin)
        s.commit()
    out = await _plan(steps, state)
    return {**out, "fix_round": done + 1} if "error" not in out else out


async def _plan(steps: list[PlanStep], state: dict) -> dict:
    with session() as s:
        origin = s.get(Task, state.get("task_id")) if state.get("task_id") else None
    # the work may set how each agent's task runs (its approval level, which workflow)
    per_agent = ((origin.params or {}).get("shared") or {}).get("task_params", {}) \
        if origin else {}
    made: list[Any] = []
    for i, step in enumerate(steps):
        if any(a >= i or a < 0 for a in step.after):
            return {"error": f"step {i}: `after` must name earlier steps (0..{i - 1})",
                    "created": [t.id for t in made]}
        receiver = handoff.resolve(step.to_agent)
        extra: dict[str, Any] = {"after": [made[a].id for a in step.after]} if step.after else {}
        if receiver:
            extra.update({k: v for k, v in (per_agent.get(receiver.id) or {}).items()
                          if k in ("autonomy", "workflow")})
        try:
            task = await asyncio.to_thread(
                handoff.create, from_task_id=state.get("task_id"),
                from_agent_id=state["agent_id"], to=step.to_agent, title=step.title,
                brief=step.brief, params=extra,
                delay_s=handoff.START_DELAY_S if not step.after else 0, allow_self=True)
        except handoff.HandoffError as e:
            return {"error": f"step {i}: {e}", "created": [t.id for t in made]}
        made.append(task)
        await get_deps().bus.broadcast(TaskUpdatedMsg(task=task.out()))
    first = next((t for t in made if not t.params.get("after")), None)
    return {"tasks": [{"step": i, "task_id": t.id, "agent": t.params.get("to_agent_name"),
                       "title": t.title, "after": t.params.get("after", [])}
                      for i, t in enumerate(made)],
            "task_id": first.id if first else None,  # who the planner walks over to
            "confirmation": f"Planned {len(made)} task(s) on the board."}


HUB_TOOLS: list[BaseTool] = [
    _tag(hand_off, "write", "Team", None),
    # planning puts tasks on the hub's own board; nothing in Marketo changes
    _tag(plan_tasks, "internal", "Team", None),
    _tag(plan_fixes, "write", "Team", None),  # the requester approves a fix round first
    _tag(activity_summary, "read", "Hub data", Zone.DATABASE),
    _tag(recent_activities, "read", "Hub data", Zone.DATABASE),
    _tag(lead_engagement, "read", "Hub data", Zone.DATABASE),
    _tag(kpi_history, "read", "Hub data", None),
    _tag(rest_get_leads, "read", "Marketo REST", Zone.DATABASE),
    _tag(rest_update_leads, "write", "Marketo REST", Zone.DATABASE),
    _tag(rest_add_leads_to_list, "write", "Marketo REST", Zone.CAMPAIGNS),
    _tag(create_program_list, "write", "Marketo REST", Zone.CAMPAIGNS),
    _tag(rest_merge_leads, "destructive", "Marketo REST", Zone.DATABASE),
    # Design: the brand image library, and saving deliverables to the hub (not Marketo)
    _tag(design.brand_images, "read", "Design", Zone.DESIGN_STUDIO),
    _tag(design.save_design, "internal", "Design", Zone.DESIGN_STUDIO),
    # Design → Marketo: templates + assets through the Asset API (approval: they're writes)
    _tag(design.list_segmentations, "read", "Design", Zone.DESIGN_STUDIO),
    _tag(design.publish_email, "write", "Design", Zone.DESIGN_STUDIO),
    _tag(design.publish_landing_page, "write", "Design", Zone.DESIGN_STUDIO),
]
HUB_TOOL_NAMES = {t.name for t in HUB_TOOLS}


# --- Marketo MCP tools ------------------------------------------------------------------------

READ_PREFIXES = ("browse_", "get_", "describe_", "facet_", "bulk_export_status",
                 "bulk_export_file")
DESTRUCTIVE_PREFIXES = ("activate_", "deactivate_", "approve_", "unapprove_", "delete_",
                        "remove_", "merge_")


def mcp_risk(name: str) -> Risk:
    if name.startswith(READ_PREFIXES):
        return "read"
    if name.startswith(DESTRUCTIVE_PREFIXES):
        return "destructive"
    return "write"  # create / clone / update / add / set / reorder / unknown: fail safe


def mcp_zone(name: str) -> Zone:
    if any(w in name for w in ("snippet", "form", "email", "landing", "thank_you", "field")):
        return Zone.DESIGN_STUDIO
    if any(w in name for w in ("lead", "bulk_export", "activit", "paging")):
        return Zone.DATABASE
    return Zone.CAMPAIGNS


def asset_tool(name: str, op: dict[str, Any]) -> BaseTool:
    """A Marketo Asset API operation (asset_api.py), called through the gateway."""
    async def call(**args: Any) -> Any:
        return await get_deps().marketo.asset(asset_api.split_args(op, args))

    t = StructuredTool(name=name, description=asset_api.describe(op), coroutine=call,
                       args_schema=asset_api.args_schema(op))
    zone = Zone.DESIGN_STUDIO if asset_api.is_design(op) else Zone.CAMPAIGNS
    return _tag(t, asset_api.risk(op), f"Marketo Asset API · {op['group']}", zone)


@functools.cache
def asset_tools() -> dict[str, BaseTool]:
    return {name: asset_tool(name, op) for name, op in asset_api.by_name().items()}


# MCP tools by topic, for the agent editor (first match wins: the more specific first)
MCP_TOPICS = [
    (("smart_campaign", "flow_step", "trigger_campaign", "schedule_campaign"),
     "Smart Campaigns"),
    (("smart_list",), "Smart Lists"),
    (("csv", "import", "field_mapping", "map_fields", "rule_history", "apply_rules",
      "undo_rule", "list_rules", "target_fields", "company_fields", "cell_diffs"), "Imports"),
    (("email_template",), "Email Templates"),
    (("email",), "Emails"),
    (("landing_page_template",), "Landing Page Templates"),
    (("landing_page",), "Landing Pages"),
    (("form", "field_set", "fieldset", "rich_text_field", "field_visibility", "autofill",
      "field_positions", "thank_you_page"), "Forms"),
    (("snippet",), "Snippets"),
    (("program", "channel", "tag", "token"), "Programs & Tokens"),
    (("list",), "Static Lists"),
    (("lead", "activit", "paging", "bulk_export"), "Leads & Activities"),
    (("folder", "file"), "Folders & Files"),
]


def mcp_group(name: str) -> str:
    topic = next((label for words, label in MCP_TOPICS if any(w in name for w in words)),
                 "Other")
    return f"Marketo MCP · {topic}"


def mcp_tool(name: str, description: str, parameters: dict[str, Any]) -> BaseTool:
    """A Marketo MCP tool, called through the gateway so it shares the rate governor (and
    works against the demo stand-in)."""
    async def call(**args: Any) -> Any:
        return await get_deps().marketo.mcp(name, args)

    t = StructuredTool(name=name, description=description or name, coroutine=call,
                       args_schema=parameters or {"type": "object", "properties": {}})
    return _tag(t, mcp_risk(name), mcp_group(name), mcp_zone(name))


@dataclass
class Catalog:
    tools: dict[str, BaseTool]
    mcp_error: str = ""


async def catalog() -> Catalog:
    """Every selectable tool. MCP tools come from the live server when connected."""
    tools = {t.name: t for t in HUB_TOOLS} | asset_tools()
    error = ""
    try:
        for d in await get_deps().marketo.mcp_tools():
            if d["name"] not in tools:
                tools[d["name"]] = mcp_tool(d["name"], d.get("description", ""),
                                            d.get("parameters", {}))
    except Exception as e:
        error = f"Could not load Marketo MCP tools: {type(e).__name__}: {e}"[:300]
        log.warning(error)
    return Catalog(tools, error)


# --- context tools (from the agent's own config) ----------------------------------------------


def memory_namespace(agent_id: str) -> tuple[str, ...]:
    return ("agents", agent_id, "memories")


def _config(runtime: ToolRuntime) -> dict[str, Any]:
    return runtime.state.get("config", {})


@tool
async def search_knowledge(query: str, runtime: ToolRuntime, k: int = 5) -> list:
    """Search your attached knowledge documents. Returns the best passages (k up to 10)."""
    found = await knowledge.search(query, _config(runtime).get("knowledge_ids", []),
                                   k=max(1, min(k, 10)))
    return found["results"]


@tool
async def load_skill(name: str, runtime: ToolRuntime) -> dict:
    """Load the full instructions of one of your skills by name before using it."""
    ids = _config(runtime).get("skill_ids", [])

    def find() -> list[Skill]:
        with session() as s:
            return list(s.exec(select(Skill).where(Skill.id.in_(ids)))) if ids else []

    skills = await asyncio.to_thread(find)
    for sk in skills:
        if sk.name.lower() == name.strip().lower():
            return {"name": sk.name, "instructions": sk.body}
    return {"error": f"No skill named {name!r}. Available: "
                     + ", ".join(sk.name for sk in skills)}


@tool
async def remember(fact: str, runtime: ToolRuntime) -> dict:
    """Save a durable fact for future tasks (a decision, ID mapping or preference).
    Never store secrets or personal data about leads."""
    fact = fact.strip()[:2000]
    if not fact:
        return {"error": "fact is empty"}
    key = f"m_{utcnow().strftime('%Y%m%d%H%M%S%f')}"
    await runtime.store.aput(memory_namespace(runtime.state["agent_id"]), key,
                             {"text": fact, "task_id": runtime.state.get("task_id"),
                              "created_at": utcnow().isoformat()})
    return {"saved": key}


async def recall_memories(store, agent_id: str, query: str, limit: int = 25) -> list[dict]:
    """Memories matching any keyword in the query (newest saved first)."""
    items = await store.asearch(memory_namespace(agent_id), limit=500)
    items.sort(key=lambda i: i.updated_at, reverse=True)
    terms = {t for t in query.lower().split() if len(t) > 2}
    rows = [{"id": i.key, "text": i.value.get("text", "")} for i in items]
    if terms:
        rows = [r for r in rows if any(t in r["text"].lower() for t in terms)]
    return rows[:limit]


@tool
async def recall(runtime: ToolRuntime, query: str = "") -> list:
    """Search your saved memories (an empty query lists recent ones)."""
    return await recall_memories(runtime.store, runtime.state["agent_id"], query)


@tool
async def forget(id: str, runtime: ToolRuntime) -> dict:
    """Delete a saved memory that is wrong or outdated, by its id."""
    await runtime.store.adelete(memory_namespace(runtime.state["agent_id"]), id)
    return {"forgotten": id}


SEARCH_KNOWLEDGE = _tag(search_knowledge, "internal", "Knowledge", None)
LOAD_SKILL = _tag(load_skill, "internal", "Skills", None)
MEMORY_TOOLS = [_tag(t, "internal", "Memory", None) for t in (remember, recall, forget)]
ATTACHMENT_TOOLS = [_tag(t, "internal", "Attachments", None)
                    for t in (attachments.read_attachment, attachments.search_attachments)]


async def tools_for(config: dict[str, Any]) -> tuple[dict[str, BaseTool], list[str]]:
    """The tools a run may use, plus names that are configured but unavailable."""
    cat = await catalog()
    chosen: dict[str, BaseTool] = {}
    missing = []
    for name in config.get("tools", []):
        if name in cat.tools:
            chosen[name] = cat.tools[name]
        else:
            missing.append(name)
    if config.get("knowledge_ids"):
        chosen[SEARCH_KNOWLEDGE.name] = SEARCH_KNOWLEDGE
    if config.get("skill_ids"):
        chosen[LOAD_SKILL.name] = LOAD_SKILL
    if config.get("memory_enabled"):
        chosen.update({t.name: t for t in MEMORY_TOOLS})
    if config.get("attachments"):  # set on runs whose task has files (hub.py)
        chosen.update({t.name: t for t in ATTACHMENT_TOOLS})
    return chosen, missing
