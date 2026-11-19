"""Emails as templates with editable sections: found in the HTML, checked, and published to
Marketo section by section (plain or dynamic content), never by replacing the whole HTML."""

import asyncio
from types import SimpleNamespace

from app import design
from app.marketo import email_sections as es

PAGE = """<html><body><table><tr><td>
<p>Acme Events</p>
<div class="mktoText" id="hero" mktoName="Hero"><p>Hello <b>there</b><br>friend</p></div>
<td><div class="x mktoText" id="details" mktoName="Details">A <div>nested</div> B</div>
<p>{{system.unsubscribeLink}} 1 Example Street</p>
</table></body></html>"""


def test_sections_are_found_with_their_own_html():
    found = es.sections(PAGE)
    assert [(s.id, s.name, s.inner) for s in found] == [
        ("hero", "Hero", "<p>Hello <b>there</b><br>friend</p>"),
        ("details", "Details", "A <div>nested</div> B")]
    assert "Hello" not in es.layout(PAGE) and "Acme Events" in es.layout(PAGE)
    # changing a section's content keeps the layout; changing the layout doesn't
    assert es.layout_hash(PAGE) == es.layout_hash(PAGE.replace("friend", "pal"))
    assert es.layout_hash(PAGE) != es.layout_hash(PAGE.replace("Acme Events", "SD"))


def test_the_check_wants_sections_and_sound_dynamic_content():
    assert "no editable sections" in es.check("<p>flat</p>")[0][0]
    dupe = PAGE.replace('id="details"', 'id="hero"')
    assert any("unique" in e for e in es.check(dupe)[0])
    nested = '<div class="mktoText" id="a"><div class="mktoText" id="b">x</div></div>'
    assert any("nested" in e for e in es.check(nested)[0])
    errors, _ = es.check(PAGE, {"hero": {"segmentation": "Guest", "segments": {
        "VIP": "<p>${name}</p>"}}, "nope": {"segmentation": "Guest", "segments": {"Default": ""}}})
    assert any("Default" in e for e in errors)  # every dynamic section needs a Default
    assert any("${" in e for e in errors)  # template variables aren't resolved there
    assert any("'nope'" in e for e in errors)  # no such section
    assert es.check(PAGE) == ([], [])


def _email(client, html, version_note="", dynamic=None):
    state = {"task_id": "tsk_sections", "agent_id": "designer", "params": {}}
    rt = SimpleNamespace(state=state)
    out = design.save_design.func(kind="email", name="Invite", runtime=rt, html=html,
                                  subject="Your seat at the Spring Customer Summit",
                                  preheader="Saturday, 12 June 2027 at Harbour Hall, with drinks "
                                            "from 6 pm.", dynamic=dynamic)
    assert not out["errors"], out["errors"]
    return asyncio.run(design.publish_email.coroutine(
        name="Invite", folder_id=300, runtime=rt, template_folder_id=40))


def test_publishing_fills_sections_and_revisions_update_only_them(client, brand):
    from tests.test_designer import EMAIL

    demo = client.app.state.hub.deps.marketo
    html = EMAIL.replace('<img src', '<div class="mktoText" id="cta" mktoName="Button">'
                         '<p>RSVP</p></div><img src')
    dynamic = {"body": {"segmentation": "Guest Type", "segments": {
        "VIP Customer": "<p>Your table is waiting.</p>",
        "Default": "<p>Join us at Harbour Hall.</p>"}}}
    first = _email(client, html, dynamic=dynamic)
    assert first["template"] == "created" and first["dynamic"]["body"]["segmentation"] == \
        "Guest Type"
    email = demo.assets[first["email_id"]]
    assert email["_sections"]["body"]["segments"] == dynamic["body"]["segments"]
    paths = [c["path"] for c in demo.asset_calls]
    assert any(p.endswith(f"/email/{first['email_id']}/content/body.json") for p in paths)

    # a revision inside a section: that section only, the template untouched
    demo.asset_calls.clear()
    second = _email(client, html.replace("<p>RSVP</p>", "<p>Reserve your seat</p>"),
                    dynamic=dynamic)
    assert second["template"] == "unchanged" and second["email_id"] == first["email_id"]
    assert email["_sections"]["cta"]["value"][0]["value"] == "<p>Reserve your seat</p>"
    assert not any("emailTemplate" in c["path"] for c in demo.asset_calls)

    # a layout change: the template changes, the email keeps its own section content
    third = _email(client, html.replace("<p>RSVP</p>", "<p>Reserve your seat</p>").replace(
        'width="600" style', 'width="600" data-v="2" style'), dynamic=dynamic)
    assert third["template"] == "layout updated"
    assert email["_sections"]["cta"]["value"][0]["value"] == "<p>Reserve your seat</p>"
    assert not any(c["path"].endswith("fullContent.json") for c in demo.asset_calls)


def test_an_unknown_segment_is_refused_with_the_real_ones(client, brand):
    from tests.test_designer import EMAIL

    out = _email(client, EMAIL, dynamic={"body": {"segmentation": "Guest Type",
                                                  "segments": {"Platinum": "<p>x</p>",
                                                               "Default": "<p>y</p>"}}})
    assert "no segment Platinum" in out["error"] and "VIP Customer" in out["error"]
