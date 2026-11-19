from app.events.schema import AgentEvent, AgentState, ServerMessage, Zone


def test_event_roundtrip_through_server_message():
    ev = AgentEvent(agent_id="list_builder", action="rest_get_leads",
                    source_zone=Zone.BREAK_ROOM, target_zone=Zone.DATABASE,
                    status_text="Running rest_get_leads...", state=AgentState.BUSY,
                    metrics={"steps": 2, "match_rate": "94.5%"})
    parsed = ServerMessage.model_validate_json(ev.model_dump_json()).root
    assert isinstance(parsed, AgentEvent) and parsed.metrics == {"steps": 2, "match_rate": "94.5%"}


async def test_marketo_credentials_never_appear_in_urls_or_errors():
    import httpx
    import pytest

    from app.marketo.governor import RateGovernor
    from app.marketo.rest_client import MarketoError, MarketoRestClient

    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(401, json={"error": "unauthorized",
                                         "error_description": "Bad client credentials"})

    rest = MarketoRestClient("https://123-abc-456.mktorest.com", "cid", "TOP-SECRET",
                             RateGovernor(calls=10, window_s=20, max_concurrent=2,
                                          daily_quota=100))
    rest._http = httpx.AsyncClient(base_url=rest.base_url,
                                   transport=httpx.MockTransport(handler))
    with pytest.raises(MarketoError) as exc:
        await rest._access_token()
    assert seen[0].method == "POST" and "TOP-SECRET" not in str(seen[0].url)
    assert b"client_secret=TOP-SECRET" in seen[0].content
    assert "TOP-SECRET" not in str(exc.value) and "Bad client credentials" in str(exc.value)


def test_marketo_reads_ride_out_network_blips_but_writes_never_repeat(monkeypatch):
    """A long scan survives a timeout or a 503; a write that may have landed isn't re-sent."""
    import asyncio

    import httpx

    from app.marketo import rest_client
    from app.marketo.governor import RateGovernor

    monkeypatch.setattr(rest_client, "NET_RETRY_DELAYS", (0, 0, 0))
    calls = {"GET": 0, "POST": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/identity/oauth/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        calls[request.method] += 1
        if request.method == "GET":
            if calls["GET"] == 1:
                raise httpx.ReadTimeout("slow")
            if calls["GET"] == 2:
                return httpx.Response(503)
            return httpx.Response(200, json={"success": True, "result": [{"id": 1}]})
        raise httpx.ReadTimeout("slow")

    async def run():
        c = rest_client.MarketoRestClient("https://x.mktorest.com", "id", "secret",
                                          RateGovernor(calls=100, window_s=20, max_concurrent=5,
                                                       daily_quota=1000))
        c._http = httpx.AsyncClient(base_url="https://x.mktorest.com",
                                    transport=httpx.MockTransport(handler))
        leads = await c.get_leads("id", ["1"], ["id"])
        try:
            await c.update_leads([{"id": 1, "firstName": "A"}])
        except httpx.ReadTimeout:
            pass
        else:
            raise AssertionError("the write should have failed, not been retried")
        return leads

    assert asyncio.run(run()) == [{"id": 1}]
    assert calls == {"GET": 3, "POST": 1}  # read retried twice; the write sent once
