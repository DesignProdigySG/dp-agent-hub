"""Human-in-the-loop notifications: email messages and the signed approval links."""

import time
from urllib.parse import urlsplit

import pytest

from app.llm.router import Completion
from tests.conftest import call, make_agent, wait_for


@pytest.fixture
def outbox(client, monkeypatch):
    """Configure email, capturing what would be sent."""
    from app import notify

    sent = {"email": []}
    monkeypatch.setattr(notify, "_smtp_send", lambda s, msg: sent["email"].append(msg))
    r = client.put("/api/config", json={"changes": {
        "hub_public_url": "http://testserver/",
        "email_enabled": True, "smtp_host": "smtp.example.com", "email_from": "hub@example.com",
        "email_to": "ops@example.com, lead@example.com", "notify_task_failures": True}})
    assert r.status_code == 200, r.text
    return sent


def pause_for_approval(client, script, reasoning="Adding the VP. See https://evil.example/x"):
    turns, _ = script
    agent = make_agent(client)
    lead_id = next(iter(client.app.state.hub.deps.marketo.leads.values()))["id"]
    turns += [Completion(reasoning, 1, 1, 0, [call("rest_add_leads_to_list",
                                                   {"list_id": 1001, "lead_ids": [lead_id]})]),
              Completion("Done.", 1, 1, 0)]
    task_id = client.post("/api/tasks", json={"title": "Add", "agent_id": agent["id"]}).json()["id"]
    wait_for(client, task_id, {"needs_approval"})
    return task_id, lead_id


def wait_sent(outbox, n=1, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(outbox["email"]) >= n:
            return
        time.sleep(0.05)
    raise AssertionError(f"notifications not sent: {outbox}")


def email_links(msg):
    """The "Label: url" lines at the end of the plain-text part."""
    text = msg.get_body(preferencelist=("plain",)).get_content()
    return dict(line.split(": ", 1) for line in text.splitlines()
                if ": http" in line)


def path(url):
    u = urlsplit(url)
    return f"{u.path}?{u.query}"


def test_signed_links_reject_forgery_and_expiry(db):
    from app.security import sign_link, verify_link

    token = sign_link({"a": "apr_1", "d": "approve"}, 60)
    assert verify_link(token)["a"] == "apr_1"
    payload, sig = token.rsplit(".", 1)
    assert verify_link(f"{payload}.{'0' * len(sig)}") is None
    assert verify_link(sign_link({"a": "apr_1", "d": "approve"}, -1)) is None
    assert verify_link("garbage") is None


def test_approval_request_is_emailed_and_its_link_approves(client, script, outbox):
    task_id, lead_id = pause_for_approval(client, script)
    wait_sent(outbox)

    email = outbox["email"][0]
    assert email["To"] == "ops@example.com, lead@example.com"
    assert "needs your approval" in email["Subject"]
    assert "evil.example" not in email.as_string()  # agent URLs removed
    links = email_links(email)
    assert {"Approve", "Reject", "Review in the hub"} <= set(links)
    assert links["Review in the hub"].startswith("http://testserver/?approval=apr_")

    # Opening the link (as a link scanner would) changes nothing
    page = client.get(path(links["Approve"]))
    assert page.status_code == 200 and "Confirm approve" in page.text
    assert page.headers["cache-control"] == "no-store"
    assert wait_for(client, task_id, {"needs_approval"})

    token = urlsplit(links["Approve"]).query.removeprefix("t=")
    client.cookies.clear()  # no session needed: the signed link is the authority
    done = client.post("/api/approvals/act", data={"t": token})
    assert done.status_code == 200 and "Approved" in done.text
    again = client.post("/api/approvals/act", data={"t": token})
    assert "Already approved" in again.text

    from sqlmodel import select

    from app.db import AuditEntry, session
    with session() as s:
        entry = s.exec(select(AuditEntry).where(AuditEntry.kind == "approval_approved")).one()
    assert entry.data["via"] == "email link"


def test_reject_link_carries_the_reason_and_bad_links_fail(client, script, outbox):
    task_id, lead_id = pause_for_approval(client, script)
    wait_sent(outbox)
    reject = email_links(outbox["email"][0])["Reject"]
    page = client.get(path(reject))
    assert "Confirm reject" in page.text and "textarea" in page.text
    token = urlsplit(reject).query.removeprefix("t=")
    client.post("/api/approvals/act", data={"t": token, "comment": "Not this week"})
    approval = next(a for a in client.get("/api/approvals").json() if a["task_id"] == task_id)
    assert approval["status"] == "rejected" and approval["comment"] == "Not this week"
    assert lead_id not in client.app.state.hub.deps.marketo.lists[1001]

    assert client.get("/api/approvals/act?t=forged.sig").status_code == 400
    assert "isn't valid" in client.post("/api/approvals/act", data={"t": "x.y"}).text


def test_channel_tests_and_validation(client, outbox):
    assert client.post("/api/config/test/email").json()["detail"].startswith("sent to")
    bad = client.put("/api/config", json={"changes": {"email_to": "not an address"}})
    assert bad.status_code == 422
    assert client.post("/api/config/test/teams").status_code == 404  # no such channel


def test_failed_tasks_notify_when_enabled(client, outbox):
    agent = make_agent(client)  # no LLM configured: the run fails
    r = client.post("/api/tasks", json={"title": "Doomed", "agent_id": agent["id"]})
    task_id = r.json()["id"]
    assert wait_for(client, task_id, {"failed", "done"})["status"] == "failed"
    wait_sent(outbox)
    assert "couldn't finish a task" in outbox["email"][0]["Subject"]


def test_webhook_secrets_never_reach_the_error_log():
    from app.notify import redact

    err = ("HTTPStatusError: Client error '401 Unauthorized' for url 'https://x.environment.api."
           "powerplatform.com/powerautomate/automations/direct/workflows/abc/triggers/manual/"
           "paths/invoke?api-version=1&sp=%2Ftriggers&sv=1.0&sig=SECRET123'")
    out = redact(err)
    assert "SECRET123" not in out and "sig=" not in out
    assert "/triggers/manual/paths/invoke?[redacted]" in out
