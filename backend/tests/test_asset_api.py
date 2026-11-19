"""The Marketo Asset API as agent tools, and the Designer publishing to Marketo."""

import asyncio
import json
import time

import httpx

from app.llm.router import Completion
from app.marketo import asset_api
from tests.conftest import call, wait_for
from tests.test_designer import EMAIL, FIELDS, PAGE


def test_every_operation_is_an_agent_tool(client):
    tools = {t["name"]: t for t in client.get("/api/tools").json()["tools"]}
    asset = {n: t for n, t in tools.items() if n.startswith("asset_")}
    assert len(asset) == len(asset_api.operations()) == 219
    assert "asset_create_email_full_content" not in asset  # 709 on template emails: withheld
    t = asset["asset_create_email_template"]
    assert t["risk"] == "write" and t["group"] == "Marketo Asset API · Email Templates"
    assert asset["asset_get_email_templates"]["risk"] == "read"
    assert asset["asset_v2_bulk_get_emails"]["risk"] == "read"  # a POST that only reads
    for name in ("asset_delete_lp_template", "asset_approve_draft_email",
                 "asset_approve_landing_page"):
        assert asset[name]["risk"] == "destructive"
    assert not any("using" in n for n in asset)  # readable names


def test_calls_are_encoded_the_way_marketo_expects(monkeypatch):
    from app.marketo import rest_client
    from app.marketo.governor import RateGovernor

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/identity/oauth/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        seen.append(request)
        if request.url.path.endswith("emailTemplates.json") and request.method == "GET":
            return httpx.Response(200, json={"success": False, "errors": [
                {"code": "603", "message": "Access denied"}]})
        return httpx.Response(200, json={"success": True, "result": [{"id": 7}]})

    async def go():
        c = rest_client.MarketoRestClient("https://x.mktorest.com", "id", "secret",
                                          RateGovernor(calls=100, window_s=20,
                                                       max_concurrent=5, daily_quota=1000))
        c._http = httpx.AsyncClient(base_url="https://x.mktorest.com",
                                    transport=httpx.MockTransport(handler))
        ops = asset_api.by_name()
        await c.asset_call(asset_api.split_args(ops["asset_create_email_template"], {
            "name": "Invite", "folder": {"id": 12, "type": "Folder"},
            "content": "<html>hi</html>"}))
        await c.asset_call(asset_api.split_args(ops["asset_create_email"], {
            "name": "Invite", "folder": {"id": 12, "type": "Program"}, "template": 7,
            "subject": "You're invited"}))
        await c.asset_call(asset_api.split_args(ops["asset_get_folder_by_name"], {
            "name": "2027-06 Spring Customer Summit", "type": "Program"}))
        try:
            await c.asset_call(asset_api.split_args(ops["asset_get_email_templates"], {}))
        except rest_client.MarketoError as e:
            return str(e)

    error = asyncio.run(go())
    multipart, form, get = seen[0], seen[1], seen[2]
    assert multipart.headers["content-type"].startswith("multipart/form-data")
    body = multipart.content.decode()
    assert 'name="content"; filename="content.html"' in body and "<html>hi</html>" in body
    assert '{"id": 12, "type": "Folder"}' in body  # objects go as JSON form fields
    assert form.headers["content-type"] == "application/x-www-form-urlencoded"
    assert "template=7" in form.content.decode() and "subject=You%27re+invited" in \
        form.content.decode()
    assert get.method == "GET" and get.url.params["name"] == "2027-06 Spring Customer Summit"
    assert "Read-Write Assets" in error  # a 603 says which permission is missing


def _turn(*calls, text=""):
    return Completion(text, 10, 5, 0.0, tool_calls=list(calls))


def _approve_next(client, task_id, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pending = [a for a in client.get("/api/approvals").json()
                   if a["task_id"] == task_id and a["status"] == "pending"]
        if pending:
            client.post(f"/api/approvals/{pending[0]['id']}/decision", json={"approved": True})
            return pending[0]
        time.sleep(0.1)
    raise AssertionError("no approval came")


def test_designer_publishes_page_and_email_to_marketo(client, script, brand):
    from app import presets

    turns, seen = script
    asyncio.run(presets.install("designer"))
    client.app.state.hub.sync_roster()
    demo = client.app.state.hub.deps.marketo
    form_id = demo._next_id + 1
    turns += [
        _turn(call("save_design", {"kind": "form", "name": "SCS registration",
                                   "fields": FIELDS}, "c1"),
              call("save_design", {"kind": "landing_page", "name": "SCS page",
                                   "html": PAGE}, "c2"),
              call("save_design", {"kind": "email", "name": "SCS invite", "html": EMAIL,
                                   "subject": "Your seat at the Spring Customer Summit",
                                   "preheader": "Saturday, 12 June 2027 at Harbour Hall, with "
                                                "drinks from 6 pm."}, "c3")),
        # publishing the page before the form exists is refused, with what to do
        _turn(call("publish_landing_page", {"name": "SCS page", "folder_id": 300}, "c4")),
    ]
    task_id = client.post("/api/tasks", json={"title": "SCS in Marketo",
                                              "agent_id": "designer"}).json()["id"]
    approval = _approve_next(client, task_id)
    assert approval["action"] == "publish_landing_page"
    turns += [_turn(call("create_form", {"name": "SCS 2027 registration",
                                         "folder": {"id": 1101, "type": "Folder"}}, "c5"))]
    approval = _approve_next(client, task_id)
    assert approval["action"] == "create_form"
    assert "in Marketo yet" in str(seen[-1]["messages"])
    turns += [
        _turn(call("save_design", {"kind": "form", "name": "SCS registration",
                                   "marketo_form_id": form_id}, "c6"),
              call("publish_landing_page", {"name": "SCS page", "folder_id": 300,
                                            "folder_type": "Program",
                                            "template_folder_id": 40}, "c7"),
              call("publish_email", {"name": "SCS invite", "folder_id": 300,
                                     "folder_type": "Program"}, "c8")),
        _turn(text="Published the page and the email to Marketo as drafts."),
    ]
    approval = _approve_next(client, task_id)  # both publishes in one approval
    assert [c["tool"] for c in approval["details"]["calls"]] == ["publish_landing_page",
                                                                 "publish_email"]
    done = wait_for(client, task_id, {"done", "failed"}, timeout=30)
    assert done["status"] == "done", done["result"]

    paths = [(c["method"], c["path"]) for c in demo.asset_calls]
    assert ("POST", "/rest/asset/v1/landingPageTemplates.json") in paths
    assert ("POST", "/rest/asset/v1/landingPages.json") in paths
    assert ("POST", "/rest/asset/v1/emailTemplates.json") in paths
    assert ("POST", "/rest/asset/v1/emails.json") in paths
    lp_content = next(c for c in demo.asset_calls if c["path"].endswith("/content.json")
                      and "landingPageTemplate" in c["path"])
    assert f"mktoForm_{form_id}" in lp_content["body"]["content"]  # the real form embedded
    tpl = next(c for c in demo.asset_calls if c["path"].endswith("landingPageTemplates.json"))
    assert tpl["body"]["folder"] == {"id": 40, "type": "Folder"}
    assert tpl["body"]["templateType"] == "freeForm"
    email = next(c for c in demo.asset_calls if c["path"].endswith("/emails.json"))
    assert email["body"]["subject"] == "Your seat at the Spring Customer Summit"
    assert email["body"]["folder"] == {"id": 300, "type": "Program"}
    designs = {g["kind"]: g["versions"][0] for g in
               client.get(f"/api/tasks/{task_id}/designs").json()}
    assert designs["email"]["marketo"]["email_id"] and \
        designs["email"]["marketo"]["email_template_id"]
    assert designs["landing_page"]["marketo"]["landing_page_id"]
    # the emails and pages stay drafts: approving them stays with a person. (Their templates
    # are approved on publish: Marketo builds assets only from approved templates.)
    approved = [c["path"] for c in demo.asset_calls if "approve" in c["path"].lower()]
    assert approved and all("Template/" in p for p in approved), approved
    assert not any(c["path"].endswith("fullContent.json") for c in demo.asset_calls)
    json.dumps(demo.asset_calls)  # every call is plain data
