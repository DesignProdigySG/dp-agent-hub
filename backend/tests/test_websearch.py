"""Web search (Brave) and the Lead Finder preset."""

import asyncio

import httpx
import pytest

from app import websearch


def search(handler, **kw):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await websearch.brave_search("saas companies singapore", http=http, **kw)

    return asyncio.run(run())


def test_search_needs_a_key(env):
    with pytest.raises(websearch.SearchError, match="Settings"):
        search(lambda r: httpx.Response(200, json={}))


def test_search_sends_the_key_in_a_header_and_returns_results(env, monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "brave-key")
    from app import config

    config.reset_settings()
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"web": {"results": [
            {"title": "Acme", "url": "https://acme.test", "description": "Widgets",
             "age": "2 days ago"}]}})

    out = search(handler, count=500, freshness="pm")
    assert out == [{"title": "Acme", "url": "https://acme.test", "description": "Widgets",
                    "age": "2 days ago"}]
    req = seen[0]
    assert req.headers["X-Subscription-Token"] == "brave-key"
    assert "brave-key" not in str(req.url)
    assert req.url.params["count"] == str(websearch.MAX_RESULTS)
    assert req.url.params["freshness"] == "pm"


def test_search_errors_do_not_leak_the_key(env, monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "brave-key")
    from app import config

    config.reset_settings()
    with pytest.raises(websearch.SearchError) as e:
        search(lambda r: httpx.Response(401, json={"error": "bad"}))
    assert "401" in str(e.value) and "brave-key" not in str(e.value)


def test_the_tool_reports_errors_to_the_agent_instead_of_raising(env):
    from app.agents.tools import web_search

    out = asyncio.run(web_search.ainvoke({"query": "anything"}))
    assert "Brave" in out[0]["error"]


@pytest.mark.parametrize("preset", ["lead_finder", "icp_finder"])
def test_the_research_presets_install_with_read_only_tools(client, preset):
    from app import presets
    from app.agents import registry
    from app.agents.tools import HUB_TOOLS, risk_of

    assert asyncio.run(presets.install(preset)) == (preset, "created")
    agent = registry.get(preset)
    assert agent.tools == ["web_search", "rest_get_leads"]
    tools = {t.name: t for t in HUB_TOOLS}
    assert all(risk_of(tools[n]) == "read" for n in agent.tools)
    assert asyncio.run(presets.install(preset))[1] == "unchanged"  # idempotent


def test_the_icp_finder_asks_for_a_brief_and_a_meru_ready_csv(client):
    from app import presets
    from app.agents import registry

    asyncio.run(presets.install("icp_finder"))
    agent = registry.get("icp_finder")
    assert "client brief" in agent.instructions
    assert "Company name,Website,Country,Industry" in agent.instructions  # Meru's import header
    assert agent.templates and "Client:" in agent.templates[0]["description"]
