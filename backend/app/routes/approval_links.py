"""Approve / reject from an emailed link, without signing in.

GET shows the request and a confirm button; only the POST decides. Link scanners and chat
previews fetch GET URLs on their own, so a GET must never change anything. The signed token
names the approval, the decision and the channel; it expires, and a decided request can't be
decided again.
"""

import html
import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app.agents import registry
from app.db import Approval, session
from app.events.schema import ApprovalStatus
from app.notify import untrusted
from app.security import verify_link

router = APIRouter()

HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
           "X-Robots-Tag": "noindex", "X-Frame-Options": "DENY",
           "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
                                      "form-action 'self'"}
CHANNELS = {"email": "email"}  # add more channels here (see app/notify.py)


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    e = html.escape
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<style>
:root{{color-scheme:light dark;--bg:#f6f6fb;--card:#fff;--ink:#1c1b22;--muted:#5f5d6b;
--line:#e2e1ec;--ok:#1b7f4b;--no:#b3261e;--accent:#4a5ac8}}
@media (prefers-color-scheme:dark){{:root{{--bg:#131318;--card:#1d1c24;--ink:#e6e4ef;
--muted:#a9a6b8;--line:#34333f}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:560px;margin:40px auto;padding:0 16px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:24px}}
h1{{font-size:20px;margin:0 0 8px}} p{{margin:8px 0}} .muted{{color:var(--muted)}}
table{{border-collapse:collapse;margin:12px 0;font-size:14px}}
td{{padding:3px 12px 3px 0;vertical-align:top}}
pre{{white-space:pre-wrap;background:var(--bg);border-radius:10px;padding:8px;font-size:12px;
max-height:220px;overflow:auto}}
textarea{{width:100%;box-sizing:border-box;border-radius:10px;border:1px solid var(--line);
background:var(--bg);color:var(--ink);padding:8px;font:inherit}}
button{{border:0;border-radius:999px;padding:10px 20px;font:600 15px system-ui;color:#fff;
cursor:pointer}} .approve{{background:var(--ok)}} .reject{{background:var(--no)}}
</style></head><body><main><div class="card">{body}</div>
<p class="muted" style="font-size:12px;text-align:center">DP Agent Hub</p>
</main></body></html>"""
    return HTMLResponse(doc, status_code=status, headers=HEADERS)


def _invalid() -> HTMLResponse:
    return _page("Link not valid", "<h1>This link isn't valid</h1><p class='muted'>It may "
                 "have expired or been changed. Open the request in the hub instead.</p>", 400)


def _load(token: str | None) -> tuple[dict, Approval] | None:
    data = verify_link(token)
    if not data:
        return None
    with session() as s:
        approval = s.get(Approval, data.get("a", ""))
    if approval is None or data.get("d") not in approval.details.get("choices",
                                                                     ["approve", "reject"]):
        return None
    return data, approval


def _label(approval: Approval, choice: str) -> str:
    return approval.details.get("choice_labels", {}).get(choice, choice.title())


def _decided(approval: Approval) -> HTMLResponse:
    e = html.escape
    when = approval.decided_at.strftime("%Y-%m-%d %H:%M UTC") if approval.decided_at else ""
    return _page("Already decided", f"<h1>Already {e(approval.status.value)}</h1>"
                 f"<p class='muted'>This request was {e(approval.status.value)} {e(when)}. "
                 "Nothing was changed.</p>")


@router.get("/approvals/act")
def confirm_page(t: str = "") -> HTMLResponse:
    loaded = _load(t)
    if loaded is None:
        return _invalid()
    data, approval = loaded
    if approval.status != ApprovalStatus.PENDING:
        return _decided(approval)
    e = html.escape
    choice = data["d"]
    approve = choice != "reject"
    d = registry.get(approval.agent_id)
    agent = d.name if d else approval.agent_id
    card = approval.details.get("card")
    if card:  # a workflow approval: show its decision facts instead of tool calls
        facts = "".join(f"<tr><td class='muted'>{e(k)}</td><td>{e(untrusted(str(v), 200))}</td>"
                        "</tr>" for k, v in (card.get("facts") or {}).items() if v)
        extra = f"<table>{facts}</table>" if facts else ""
    else:
        extra = ""
    calls = "".join(
        f"<tr><td>{e(c.get('risk', 'write'))}</td><td><strong>{e(c.get('tool', ''))}</strong>"
        f"<pre>{e(json.dumps(c.get('args', {}), indent=2)[:2000])}</pre></td></tr>"
        for c in approval.details.get("calls", []))
    comment = ("" if approve and not card else
               f"<p><label>{'Note for the log' if card else 'Reason'} (optional)<br>"
               "<textarea name='comment' rows='3' maxlength='1000'></textarea></label></p>")
    verb = _label(approval, choice)
    return _page(f"{verb}: {agent}", f"""
<h1>{e(verb)}?</h1>
<p><strong>{e(agent)}</strong> wants to run: <strong>{e(approval.action)}</strong></p>
<p class="muted">{e(untrusted(approval.summary, 1200))}</p>
<table>{calls}</table>{extra}
<form method="post" action="act">
<input type="hidden" name="t" value="{e(t)}">{comment}
<button class="{'approve' if approve else 'reject'}" type="submit">
Confirm {e(verb.lower())}</button>
</form>
<p class="muted" style="font-size:13px">To change the arguments first, open the request in
the hub.</p>""")


@router.post("/approvals/act")
async def act(request: Request, t: str = Form(""), comment: str = Form("")) -> HTMLResponse:
    loaded = _load(t)
    if loaded is None:
        return _invalid()
    data, approval = loaded
    if approval.status != ApprovalStatus.PENDING:
        return _decided(approval)
    choice = data["d"]
    approved = choice != "reject"
    via = f"{CHANNELS.get(data.get('c', ''), 'unknown')} link"
    try:
        await request.app.state.hub.decide(
            approval.id, approved, comment.strip()[:1000], via=via,
            choice=choice if approval.details.get("workflow") else None)
    except ValueError:  # decided a moment ago by someone else
        with session() as s:
            return _decided(s.get(Approval, approval.id))
    word = (_label(approval, choice) if approval.details.get("workflow")
            else "Approved" if approved else "Rejected")
    return _page(word, f"<h1>{word}</h1><p class='muted'>The agent has been told and carries "
                 "on from here. You can close this page.</p>")
