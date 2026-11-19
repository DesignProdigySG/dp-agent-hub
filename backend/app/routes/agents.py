"""Agents, the tool catalog, skills, knowledge documents and agent memories.

The roster (GET /agents) is visible to viewers; full configs and every change need the admin.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import select

from app import knowledge, reporting
from app.agents import registry
from app.agents.tools import catalog, memory_namespace, public
from app.db import KnowledgeChunk, KnowledgeDoc, Skill, audit, session
from app.events.schema import AgentProfile, utcnow
from app.hub import Hub
from app.security import require_admin, require_viewer

viewer = APIRouter(dependencies=[Depends(require_viewer)])
admin = APIRouter(dependencies=[Depends(require_admin)])


def hub(request: Request) -> Hub:
    return request.app.state.hub


def _raise(e: registry.RegistryError):
    raise HTTPException(e.status, str(e)) from None


async def _known_tools() -> set[str] | None:
    """Tool names to validate against, or None when the MCP catalog couldn't load (so
    configured MCP tools aren't rejected just because the server is unreachable)."""
    cat = await catalog()
    return None if cat.mcp_error else set(cat.tools)


# --- agents -----------------------------------------------------------------------------------


@viewer.get("/agents/{agent_id}/report")
def agent_report(agent_id: str) -> dict[str, Any]:
    """The agent's standard report: latest headline, KPIs vs a week earlier, activity."""
    d = registry.get(agent_id)
    if d is None:
        raise HTTPException(404, "agent not found")
    return reporting.agent_report(d)


@viewer.get("/agents", response_model=list[AgentProfile])
def list_agents() -> list[AgentProfile]:
    return registry.profiles()


@admin.get("/agents/{agent_id}/config")
def agent_config(agent_id: str) -> dict[str, Any]:
    d = registry.get(agent_id)
    if d is None:
        raise HTTPException(404, "agent not found")
    return registry.config(d)


@admin.post("/agents", status_code=201)
async def create_agent(body: registry.AgentIn, request: Request) -> dict[str, Any]:
    try:
        d = registry.create(body, await _known_tools())
    except registry.RegistryError as e:
        _raise(e)
    audit("agent_created", d.name, agent_id=d.id)
    await hub(request).roster_changed()
    return registry.config(d)


@admin.put("/agents/{agent_id}")
async def update_agent(agent_id: str, body: dict[str, Any], request: Request) -> dict[str, Any]:
    try:
        d = registry.update(agent_id, body, await _known_tools())
    except registry.RegistryError as e:
        _raise(e)
    except ValueError as e:  # pydantic validation of the merged config
        raise HTTPException(422, str(e)) from None
    audit("agent_updated", d.name, agent_id=d.id, data={"fields": sorted(body)})
    await hub(request).roster_changed()
    return registry.config(d)


@admin.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, request: Request) -> None:
    if agent_id in hub(request).busy:
        raise HTTPException(409, "the agent is running or awaiting approval")
    try:
        registry.delete(agent_id)
    except registry.RegistryError as e:
        _raise(e)
    store = request.app.state.store
    for item in await store.asearch(memory_namespace(agent_id), limit=10_000):
        await store.adelete(memory_namespace(agent_id), item.key)
    audit("agent_deleted", agent_id, agent_id=agent_id)
    await hub(request).roster_changed()


@admin.get("/tools")
async def list_tools() -> dict[str, Any]:
    cat = await catalog()
    return {"tools": [public(t) for t in cat.tools.values()], "mcp_error": cat.mcp_error}


# --- memories ---------------------------------------------------------------------------------


class MemoryIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def _memory_out(item) -> dict[str, Any]:
    return {"id": item.key, "text": item.value.get("text", ""),
            "task_id": item.value.get("task_id"), "updated_at": item.updated_at.isoformat()}


def _agent_or_404(agent_id: str):
    if registry.get(agent_id) is None:
        raise HTTPException(404, "agent not found")


@admin.get("/agents/{agent_id}/memories")
async def list_memories(agent_id: str, request: Request) -> list[dict[str, Any]]:
    _agent_or_404(agent_id)
    items = await request.app.state.store.asearch(memory_namespace(agent_id), limit=1000)
    items.sort(key=lambda i: i.updated_at, reverse=True)
    return [_memory_out(i) for i in items]


@admin.post("/agents/{agent_id}/memories", status_code=201)
async def add_memory(agent_id: str, body: MemoryIn, request: Request) -> dict[str, Any]:
    _agent_or_404(agent_id)
    key = f"m_{utcnow().strftime('%Y%m%d%H%M%S%f')}"
    store = request.app.state.store
    await store.aput(memory_namespace(agent_id), key,
                     {"text": body.text, "task_id": None, "created_at": utcnow().isoformat()})
    return _memory_out(await store.aget(memory_namespace(agent_id), key))


@admin.put("/agents/{agent_id}/memories/{key}")
async def edit_memory(agent_id: str, key: str, body: MemoryIn,
                      request: Request) -> dict[str, Any]:
    store = request.app.state.store
    item = await store.aget(memory_namespace(agent_id), key)
    if item is None:
        raise HTTPException(404, "memory not found")
    await store.aput(memory_namespace(agent_id), key, {**item.value, "text": body.text})
    return _memory_out(await store.aget(memory_namespace(agent_id), key))


@admin.delete("/agents/{agent_id}/memories/{key}", status_code=204)
async def delete_memory(agent_id: str, key: str, request: Request) -> None:
    await request.app.state.store.adelete(memory_namespace(agent_id), key)


# --- skills -----------------------------------------------------------------------------------


class SkillIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=50_000)


@admin.get("/skills")
def list_skills() -> list[dict[str, Any]]:
    with session() as s:
        return [k.model_dump(mode="json") for k in s.exec(select(Skill).order_by(Skill.name))]


def _unique_skill_name(s, name: str, skill_id: str | None = None) -> None:
    clash = s.exec(select(Skill).where(Skill.name == name)).first()
    if clash and clash.id != skill_id:
        raise HTTPException(409, f"a skill named {name!r} already exists")


@admin.post("/skills", status_code=201)
async def create_skill(body: SkillIn, request: Request) -> dict[str, Any]:
    with session() as s:
        _unique_skill_name(s, body.name.strip())
        skill = Skill(**{**body.model_dump(), "name": body.name.strip()})
        s.add(skill)
        s.commit()
    audit("skill_created", skill.name)
    await hub(request).roster_changed()
    return skill.model_dump(mode="json")


@admin.put("/skills/{skill_id}")
async def update_skill(skill_id: str, body: SkillIn, request: Request) -> dict[str, Any]:
    with session() as s:
        skill = s.get(Skill, skill_id)
        if skill is None:
            raise HTTPException(404, "skill not found")
        _unique_skill_name(s, body.name.strip(), skill_id)
        skill.name, skill.description, skill.body = body.name.strip(), body.description, body.body
        skill.updated_at = utcnow()
        s.add(skill)
        s.commit()
    await hub(request).roster_changed()
    return skill.model_dump(mode="json")


@admin.delete("/skills/{skill_id}", status_code=204)
async def delete_skill(skill_id: str, request: Request) -> None:
    with session() as s:
        skill = s.get(Skill, skill_id)
        if skill is None:
            raise HTTPException(404, "skill not found")
        s.delete(skill)
        s.commit()
    registry.detach("skill_ids", skill_id)
    audit("skill_deleted", skill.name)
    await hub(request).roster_changed()


# --- knowledge --------------------------------------------------------------------------------


class DocIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    source: str = Field(default="", max_length=300)
    content: str = Field(max_length=2_000_000)


def _doc_out(d: KnowledgeDoc, chunks: int | None = None) -> dict[str, Any]:
    out = d.model_dump(mode="json", exclude={"content"})
    out["chars"] = len(d.content)
    if chunks is not None:
        out["chunks"] = chunks
    return out


@admin.get("/knowledge")
def list_docs() -> dict[str, Any]:
    from sqlalchemy import func

    with session() as s:
        counts = dict(s.exec(select(KnowledgeChunk.doc_id, func.count())
                             .group_by(KnowledgeChunk.doc_id)).all())
        docs = [_doc_out(d, counts.get(d.id, 0))
                for d in s.exec(select(KnowledgeDoc).order_by(KnowledgeDoc.title))]
    return {"docs": docs, "vector_search": knowledge.vector_ready()}


@admin.get("/knowledge/{doc_id}")
def get_doc(doc_id: str) -> dict[str, Any]:
    with session() as s:
        d = s.get(KnowledgeDoc, doc_id)
    if d is None:
        raise HTTPException(404, "document not found")
    return {**_doc_out(d), "content": d.content}


@admin.post("/knowledge", status_code=201)
async def create_doc(body: DocIn, request: Request) -> dict[str, Any]:
    with session() as s:
        d = KnowledgeDoc(**body.model_dump())
        s.add(d)
        s.commit()
    d = await knowledge.index_doc(d.id)
    audit("knowledge_created", d.title)
    await hub(request).roster_changed()
    return _doc_out(d)


@admin.put("/knowledge/{doc_id}")
async def update_doc(doc_id: str, body: DocIn, request: Request) -> dict[str, Any]:
    with session() as s:
        d = s.get(KnowledgeDoc, doc_id)
        if d is None:
            raise HTTPException(404, "document not found")
        for k, v in body.model_dump().items():
            setattr(d, k, v)
        d.updated_at = utcnow()
        s.add(d)
        s.commit()
    d = await knowledge.index_doc(doc_id)
    await hub(request).roster_changed()
    return _doc_out(d)


@admin.delete("/knowledge/{doc_id}", status_code=204)
async def delete_doc(doc_id: str, request: Request) -> None:
    from sqlmodel import delete

    with session() as s:
        d = s.get(KnowledgeDoc, doc_id)
        if d is None:
            raise HTTPException(404, "document not found")
        s.exec(delete(KnowledgeChunk).where(KnowledgeChunk.doc_id == doc_id))
        s.delete(d)
        s.commit()
    registry.detach("knowledge_ids", doc_id)
    audit("knowledge_deleted", d.title)
    await hub(request).roster_changed()


@admin.post("/knowledge/reindex")
async def reindex() -> dict[str, Any]:
    return {"reindexed": await knowledge.reindex_all(only_stale=False)}


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    doc_ids: list[str] | None = None  # default: every document
    k: int = Field(default=5, ge=1, le=20)


@admin.post("/knowledge/search")
async def search_docs(body: SearchIn) -> dict[str, Any]:
    ids = body.doc_ids
    if ids is None:
        with session() as s:
            ids = list(s.exec(select(KnowledgeDoc.id)).all())
    return await knowledge.search(body.query, ids, body.k)

