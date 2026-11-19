"""Agents handing work to each other."""

import pytest

from app import handoff
from app.llm.router import Completion
from tests.conftest import call, make_agent, wait_for
from tests.test_data_health import doctor, scan_task  # noqa: F401 (fixture)


@pytest.fixture
def events(client, monkeypatch):
    """Every message the hub broadcasts."""
    bus = client.app.state.hub.deps.bus
    seen = []
    orig = bus.broadcast

    async def spy(msg):
        seen.append(msg)
        await orig(msg)

    monkeypatch.setattr(bus, "broadcast", spy)
    return seen


def _task(client, task_id):
    return next(t for t in client.get("/api/tasks").json() if t["id"] == task_id)


def test_an_agent_hands_a_task_to_a_teammate(client, script, events, monkeypatch):
    monkeypatch.setattr(handoff, "START_DELAY_S", 1)
    client.put("/api/config", json={"changes": {"marketo_ui_url": "https://app-x.marketo.com/#"}})
    turns, seen = script
    sender = make_agent(client, name="Data Doctor", tools=["hand_off"], autonomy="autonomous")
    receiver = make_agent(client, name="Qualifier", tools=[])
    up = client.post("/api/attachments", files={"file": ("webinar.csv", b"email\na@b.com\n")})
    turns += [Completion("", 1, 1, 0, [call("hand_off", {
                  "to_agent": "Qualifier", "title": "Qualify 2 leads",
                  "brief": "Two webinar attendees look like strong fits.\n\nPlease route them.",
                  "lead_ids": [301, 302], "attachment_ids": ["webinar.csv"]})]),
              Completion("Handed off to Qualifier (task created).", 1, 1, 0),
              Completion("Qualified both.", 1, 1, 0)]  # the receiver's run
    origin = client.post("/api/tasks", json={"title": "Check the webinar list",
                                             "agent_id": sender["id"],
                                             "attachment_ids": [up.json()["id"]]}).json()
    wait_for(client, origin["id"], {"done", "failed"})
    assert _task(client, origin["id"])["status"] == "done"
    # the tool told the sender what happened
    tool_msg = str(seen[1]["messages"][-1])
    assert "Handed off to Qualifier" in tool_msg and "Qualify 2 leads" in tool_msg

    new = next(t for t in client.get("/api/tasks").json() if t["agent_id"] == receiver["id"])
    p = new["params"]
    assert (p["from_agent_id"], p["from_task_id"], p["hops"], p["lead_ids"]) == (
        sender["id"], origin["id"], 1, [301, 302])
    assert new["title"] == "Qualify 2 leads" and new["scheduled_for"]
    assert "[301](https://app-x.marketo.com/leadDatabase/loadLeadDetail?leadId=301)" in \
        new["description"]
    assert new["history"][0]["status"] == "handed_off" and "Data Doctor" in \
        new["history"][0]["result"]
    assert [a["filename"] for a in client.get(f"/api/tasks/{new['id']}/attachments").json()] \
        == ["webinar.csv"]
    # the floor saw it: the sender goes over to the receiver with two scripted lines
    ev = next(e for e in events if getattr(e, "action", "") == "handoff")
    assert ev.agent_id == sender["id"] and ev.handoff.to_agent_id == receiver["id"]
    assert ev.handoff.task_id == new["id"]
    assert (ev.handoff.line_from, ev.handoff.line_to) == ("2 leads ready for you", "On it")
    # ... and the receiver picks it up a moment later, with the brief and the file
    done = wait_for(client, new["id"], {"done", "failed"}, timeout=20)
    assert done["status"] == "done" and done["result"] == "Qualified both."
    brief = str(seen[-1]["messages"][0])
    assert "Two webinar attendees" in brief and "a@b.com" in brief


def test_refusals_come_back_as_tool_errors(client, script):
    turns, seen = script
    me = make_agent(client, name="Loner", tools=["hand_off"], autonomy="autonomous")
    turns += [Completion("", 1, 1, 0, [call("hand_off", {"to_agent": "Loner", "title": "x",
                                                         "brief": "y"}, "c1"),
                                       call("hand_off", {"to_agent": "Nobody", "title": "x",
                                                         "brief": "y"}, "c2")]),
              Completion("Nothing to hand off.", 1, 1, 0)]
    t = client.post("/api/tasks", json={"title": "Try", "agent_id": me["id"]}).json()
    assert wait_for(client, t["id"], {"done", "failed"})["status"] == "done"
    results = [str(m) for m in seen[1]["messages"][-2:]]
    assert "hand work to yourself" in results[0]
    assert "no agent named" in results[1] and "Nobody" in results[1]
    assert len(client.get("/api/tasks").json()) == 1  # nothing was created


def test_hops_are_capped(client):
    a = make_agent(client, name="Alpha", tools=["hand_off"])
    b = make_agent(client, name="Bravo", tools=["hand_off"])
    task = handoff.create(from_task_id=None, from_agent_id=a["id"], to="Bravo", title="1",
                          brief="first")
    for n in range(2, handoff.MAX_HOPS + 1):
        task = handoff.create(from_task_id=task.id, from_agent_id=b["id"] if n % 2 == 0
                              else a["id"], to="Alpha" if n % 2 == 0 else "bravo",
                              title=str(n), brief="again")
        assert task.params["hops"] == n
    with pytest.raises(handoff.HandoffError, match="already been handed on"):
        handoff.create(from_task_id=task.id, from_agent_id=a["id"], to="Bravo", title="4",
                       brief="loop")
    assert (handoff.lines(task)) == ("again", "On it")
    assert handoff._short("A rather long first line that keeps going on") == \
        "A rather long first line that keeps…"


def test_the_data_doctor_hands_its_best_leads_on(client, doctor, script, events,  # noqa: F811
                                                 monkeypatch):
    monkeypatch.setattr(handoff, "START_DELAY_S", 1)  # the receiver answers "Done." (script)
    receiver = make_agent(client, name="Qualifier", tools=[])
    task = wait_for(client, scan_task(client, max_lead_id=60, handoff_to="Qualifier",
                                      handoff_max=5), {"done", "failed"}, timeout=60)
    assert task["status"] == "done", task["result"]
    assert "**Handed off** 5 leads to Qualifier" in task["result"]
    new = next(t for t in client.get("/api/tasks").json() if t["agent_id"] == receiver["id"])
    assert new["params"]["from_agent_id"] == "data_doctor" and len(new["params"]["lead_ids"]) == 5
    assert "worth qualifying" in new["description"]
    ev = next(e for e in events if getattr(e, "action", "") == "handoff")
    assert ev.agent_id == "data_doctor" and ev.handoff.line_from == "5 leads ready for you"
    assert wait_for(client, new["id"], {"done", "failed"}, timeout=20)["status"] == "done"
