"""Editing, re-running and archiving tasks."""

import time

from app.llm.router import Completion
from tests.conftest import call, make_agent, wait_for


def _task(client, task_id):
    return next(t for t in client.get("/api/tasks").json() if t["id"] == task_id)


def _upload(client, name, data):
    r = client.post("/api/attachments", files={"file": (name, data)})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_edit_a_queued_task_and_its_files(client):
    agent = make_agent(client, tools=[])
    a, b = _upload(client, "a.md", b"first brief"), _upload(client, "b.md", b"second brief")
    task = client.post("/api/tasks", json={"title": "later", "agent_id": agent["id"],
                                           "scheduled_for": "2099-01-01T00:00:00Z",
                                           "attachment_ids": [a]}).json()
    r = client.patch(f"/api/tasks/{task['id']}", json={
        "title": "Renamed", "description": "New brief", "params": {"region": "EMEA"},
        "attachment_ids": [b], "remove_attachment_ids": [a]})
    assert r.status_code == 200, r.text
    assert (r.json()["title"], r.json()["params"]) == ("Renamed", {"region": "EMEA"})
    assert [f["filename"] for f in client.get(f"/api/tasks/{task['id']}/attachments").json()] \
        == ["b.md"]
    assert client.patch(f"/api/tasks/{task['id']}", json={"title": None}).json()["title"] == \
        "Renamed"  # null doesn't blank a field


def test_move_a_finished_task_back_to_queued(client, script):
    turns, seen = script
    agent = make_agent(client, tools=[])
    first = _upload(client, "brief.md", b"Event on 12 June.")
    turns += [Completion("Draft one, for 12 June.", 1, 1, 0),
              Completion("Revised after feedback.", 1, 1, 0)]
    task = client.post("/api/tasks", json={"title": "Event page", "agent_id": agent["id"],
                                           "attachment_ids": [first]}).json()
    wait_for(client, task["id"], {"done"})
    extra = _upload(client, "speakers.csv", b"name\nDerek Huff\n")
    client.post(f"/api/tasks/{task['id']}/feedback",
                json={"feedback": "Add the speakers.", "attachment_ids": [extra]})
    wait_for(client, task["id"], {"done"})

    # a finished task's record can be edited, but not the files it used
    assert client.patch(f"/api/tasks/{task['id']}", json={"title": "Event page v1"}) \
        .status_code == 200
    newer = _upload(client, "brief v2.md", b"Event moved to 19 June.")
    assert client.patch(f"/api/tasks/{task['id']}", json={"attachment_ids": [newer]}) \
        .status_code == 409

    turns += [Completion("Fresh draft for 19 June.", 1, 1, 0)]
    calls_before = len(seen)
    r = client.post(f"/api/tasks/{task['id']}/requeue", json={
        "description": "Use the new date.", "attachment_ids": [newer],
        "remove_attachment_ids": [first]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "queued" and r.json()["run"] == 1
    hist = r.json()["history"]
    assert hist[0]["run"] == 0 and hist[0]["result"] == "Revised after feedback."
    assert hist[0]["feedback_rounds"] == 1 and "revisions" not in r.json()["params"]
    done = wait_for(client, task["id"], {"done"})
    assert done["result"] == "Fresh draft for 19 June."
    fresh = seen[calls_before]["messages"]
    assert len(fresh) == 1  # a fresh conversation: only the new brief
    brief = str(fresh[0])
    assert "Use the new date." in brief and "Event moved to 19 June." in brief
    assert "Derek Huff" in brief  # files from feedback rounds are part of the new brief
    assert "Event on 12 June." not in brief and "revisions" not in brief
    assert client.post(f"/api/tasks/{task['id']}/requeue", json={}).json()["run"] == 2


def test_archive_hides_without_deleting_and_holds_queued_tasks(client):
    from app.events.schema import utcnow

    agent = make_agent(client, tools=[])
    task = client.post("/api/tasks", json={"title": "Later", "agent_id": agent["id"],
                                           "scheduled_for": "2099-01-01T00:00:00Z"}).json()
    archived = client.post(f"/api/tasks/{task['id']}/archive").json()
    assert archived["archived_at"] and archived["status"] == "queued"
    # due now, but archived: the hub doesn't start it
    client.patch(f"/api/tasks/{task['id']}", json={"scheduled_for": utcnow().isoformat()})
    time.sleep(2.5)
    assert _task(client, task["id"])["status"] == "queued"
    back = client.post(f"/api/tasks/{task['id']}/unarchive").json()
    assert back["archived_at"] is None
    assert wait_for(client, task["id"], {"done", "failed"})


def test_running_or_waiting_tasks_cant_be_changed(client, script):
    turns, _ = script
    agent = make_agent(client)
    lead_id = next(iter(client.app.state.hub.deps.marketo.leads.values()))["id"]
    turns += [Completion("", 1, 1, 0, [call("rest_add_leads_to_list",
                                            {"list_id": 1001, "lead_ids": [lead_id]})])]
    task = client.post("/api/tasks", json={"title": "Add", "agent_id": agent["id"]}).json()
    wait_for(client, task["id"], {"needs_approval"})
    for path in ("archive", "requeue"):
        assert client.post(f"/api/tasks/{task['id']}/{path}", json={}).status_code == 409
    assert client.patch(f"/api/tasks/{task['id']}", json={"title": "x"}).status_code == 409

