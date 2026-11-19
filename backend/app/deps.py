"""Process-wide singletons wired up in the FastAPI lifespan.

Settings can change at runtime (Settings page), so dependencies that hold credentials are
rebuilt by `reconfigure` rather than captured once at startup. Agents always read
`get_deps().marketo` / `.llm` at call time, so a swap takes effect on their next call.
"""

import logging
from dataclasses import dataclass

from app.config import Settings, get_settings
from app.events.bus import EventBus
from app.llm.router import LLMRouter
from app.marketo.gateway import DemoMarketo, LiveMarketo, MarketoGateway
from app.marketo.governor import RateGovernor
from app.marketo.mcp_client import MarketoMcpClient
from app.marketo.rest_client import MarketoRestClient
from app.storage.lake import LakeArchiver

log = logging.getLogger(__name__)

MARKETO_KEYS = {"marketo_mode", "marketo_munchkin_id", "marketo_client_id",
                "marketo_client_secret", "marketo_mcp_url"}
GOVERNOR_KEYS = {"governor_calls", "governor_window_s", "governor_max_concurrent",
                 "governor_daily_quota"}


@dataclass
class Deps:
    bus: EventBus
    governor: RateGovernor
    marketo: MarketoGateway
    llm: LLMRouter
    lake: LakeArchiver
    marketo_error: str = ""  # why live mode fell back to demo, if it did

    @property
    def settings(self) -> Settings:
        return get_settings()


_deps: Deps | None = None


def build_marketo(settings: Settings, governor: RateGovernor) -> tuple[MarketoGateway, str]:
    """Live gateway when configured; otherwise the demo sandbox (with the reason)."""
    if settings.marketo_mode != "live":
        return DemoMarketo(governor), ""
    if not settings.marketo_configured:
        msg = ("Live mode needs a Munchkin ID, client ID and client secret; running the demo "
               "sandbox until they are set.")
        log.warning(msg)
        return DemoMarketo(governor), msg
    rest = MarketoRestClient(settings.marketo_rest_url, settings.marketo_client_id,
                             settings.marketo_client_secret, governor)
    mcp = (MarketoMcpClient(settings.marketo_mcp_url, settings.marketo_munchkin_id,
                            settings.marketo_client_id, settings.marketo_client_secret,
                            governor) if settings.marketo_mcp_url else None)
    return LiveMarketo(rest, mcp), ""


def build_deps(settings: Settings) -> Deps:
    global _deps
    governor = RateGovernor(
        calls=settings.governor_calls,
        window_s=settings.governor_window_s,
        max_concurrent=settings.governor_max_concurrent,
        daily_quota=settings.governor_daily_quota,
    )
    marketo, error = build_marketo(settings, governor)
    _deps = Deps(bus=EventBus(), governor=governor, marketo=marketo, llm=LLMRouter(),
                 lake=LakeArchiver(), marketo_error=error)
    return _deps


async def reconfigure(settings: Settings, changed: set[str]) -> None:
    deps = get_deps()
    if changed & GOVERNOR_KEYS:
        deps.governor.configure(settings.governor_calls, settings.governor_window_s,
                                settings.governor_max_concurrent, settings.governor_daily_quota)
    if changed & MARKETO_KEYS:
        old = deps.marketo
        deps.marketo, deps.marketo_error = build_marketo(settings, deps.governor)
        await old.aclose()
        log.info("Marketo connection rebuilt (%s mode)", settings.marketo_mode)
    if any(k.startswith(("adls_", "azure_")) for k in changed):
        deps.lake.reset()


def get_deps() -> Deps:
    if _deps is None:
        raise RuntimeError("deps not initialised; is the app lifespan running?")
    return _deps
