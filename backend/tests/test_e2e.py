"""Drive the real app (demo Marketo, scripted LLM) through FastAPI and the WebSocket: run,
pause, approve, finish."""

import json

from app.llm.router import Completion
from tests.conftest import call, make_agent, wait_for

# `client` (signed-in admin) and `script` (scripted LLM) come from conftest.py.


def test_agent_pauses_for_approval_then_completes(client, script):
    turns, _ = script
    agent = make_agent(client)
    lead_id = next(iter(client.app.state.hub.deps.marketo.leads.values()))["id"]
    turns += [Completion("", 10, 5, 0.0, tool_calls=[
                  call("rest_add_leads_to_list", {"list_id": 1001, "lead_ids": [lead_id]})]),
              Completion("Added 1 lead to list 1001.", 10, 5, 0.0)]
    with client.websocket_connect("/ws") as ws:
        assert json.loads(ws.receive_text())["type"] == "snapshot"
        task_id = client.post("/api/tasks", json={"title": "Add to list",
                                                  "agent_id": agent["id"]}).json()["id"]
        wait_for(client, task_id, {"needs_approval"})

        types = set()
        while "approval_updated" not in types:
            types.add(json.loads(ws.receive_text())["type"])
        assert {"task_updated", "agent_event"} <= types

    approval = next(a for a in client.get("/api/approvals").json() if a["task_id"] == task_id)
    assert approval["action"] == "rest_add_leads_to_list"
    assert approval["details"]["calls"][0]["risk"] == "write"

    r = client.post(f"/api/approvals/{approval['id']}/decision", json={"approved": True})
    assert r.status_code == 200
    done = wait_for(client, task_id, {"done", "failed"})
    assert done["status"] == "done", done["result"]
    assert done["result"] == "Added 1 lead to list 1001."

    # deciding twice is rejected
    again = client.post(f"/api/approvals/{approval['id']}/decision", json={"approved": True})
    assert again.status_code == 409


def test_read_only_agent_finishes_without_approval(client, script):
    turns, _ = script
    agent = make_agent(client, name="Reader", tools=["activity_summary"])
    turns += [Completion("", 10, 5, 0.0, tool_calls=[call("activity_summary", {"days": 1})]),
              Completion("Quiet week.", 10, 5, 0.0)]
    task_id = client.post("/api/tasks", json={"title": "Summarise",
                                              "agent_id": agent["id"]}).json()["id"]
    done = wait_for(client, task_id, {"done", "failed"})
    assert done["status"] == "done" and done["result"] == "Quiet week."
    assert not [a for a in client.get("/api/approvals").json() if a["task_id"] == task_id]


def test_only_queued_tasks_are_editable(client):
    agent = make_agent(client)
    r = client.post("/api/tasks", json={"title": "later", "agent_id": agent["id"],
                                        "scheduled_for": "2099-01-01T00:00:00Z"})
    task_id = r.json()["id"]
    assert client.patch(f"/api/tasks/{task_id}", json={"title": "renamed"}).json()["title"] == \
        "renamed"
    assert client.delete(f"/api/tasks/{task_id}").status_code == 204
    assert client.post("/api/tasks", json={"title": "x", "agent_id": "nobody"}).status_code == 422
