"""What an approval is really about, in words a reviewer can check.

A paused tool call names Marketo objects by ID ("asset_approve_draft_email {id: 1201}").
This turns each call into an item: what will happen ("Approve"), to what ("Email"), its name
and subject, a link to open it in Marketo, and, when the agent designed it in this task, the
design to preview right in the approval.
"""

import re
from typing import Any

from sqlmodel import select

from app.db import DesignDeliverable, MarketoChange, session
from app.marketo import asset_api, links

VERBS = {"approve": "Approve", "unapprove": "Unapprove", "activate": "Activate",
         "deactivate": "Deactivate", "delete": "Delete", "remove": "Remove", "merge": "Merge",
         "clone": "Clone", "create": "Create", "update": "Update", "add": "Add to",
         "schedule": "Schedule", "publish": "Publish", "request": "Request", "trigger": "Run"}
# Designs record their Marketo IDs under these keys (app/design.py)
DESIGN_IDS = {"email_id": "email", "landing_page_id": "landing_page",
              "marketo_form_id": "form"}


def _verb(tool: str) -> str:
    head = re.sub(r"^(asset_|rest_)(v2_)?", "", tool).split("_")[0]
    return VERBS.get(head, head.replace("_", " ").title())


def _kind(tool: str) -> str | None:
    op = asset_api.by_name().get(tool)
    if op:
        return links.ASSET_GROUPS.get(op["group"])
    if tool in ("publish_email", "publish_landing_page"):
        return tool.removeprefix("publish_")
    return next(({"flow_step": "smart_campaign", "field": "form"}.get(n, n)
                 for n in links.MCP_NOUNS if n in tool), None)


def items(task_id: str | None, calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One item per call: {verb, kind, label, id, name, subject, url, design_id}."""
    with session() as s:
        designs = list(s.exec(select(DesignDeliverable).where(
            DesignDeliverable.task_id == task_id))) if task_id else []
        changes = list(s.exec(select(MarketoChange).where(
            MarketoChange.task_id == task_id))) if task_id else []
    by_marketo: dict[tuple[str, str], DesignDeliverable] = {}
    for d in sorted(designs, key=lambda d: d.version):  # the latest version wins
        for key, kind in DESIGN_IDS.items():
            if (d.marketo or {}).get(key) or (key == "marketo_form_id" and
                                               (d.spec or {}).get(key)):
                oid = (d.marketo or {}).get(key) or (d.spec or {}).get(key)
                by_marketo[(kind, str(oid))] = d
    named = {(c.kind, c.object_id): c.name for c in changes if c.name}
    sources = {(c.kind, c.object_id): c.detail.removeprefix("cloned from ").strip()
               for c in changes if c.detail.startswith("cloned from ")}
    out = []
    for c in calls:
        tool, args = c.get("tool") or c.get("name", ""), c.get("args") or {}
        if tool == "plan_fixes":  # a round of fixes: the steps, each for its agent
            out.append(_fix_plan(args.get("steps") or []))
            continue
        kind = _kind(tool)
        oid = str(args.get("id") or args.get("list_id") or "")
        design = by_marketo.get((kind, oid)) if kind else None
        if design is None and kind and (source := sources.get((kind, oid))):
            design = _design_for(kind, source)  # a copy of another agent's design
        if design is None and tool.startswith("publish_"):
            design = next((d for d in reversed(designs) if d.name == args.get("name")), None)
        name = (design.name if design else None) or named.get((kind, oid)) or \
            args.get("name") or ""
        out.append({"verb": _verb(tool), "kind": kind or "", "label":
                    links.LABELS.get(kind or "", kind or tool), "id": oid or None,
                    "name": name, "subject": _subject(design),
                    "url": links.url(kind, oid) if kind and oid else None,
                    "design_id": design.id if design else None})
    return out


def _fix_plan(steps: list[dict[str, Any]]) -> dict[str, Any]:
    from app.agents import registry

    names = {d.id: d.name for d in registry.all_defs()}
    listed = [{"agent": names.get(st.get("to_agent", ""), st.get("to_agent", "")),
               "title": st.get("title", ""), "brief": st.get("brief", "")} for st in steps]
    return {"verb": "Plan", "kind": "plan", "label": "Fix round",
            "id": None, "name": f"{len(listed)} step(s)", "subject": "", "url": None,
            "design_id": None, "steps": listed}


GET_BY_ID = {"email": "asset_get_email_by_id", "landing_page": "asset_get_landing_page_by_id",
             "program": "asset_get_program_by_id", "form": "asset_get_lp_form_by_id",
             "smart_campaign": "asset_get_smart_campaign_by_id"}


async def fill_in(its: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Items nothing named yet (e.g. assets another agent copied): their name from Marketo,
    and the design of the same name, if an agent designed it. Best effort."""
    from app.deps import get_deps

    for it in its:
        op = GET_BY_ID.get(it["kind"])
        if it["name"] or not it["id"] or op is None:
            continue
        try:
            body = await get_deps().marketo.asset(asset_api.split_args(
                asset_api.by_name()[op], {"id": int(it["id"])}))
            it["name"] = ((body or {}).get("result") or [{}])[0].get("name") or ""
        except Exception:  # the item still shows by ID, with its link
            continue
        if it["name"] and not it["design_id"] and (d := _design_named(it["kind"], it["name"])):
            it["design_id"], it["subject"] = d.id, _subject(d)
    return its


def _subject(d: DesignDeliverable | None) -> str:
    from app.design import plain_tokens

    return plain_tokens(d.subject, d.task_id) if d and d.subject else ""


def _design_named(kind: str, name: str) -> DesignDeliverable | None:
    with session() as s:
        return s.exec(select(DesignDeliverable).where(
            DesignDeliverable.kind == kind, DesignDeliverable.name == name)
            .order_by(DesignDeliverable.created_at.desc())).first()


def _design_for(kind: str, marketo_id: str) -> DesignDeliverable | None:
    """The design (from any task) that was published as this Marketo asset."""
    key = next((k for k, v in DESIGN_IDS.items() if v == kind), None)
    if key is None:
        return None
    with session() as s:
        rows = list(s.exec(select(DesignDeliverable).where(DesignDeliverable.kind == kind)
                           .order_by(DesignDeliverable.created_at.desc()).limit(500)))
    return next((d for d in rows if str((d.marketo or {}).get(key)) == str(marketo_id)), None)


def item_name(it: dict[str, Any]) -> str:
    """How an item reads in a sentence: its name, or its kind and ID."""
    return it.get("name") or " ".join(x for x in (it.get("label"), f"#{it['id']}"
                                                  if it.get("id") else "") if x) or "item"


def summary(agent_name: str, its: list[dict[str, Any]]) -> str:
    """"Designer wants to approve in Marketo: the email “Invitation”, …"."""
    if not its:
        return f"{agent_name} wants to make changes in Marketo."
    if all(i["kind"] == "plan" for i in its):
        steps = [st for i in its for st in i.get("steps", [])]
        who = list(dict.fromkeys(st["agent"] for st in steps))
        return (f"{agent_name} proposes a round of fixes: {len(steps)} step(s) for "
                f"{', '.join(who)}. Nothing starts until you approve.")
    verbs = list(dict.fromkeys(i["verb"].lower() for i in its))
    what = [f"the {i['label'].lower()} “{i['name']}”" if i["name"] else
            f"{i['label'].lower()} {i['id']}" if i["id"] else i["label"].lower() for i in its]
    shown = ", ".join(what[:6]) + (f" and {len(what) - 6} more" if len(what) > 6 else "")
    return f"{agent_name} wants to {' / '.join(verbs)} in Marketo: {shown}."
