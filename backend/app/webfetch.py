"""Read a public web page as plain text, for research agents.

Agents get page text, never raw HTML, and only from the public internet: every host (including
each redirect target) must resolve to public addresses, so a page can't point the hub at its own
network (localhost, the database, cloud metadata). Nothing is logged in to; sites that refuse
automated readers just return an error to the agent.
"""

import asyncio
import ipaddress
import re
import socket
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

MAX_BYTES = 1_500_000
MAX_CHARS = 20_000
MAX_REDIRECTS = 3
TIMEOUT = 10
USER_AGENT = "Mozilla/5.0 (compatible; AgentHubReader/1.0)"
BLOCKED_HOSTS = ("linkedin.com",)  # its terms forbid automated access


class FetchError(RuntimeError):
    pass


def _resolve(host: str) -> list[str]:
    """Every address the host resolves to (tests replace this)."""
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


async def check_url(url: str) -> None:
    """Raise FetchError unless the URL is http(s) to a host with only public addresses."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchError("Only http and https web addresses can be read.")
    host = parts.hostname.lower().rstrip(".")
    if any(host == b or host.endswith("." + b) for b in BLOCKED_HOSTS):
        raise FetchError(f"{host} doesn't allow automated reading; skip it.")
    try:
        addrs = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addrs = [ipaddress.ip_address(a.split("%")[0])
                     for a in await asyncio.to_thread(_resolve, host)]
        except (OSError, ValueError):
            raise FetchError(f"Couldn't find the site {host}.") from None
    if not addrs or any(not a.is_global or a.is_multicast for a in addrs):
        raise FetchError("That address isn't on the public internet.")


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe",
            "template"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section",
             "article", "blockquote", "td", "th", "dd", "dt"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """(title, readable text) from an HTML page."""
    p = _Text()
    p.feed(html)
    p.close()
    lines = (re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in "".join(p.parts).split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return " ".join(p.title.split()), text


async def fetch_page(url: str, http: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Return {url, title, text, truncated} for a public page."""
    url = url.strip()
    own = http is None
    http = http or httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False)
    try:
        for _ in range(MAX_REDIRECTS + 1):
            await check_url(url)
            async with http.stream("GET", url, headers={
                    "User-Agent": USER_AGENT, "Accept": "text/html,text/plain"}) as resp:
                if resp.is_redirect and "location" in resp.headers:
                    url = urljoin(url, resp.headers["location"])
                    continue
                if resp.status_code >= 400:
                    raise FetchError(f"The site answered HTTP {resp.status_code}.")
                kind = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                if kind not in ("text/html", "text/plain", "application/xhtml+xml", ""):
                    raise FetchError(f"That page isn't text ({kind}); it can't be read.")
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) >= MAX_BYTES:
                        break
                raw = bytes(body[:MAX_BYTES]).decode(resp.encoding or "utf-8", "replace")
                break
        else:
            raise FetchError("Too many redirects.")
    except httpx.TimeoutException:
        raise FetchError("The site took too long to answer.") from None
    except httpx.HTTPError as e:
        raise FetchError(f"Couldn't read the page ({type(e).__name__}).") from None
    finally:
        if own:
            await http.aclose()
    title, text = html_to_text(raw) if kind != "text/plain" else ("", raw.strip())
    return {"url": url, "title": title, "text": text[:MAX_CHARS],
            "truncated": len(text) > MAX_CHARS}
