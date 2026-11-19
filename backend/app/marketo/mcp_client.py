"""Marketo MCP client: exposes the MCP server's asset/orchestration tools, governed."""

import json
import logging
import re
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.marketo.governor import RateGovernor

log = logging.getLogger(__name__)


class MarketoMcpClient:
    def __init__(
        self,
        url: str,
        munchkin_id: str,
        client_id: str,
        client_secret: str,
        governor: RateGovernor,
    ):
        # Adobe's Marketo MCP server authenticates with the same LaunchPoint credentials
        # as the REST API, passed as headers.
        headers = {
            "X-Marketo-Client-Id": client_id,
            "X-Marketo-Client-Secret": client_secret,
            "X-Marketo-Munchkin-Id": munchkin_id,
        }
        self._client = MultiServerMCPClient(
            {"marketo": {"url": url, "transport": "streamable_http", "headers": headers}}
        )
        self._governor = governor
        self._tools: dict[str, BaseTool] | None = None

    async def tools(self) -> dict[str, BaseTool]:
        if self._tools is None:
            self._tools = {t.name: t for t in await self._client.get_tools()}
            log.info("loaded %d Marketo MCP tools", len(self._tools))
        return self._tools

    async def call(self, name: str, args: dict[str, Any]) -> Any:
        tools = await self.tools()
        if name not in tools:
            raise KeyError(f"Marketo MCP server has no tool named {name!r}")
        result = await self._governor.run("mcp", lambda: tools[name].ainvoke(args))
        return _decode(result)


def _decode(result: Any) -> Any:
    """MCP tools return text content blocks; unwrap JSON where possible."""
    if isinstance(result, tuple):  # (content, artifact) form
        result = result[0]
    if isinstance(result, list):
        texts = [b.get("text", "") if isinstance(b, dict) else str(b) for b in result]
        result = "\n".join(texts)
    if isinstance(result, str):
        # Marketo's MCP server often wraps its JSON in a ```json fence inside the text.
        fence = re.search(r"```json\s*(.*?)```", result, re.S)
        try:
            return json.loads(fence.group(1) if fence else result)
        except ValueError:
            return result
    return result
