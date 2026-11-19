"""Links into Marketo for everything agents create or change."""

from app.llm.router import Completion
from app.marketo import links
from tests.conftest import call, make_agent, wait_for

CLASSIC = "https://app-ab12.marketo.com/#"
EXPERIENCE = "https://experience.adobe.com/#/@acme/so:123-ABC-456/marketo-engage/classic/"


def _set_base(client, base):
    r = client.put("/api/config", json={"changes": {"marketo_ui_url": base}})
    assert r.status_code == 200, r.text


def test_link_formats(client):
    assert links.url("program", 1001) is None  # no address set: no links
    _set_base(client, CLASSIC)
    assert links.url("program", 1001) == f"{CLASSIC}ME1001A1"  # event programs
    assert links.url("program", 1001, "PG") == f"{CLASSIC}PG1001A1"  # a Default program
    assert links.url("landing_page", 7) == f"{CLASSIC}LP7A1"
    assert links.url("smart_campaign", 1379) == f"{CLASSIC}SC1379A1"
    assert links.url("lead", 869) == \
        "https://app-ab12.marketo.com/leadDatabase/loadLeadDetail?leadId=869"
    assert links.url("email_template", 5) is None  # no reliable link: listed by ID
    _set_base(client, EXPERIENCE)  # pasted with classic/ or without: the same links
    assert links.url("form", 3) == f"{EXPERIENCE}FO3A1"
    root = EXPERIENCE.removesuffix("classic/")
    _set_base(client, root)
    assert links.url("program", 1151) == f"{root}classic/ME1151A1"
    assert links.url("email", 1395) == f"{root}email/1395/overview/details"  # the email editor


def test_marketo_links_from_its_apis_open_for_you(client):
    root = EXPERIENCE.removesuffix("classic/")
    text = ("[Program](https://app-abc123.marketo.com/#ME1150A1), "
            "[Email](https://app-abc123.marketo.com/#EM1389A1LA1), https://experience.adobe."
            "com/#/@ABCD1234@AdobeOrg/so:123-ABC-456/marketo-engage/classic/SC1395A1")
    assert links.rewrite(text) == text  # no address set: left alone
    _set_base(client, root)
    assert links.rewrite(text) == (
        f"[Program]({root}classic/ME1150A1), [Email]({root}email/1389/overview/details), "
        f"{root}classic/SC1395A1")


def test_what_a_tool_call_changed():
    created = links.changes_from_tool("asset_create_email", {"name": "Invite"},
                                      '{"success": true, "result": [{"id": 55}]}')
    assert created == [{"kind": "email", "object_id": 55, "action": "created",
                        "name": "Invite"}]
    updated = links.changes_from_tool("asset_update_landing_page_template_content",
                                      {"id": 9, "content": "<html/>"}, {"success": True})
    assert updated[0] | {} == {"kind": "landing_page_template", "object_id": 9,
                               "action": "updated", "name": ""}
    assert links.changes_from_tool("asset_get_email_by_id", {"id": 1}, {"result": [{}]}) == []
    assert links.changes_from_tool("asset_create_email", {}, {"success": False}) == []
    assert links.changes_from_tool("create_form", {"name": "Reg"}, {"id": 5001})[0]["kind"] \
        == "form"
    assert links.changes_from_tool("add_field_to_form", {"id": 5001, "fieldId": "Company"},
                                   {"id": 5001})[0]["action"] == "updated"
    published = links.changes_from_tool("publish_email", {"name": "Invite"}, {
        "published": "Invite", "email_id": 12, "email_template_id": 34})
    assert [(c["kind"], c["object_id"]) for c in published] == [("email", 12),
                                                                ("email_template", 34)]


def test_agents_link_what_they_change(client, script):
    turns, seen = script
    _set_base(client, CLASSIC)
    agent = make_agent(client)
    lead_id = next(iter(client.app.state.hub.deps.marketo.leads.values()))["id"]
    turns += [Completion("", 1, 1, 0, [call("rest_add_leads_to_list",
                                            {"list_id": 1001, "lead_ids": [lead_id]})]),
              Completion("Added the lead to [list 1001](https://app-ab12.marketo.com/#"
                         "ST1001A1).", 1, 1, 0)]
    task_id = client.post("/api/tasks", json={"title": "Add", "agent_id": agent["id"]}).json()[
        "id"]
    wait_for(client, task_id, {"needs_approval"})
    approval = next(a for a in client.get("/api/approvals").json() if a["task_id"] == task_id)
    from app.config import get_settings
    from app.db import Approval, session
    from app.notify import approval_message

    with session() as s:
        msg = approval_message(get_settings(), s.get(Approval, approval["id"]), "List Builder",
                               "email")
    assert ("Open static list 1001 in Marketo", f"{CLASSIC}ST1001A1") in msg.actions
    client.post(f"/api/approvals/{approval['id']}/decision", json={"approved": True})
    assert wait_for(client, task_id, {"done", "failed"})["status"] == "done"
    # the agent was told the link, and the task and the agent report list it
    assert f"{CLASSIC}ST1001A1" in str(seen[-1]["messages"])
    changes = client.get(f"/api/tasks/{task_id}/marketo").json()
    assert changes["links_configured"] is True
    assert [(c["kind"], c["url"]) for c in changes["changes"]] == [
        ("static_list", f"{CLASSIC}ST1001A1")]
    report = client.get(f"/api/agents/{agent['id']}/report").json()
    assert report["marketo"][0]["url"] == f"{CLASSIC}ST1001A1"


def test_repeated_changes_read_as_one_line(client):
    for field in ("Company", "Title", "MobilePhone"):
        links.record(task_id="t1", agent_id="designer", kind="form", object_id=5001,
                     action="updated", detail=f"added {field}")
    links.record(task_id="t1", agent_id="designer", kind="form", object_id=5001,
                 action="created", name="Registration")
    rows = links.for_task("t1")
    assert [(r["action"], r["count"], r["detail"]) for r in rows] == [
        ("updated", 3, "3 changes"), ("created", 1, "")]
