"""Auth, encrypted settings, ingestion, snapshots and insights, end to end through the API."""

import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import select
from starlette.websockets import WebSocketDisconnect

from app.llm.router import Completion
from tests.conftest import ADMIN_PASSWORD, call, make_agent


def wait_until(fn, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result := fn():
            return result
        time.sleep(0.1)
    raise AssertionError("condition not met in time")


# --- auth ---------------------------------------------------------------------------------

def test_everything_needs_sign_in_by_default(anon):
    assert anon.get("/api/health").status_code == 200
    assert anon.get("/api/tasks").status_code == 401
    assert anon.get("/api/config").status_code == 401
    assert anon.post("/api/tasks", json={"title": "x", "agent_id": "anyone"}).status_code == 401
    with pytest.raises(WebSocketDisconnect) as exc, anon.websocket_connect("/ws") as ws:
        ws.receive_text()
    assert exc.value.code == 4401
    assert anon.get("/api/auth/me").json() == {
        "authenticated": False, "setup_required": False, "public_read_access": False}


def test_login_logout_and_bad_password(anon):
    assert anon.post("/api/auth/login", json={"password": "nope"}).status_code == 401
    assert anon.post("/api/auth/login", json={"password": ADMIN_PASSWORD}).status_code == 200
    assert anon.get("/api/auth/me").json()["authenticated"] is True
    cookie = anon.cookies.get("hub_session")
    assert cookie and "." in cookie
    anon.post("/api/auth/logout")
    assert anon.get("/api/tasks").status_code == 401


def test_login_is_throttled(anon):
    codes = [anon.post("/api/auth/login", json={"password": "wrong"}).status_code
             for _ in range(7)]
    assert codes[:5] == [401] * 5 and codes[-1] == 429


def test_password_change_invalidates_old_sessions(client, anon):
    old_cookie = client.cookies.get("hub_session")
    r = client.post("/api/auth/password",
                    json={"current": ADMIN_PASSWORD, "new": "an even longer passphrase"})
    assert r.status_code == 200
    assert client.get("/api/tasks").status_code == 200  # the changer got a fresh cookie
    client.cookies.clear()
    client.cookies.set("hub_session", old_cookie)
    assert client.get("/api/tasks").status_code == 401


def test_first_run_setup_requires_the_logged_code(env, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "")
    from fastapi.testclient import TestClient

    from app import security
    from app.main import app

    with TestClient(app) as c:
        assert c.get("/api/auth/me").json()["setup_required"] is True
        bad = c.post("/api/auth/setup", json={"code": "0000-0000-0000",
                                              "password": "a long enough password"})
        assert bad.status_code == 401
        code = security.setup_code()
        short = c.post("/api/auth/setup", json={"code": code, "password": "short"})
        assert short.status_code == 422
        ok = c.post("/api/auth/setup", json={"code": code, "password": "a long enough password"})
        assert ok.status_code == 200 and c.get("/api/tasks").status_code == 200
        again = c.post("/api/auth/setup", json={"code": code, "password": "another password!"})
        assert again.status_code == 409


# --- settings -----------------------------------------------------------------------------

def _field(cfg, key):
    return next(f for f in cfg["fields"] if f["key"] == key)


def test_secrets_are_encrypted_at_rest_and_never_returned(client):
    secret = "sk-ant-test-0123456789abcdef"
    r = client.put("/api/config", json={"changes": {"anthropic_api_key": secret}})
    assert r.status_code == 200
    field = _field(r.json(), "anthropic_api_key")
    assert field["value"] is None and field["is_set"] and field["hint"] == "…cdef"
    assert secret not in r.text
    assert secret not in client.get("/api/config").text

    from app.config import get_settings
    from app.db import AppSetting, session

    assert get_settings().anthropic_api_key == secret
    with session() as s:
        row = s.get(AppSetting, "anthropic_api_key")
    assert row.secret and secret not in row.value

    client.put("/api/config", json={"changes": {"anthropic_api_key": None}})
    assert get_settings().anthropic_api_key == ""


def test_settings_validation_and_sources(client):
    bad = client.put("/api/config", json={"changes": {"marketo_munchkin_id": "not-a-munchkin"}})
    assert bad.status_code == 422
    assert "marketo_munchkin_id" in bad.json()["detail"]["errors"]
    assert client.put("/api/config", json={"changes": {"nope": 1}}).status_code == 422

    ok = client.put("/api/config", json={"changes": {"marketo_munchkin_id": "123-abc-456",
                                                     "llm_daily_budget_usd": "2.5"}})
    assert ok.status_code == 200
    munchkin = _field(ok.json(), "marketo_munchkin_id")
    assert munchkin["value"] == "123-ABC-456" and munchkin["source"] == "ui"
    assert _field(ok.json(), "llm_daily_budget_usd")["value"] == 2.5
    assert _field(ok.json(), "marketo_mode")["source"] in ("env", "default")


def test_switching_to_live_without_credentials_stays_on_demo(client):
    r = client.put("/api/config", json={"changes": {"marketo_mode": "live"}})
    assert r.status_code == 200
    assert "Munchkin" in r.json()["status"]["marketo_error"]
    with client.websocket_connect("/ws") as ws:
        assert json.loads(ws.receive_text())["marketo_mode"] == "demo"


def test_llm_test_reports_missing_key(client):
    r = client.post("/api/config/test/llm", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert all("no Anthropic API key" in x["error"] for x in body["results"])


# --- ingestion, snapshots, insights -----------------------------------------------------------

def test_demo_activities_are_ingested_and_summarised(client):
    summary = wait_until(lambda: (s := client.get("/api/insights/activities?days=1").json())
                         ["total"] > 0 and s)
    assert summary["engaged_leads"] > 0 and summary["by_type"]
    status = client.get("/api/insights/ingestion").json()
    assert status["source"] == "demo" and status["sources"]["demo"]["total"] > 0
    recent = client.get("/api/insights/activities/recent?limit=5").json()
    assert 0 < len(recent) <= 5


def test_snapshot_captures_kpis_and_is_idempotent(client, script):
    agent = make_agent(client)
    task = client.post("/api/tasks", json={"title": "qa", "agent_id": agent["id"]}).json()
    wait_until(lambda: next(t for t in client.get("/api/tasks").json()
                            if t["id"] == task["id"])["status"] == "done")
    first = client.post("/api/insights/snapshot").json()
    second = client.post("/api/insights/snapshot").json()
    assert first["metrics"] == second["metrics"] > 0

    rows = client.get("/api/insights/kpis?days=2").json()
    metrics = {(r["scope"], r["scope_id"], r["metric"]): r for r in rows}
    assert metrics[("agent", "list_builder", "steps")]["value"] == 0
    assert metrics[("agent", "list_builder", "runs")]["value"] == 1
    assert metrics[("tasks", "", "done")]["value"] >= 1
    assert ("llm", "", "calls") in metrics
    assert client.get("/api/insights/llm?days=1").status_code == 200


def test_agent_kpis_survive_restart(env, script):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        c.post("/api/auth/login", json={"password": ADMIN_PASSWORD})
        agent = make_agent(c)
        task = c.post("/api/tasks", json={"title": "qa", "agent_id": agent["id"]}).json()
        wait_until(lambda: next(t for t in c.get("/api/tasks").json()
                                if t["id"] == task["id"])["status"] == "done")
    with TestClient(app) as c:
        c.post("/api/auth/login", json={"password": ADMIN_PASSWORD})
        with c.websocket_connect("/ws") as ws:
            snap = json.loads(ws.receive_text())
    status = next(s for s in snap["statuses"] if s["agent_id"] == "list_builder")
    assert "steps" in status["metrics"]


def test_agents_read_the_activity_store(client, script):
    turns, seen = script
    wait_until(lambda: client.get("/api/insights/activities?days=1").json()["total"] > 0)
    agent = make_agent(client, name="Signals", tools=["activity_summary"])
    turns += [Completion("", 1, 1, 0, [call("activity_summary", {"days": 1})]),
              Completion("Summarised.", 1, 1, 0)]
    task = client.post("/api/tasks", json={"title": "signals", "agent_id": agent["id"]}).json()
    done = wait_until(lambda: (t := next(t for t in client.get("/api/tasks").json()
                                         if t["id"] == task["id"]))["status"] in
                      ("done", "failed") and t)
    assert done["status"] == "done", done["result"]
    result = json.loads(seen[1]["messages"][-1]["content"])
    assert result["total"] > 0


# --- unit-level pieces ----------------------------------------------------------------------

def test_activity_dedupe_on_reingest(db):
    from app.db import MarketoActivity, session
    from app.ingest import insert_activities
    from app.marketo.datastreams import normalize_activity

    rec = {"id": 991, "leadId": 5, "activityTypeId": 2, "activityDate": "2026-11-03T10:00:00Z",
           "primaryAttributeValue": "Demo Request",
           "attributes": [{"name": "Form Fields", "value": "x"}]}
    row = normalize_activity(rec, "rest", {2: "Fill Out Form"})
    assert row["activity_type"] == "Fill Out Form" and row["attributes"] == {"Form Fields": "x"}
    assert insert_activities([row]) == 1
    assert insert_activities([row]) == 0
    with session() as s:
        assert len(s.exec(select(MarketoActivity)).all()) == 1


def test_normalizes_datastreams_cloudevents():
    from app.marketo.datastreams import normalize_activity

    entry = {"position": "pos-1", "event": {
        "id": "evt-1", "type": "com.adobe.platform.marketo.activity",
        "time": "2026-11-03T12:00:00Z",
        "data": {"leadId": "77", "activityTypeId": 11, "activityType": "Click Email",
                 "primaryAttributeValue": "Q4 Launch"}}}
    row = normalize_activity(entry, "datastreams")
    assert row["external_id"] == "evt-1" and row["lead_id"] == 77
    assert row["activity_type"] == "Click Email"
    assert row["occurred_at"] == datetime(2026, 11, 3, 12, tzinfo=UTC)
    assert row["raw"] is entry


async def test_journal_client_follows_link_and_backs_off():
    import httpx

    from app.config import Settings
    from app.marketo.datastreams import IMS_TOKEN_URL, JournalClient

    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if str(req.url) == IMS_TOKEN_URL:
            assert b"client_credentials" in req.content
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert req.headers["authorization"] == "Bearer tok"
        assert req.headers["x-api-key"] == "cid" and req.headers["x-ims-org-id"] == "org@AdobeOrg"
        if "since=" not in str(req.url):
            return httpx.Response(200, json={"events": [{"position": "p1", "event": {"id": "e1"}}]},
                                  headers={"link": '</journal?since=p1>; rel="next"'})
        return httpx.Response(204, headers={"retry-after": "7",
                                            "link": '</journal?since=p1>; rel="next"'})

    s = Settings(_env_file=None, adobe_client_id="cid", adobe_client_secret="sec",
                 adobe_org_id="org@AdobeOrg", datastreams_journal_url="https://events.example/journal")
    client = JournalClient(s, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    entries, nxt, retry = await client.fetch(None)
    assert len(entries) == 1 and nxt == "https://events.example/journal?since=p1" and retry == 0
    entries, nxt2, retry = await client.fetch(nxt)
    assert entries == [] and nxt2 == nxt and retry == 7
    assert calls.count(IMS_TOKEN_URL) == 1  # token cached


async def test_journal_client_refreshes_a_token_the_project_no_longer_accepts():
    import httpx

    from app.config import Settings
    from app.marketo.datastreams import IMS_TOKEN_URL, JournalClient

    tokens = iter(["stale", "fresh"])

    def handler(req: httpx.Request) -> httpx.Response:
        if str(req.url) == IMS_TOKEN_URL:
            return httpx.Response(200, json={"access_token": next(tokens), "expires_in": 3600})
        if req.headers["authorization"] == "Bearer stale":
            return httpx.Response(403, json={"error_code": "403003",
                                             "message": "Api Key is invalid"})
        return httpx.Response(204, headers={"retry-after": "5"})

    s = Settings(_env_file=None, adobe_client_id=" cid", adobe_client_secret="sec",
                 adobe_org_id="org@AdobeOrg", datastreams_journal_url="https://events.example/j")
    client = JournalClient(s, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert await client.fetch(None) == ([], "https://events.example/j", 5)


def test_snapshot_number_parsing():
    from app.snapshots import as_number

    assert as_number("94.5%") == 94.5 and as_number(3) == 3.0
    assert as_number("instant") is None and as_number(True) is None


def test_purge_respects_retention(db):
    from app.ingest import insert_activities, purge_older_than
    from app.marketo.datastreams import normalize_activity

    old = normalize_activity({"id": 1, "activityDate": (datetime.now(UTC) - timedelta(days=400))
                              .isoformat()}, "rest")
    new = normalize_activity({"id": 2, "activityDate": datetime.now(UTC).isoformat()}, "rest")
    insert_activities([old, new])
    assert purge_older_than(365) == 1


def test_scene_layout_round_trip(client):
    first = client.get("/api/scene").json()
    assert first["pieces"] is None and first["version"] == 0  # default decor
    pieces = [{"piece": "round-hq-brick-2x4", "color": "red", "x": 2, "y": 1, "z": -3, "rot": 1},
              {"piece": "lab-server-rack", "color": "white", "x": -19, "y": 1, "z": -19, "rot": 0}]
    r = client.put("/api/scene", json={"pieces": pieces, "base_version": 0})
    assert r.status_code == 200 and r.json()["version"] == 1
    assert client.get("/api/scene").json()["pieces"] == [{**pieces[0], "x": 2.0, "z": -3.0},
                                                         {**pieces[1], "x": -19.0, "z": -19.0}]
    bad = {"pieces": [{**pieces[0], "piece": "../../etc/passwd"}], "base_version": 1}
    assert client.put("/api/scene", json=bad).status_code == 422
    assert client.put("/api/scene", json={"pieces": pieces}).status_code == 422  # no version
    reset = client.put("/api/scene", json={"pieces": None, "base_version": 1}).json()
    assert reset["pieces"] is None and reset["version"] == 2
    assert client.get("/api/scene").json()["pieces"] is None


def test_stale_scene_save_is_refused_and_history_restores(client):
    """A tab that loaded an older layout (or never loaded it) can't overwrite newer work,
    and every replaced layout can be restored."""
    brick = {"piece": "round-hq-brick-2x2", "color": "blue", "x": 0, "y": 1, "z": 0, "rot": 0}
    mine = [brick, {**brick, "x": 4}]
    assert client.put("/api/scene", json={"pieces": mine, "base_version": 0}).status_code == 200
    # a stale tab still at version 0 (e.g. showing the default decor) tries to save
    stale = client.put("/api/scene", json={"pieces": [brick], "base_version": 0})
    assert stale.status_code == 409 and stale.json()["detail"]["version"] == 1
    assert len(client.get("/api/scene").json()["pieces"]) == 2  # untouched
    client.put("/api/scene", json={"pieces": [brick], "base_version": 1})
    history = client.get("/api/scene/history").json()
    assert [(h["version"], h["pieces"]) for h in history] == [(1, 2)]
    r = client.post(f"/api/scene/history/{history[0]['id']}/restore", json={"base_version": 2})
    assert r.status_code == 200 and len(r.json()["pieces"]) == 2 and r.json()["version"] == 3
    assert client.post(f"/api/scene/history/{history[0]['id']}/restore",
                       json={"base_version": 2}).status_code == 409
    for v in range(3, 3 + 25):  # only the last 20 are kept
        client.put("/api/scene", json={"pieces": [brick], "base_version": v})
    assert len(client.get("/api/scene/history").json()) == 20


def test_pasted_settings_are_trimmed(client):
    from app.config import get_settings

    org = "0123456789ABCDEF01234567@AdobeOrg"
    r = client.put("/api/config", json={"changes": {"adobe_client_id": " abc123 \n",
                                                    "adobe_org_id": f" {org}"}})
    assert r.status_code == 200
    assert get_settings().adobe_client_id == "abc123"
    assert get_settings().adobe_org_id == org
