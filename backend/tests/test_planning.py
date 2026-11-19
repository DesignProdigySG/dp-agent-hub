"""Planning work as tasks that wait for each other, fix rounds, approvals that name what
they're about, and copying a list into a program."""

from app import handoff
from app.llm.router import Completion
from tests.conftest import call, make_agent, wait_for
from tests.test_handoff import events  # noqa: F401 (fixture)


def test_a_plan_runs_in_order_with_earlier_results_in_each_brief(client, script, events,  # noqa: F811
                                                                  monkeypatch):
    monkeypatch.setattr(handoff, "START_DELAY_S", 1)
    turns, seen = script
    pm = make_agent(client, name="Project Manager", tools=["plan_tasks"])
    designer = make_agent(client, name="Designer", tools=[])
    builder = make_agent(client, name="Campaigner", tools=[])
    turns += [Completion("", 1, 1, 0, [call("plan_tasks", {"steps": [
                  {"to_agent": "Designer", "title": "Design the invite", "brief": "Emails."},
                  {"to_agent": "Campaigner", "title": "Build the program", "brief": "Program.",
                   "after": [0]},
                  {"to_agent": pm["id"], "title": "Report back", "brief": "Status.",
                   "after": [1]}]})]),
              Completion("Planned.", 1, 1, 0),
              Completion("Invite designed: email 77.", 1, 1, 0),  # the Designer
              Completion("Program 900 built.", 1, 1, 0),  # the Campaigner
              Completion("Ready to test.", 1, 1, 0)]  # the PM's report
    origin = client.post("/api/tasks", json={"title": "Plan the event", "agent_id": pm["id"],
                                             "description": "brief"}).json()
    wait_for(client, origin["id"], {"done", "failed"})  # planning is internal: no approval
    tasks = {t["title"]: t for t in client.get("/api/tasks").json()}
    design, build, report = (tasks["Design the invite"], tasks["Build the program"],
                             tasks["Report back"])
    assert (design["agent_id"], build["agent_id"], report["agent_id"]) == (
        designer["id"], builder["id"], pm["id"])
    assert build["params"]["after"] == [design["id"]] and report["params"]["after"] == [
        build["id"]]
    assert build["status"] == "queued"  # waits while the design isn't done
    assert wait_for(client, report["id"], {"done", "failed"}, timeout=30)["status"] == "done"
    build_brief = next(str(x["messages"][0]) for x in seen if "Build the program" in
                       str(x["messages"][0]))
    assert "Invite designed: email 77." in build_brief  # it got the Designer's result
    # the relay on the floor: whoever finished last walks over to the next agent
    relays = [e.handoff.to_agent_id for e in events if getattr(e, "action", "") == "handoff"]
    assert relays == [designer["id"], builder["id"], pm["id"]]


def test_a_task_waiting_for_a_failed_one_fails_too(client, script, monkeypatch):
    monkeypatch.setattr(handoff, "START_DELAY_S", 1)
    a = make_agent(client, name="First", tools=[])
    b = make_agent(client, name="Second", tools=[])
    first = client.post("/api/tasks", json={"title": "one", "agent_id": a["id"],
                                            "scheduled_for": "2099-01-01T00:00:00Z"}).json()
    task = handoff.create(from_task_id=first["id"], from_agent_id=a["id"], to=b["id"],
                          title="two", brief="x", params={"after": [first["id"]]}, delay_s=0)
    from app.db import Task, session
    from app.events.schema import TaskStatus

    with session() as s:
        t = s.get(Task, first["id"])
        t.status = TaskStatus.FAILED
        s.add(t)
        s.commit()
    out = wait_for(client, task.id, {"failed", "done"})
    assert out["status"] == "failed" and "“one”" in out["result"]


def test_an_approval_names_what_it_is_about(db):
    from app import review
    from app.db import DesignDeliverable, MarketoChange, session

    with session() as s:
        s.add(DesignDeliverable(task_id="t1", agent_id="designer", kind="email", name="Invitation",
                                version=1,
                                subject="You're invited", marketo={"email_id": 1365}))
        s.add(MarketoChange(task_id="t1", agent_id="designer", kind="landing_page",
                            object_id="1223", name="Registration", action="published"))
        s.commit()
    items = review.items("t1", [{"tool": "asset_approve_draft_email", "args": {"id": 1365}},
                                {"tool": "asset_approve_landing_page", "args": {"id": 1223}},
                                {"tool": "asset_activate_smart_campaign", "args": {"id": 9}}])
    assert [(i["verb"], i["kind"], i["name"]) for i in items] == [
        ("Approve", "email", "Invitation"), ("Approve", "landing_page", "Registration"),
        ("Activate", "smart_campaign", "")]
    assert items[0]["subject"] == "You're invited" and items[0]["design_id"]
    assert review.summary("Designer", items) == (
        "Designer wants to approve / activate in Marketo: the email “Invitation”, the landing "
        "page “Registration”, smart campaign 9.")


def test_request_changes_sends_notes_back_and_the_agent_comes_back_to_you(client, script):
    turns, seen = script
    agent = make_agent(client, name="Builder", tools=["rest_add_leads_to_list"])
    turns += [Completion("Adding them now.", 1, 1, 0, [call("rest_add_leads_to_list", {
                  "list_id": 7, "lead_ids": [1, 2]})]),
              Completion("Should I drop lead 2 entirely, or keep it for later?", 1, 1, 0),
              Completion("Dropped lead 2 for good.", 1, 1, 0)]
    task = client.post("/api/tasks", json={"title": "Build the list", "agent_id": agent["id"]})
    task = task.json()
    client.post(f"/api/tasks/{task['id']}/messages", json={"text": "Keep it small."})
    wait_for(client, task["id"], {"needs_approval"})
    approval = next(a for a in client.get("/api/approvals").json() if a["task_id"] == task["id"])
    no_notes = client.post(f"/api/approvals/{approval['id']}/decision",
                           json={"approved": False, "choice": "revise", "comment": " "})
    assert no_notes.status_code == 409  # changes need notes
    r = client.post(f"/api/approvals/{approval['id']}/decision",
                    json={"approved": False, "choice": "revise", "comment": "Only lead 1."})
    assert r.status_code == 200 and r.json()["details"]["choice"] == "revise"
    assert "Keep it small." in str(seen[0]["messages"][0])  # a note before it started: briefed

    # it answered without asking again: that comes back to you, not straight to "done"
    back = wait_for(client, task["id"], {"needs_approval", "done", "failed"})
    assert back["status"] == "needs_approval" and back["result"].startswith("Should I drop")
    told = str(seen[-1]["messages"])
    assert "wants changes" in told and "Only lead 1." in told  # the agent got the notes
    ask = next(a for a in client.get("/api/approvals").json()
               if a["task_id"] == task["id"] and a["status"] == "pending")
    assert ask["action"] == "reply" and ask["details"]["kind"] == "reply"

    # you answer in the conversation, like a chat: another round in the same thread
    client.post(f"/api/tasks/{task['id']}/messages", json={"text": "Drop it for good."})
    again = wait_for(client, task["id"], {"needs_approval", "done", "failed"})
    assert again["result"] == "Dropped lead 2 for good." and "Drop it for good." in \
        str(seen[-1]["messages"])
    ask = next(a for a in client.get("/api/approvals").json()
               if a["task_id"] == task["id"] and a["status"] == "pending")
    r = client.post(f"/api/approvals/{ask['id']}/decision",
                    json={"approved": True, "choice": "done", "comment": ""})
    assert r.status_code == 200
    assert wait_for(client, task["id"], {"done"})["result"] == "Dropped lead 2 for good."
    thread = [(m["author_id"], m["kind"]) for m in
              client.get(f"/api/tasks/{task['id']}/messages").json()]
    assert thread == [("you", "note"), ("you", "changes"), (agent["id"], "result"),
                      ("you", "feedback"), (agent["id"], "result"), ("you", "approved")]


def test_approve_some_items_and_send_the_rest_back(client, script):
    turns, seen = script
    agent = make_agent(client, name="Builder", tools=["rest_add_leads_to_list"])
    turns += [Completion("Adding both.", 1, 1, 0, [
                  call("rest_add_leads_to_list", {"list_id": 7, "lead_ids": [1]}),
                  call("rest_add_leads_to_list", {"list_id": 8, "lead_ids": [2]})]),
              Completion("Added to list 7; list 8 needs a different lead, which one?", 1, 1, 0)]
    task = client.post("/api/tasks", json={"title": "Two lists", "agent_id": agent["id"]}).json()
    wait_for(client, task["id"], {"needs_approval"})
    approval = next(a for a in client.get("/api/approvals").json() if a["task_id"] == task["id"])
    r = client.post(f"/api/approvals/{approval['id']}/decision",
                    json={"approved": True, "selected": [0], "comment": "Not lead 2."})
    assert r.status_code == 200
    assert r.json()["details"]["choice"] == "partial" and r.json()["details"]["selected"] == [0]
    back = wait_for(client, task["id"], {"needs_approval", "done", "failed"})
    assert back["status"] == "needs_approval"  # it came back to you about the one sent back
    told = str(seen[-1]["messages"])
    assert "approved the other items" in told and "Not lead 2." in told
    said = [m["text"] for m in client.get(f"/api/tasks/{task['id']}/messages").json()
            if m["author_id"] == "you"]
    assert said[0].startswith("Approved ") and "Not yet:" in said[0]


def test_a_rejection_stops_the_steps_after_it(client, script, monkeypatch):
    from app.db import Approval, Task, session
    from app.events.schema import ApprovalStatus, TaskStatus

    monkeypatch.setattr(handoff, "START_DELAY_S", 1)
    a = make_agent(client, name="Designer", tools=[])
    b = make_agent(client, name="Campaigner", tools=[])
    first = client.post("/api/tasks", json={"title": "Design it", "agent_id": a["id"],
                                            "scheduled_for": "2099-01-01T00:00:00Z"}).json()
    with session() as s:
        t = s.get(Task, first["id"])
        t.status = TaskStatus.DONE
        s.add(t)
        s.add(Approval(task_id=t.id, agent_id=a["id"], action="tool_calls", summary="x",
                       status=ApprovalStatus.REJECTED))
        s.commit()
    nxt = handoff.create(from_task_id=first["id"], from_agent_id=a["id"], to=b["id"],
                         title="Build it", brief="x", params={"after": [first["id"]]}, delay_s=0)
    out = wait_for(client, nxt.id, {"failed", "done"})
    assert out["status"] == "failed" and "you rejected “Design it”" in out["result"]


def test_previews_show_marketo_tokens_as_values_not_placeholders():
    from app.design import _tokens

    html = ('<a href="{{my.Registration URL}}">RSVP</a><p>Join us on {{my.Event Date}} at '
            '{{my.Event Venue:default=the club}} for {{my.Mystery}}.</p>')
    out = _tokens(html, {"Event Date": "Saturday 14 March", "Registration URL": "#reg"})
    assert '<a href="#reg">' in out  # in a link: the plain value
    assert "Saturday 14 March</span>" in out and "the club</span>" in out  # marked as tokens
    assert "{{my.Mystery}}</span>" in out and "[Mystery]" not in out  # unknown: the token itself
    assert 'title="Marketo token {{my.Event Date}}"' in out


def test_a_cloned_asset_is_recorded_under_its_own_id():
    from app.marketo import links

    found = links.changes_from_tool("asset_clone_email", {"id": 1365, "name": "Invite (run 2)"},
                                    '{"success": true, "result": [{"id": 1400}]}')
    assert found == [{"kind": "email", "object_id": 1400, "action": "cloned",
                      "name": "Invite (run 2)", "detail": "cloned from 1365"}]


def test_a_fix_round_waits_for_you_and_there_are_at_most_two(client, script):
    from app.db import Task, session

    turns, seen = script
    auditor = make_agent(client, name="Checker", tools=[])
    pm = make_agent(client, name="Planner", tools=["plan_fixes"])
    fix = {"steps": [{"to_agent": auditor["id"], "title": "Check again", "brief": "Re-check."}]}
    turns += [Completion("Blocked: proposing fixes.", 1, 1, 0, [call("plan_fixes", fix)]),
              Completion("Status: fixes planned.", 1, 1, 0),
              Completion("All checked.", 1, 1, 0)]
    task = client.post("/api/tasks", json={"title": "Report back", "agent_id": pm["id"]}).json()
    wait_for(client, task["id"], {"needs_approval"})
    card = next(a for a in client.get("/api/approvals").json() if a["task_id"] == task["id"])
    assert card["action"] == "plan_fixes" and "proposes a round of fixes" in card["summary"]
    assert card["details"]["items"][0]["steps"][0]["title"] == "Check again"
    assert len([t for t in client.get("/api/tasks").json() if t["title"] == "Check again"]) == 0
    client.post(f"/api/approvals/{card['id']}/decision", json={"approved": True, "comment": ""})
    wait_for(client, task["id"], {"done"})
    made = [t for t in client.get("/api/tasks").json() if t["title"] == "Check again"]
    assert len(made) == 1 and made[0]["params"]["shared"]["fix_round"] == 1

    # the round count travels with the work: after two rounds, no more
    with session() as s:
        t = s.get(Task, made[0]["id"])
        t.params = {**t.params, "shared": {**t.params["shared"], "fix_round": 2}}
        s.add(t)
        s.commit()
    import asyncio
    from types import SimpleNamespace

    from app.agents.tools import plan_fixes
    out = asyncio.run(plan_fixes.coroutine(
        steps=[], runtime=SimpleNamespace(state={"task_id": made[0]["id"],
                                                 "agent_id": auditor["id"]})))
    assert "2 fix rounds already" in out["error"]


def test_a_finished_agent_handing_on_stays_idle():
    from app import handoff
    from app.db import Task
    from app.events.schema import AgentState, AgentStatus, Zone

    nxt = Task(title="Build it", agent_id="campaigner", params={"to_agent_name": "Campaigner"})
    done = AgentStatus(agent_id="designer", zone=Zone.DESIGN_STUDIO, state=AgentState.IDLE,
                       status_text="Task complete")
    ev = handoff.event(nxt, done)
    assert ev.action == "handoff" and ev.handoff.to_agent_id == "campaigner"
    assert ev.state == AgentState.IDLE and ev.status_text == "Task complete"
    busy = done.model_copy(update={"state": AgentState.BUSY})
    assert handoff.event(nxt, busy).status_text == "Handing off to Campaigner"


def test_the_report_sees_the_whole_run(db):
    from app.db import Task, session
    from app.events.schema import TaskStatus
    from app.hub import earlier_results

    with session() as s:
        a = Task(title="Design", agent_id="designer", status=TaskStatus.DONE, result="Emails")
        s.add(a)
        s.commit()
        b = Task(title="Build", agent_id="campaigner", status=TaskStatus.DONE, result="Program",
                 params={"after": [a.id]})
        s.add(b)
        s.commit()
        c = Task(title="Check", agent_id="auditor", status=TaskStatus.DONE, result="x" * 9000,
                 params={"after": [b.id]})
        s.add(c)
        s.commit()
        report = Task(title="Report", agent_id="project_manager", params={"after": [c.id]})
    text = earlier_results(report)
    assert "Emails" in text and "Program" in text and "(shortened)" in text
    assert text.index("### Design") < text.index("### Build") < text.index("### Check")


def test_a_list_is_copied_into_the_program(client, monkeypatch):
    import asyncio

    from app.agents.tools import create_program_list
    from app.deps import get_deps
    from app.marketo import links

    m = get_deps().marketo
    lists = {7: [1, 2, 3]}
    made: list[dict] = []

    async def asset(call):
        path = call["path"]
        if path.endswith("/program/50.json"):
            return {"result": [{"id": 50, "name": "202703 - Spring Summit"}]}
        if path.endswith("/staticList/byName.json"):
            return {"result": [x for x in made if x["name"] == call["query"]["name"]]}
        if path.endswith("/staticLists.json"):
            body = call.get("body") or call.get("form") or {}
            made.append({"id": 90, "name": body["name"],
                         "folder": {"id": 50, "type": "Program", "name": "202703 - Spring Summit"}})
            lists[90] = []
            return {"result": [made[-1]]}
        raise AssertionError(path)

    async def list_leads(list_id, batch, fields):
        return [{"id": i} for i in lists[list_id]]

    async def add_leads_to_list(list_id, ids):
        lists[list_id] += ids

    monkeypatch.setattr(m, "asset", asset)
    monkeypatch.setattr(m, "list_leads", list_leads)
    monkeypatch.setattr(m, "add_leads_to_list", add_leads_to_list)
    args = {"program_id": 50, "name": "Invite list", "copy_from_list_id": 7}
    out = asyncio.run(create_program_list.ainvoke(args))
    assert out["list_id"] == 90 and lists[90] == [1, 2, 3] and lists[7] == [1, 2, 3]
    assert out["smart_list_value"] == "202703 - Spring Summit.Invite list" and out["created"]
    again = asyncio.run(create_program_list.ainvoke(args))  # safe to repeat: no second list
    assert again["list_id"] == 90 and not again["created"] and len(made) == 1
    change = links.changes_from_tool("create_program_list", args, out)[0]
    assert change["kind"] == "static_list" and change["object_id"] == 90


