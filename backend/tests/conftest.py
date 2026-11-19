"""Shared fixtures.

The app is exercised against SQLite by default. Set TEST_DATABASE_URL to a scratch Postgres
database to run the same tests against Postgres (tables are truncated after each test).
"""

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

ADMIN_PASSWORD = "correct horse battery staple"
TEST_PG = os.environ.get("TEST_DATABASE_URL", "")


def _reset_modules() -> None:
    from app import config, db, security, settings_store

    config.reset_settings()
    security.reset_keys()
    settings_store.reset_store()
    db.dispose_engine()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated settings: temp data dir, demo Marketo, no LLM keys, fast pacing."""
    values = {
        "DATA_DIR": str(tmp_path),
        "BRAND_DIR": str(tmp_path / "no-brand"),  # tests that need one use `brand` below
        "DATABASE_URL": TEST_PG,
        "HUB_SECRET_KEY": "",
        "MARKETO_MODE": "demo",
        "MARKETO_MUNCHKIN_ID": "",
        "MARKETO_CLIENT_ID": "",
        "MARKETO_CLIENT_SECRET": "",
        "AGENT_PACING_S": "0",
        "ANTHROPIC_API_KEY": "",
        "ADMIN_PASSWORD": ADMIN_PASSWORD,
        "ACTIVITY_POLL_SECONDS": "1",
        "PUBLIC_READ_ACCESS": "false",
    }
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    _reset_modules()
    yield values
    if TEST_PG:
        from app.db import get_engine

        with get_engine().begin() as conn:
            tables = [r[0] for r in conn.execute(text(
                "select tablename from pg_tables where schemaname='public' "
                "and tablename <> 'alembic_version'"))]
            if tables:
                conn.execute(text("truncate " + ", ".join(f'"{t}"' for t in tables) +
                                  " restart identity cascade"))
    _reset_modules()


EXAMPLE_BRAND = Path(__file__).resolve().parents[1] / "brand" / "example"


@pytest.fixture
def brand(env, monkeypatch):
    """The example brand pack (backend/brand/example) instead of none."""
    from app import design

    monkeypatch.setattr(design, "brand_dir", lambda: EXAMPLE_BRAND)
    return EXAMPLE_BRAND


@pytest.fixture
def db(env):
    """Database ready for direct use (no app running)."""
    from app.db import init_db

    init_db()
    return env


@pytest.fixture
def anon(env):
    """A running app with no session cookie."""
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def client(anon):
    """A running app signed in as the admin."""
    r = anon.post("/api/auth/login", json={"password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return anon


# --- agent helpers ---------------------------------------------------------------------------


def call(name, args, cid=None):
    return {"id": cid or f"call_{name}", "name": name, "args": args}


@pytest.fixture
def script(monkeypatch):
    """Replace LLMRouter.chat with scripted turns; records what each call was given."""
    from app.llm.router import Completion, LLMRouter

    turns: list[Completion] = []
    seen: list[dict] = []

    async def fake_chat(self, tier, system, messages, tools, **kw):
        seen.append({"tier": tier, "system": system, "messages": list(messages),
                     "tools": [t.name for t in tools], "json_schema": kw.get("json_schema")})
        return turns.pop(0) if turns else Completion("Done.", 10, 5, 0.0)

    monkeypatch.setattr(LLMRouter, "chat", fake_chat)
    return turns, seen


def make_agent(client, **over):
    body = {"name": "List Builder", "title": "Builds static lists", "tools":
            ["rest_get_leads", "rest_add_leads_to_list"], **over}
    r = client.post("/api/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def wait_for(client, task_id, statuses, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = next(t for t in client.get("/api/tasks").json() if t["id"] == task_id)
        if task["status"] in statuses:
            return task
        time.sleep(0.1)
    raise AssertionError(f"task {task_id} stuck in {task['status']}")
