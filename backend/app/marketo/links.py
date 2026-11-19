"""Links into Marketo for everything agents create or change there.

Each change is recorded (marketo_change) with its kind and ID; the link is built when it's
shown, from Settings > "Marketo address for links", so fixing that setting fixes every link.

Two kinds of address work:

  * Adobe Experience Cloud, e.g. https://experience.adobe.com/#/@org/so:123-ABC-456/
    marketo-engage/ : emails open in the email editor (email/<id>/overview/details), the
    rest in the classic UI by Marketo's own codes (classic/ME1234A1 for an event program,
    LP / FO / SC / ST for landing pages, forms, smart campaigns, static lists).
  * The classic address, e.g. https://app-ab12.marketo.com/# : the codes right after it.

Leads open their detail page. Templates, snippets, smart lists and files have no link we can
rely on, so they're listed by ID only. Links Marketo's own APIs return (either style, any org
form) are rewritten to the configured address, so agents quote links that open for you.
"""

import ast
import json
import logging
import re
from datetime import datetime
from typing import Any

from sqlmodel import select

from app.config import get_settings
from app.db import MarketoChange, session

log = logging.getLogger(__name__)

# The hub's programs are event programs (ME); a Default program's code would be PG.
CODES = {"program": "ME", "landing_page": "LP", "form": "FO", "smart_campaign": "SC",
         "static_list": "ST", "email": "EM"}
KIND_OF_CODE = {**{v: k for k, v in CODES.items()}, "PG": "program"}
EXPERIENCE = re.compile(r"^(https://experience\.adobe\.com/#/@[^/]+/so:[^/]+/marketo-engage/)"
                        r"(?:classic/)?$")
LABELS = {"lead": "Lead", "email": "Email", "email_template": "Email template",
          "landing_page": "Landing page", "landing_page_template": "Landing page template",
          "form": "Form", "snippet": "Snippet", "program": "Program",
          "smart_campaign": "Smart campaign", "smart_list": "Smart list",
          "static_list": "Static list", "folder": "Folder", "file": "File",
          "fragment": "Fragment", "token": "Token"}
ASSET_GROUPS = {"Emails": "email", "Emails (New)": "email", "Email Templates": "email_template",
                "Email Templates (New)": "email_template", "Landing Pages": "landing_page",
                "Landing Page Content": "landing_page", "Landing Page Templates":
                "landing_page_template", "Forms": "form", "Form Fields": "form",
                "Snippets": "snippet", "Programs": "program", "Smart Campaigns":
                "smart_campaign", "Smart Lists": "smart_list", "Static Lists": "static_list",
                "Files": "file", "Folders": "folder", "Fragments (New)": "fragment",
                "Tokens": "token"}
VERBS = {"create": "created", "clone": "cloned", "update": "updated", "approve": "approved",
         "unapprove": "unapproved", "discard": "discarded draft of", "delete": "deleted",
         "activate": "activated", "deactivate": "deactivated", "add": "updated",
         "remove": "updated", "reorder": "updated", "schedule": "scheduled",
         "trigger": "requested", "request": "requested", "upload": "uploaded",
         "bulk": "updated", "state": "updated"}
MCP_NOUNS = ["smart_campaign", "smart_list", "snippet", "program", "form", "folder", "token",
             "flow_step", "field"]


def _base() -> tuple[str, bool]:
    """The configured address, and whether it's Experience Cloud (normalised to the
    .../marketo-engage/ root)."""
    base = get_settings().marketo_ui_url.strip()
    if base and not base.endswith(("/", "#")):
        base += "/"
    m = EXPERIENCE.match(base)
    return (m.group(1), True) if m else (base, False)


def url(kind: str, object_id: Any, code: str | None = None) -> str | None:
    """`code` overrides the kind's own (e.g. PG for a Default program)."""
    base, experience = _base()
    if not base or object_id in (None, ""):
        return None
    if experience:
        if kind == "email":
            return f"{base}email/{object_id}/overview/details"
        if kind == "lead":
            return f"{base}classic/leadDatabase/loadLeadDetail?leadId={object_id}"
        code = code or CODES.get(kind)
        return f"{base}classic/{code}{object_id}A1" if code else None
    if kind == "lead":
        root = base[:-1] if base.endswith("#") else base
        return f"{root}leadDatabase/loadLeadDetail?leadId={object_id}"
    code = code or CODES.get(kind)
    return f"{base}{code}{object_id}A1" if code else None


MARKETO_LINK = re.compile(
    r"https?://(?:app-[a-z0-9]+\.marketo\.com/#|experience\.adobe\.com/#/@[^/\s)]+/so:"
    r"[^/\s)]+/marketo-engage/(?:classic/)?)([A-Z]{2,3})(\d+)(?:[A-Z]+\d+)+")
ENGAGE_ROOT = re.compile(r"https://experience\.adobe\.com/#/@[^/\s)]+/so:[^/\s)]+/"
                         r"marketo-engage/")


def rewrite(text: str) -> str:
    """Marketo links in text (as Marketo's APIs return them) pointed at the configured
    address: asset codes become our links; other Experience Cloud paths get our root."""
    base, experience = _base()
    if not base or not isinstance(text, str) or "marketo" not in text:
        return text

    def asset(m: re.Match) -> str:
        code, oid = m.group(1), m.group(2)
        kind = KIND_OF_CODE.get(code)
        return (url(kind, oid, code if kind == "program" else None) if kind else None) \
            or m.group(0)

    text = MARKETO_LINK.sub(asset, text)
    return ENGAGE_ROOT.sub(base, text) if experience else text


def out(c: MarketoChange) -> dict[str, Any]:
    return {"id": c.id, "task_id": c.task_id, "agent_id": c.agent_id, "kind": c.kind,
            "label": LABELS.get(c.kind, c.kind), "object_id": c.object_id, "name": c.name,
            "action": c.action, "detail": c.detail, "url": url(c.kind, c.object_id),
            "created_at": c.created_at.isoformat()}


def record(*, task_id: str | None, agent_id: str, kind: str, object_id: Any, action: str,
           name: str = "", detail: str = "") -> dict[str, Any]:
    c = MarketoChange(task_id=task_id, agent_id=agent_id, kind=kind, object_id=str(object_id),
                      name=str(name or "")[:200], action=action, detail=detail[:500])
    with session() as s:
        s.add(c)
        s.commit()
    return out(c)


def _collapse(rows: list[MarketoChange]) -> list[dict[str, Any]]:
    """One line per object and action: four fields added to a form read as one update."""
    merged: dict[tuple[str, str, str, str | None], dict[str, Any]] = {}
    for c in rows:
        key = (c.kind, c.object_id, c.action, c.task_id)
        if key in merged:
            m = merged[key]
            m["count"] += 1
            m["detail"] = f"{m['count']} changes"
            m["name"] = m["name"] or c.name
        else:
            merged[key] = {**out(c), "count": 1}
    return list(merged.values())


def for_task(task_id: str) -> list[dict[str, Any]]:
    with session() as s:
        return _collapse(list(s.exec(select(MarketoChange).where(
            MarketoChange.task_id == task_id).order_by(MarketoChange.created_at))))


def for_agent(agent_id: str, since: datetime, limit: int = 12) -> list[dict[str, Any]]:
    with session() as s:
        rows = list(s.exec(select(MarketoChange).where(
            MarketoChange.agent_id == agent_id, MarketoChange.created_at >= since)
            .order_by(MarketoChange.created_at.desc()).limit(limit * 5)))
    return _collapse(rows)[:limit]


# --- from agent tool calls -----------------------------------------------------------------------


def parse(content: Any) -> Any:
    if not isinstance(content, str):
        return content
    for loader in (json.loads, ast.literal_eval):
        try:
            return loader(content)
        except (ValueError, SyntaxError, TypeError):
            continue
    return None


def _first(result: Any) -> dict[str, Any]:
    if isinstance(result, dict) and isinstance(result.get("result"), list):
        result = result["result"]
    if isinstance(result, list):
        result = result[0] if result else {}
    return result if isinstance(result, dict) else {}


def _verb(name: str) -> str | None:
    head = re.sub(r"^(asset_|rest_)(v2_)?", "", name).split("_")[0]
    return VERBS.get(head)


def changes_from_tool(name: str, args: dict[str, Any], result: Any) -> list[dict[str, Any]]:
    """What a successful write tool call changed in Marketo: [{kind, object_id, action,
    name}]. Reads (and failed calls) change nothing."""
    data = parse(result)
    if isinstance(data, dict) and (data.get("error") or data.get("success") is False):
        return []
    found: list[dict[str, Any]] = []
    if name == "publish_email" and isinstance(data, dict):
        found += [{"kind": "email", "object_id": data.get("email_id"), "action": "published",
                   "name": data.get("published")},
                  {"kind": "email_template", "object_id": data.get("email_template_id"),
                   "action": "published", "name": f"{data.get('published')} (template)"}]
    elif name == "publish_landing_page" and isinstance(data, dict):
        found += [{"kind": "landing_page", "object_id": data.get("landing_page_id"),
                   "action": "published", "name": data.get("published")},
                  {"kind": "landing_page_template",
                   "object_id": data.get("landing_page_template_id"), "action": "published",
                   "name": f"{data.get('published')} (template)"}]
    elif name.startswith("asset_"):
        from app.marketo import asset_api

        op = asset_api.by_name().get(name)
        verb = _verb(name)
        kind = ASSET_GROUPS.get(op["group"]) if op else None
        if op and kind and verb and asset_api.risk(op) != "read":
            first = _first(data)
            # a clone is a new asset: record its own ID (the call's `id` is the source's)
            oid = (first.get("id") or args.get("id")) if verb in ("cloned", "created") \
                else (args.get("id") or first.get("id"))
            found.append({"kind": kind, "object_id": oid, "action": verb,
                          "name": args.get("name") or first.get("name") or "",
                          **({"detail": f"cloned from {args['id']}"} if verb == "cloned"
                             and args.get("id") else {})})
    elif name == "rest_update_leads":
        found += [{"kind": "lead", "object_id": lead.get("id"), "action": "updated",
                   "name": ""} for lead in (args.get("leads") or [])[:50]]
    elif name == "create_program_list" and isinstance(data, dict):
        found.append({"kind": "static_list", "object_id": data.get("list_id"),
                      "action": "created" if data.get("created") else "updated",
                      "name": data.get("name") or "",
                      "detail": f"{data.get('members')} people, copied from list "
                                f"{data.get('copied_from')}"})
    elif name == "rest_merge_leads":
        found.append({"kind": "lead", "object_id": args.get("winner_id"), "action": "merged",
                      "name": "", "detail": f"merged in leads {args.get('loser_ids')}"})
    elif name == "rest_add_leads_to_list":
        found.append({"kind": "static_list", "object_id": args.get("list_id"),
                      "action": "updated", "name": "",
                      "detail": f"added {len(args.get('lead_ids') or [])} lead(s)"})
    else:  # Marketo MCP: create_form, add_field_to_form, clone_program, ...
        verb = _verb(name)
        noun = next((n for n in MCP_NOUNS if n in name), None)
        if verb and noun:
            kind = {"flow_step": "smart_campaign", "field": "form"}.get(noun, noun)
            first = _first(data)
            oid = first.get("id") if verb in ("created", "cloned") else (
                args.get("id") or first.get("id"))
            found.append({"kind": kind, "object_id": oid, "action": verb,
                          "name": args.get("name") or first.get("name") or ""})
    return [f for f in found if f.get("object_id") not in (None, "")]


def note(changes: list[dict[str, Any]]) -> str:
    """Appended to a tool result so the agent can cite the links."""
    lines = []
    for c in changes:
        what = f"{LABELS.get(c['kind'], c['kind'])} {c['object_id']}"
        lines.append(f"- {what} ({c['action']}): " + (c.get("url") or "no link (add Settings "
                     "> Marketo address for links)" if c["kind"] in CODES or c["kind"] == "lead"
                     else "no direct link for this kind"))
    return ("\n\nMarketo links (include these in your summary):\n" + "\n".join(lines)
            if lines else "")


def referenced(tool: str, args: dict[str, Any], limit: int = 3) -> list[tuple[str, str]]:
    """Existing Marketo objects a pending tool call would act on, as (label, url) buttons for
    approval messages."""
    refs: list[tuple[str, Any]] = []
    if tool == "rest_update_leads":
        refs += [("lead", lead.get("id")) for lead in args.get("leads") or []]
    elif tool == "rest_merge_leads":
        refs += [("lead", args.get("winner_id"))] + [("lead", i) for i in
                                                      args.get("loser_ids") or []]
    elif tool == "rest_add_leads_to_list":
        refs.append(("static_list", args.get("list_id")))
    elif tool.startswith("asset_") and args.get("id"):
        from app.marketo import asset_api

        op = asset_api.by_name().get(tool)
        if op and ASSET_GROUPS.get(op["group"]):
            refs.append((ASSET_GROUPS[op["group"]], args["id"]))
    elif args.get("id"):
        noun = next((n for n in MCP_NOUNS if n in tool), None)
        if noun:
            refs.append(({"flow_step": "smart_campaign", "field": "form"}.get(noun, noun),
                         args["id"]))
    out_: list[tuple[str, str]] = []
    for kind, oid in refs:
        u = url(kind, oid)
        if u and (label := f"Open {LABELS.get(kind, kind).lower()} {oid} in Marketo") not in \
                [x[0] for x in out_]:
            out_.append((label, u))
    return out_[:limit]
