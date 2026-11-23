"""Web search for agents, through the Brave Search API.

The key (Settings > Web search) travels in a request header, never the URL, and errors are
reported without the request URL or credentials, like the paid verification calls.
"""

import logging
from typing import Any

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
MAX_RESULTS = 20


class SearchError(RuntimeError):
    pass


async def brave_search(query: str, count: int = 10, freshness: str | None = None,
                       http: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
    """Return [{title, url, description, age}] for a web search."""
    key = get_settings().brave_api_key
    if not key:
        raise SearchError("No Brave Search API key. Add one in Settings > Web search.")
    query = query.strip()
    if not query:
        raise SearchError("Empty search query.")
    params: dict[str, Any] = {"q": query[:400], "count": max(1, min(count, MAX_RESULTS))}
    if freshness in ("pd", "pw", "pm", "py"):  # past day / week / month / year
        params["freshness"] = freshness
    own = http is None
    http = http or httpx.AsyncClient(timeout=30)
    try:
        resp = await http.get(BRAVE_URL, params=params, headers={
            "X-Subscription-Token": key, "Accept": "application/json"})
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise SearchError(f"Brave Search answered HTTP {e.response.status_code}") from None
    except httpx.HTTPError as e:
        raise SearchError(f"Brave Search request failed ({type(e).__name__})") from None
    finally:
        if own:
            await http.aclose()
    results = (resp.json().get("web") or {}).get("results") or []
    return [{"title": r.get("title", ""), "url": r.get("url", ""),
             "description": r.get("description", ""), "age": r.get("age", "")}
            for r in results]
