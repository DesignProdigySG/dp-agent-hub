"""Agent definitions, stored in `agent_def`. Every agent is configured here and runs the
tool-calling graph (agents/custom.py).

A run pins the agent's config at start (`run_config`), so editing an agent never changes a
run that is in flight or paused for approval.
"""

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlmodel import select

from app.db import AgentDef, KnowledgeDoc, Skill, Task, session
from app.events.schema import AgentProfile, TaskStatus, TaskTemplate, Zone, utcnow

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
# The hub's cast (frontend/public/assets/characters) and the Kenney Mini Characters.
CAST = {"the-data-doctor", "the-qualifier", "the-designer", "the-private-investigator",
        "the-campaigner", "the-auditor", "the-flight-attendant", "the-project-manager"}
CHARACTERS = CAST | {f"{g}-{v}" for g in ("female", "male") for v in "abcdef"}


class RegistryError(ValueError):
    def __init__(self, message: str, status: int = 422):
        self.status = status
        super().__init__(message)


class AgentIn(BaseModel):
    """Create/update payload. On update every field is optional (see `update`)."""

    id: str | None = None
    name: str = Field(min_length=1, max_length=60)
    title: str = Field(default="", max_length=120)
    color: str = "#5b6abf"
    character: str = ""
    home_zone: Zone = Zone.BREAK_ROOM
    model_tier: Literal["fast", "standard", "strong"] = "standard"
    enabled: bool = True
    instructions: str = Field(default="", max_length=20_000)
    tools: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)
    knowledge_ids: list[str] = Field(default_factory=list)
    memory_enabled: bool = False
    autonomy: Literal["approve_writes", "approve_destructive", "autonomous"] = "approve_writes"
    max_steps: int = Field(default=12, ge=1, le=50)
    templates: list[TaskTemplate] = Field(default_factory=list)

    @field_validator("color")
    @classmethod
    def _color(cls, v: str) -> str:
        if not HEX_RE.fullmatch(v):
            raise ValueError("color must be a hex value like #3b6fd8")
        return v

    @field_validator("character")
    @classmethod
    def _character(cls, v: str) -> str:
        if v and v not in CHARACTERS:
            raise ValueError("unknown character")
        return v


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    s = s if s and s[0].isalpha() else f"agent_{s}"
    return s[:40]


def all_defs() -> list[AgentDef]:
    with session() as s:
        return list(s.exec(select(AgentDef).order_by(AgentDef.created_at)).all())


def get(agent_id: str) -> AgentDef | None:
    with session() as s:
        return s.get(AgentDef, agent_id)


def _channels(d: AgentDef) -> list[str]:
    if d.workflow:
        return ["rest", "mcp"]
    from app.agents.tools import HUB_TOOL_NAMES

    out = []
    if any(t.startswith("rest_") for t in d.tools):
        out.append("rest")
    if any(t not in HUB_TOOL_NAMES for t in d.tools):
        out.append("mcp")
    return out


def profiles() -> list[AgentProfile]:
    defs = all_defs()
    with session() as s:
        skills = {k.id: k.name for k in s.exec(select(Skill))}
        docs = {k.id: k.title for k in s.exec(select(KnowledgeDoc))}
    return [AgentProfile(
        id=d.id, name=d.name, title=d.title, home_zone=Zone(d.home_zone),
        model_tier=d.model_tier, channels=_channels(d), color=d.color, character=d.character,
        workflow=d.workflow,
        knowledge=[docs[i] for i in d.knowledge_ids if i in docs],
        templates=[TaskTemplate.model_validate(t) for t in d.templates],
        enabled=d.enabled, tools=d.tools,
        skills=[skills[i] for i in d.skill_ids if i in skills],
        memory_enabled=d.memory_enabled, autonomy=d.autonomy,
    ) for d in defs]


def config(d: AgentDef) -> dict[str, Any]:
    """Full editable config, for the admin editor."""
    return d.model_dump(mode="json")


def run_config(d: AgentDef) -> dict[str, Any]:
    """The snapshot of config a run is pinned to."""
    return {k: getattr(d, k) for k in (
        "name", "title", "home_zone", "model_tier", "instructions", "tools", "skill_ids",
        "knowledge_ids", "memory_enabled", "autonomy", "max_steps")}


def _check_refs(s, data: dict[str, Any]) -> None:
    for key, model, label in (("skill_ids", Skill, "skill"),
                              ("knowledge_ids", KnowledgeDoc, "knowledge document")):
        ids = data.get(key)
        if ids:
            found = set(s.exec(select(model.id).where(model.id.in_(ids))).all())
            if missing := [i for i in ids if i not in found]:
                raise RegistryError(f"unknown {label}: {', '.join(missing)}")


def _check_tools(tools: list[str], known: set[str] | None) -> None:
    if len(tools) != len(set(tools)):
        raise RegistryError("tools contains duplicates")
    if known is not None and (unknown := [t for t in tools if t not in known]):
        raise RegistryError(f"unknown tool: {', '.join(unknown)}")


def create(body: AgentIn, known_tools: set[str] | None) -> AgentDef:
    agent_id = body.id or _slug(body.name)
    if not ID_RE.fullmatch(agent_id):
        raise RegistryError("id must be 2-40 lowercase letters, digits or underscores, "
                            "starting with a letter")
    _check_tools(body.tools, known_tools)
    data = body.model_dump(mode="json", exclude={"id"})
    with session() as s:
        if s.get(AgentDef, agent_id):
            raise RegistryError(f"an agent with id {agent_id!r} already exists", 409)
        _check_refs(s, data)
        d = AgentDef(id=agent_id, **data)
        s.add(d)
        s.commit()
    return d


def update(agent_id: str, changes: dict[str, Any], known_tools: set[str] | None) -> AgentDef:
    with session() as s:
        d = s.get(AgentDef, agent_id)
        if d is None:
            raise RegistryError("agent not found", 404)
        changes = {k: v for k, v in changes.items() if k != "id"}
        if unknown := set(changes) - set(AgentIn.model_fields):
            raise RegistryError("unknown field: " + ", ".join(sorted(unknown)))
        merged = AgentIn.model_validate({**config(d), **changes})  # validates the result
        data = merged.model_dump(mode="json", exclude={"id"})
        if "tools" in changes:
            _check_tools(merged.tools, known_tools)
        _check_refs(s, {k: data[k] for k in ("skill_ids", "knowledge_ids") if k in changes})
        for k in changes:
            setattr(d, k, data[k])
        d.updated_at = utcnow()
        s.add(d)
        s.commit()
    return d


ACTIVE = (TaskStatus.QUEUED, TaskStatus.IN_PROGRESS, TaskStatus.NEEDS_APPROVAL)


def delete(agent_id: str) -> None:
    with session() as s:
        d = s.get(AgentDef, agent_id)
        if d is None:
            raise RegistryError("agent not found", 404)
        active = s.exec(select(Task).where(Task.agent_id == agent_id,
                                           Task.status.in_(ACTIVE))).all()
        if active:
            raise RegistryError(f"{len(active)} task(s) for this agent are queued, running or "
                                "awaiting approval; finish or delete them first", 409)
        s.delete(d)
        s.commit()


def detach(kind: Literal["skill_ids", "knowledge_ids"], item_id: str) -> None:
    """Remove a deleted skill or document from every agent that uses it."""
    with session() as s:
        for d in s.exec(select(AgentDef)):
            ids = getattr(d, kind)
            if item_id in ids:
                setattr(d, kind, [i for i in ids if i != item_id])
                d.updated_at = utcnow()
                s.add(d)
        s.commit()
