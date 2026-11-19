"""Configurable agents: CRUD, the tool catalog, the generic tool-calling graph (with approval
gates, autonomy and memory), skills and knowledge search. The LLM is scripted."""

import pytest

from app.agents.tools import mcp_risk, needs_approval
from app.knowledge import chunk_text, cosine
from app.llm.router import Completion, to_anthropic, to_openai
from tests.conftest import call, make_agent, wait_for


def run_task(client, agent_id, title="Add VPs to list 1001"):
    r = client.post("/api/tasks", json={"title": title, "agent_id": agent_id,
                                        "description": "Find the leads and add them."})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def first_lead_email(client):
    demo = client.app.state.hub.deps.marketo
    lead = next(iter(demo.leads.values()))
    return lead["id"], lead["email"]


# --- pure units -------------------------------------------------------------------------------


def test_approval_policy():
    assert not needs_approval("read", "approve_writes")
    assert not needs_approval("internal", "approve_writes")
    assert needs_approval("write", "approve_writes")
    assert needs_approval("destructive", "approve_writes")
    assert not needs_approval("write", "approve_destructive")
    assert needs_approval("destructive", "approve_destructive")
    assert not needs_approval("destructive", "autonomous")
    assert needs_approval("write", "something_else")  # unknown settings fail safe


def test_mcp_risk_by_name():
    assert mcp_risk("browse_programs") == "read"
    assert mcp_risk("get_snippet_content") == "read"
    assert mcp_risk("clone_program") == "write"
    assert mcp_risk("activate_smart_campaign") == "destructive"
    assert mcp_risk("approve_snippet") == "destructive"
    assert mcp_risk("brand_new_tool") == "write"


def test_message_conversion():
    msgs = [{"role": "user", "content": "go"},
            {"role": "assistant", "content": "ok", "tool_calls": [call("a", {"x": 1}, "c1"),
                                                                 call("b", {}, "c2")]},
            {"role": "tool", "tool_call_id": "c1", "name": "a", "content": "1"},
            {"role": "tool", "tool_call_id": "c2", "name": "b", "content": "err",
             "is_error": True}]
    a = to_anthropic(msgs)
    assert [m["role"] for m in a] == ["user", "assistant", "user"]
    assert [b["type"] for b in a[1]["content"]] == ["text", "tool_use", "tool_use"]
    assert [b["tool_use_id"] for b in a[2]["content"]] == ["c1", "c2"]
    assert a[2]["content"][1]["is_error"] is True
    o = to_openai("sys", msgs)
    assert o[0] == {"role": "system", "content": "sys"}
    assert o[2]["tool_calls"][0]["function"] == {"name": "a", "arguments": '{"x": 1}'}
    assert [m["role"] for m in o[3:]] == ["tool", "tool"]


def test_chunking_and_cosine():
    text = "\n\n".join(f"Paragraph {i} " + "word " * 100 for i in range(10))
    chunks = chunk_text(text, size=1200)
    assert all(len(c) <= 1200 for c in chunks) and len(chunks) >= 4
    assert chunk_text("x" * 3000, size=1000)[0] == "x" * 1000
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == 0.0


# --- CRUD -------------------------------------------------------------------------------------


def test_disabled_agents_take_no_tasks(client):
    make_agent(client)
    assert client.put("/api/agents/list_builder", json={"enabled": False}).status_code == 200
    r = client.post("/api/tasks", json={"title": "x", "agent_id": "list_builder"})
    assert r.status_code == 409


def test_custom_agent_crud(client):
    agent = make_agent(client)
    assert agent["id"] == "list_builder"
    profile = next(a for a in client.get("/api/agents").json() if a["id"] == "list_builder")
    assert profile["channels"] == ["rest"]
    assert client.post("/api/agents", json={"name": "List Builder"}).status_code == 409
    bad = client.post("/api/agents", json={"name": "Nope", "tools": ["rm_rf"]})
    assert bad.status_code == 422 and "unknown tool" in bad.text
    assert client.put("/api/agents/list_builder", json={"color": "red"}).status_code == 422
    assert client.put("/api/agents/list_builder", json={"bogus": 1}).status_code == 422

    r = client.put("/api/agents/list_builder", json={"tools": ["browse_programs"],
                                                     "autonomy": "autonomous"})
    assert r.status_code == 200 and r.json()["tools"] == ["browse_programs"]

    # can't delete with queued work; can once it's gone
    task = client.post("/api/tasks", json={"title": "later", "agent_id": "list_builder",
                                           "scheduled_for": "2099-01-01T00:00:00Z"}).json()
    assert client.delete("/api/agents/list_builder").status_code == 409
    client.delete(f"/api/tasks/{task['id']}")
    assert client.delete("/api/agents/list_builder").status_code == 204
    assert all(a["id"] != "list_builder" for a in client.get("/api/agents").json())


def test_agent_admin_routes_need_admin(anon):
    assert anon.get("/api/tools").status_code == 401
    assert anon.post("/api/agents", json={"name": "x"}).status_code == 401
    assert anon.get("/api/skills").status_code == 401


def test_tool_catalog(client):
    body = client.get("/api/tools").json()
    tools = {t["name"]: t for t in body["tools"]}
    assert body["mcp_error"] == ""
    assert tools["rest_merge_leads"]["risk"] == "destructive"
    assert tools["approve_snippet"]["group"] == "Marketo MCP · Snippets"
    assert tools["activity_summary"]["risk"] == "read"


# --- running custom agents --------------------------------------------------------------------


def test_custom_agent_runs_tools_and_waits_for_write_approval(client, script):
    turns, seen = script
    lead_id, email = first_lead_email(client)
    make_agent(client)
    turns += [
        Completion("Looking up the lead.", 1, 1, 0, [call("rest_get_leads", {
            "filter_type": "email", "values": [email]})]),
        Completion("Adding them.", 1, 1, 0, [call("rest_add_leads_to_list", {
            "list_id": 1001, "lead_ids": [lead_id]})]),
        Completion("Added 1 lead to list 1001.", 1, 1, 0),
    ]
    task_id = run_task(client, "list_builder")
    wait_for(client, task_id, {"needs_approval"})
    approval = next(a for a in client.get("/api/approvals").json() if a["task_id"] == task_id)
    assert approval["action"] == "rest_add_leads_to_list"
    assert approval["details"]["calls"][0]["args"]["lead_ids"] == [lead_id]
    # the read ran without asking, and its result went back to the model
    assert any(m["role"] == "tool" and email in m["content"] for m in seen[1]["messages"])
    assert "rest_add_leads_to_list" in seen[0]["tools"]
    assert "Tool results" in seen[0]["system"]  # prompt-injection guardrail is present

    client.post(f"/api/approvals/{approval['id']}/decision", json={"approved": True})
    done = wait_for(client, task_id, {"done", "failed"})
    assert done["status"] == "done", done["result"]
    assert done["result"] == "Added 1 lead to list 1001."
    assert lead_id in client.app.state.hub.deps.marketo.lists[1001]


def test_rejected_write_is_not_executed(client, script):
    turns, seen = script
    lead_id, _ = first_lead_email(client)
    make_agent(client)
    turns += [Completion("", 1, 1, 0, [call("rest_add_leads_to_list", {
                  "list_id": 1002, "lead_ids": [lead_id]})]),
              Completion("The reviewer declined; nothing changed.", 1, 1, 0)]
    task_id = run_task(client, "list_builder")
    wait_for(client, task_id, {"needs_approval"})
    approval = next(a for a in client.get("/api/approvals").json() if a["task_id"] == task_id)
    client.post(f"/api/approvals/{approval['id']}/decision",
                json={"approved": False, "comment": "wrong list"})
    done = wait_for(client, task_id, {"done", "failed"})
    assert done["status"] == "done"
    assert lead_id not in client.app.state.hub.deps.marketo.lists[1002]
    rejected = next(m for m in seen[-1]["messages"] if m["role"] == "tool")
    assert rejected["is_error"] and "wrong list" in rejected["content"]


def test_autonomous_agent_skips_approval(client, script):
    turns, _ = script
    lead_id, _ = first_lead_email(client)
    make_agent(client, autonomy="autonomous")
    turns += [Completion("", 1, 1, 0, [call("rest_add_leads_to_list", {
        "list_id": 1002, "lead_ids": [lead_id]})])]
    done = wait_for(client, run_task(client, "list_builder"), {"done", "failed"})
    assert done["status"] == "done", done["result"]
    assert lead_id in client.app.state.hub.deps.marketo.lists[1002]
    assert not client.get("/api/approvals").json()


def test_step_limit_and_tool_errors(client, script):
    turns, seen = script
    make_agent(client, max_steps=2, tools=["browse_programs"])
    turns += [Completion("", 1, 1, 0, [call("not_my_tool", {})]),
              Completion("", 1, 1, 0, [call("browse_programs", {"maxReturn": 1}, "c2")])]
    done = wait_for(client, run_task(client, "list_builder"), {"done", "failed"})
    assert done["result"].startswith("Stopped after 2 steps")
    unknown = next(m for m in seen[1]["messages"] if m["role"] == "tool")
    assert unknown["is_error"] and "not available" in unknown["content"]


def test_custom_agent_fails_clearly_without_llm(client):
    make_agent(client)
    done = wait_for(client, run_task(client, "list_builder"), {"done", "failed"})
    assert done["status"] == "failed" and "No LLM could answer" in done["result"]


def test_memory_persists_across_tasks_and_is_editable(client, script):
    turns, seen = script
    make_agent(client, memory_enabled=True, tools=[])
    turns += [Completion("", 1, 1, 0, [call("remember", {"fact": "EMEA routes to list 1042"})]),
              Completion("Noted.", 1, 1, 0)]
    wait_for(client, run_task(client, "list_builder"), {"done"})
    assert "remember" in seen[0]["tools"]

    memories = client.get("/api/agents/list_builder/memories").json()
    assert [m["text"] for m in memories] == ["EMEA routes to list 1042"]

    wait_for(client, run_task(client, "list_builder", "Second task"), {"done"})
    assert "EMEA routes to list 1042" in seen[-1]["system"]

    key = memories[0]["id"]
    r = client.put(f"/api/agents/list_builder/memories/{key}", json={"text": "EMEA -> 1043"})
    assert r.json()["text"] == "EMEA -> 1043"
    assert client.post("/api/agents/list_builder/memories",
                       json={"text": "added by hand"}).status_code == 201
    client.delete(f"/api/agents/list_builder/memories/{key}")
    assert [m["text"] for m in client.get("/api/agents/list_builder/memories").json()] == \
        ["added by hand"]


def test_skills_and_knowledge_reach_the_agent(client, script):
    turns, seen = script
    skill = client.post("/api/skills", json={
        "name": "Webinar launch", "description": "Steps to launch a webinar",
        "body": "1. Clone the template. 2. Never activate before approval."}).json()
    assert client.post("/api/skills", json={"name": "Webinar launch"}).status_code == 409
    doc = client.post("/api/knowledge", json={
        "title": "Routing matrix", "content": "EMEA leads route to list 1042.\n\n"
                                              "APAC leads route to list 1077."}).json()
    make_agent(client, skill_ids=[skill["id"]], knowledge_ids=[doc["id"]], tools=[])
    turns += [Completion("", 1, 1, 0, [call("load_skill", {"name": "webinar launch"}),
                                       call("search_knowledge", {"query": "APAC routing"},
                                            "c2")]),
              Completion("APAC goes to 1077.", 1, 1, 0)]
    done = wait_for(client, run_task(client, "list_builder"), {"done", "failed"})
    assert done["status"] == "done", done["result"]
    assert {"load_skill", "search_knowledge"} <= set(seen[0]["tools"])
    assert "Webinar launch: Steps to launch a webinar" in seen[0]["system"]
    results = [m["content"] for m in seen[1]["messages"] if m["role"] == "tool"]
    assert "Never activate before approval" in results[0]
    assert "1077" in results[1]

    profile = next(a for a in client.get("/api/agents").json() if a["id"] == "list_builder")
    assert profile["skills"] == ["Webinar launch"] and profile["knowledge"] == ["Routing matrix"]

    # deleting them detaches them from the agent
    client.delete(f"/api/skills/{skill['id']}")
    client.delete(f"/api/knowledge/{doc['id']}")
    cfg = client.get("/api/agents/list_builder/config").json()
    assert cfg["skill_ids"] == [] and cfg["knowledge_ids"] == []


def test_semantic_search_with_embeddings(client, monkeypatch):
    from app import knowledge
    from app.config import apply_overrides

    def vec(text):  # toy embedding: which topic words appear
        return [float(w in text.lower()) for w in ("pricing", "routing", "brand")]

    async def fake_embed(texts):
        return [vec(t) for t in texts]

    monkeypatch.setattr(knowledge, "embed", fake_embed)
    apply_overrides({"embedding_model": "openai/text-embedding-3-small"})
    for title, content in [("Brand", "Brand voice: friendly."),
                           ("Routing", "Lead routing rules by region."),
                           ("Pricing", "Pricing tiers and discounts.")]:
        d = client.post("/api/knowledge", json={"title": title, "content": content}).json()
        assert d["embedding_model"] == "openai/text-embedding-3-small"
    r = client.post("/api/knowledge/search", json={"query": "how does routing work", "k": 1})
    assert r.json()["mode"] == "semantic"
    assert r.json()["results"][0]["title"] == "Routing"


# --- LangChain alignment ----------------------------------------------------------------------


def test_router_chat_model_message_conversion():
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    from app.llm.chat_model import to_router_messages
    system, msgs = to_router_messages([
        SystemMessage("Be brief."), HumanMessage("hi"),
        AIMessage("", tool_calls=[{"id": "c1", "name": "t", "args": {"a": 1}}]),
        ToolMessage("boom", tool_call_id="c1", name="t", status="error")])
    assert system == "Be brief."
    assert msgs == [{"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "",
                     "tool_calls": [{"id": "c1", "name": "t", "args": {"a": 1}}]},
                    {"role": "tool", "tool_call_id": "c1", "name": "t", "content": "boom",
                     "is_error": True}]


def test_reviewer_can_edit_tool_arguments(client, script):
    turns, _ = script
    lead_id, _ = first_lead_email(client)
    make_agent(client)
    turns += [Completion("", 1, 1, 0, [call("rest_add_leads_to_list", {
                  "list_id": 1001, "lead_ids": [lead_id]})]),
              Completion("Done.", 1, 1, 0)]
    task_id = run_task(client, "list_builder")
    wait_for(client, task_id, {"needs_approval"})
    approval = next(a for a in client.get("/api/approvals").json() if a["task_id"] == task_id)
    url = f"/api/approvals/{approval['id']}/decision"
    assert client.post(url, json={"approved": False, "edits": {"0": {}}}).status_code == 409
    assert client.post(url, json={"approved": True, "edits": {"3": {}}}).status_code == 409
    r = client.post(url, json={"approved": True, "edits": {
        "0": {"list_id": 1002, "lead_ids": [lead_id]}}})
    assert r.status_code == 200, r.text
    assert r.json()["details"]["calls"][0]["edited_args"]["list_id"] == 1002
    assert wait_for(client, task_id, {"done", "failed"})["status"] == "done"
    lists = client.app.state.hub.deps.marketo.lists
    assert lead_id in lists[1002] and lead_id not in lists[1001]



def test_tool_exceptions_go_back_to_the_model(client, script, monkeypatch):
    turns, seen = script
    demo = client.app.state.hub.deps.marketo

    async def broken(*a, **k):
        raise RuntimeError("Marketo said no")

    monkeypatch.setattr(demo, "get_leads", broken)
    make_agent(client)
    turns += [Completion("", 1, 1, 0, [call("rest_get_leads", {
        "filter_type": "email", "values": ["x@y.z"]})])]
    done = wait_for(client, run_task(client, "list_builder"), {"done", "failed"})
    assert done["status"] == "done", done["result"]
    err = next(m for m in seen[1]["messages"] if m["role"] == "tool")
    assert err["is_error"] and "Marketo said no" in err["content"]


def test_agent_character_is_validated_and_shown(client):
    agent = make_agent(client, character="female-c")
    profile = next(a for a in client.get("/api/agents").json() if a["id"] == agent["id"])
    assert profile["character"] == "female-c"
    assert client.put(f"/api/agents/{agent['id']}", json={"character": "robot"}).status_code == 422
    assert client.put(f"/api/agents/{agent['id']}", json={"character": ""}).status_code == 200

