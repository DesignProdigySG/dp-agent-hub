"""fetch_page: public pages only, as plain text."""

import asyncio

import httpx
import pytest

from app import webfetch

PUBLIC = "93.184.216.34"
ADDRESSES = {"site.test": [PUBLIC], "inside.test": ["10.0.0.5"], "mixed.test": [PUBLIC, "::1"]}


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    def resolve(host):
        if host not in ADDRESSES:
            raise OSError("not found")
        return ADDRESSES[host]

    monkeypatch.setattr(webfetch, "_resolve", resolve)


def fetch(url, handler):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await webfetch.fetch_page(url, http=http)

    return asyncio.run(run())


def html(body, **kw):
    return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"},
                          text=body, **kw)


PAGE = """<html><head><title> Laptop  reviews </title><style>.x{}</style></head>
<body><nav>Home | Products</nav><h1>What buyers say</h1>
<p>Battery &amp; support were <b>disappointing</b>.</p><script>track()</script>
<ul><li>Too heavy</li><li>Slow repairs</li></ul><footer>(c) 2026</footer></body></html>"""


def test_a_page_comes_back_as_readable_text():
    out = fetch("https://site.test/reviews", lambda r: html(PAGE))
    assert out["title"] == "Laptop reviews"
    assert "Battery & support were disappointing." in out["text"]
    assert "Too heavy" in out["text"] and "Slow repairs" in out["text"]
    for hidden in ("track()", "Home | Products", "(c) 2026", ".x{}"):
        assert hidden not in out["text"]
    assert out["truncated"] is False


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://169.254.169.254/latest/meta-data/", "http://[::1]/",
    "http://10.1.2.3/", "file:///etc/passwd", "ftp://site.test/", "http://inside.test/",
    "http://mixed.test/", "http://nowhere.test/", "https://www.linkedin.com/in/someone"])
def test_only_the_public_internet_is_reachable(url):
    def never(request):
        raise AssertionError(f"should not have requested {request.url}")

    with pytest.raises(webfetch.FetchError):
        fetch(url, never)


def test_redirect_targets_are_checked_too():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://inside.test/admin"})

    with pytest.raises(webfetch.FetchError, match="public internet"):
        fetch("https://site.test/go", handler)
    assert seen == ["https://site.test/go"]


def test_safe_redirects_are_followed_a_few_times_only():
    def handler(request):
        if request.url.path == "/final":
            return html("<p>arrived</p>")
        return httpx.Response(301, headers={"location": "/final"})

    assert fetch("https://site.test/start", handler)["url"] == "https://site.test/final"
    loop = lambda r: httpx.Response(302, headers={"location": "/again"})  # noqa: E731
    with pytest.raises(webfetch.FetchError, match="redirects"):
        fetch("https://site.test/again", loop)


def test_long_pages_are_truncated_and_binaries_refused():
    out = fetch("https://site.test/", lambda r: html("<p>" + "word " * 10_000 + "</p>"))
    assert out["truncated"] is True and len(out["text"]) == webfetch.MAX_CHARS
    pdf = lambda r: httpx.Response(200, headers={"content-type": "application/pdf"},  # noqa: E731
                                   content=b"%PDF")
    with pytest.raises(webfetch.FetchError, match="isn't text"):
        fetch("https://site.test/a.pdf", pdf)
    with pytest.raises(webfetch.FetchError, match="403"):
        fetch("https://site.test/", lambda r: httpx.Response(403))


def test_the_tool_reports_errors_to_the_agent_instead_of_raising(env):
    from app.agents.tools import fetch_page

    out = asyncio.run(fetch_page.ainvoke({"url": "http://127.0.0.1:8000/api"}))
    assert "error" in out and out["url"] == "http://127.0.0.1:8000/api"
