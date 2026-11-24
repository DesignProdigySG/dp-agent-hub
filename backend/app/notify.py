"""Human-in-the-loop notifications: tell reviewers by email when an agent needs approval
(and, optionally, when a task fails).

Channels are pluggable: `_deliver` picks the sender for a channel and `channels()` lists the
ones that are configured. To add another (Microsoft Teams, Slack, ...), write a sender that
takes a `Message`, add its settings in app/config.py and app/settings_store.py, and list it
in `channels()` and app/routes/approval_links.py's CHANNELS.

Messages carry signed Approve / Reject links and a Review link into the hub. The action links
open a confirmation page; nothing is decided until the reviewer confirms there, so link
scanners and chat previews (which open URLs automatically) can't approve anything. A link is
tied to one approval, one decision and one channel, expires, and stops working once the
request has been decided.

Agent-written text (the reasoning in a summary) is untrusted: it is shortened, URLs are
removed, and it is escaped, so a manipulated agent can't put a convincing link in front of a
reviewer.
"""

import asyncio
import html
import logging
import re
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any

from app.config import Settings, get_settings
from app.db import Approval, audit
from app.marketo import links
from app.security import sign_link

log = logging.getLogger(__name__)

URL_RE = re.compile(r"(https?://|www\.)\S+", re.I)
URL_QUERY_RE = re.compile(r"(https?://[^\s?'\"]+)\?[^\s'\"]*")


@dataclass
class Message:
    title: str
    text: str
    facts: list[tuple[str, str]] = field(default_factory=list)
    actions: list[tuple[str, str]] = field(default_factory=list)  # (label, url)
    tone: str = "attention"  # attention | warning | good
    # An optional formatted section, already sanitised: Markdown for plain-text channels,
    # HTML (<h3> <p> <ul> <li> <b> only) for email.
    detail_title: str = ""
    detail_markdown: str = ""
    detail_html: str = ""


def redact(text: str) -> str:
    """Drop URL query strings from an error: a webhook URL's signature makes it a secret."""
    return URL_QUERY_RE.sub(r"\1?[redacted]", text)


def untrusted(text: str, limit: int = 600) -> str:
    """Agent-written text, made safe to show: no URLs, bounded length, single spaced."""
    text = URL_RE.sub("[link removed]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def action_url(s: Settings, approval_id: str, decision: str, channel: str) -> str:
    token = sign_link({"a": approval_id, "d": decision, "c": channel},
                      s.approval_link_hours * 3600)
    return f"{s.hub_public_url}/api/approvals/act?t={token}"


def workflow_message(s: Settings, approval: Approval, agent_name: str, channel: str) -> Message:
    """A code-defined workflow's approval (app/workflows) with the workflow's own choices.
    The workflow's `card` may carry a summary, a lead and `facts` ({label: value})."""
    det = approval.details
    card = det.get("card", {})
    lead = card.get("lead", {})
    who = " ".join(x for x in (lead.get("firstName"), lead.get("lastName")) if x)
    lead_line = f"{who} · {lead.get('title') or ''} · {lead.get('company') or ''}".strip(" ·")
    facts = [(k, untrusted(str(v), 120))
             for k, v in [("Lead", lead_line), *(card.get("facts") or {}).items()] if v]
    facts.append(("Links expire", f"in {s.approval_link_hours} h"))
    labels = det.get("choice_labels", {})
    return Message(
        title=f"{agent_name} needs your decision",
        text=untrusted(card.get("summary") or approval.summary),
        facts=facts,
        actions=[(labels.get(c, c.title()), action_url(s, approval.id, c, channel))
                 for c in det.get("choices", [])]
        + [("Review in the hub", f"{s.hub_public_url}/?approval={approval.id}")]
        + ([("Open lead in Marketo", u)] if (u := links.url("lead", det.get("lead_id")))
           else []),
    )


def approval_message(s: Settings, approval: Approval, agent_name: str, channel: str) -> Message:
    if approval.details.get("workflow"):
        return workflow_message(s, approval, agent_name, channel)
    calls = approval.details.get("calls", [])
    facts = [("Agent", agent_name), ("Action", approval.action)]
    for c in calls[:5]:
        facts.append((f"{c.get('risk', 'write').title()} call", c.get("tool", "")))
    if len(calls) > 5:
        facts.append(("More calls", str(len(calls) - 5)))
    facts.append(("Links expire", f"in {s.approval_link_hours} h"))
    return Message(
        title=f"{agent_name} needs your approval",
        text=untrusted(approval.summary),
        facts=facts,
        actions=[("Approve", action_url(s, approval.id, "approve", channel)),
                 ("Reject", action_url(s, approval.id, "reject", channel)),
                 ("Review in the hub", f"{s.hub_public_url}/?approval={approval.id}")]
        + [ref for c in calls for ref in links.referenced(c.get("tool", ""),
                                                          c.get("args") or {})][:3],
    )


# --- channels ---------------------------------------------------------------------------------


def email_message(s: Settings, m: Message) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = m.title
    msg["From"] = s.email_from
    msg["To"] = ", ".join(s.email_recipients)
    facts_text = "\n".join(f"{k}: {v}" for k, v in m.facts)
    links_text = "\n".join(f"{label}: {url}" for label, url in m.actions)
    detail_text = f"{m.detail_title}\n\n{m.detail_markdown}\n\n" if m.detail_markdown else ""
    msg.set_content(f"{m.title}\n\n{m.text}\n\n{facts_text}\n\n{detail_text}{links_text}\n")
    e = html.escape
    colors = {"Approve": "#1b7f4b", "Reject": "#b3261e"}
    buttons = "".join(
        f'<a href="{e(url)}" style="display:inline-block;margin:0 8px 8px 0;padding:10px 18px;'
        f'border-radius:20px;text-decoration:none;color:#fff;font-weight:600;'
        f'background:{colors.get(label, "#4a5ac8")}">{e(label)}</a>'
        for label, url in m.actions)
    rows = "".join(f'<tr><td style="padding:2px 12px 2px 0;color:#666">{e(k)}</td>'
                   f"<td>{e(v)}</td></tr>" for k, v in m.facts)
    msg.add_alternative(
        f'<div style="font-family:system-ui,sans-serif;max-width:560px">'
        f'<h2 style="font-size:18px">{e(m.title)}</h2><p>{e(m.text)}</p>'
        f'<table style="font-size:14px;margin:12px 0">{rows}</table>'
        + (f'<div style="border-left:3px solid #4a5ac8;padding:4px 12px;margin:12px 0">'
           f'<p style="color:#666;margin:0">{e(m.detail_title)}</p>{m.detail_html}</div>'
           if m.detail_html else "")
        + f'{buttons}'
        f'<p style="color:#888;font-size:12px">Approve and Reject open a confirmation page '
        f"in the DP Agent Hub.</p></div>", subtype="html")
    return msg


def _smtp_send(s: Settings, msg: EmailMessage) -> None:
    context = ssl.create_default_context()
    if s.smtp_security == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, context=context,
                                                timeout=30)
    else:
        server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30)
    with server:
        if s.smtp_security == "starttls":
            server.starttls(context=context)
        if s.smtp_username:
            server.login(s.smtp_username, s.smtp_password)
        server.send_message(msg)


async def send_email(s: Settings, m: Message) -> None:
    await asyncio.to_thread(_smtp_send, s, email_message(s, m))


# --- sending ----------------------------------------------------------------------------------


async def _deliver(s: Settings, channel: str, m: Message) -> dict[str, Any]:
    try:
        await send_email(s, m)
        return {"channel": channel, "ok": True}
    except Exception as e:
        error = redact(f"{type(e).__name__}: {e}")[:300]
        log.warning("%s notification failed: %s", channel, error)
        audit("notification_failed", f"{channel}: {error}", data={"channel": channel})
        return {"channel": channel, "ok": False, "error": error}


def channels(s: Settings) -> list[str]:
    return [c for c, ready in (("email", s.email_ready),) if ready]


async def approval_requested(approval: Approval, agent_name: str) -> list[dict[str, Any]]:
    """Notify every configured channel; failures are logged and audited, never raised."""
    s = get_settings()
    results = [await _deliver(s, c, approval_message(s, approval, agent_name, c))
               for c in channels(s)]
    if results:
        audit("notification_sent", f"Approval request sent to {', '.join(channels(s))}",
              task_id=approval.task_id, agent_id=approval.agent_id,
              data={"results": results, "approval_id": approval.id})
    return results


async def task_failed(task_id: str, title: str, agent_name: str, error: str) -> None:
    s = get_settings()
    if not s.notify_task_failures:
        return
    m = Message(title=f"{agent_name} couldn't finish a task", text=untrusted(error, 400),
                facts=[("Task", title), ("Agent", agent_name)],
                actions=[("Open the board", f"{s.hub_public_url}/")], tone="warning")
    for c in channels(s):
        await _deliver(s, c, m)


async def test(channel: str) -> dict[str, Any]:
    """Send a test message to one channel, whether or not it is switched on."""
    s = get_settings()
    if channel == "email" and not (s.smtp_host and s.email_from and s.email_recipients):
        return {"ok": False, "error": "SMTP server, from address and reviewers are required"}
    m = Message(title="Test from the DP Agent Hub",
                text="Approval requests will arrive like this, with Approve / Reject links.",
                facts=[("Links point to", s.hub_public_url)],
                actions=[("Open the hub", f"{s.hub_public_url}/")], tone="good")
    result = await _deliver(s, channel, m)
    if result["ok"]:
        result["detail"] = f"sent to {', '.join(s.email_recipients)}"
    return result
