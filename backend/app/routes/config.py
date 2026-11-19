"""Runtime settings (admin only) and connection tests."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app import notify
from app.config import get_settings
from app.llm.router import plan_route
from app.marketo.datastreams import JournalClient
from app.marketo.mcp_client import MarketoMcpClient
from app.marketo.rest_client import MarketoRestClient
from app.security import require_admin
from app.settings_store import SettingsError, get_store

router = APIRouter(prefix="/config", dependencies=[Depends(require_admin)])


def _status(request: Request) -> dict[str, Any]:
    hub = request.app.state.hub
    s = get_settings()
    routes = {}
    for tier in ("fast", "standard", "strong"):
        route = plan_route(s, tier)
        routes[tier] = {"models": route.models, "blocked": route.blocked}
    return {
        "database": "postgres" if s.is_postgres else "sqlite",
        "marketo_error": hub.deps.marketo_error,
        "routes": routes,
        "ingestion": request.app.state.ingestor.status(),
    }


@router.get("")
def get_config(request: Request) -> dict:
    return {**get_store().describe(), "status": _status(request)}


class ConfigChanges(BaseModel):
    changes: dict[str, Any]


@router.put("")
async def update_config(body: ConfigChanges, request: Request) -> dict:
    try:
        await get_store().update(body.changes)
    except SettingsError as e:
        raise HTTPException(422, {"errors": e.errors}) from None
    return {**get_store().describe(), "status": _status(request)}


class TestRequest(BaseModel):
    model: str | None = None


@router.post("/test/{target}")
async def test_connection(target: str, request: Request, body: TestRequest | None = None) -> dict:
    s = get_settings()
    deps = request.app.state.hub.deps
    if target == "marketo":
        if not s.marketo_configured:
            return {"ok": False, "error": "Munchkin ID, client ID and client secret are required"}
        rest = MarketoRestClient(s.marketo_rest_url, s.marketo_client_id,
                                 s.marketo_client_secret, deps.governor)
        result: dict[str, Any] = {}
        try:
            await rest._access_token(force=True)
            result["rest"] = {"ok": True, "detail": f"token issued by {s.marketo_rest_url}"}
        except Exception as e:
            result["rest"] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
        finally:
            await rest.aclose()
        if s.marketo_mcp_url:
            mcp = MarketoMcpClient(s.marketo_mcp_url, s.marketo_munchkin_id, s.marketo_client_id,
                                   s.marketo_client_secret, deps.governor)
            try:
                tools = await mcp.tools()
                result["mcp"] = {"ok": True, "detail": f"{len(tools)} tools available"}
            except Exception as e:
                result["mcp"] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
        result["ok"] = all(v["ok"] for v in result.values() if isinstance(v, dict))
        return result
    if target == "llm":
        models = ([body.model] if body and body.model else
                  [s.llm_fast_model, s.llm_standard_model, s.llm_strong_model])
        results = [await deps.llm.test(m) for m in dict.fromkeys(m for m in models if m)]
        return {"ok": all(r["ok"] for r in results), "results": results}
    if target == "datastreams":
        if not s.datastreams_configured:
            return {"ok": False, "error": "Org ID, client ID, client secret and journal URL "
                                          "are required"}
        client = JournalClient(s)
        try:
            entries, _, retry = await client.fetch(None)
            detail = (f"journal reachable; {len(entries)} events on the first page"
                      if entries else f"journal reachable; no events yet (retry in {retry}s)")
            return {"ok": True, "detail": detail}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
        finally:
            await client.aclose()
    if target == "datalake":
        return await deps.lake.test()
    if target == "email":
        return await notify.test(target)
    raise HTTPException(404, f"unknown test target {target!r}")
