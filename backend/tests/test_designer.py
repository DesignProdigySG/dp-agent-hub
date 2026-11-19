"""Designer: the preset, the brand check (with and without a brand pack), previews and
exports, creating the form in Marketo behind approval, and feedback rounds on the same task."""

import asyncio
import time

from app import design
from app.llm.router import Completion
from tests.conftest import call, wait_for

IMG = "https://images.example.com/brand/conference-hall.jpg?w=2400&q=80"
PAGE = ("<!doctype html><html><head><title>Spring Customer Summit 2027</title>"
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
        '<body class="bg-mist"><img src="' + IMG + '" alt="The conference hall">'
        '<a href="#register" class="bg-brand-600">Reserve your seat</a>'
        '<section id="register">{{marketo_form}}</section></body></html>')
EMAIL = ('<table width="600" style="background:#FFFFFF"><tr><td style="color:#111827">'
         '<div class="mktoText" id="body" mktoName="Body">'
         "Hi {{lead.First Name:default=there}},<p>Join us at Harbour Hall.</p></div>"
         '<img src="' + IMG.replace("2400", "1200") + '" alt="The conference hall" width="600">'
         "<p>1 Example Street, Springfield "
         '<a href="https://www.example.com/privacy" style="color:#2563EB">Privacy</a> '
         '<a href="{{system.unsubscribeLink}}" style="color:#2563EB">Unsubscribe</a></p>'
         "</td></tr></table>")
SUBJECT = "Your seat at the Spring Customer Summit"
PREHEADER = "Saturday, 12 June 2027 at Harbour Hall, with drinks from 6 pm."
FIELDS = [{"fieldId": "Company", "label": "Company", "required": True},
          {"fieldId": "MobilePhone", "label": "Mobile (for event updates)",
           "type": "tel", "required": True}]


def turn(*calls, text=""):
    return Completion(text, 10, 5, 0.0, tool_calls=list(calls))


# --- the brand check -------------------------------------------------------------------------


def test_brand_check_accepts_on_brand_work_and_names_what_is_off(brand):
    assert design.check("landing_page", PAGE, form_on_task=True) == {"errors": [],
                                                                    "warnings": []}
    off = PAGE.replace(IMG, "https://example.com/stock.jpg").replace(
        "bg-mist", "bg-[#FF00FF]").replace("Reserve your seat", "Click here")
    errors = design.check("landing_page", off, form_on_task=True)
    assert any("not in the approved library" in e for e in errors["errors"])
    assert any("#FF00FF" in e for e in errors["errors"])
    assert errors["warnings"] == ["brand voice: avoid 'click here'"]
    assert any("{{marketo_form}}" in e for e in design.check(
        "landing_page", PAGE.replace("{{marketo_form}}", ""), form_on_task=True)["errors"])

    ok = design.check("email", EMAIL, subject=SUBJECT, preheader=PREHEADER)
    assert ok == {"errors": [], "warnings": []}
    bad = design.check("email", EMAIL.replace("{{system.unsubscribeLink}}", "#"), subject="x" * 70)
    assert any("unsubscribe" in e for e in bad["errors"])
    assert any("70 characters" in e for e in bad["errors"])
    no_address = design.check("email", EMAIL.replace("1 Example Street", "Somewhere"),
                              subject=SUBJECT, preheader=PREHEADER)
    assert any("physical address" in e for e in no_address["errors"])

    form = design.check("form", fields=[{"fieldId": "Email", "label": "Email"},
                                        {"fieldId": "Diet", "type": "select"}])
    assert len(form["errors"]) == 2  # Email is automatic; a select needs options


def test_without_a_brand_pack_any_image_and_colour_is_fine(env):
    assert design.images() == [] and design.palette() == set()
    anything = PAGE.replace(IMG, "https://example.com/stock.jpg").replace(
        "bg-mist", "bg-[#FF00FF]")
    assert design.check("landing_page", anything, form_on_task=True)["errors"] == []
    email = design.check("email", EMAIL.replace("1 Example Street", "Somewhere"),
                         subject=SUBJECT, preheader=PREHEADER)
    assert email["errors"] == []  # no footer address to require
    assert "note" in design.brand_images.invoke({"query": "hall"})[0]
    assert design.tailwind_config_js() == "" and design.form_style_js() == ""
    # the generic voice check still runs
    assert design.check("landing_page", PAGE.replace("Reserve your seat", "Click here"),
                        form_on_task=True)["warnings"] == ["brand voice: avoid 'click here'"]


def test_the_example_brand_pack_is_read(brand):
    assert "#2563EB" in design.palette() and len(design.images()) == 2
    assert "tailwind.config = {" in design.tailwind_config_js()
    hits = design.brand_images.invoke({"query": "conference", "use": "hero"})
    assert [h["id"] for h in hits] == ["conference-hall"]
    assert design.brand()["from_email"] == "events@example.com"


def test_preview_swaps_in_the_form_and_tokens(db):
    from app.db import DesignDeliverable

    d = DesignDeliverable(task_id="t", agent_id="designer", kind="email", name="x",
                          html=EMAIL)
    html = design.render(d)
    assert ">there</span>," in html and "#unsubscribe" in html  # the default, marked a token
    assert design.render(d, "export") == EMAIL  # export keeps Marketo tokens


# --- the Designer end to end ------------------------------------------------------------------


def designer(client):
    from app import presets

    agent_id, outcome = asyncio.run(presets.install("designer"))
    assert (agent_id, outcome) == ("designer", "created")
    client.app.state.hub.sync_roster()


def test_the_designer_preset_brings_its_brand_pack(client, brand):
    from app import presets
    from app.agents import registry

    designer(client)
    d = registry.get("designer")
    assert {"brand_images", "save_design", "create_form", "publish_email"} <= set(d.tools)
    assert len(d.skill_ids) == 3 and d.max_steps == 30
    titles = {k["title"] for k in client.get("/api/knowledge").json()["docs"]}
    assert {"Example Co Design System", "Example Co Approved Images"} <= titles
    assert d.instructions.startswith("You are the designer")
    # installing again changes nothing on the agent
    assert asyncio.run(presets.install("designer")) == ("designer", "unchanged")


def test_the_designer_preset_works_without_a_brand_pack(client):
    from app.agents import registry

    designer(client)
    assert registry.get("designer").knowledge_ids == []


def test_design_round_trip_with_marketo_form_and_feedback(client, script, brand):
    turns, seen = script
    designer(client)
    demo = client.app.state.hub.deps.marketo
    turns += [
        turn(call("save_design", {"kind": "form", "name": "SCS registration",
                                  "fields": FIELDS, "button": "Reserve your seat"}, "c1")),
        # first try uses an off-brand colour; the check sends it back
        turn(call("save_design", {"kind": "landing_page", "name": "SCS landing page",
                                  "html": PAGE.replace("bg-mist", "bg-[#FF00FF]")}, "c2")),
        turn(call("save_design", {"kind": "landing_page", "name": "SCS landing page",
                                  "html": PAGE}, "c3")),
        turn(call("save_design", {"kind": "email", "name": "SCS invitation", "html": EMAIL,
                                  "subject": SUBJECT, "preheader": PREHEADER}, "c4")),
        turn(call("create_form", {"name": "SCS 2027 registration",
                                  "folder": {"id": 1101, "type": "Folder"}}, "c5")),
    ]
    task_id = client.post("/api/tasks", json={"title": "Spring Customer Summit assets",
                                              "agent_id": "designer"}).json()["id"]
    wait_for(client, task_id, {"needs_approval"}, timeout=30)
    # the check result went back to the model after the off-brand save
    assert any("#FF00FF" in str(m) for m in seen[2]["messages"])
    approval = next(a for a in client.get("/api/approvals").json() if a["task_id"] == task_id)
    assert approval["action"] == "create_form"
    form_id = demo._next_id + 1
    turns += [
        turn(call("add_field_to_form", {"id": form_id, "fieldId": "Company",
                                        "required": True}, "c6"),
             call("add_field_to_form", {"id": form_id, "fieldId": "MobilePhone",
                                        "required": True}, "c7")),
    ]
    client.post(f"/api/approvals/{approval['id']}/decision", json={"approved": True})
    approval = None
    for _ in range(50):
        pending = [a for a in client.get("/api/approvals").json()
                   if a["task_id"] == task_id and a["status"] == "pending"]
        if pending:
            approval = pending[0]
            break
        time.sleep(0.1)
    assert approval  # both fields in one approval card
    assert [c["tool"] for c in approval["details"]["calls"]] == ["add_field_to_form"] * 2
    turns += [
        turn(call("save_design", {"kind": "form", "name": "SCS registration",
                                  "marketo_form_id": form_id}, "c8")),
        turn(text="Landing page, form (Marketo form created) and invitation email are ready."),
    ]
    client.post(f"/api/approvals/{approval['id']}/decision", json={"approved": True})
    done = wait_for(client, task_id, {"done", "failed"}, timeout=30)
    assert done["status"] == "done", done["result"]
    assert demo.forms[form_id]["fields"] == ["FirstName", "LastName", "Email", "Company",
                                             "MobilePhone"]

    designs = client.get(f"/api/tasks/{task_id}/designs").json()
    assert [(g["kind"], len(g["versions"])) for g in designs] == [
        ("landing_page", 2), ("form", 2), ("email", 1)]
    page = designs[0]["versions"][0]
    assert page["checks"]["errors"] == [] and designs[0]["versions"][1]["checks"]["errors"]
    preview = client.get(f"/api/designs/{page['id']}").json()["html"]
    assert 'data-preview="marketo-form"' in preview
    assert "Mobile (for event updates)" in preview
    export = client.get(f"/api/designs/{page['id']}?mode=export").json()["html"]
    assert f"mktoForm_{form_id}" in export and "{{marketo_form}}" not in export

    # feedback: the same task runs again on its own thread with the reviewer's notes
    turns += [
        turn(call("save_design", {"kind": "landing_page", "name": "SCS landing page",
                                  "html": PAGE.replace("Reserve your seat",
                                                       "Request your invitation")}, "c9")),
        turn(text="Changed the button to 'Request your invitation'."),
    ]
    r = client.post(f"/api/tasks/{task_id}/feedback",
                    json={"feedback": "Make the button say 'Request your invitation'."})
    assert r.status_code == 200 and r.json()["round"] == 1
    again = wait_for(client, task_id, {"done", "failed"}, timeout=30)
    assert again["status"] == "done" and "Request your invitation" in again["result"]
    last_call = seen[-1]["messages"]
    assert any("Feedback round 1" in str(m) for m in last_call)
    assert any("SCS invitation" in str(m) for m in last_call)  # it remembers its earlier work
    page_versions = client.get(f"/api/tasks/{task_id}/designs").json()[0]["versions"]
    assert [(v["version"], v["round"]) for v in page_versions] == [(3, 1), (2, 0), (1, 0)]
    assert client.post(f"/api/tasks/{task_id}/feedback", json={"feedback": "x"}).status_code \
        == 422  # too short to act on


def test_the_live_form_embed_carries_the_brand_form_script(env, tmp_path, monkeypatch):
    html = design.form_embed(1234)
    assert 'MktoForms2.loadForm(' in html and 'mktoForm_1234' in html
    assert html.count("<script") == 2  # no brand script: the loader and the form only
    (tmp_path / "pack").mkdir()
    (tmp_path / "pack" / "form_style.js").write_text("/* restyle */")
    monkeypatch.setattr(design, "brand_dir", lambda: tmp_path / "pack")
    assert "<script>/* restyle */</script>" in design.form_embed(1234)


def test_publish_email_needs_a_sender(env):
    from types import SimpleNamespace

    out = asyncio.run(design.publish_email.coroutine(
        name="x", folder_id=1, runtime=SimpleNamespace(state={"task_id": "t"})))
    assert "No sender" in out["error"]
