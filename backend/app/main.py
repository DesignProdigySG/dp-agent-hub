import asyncio
import logging
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from langgraph.store.sqlite.aio import AsyncSqliteStore

from app import knowledge
from app.config import get_settings
from app.db import dispose_engine, init_db
from app.deps import build_deps, reconfigure
from app.hub import Hub
from app.ingest import ActivityIngestor
from app.routes import (
    agents,
    api,
    approval_links,
    attachments,
    auth,
    config,
    data_health,
    design,
    insights,
    scene,
    schedules,
)
from app.security import hash_password, is_admin
from app.settings_store import get_store
from app.snapshots import SnapshotScheduler

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


def checkpointer_for(settings):
    """Paused agent runs (awaiting approval) persist in the same database as everything else."""
    if settings.is_postgres:
        return AsyncPostgresSaver.from_conn_string(settings.libpq_url)
    return AsyncSqliteSaver.from_conn_string(str(settings.data_dir / "checkpoints.db"))


def store_for(settings):
    """LangGraph's long-term store, which holds agent memories."""
    if settings.is_postgres:
        return AsyncPostgresStore.from_conn_string(settings.libpq_url)
    return AsyncSqliteStore.from_conn_string(str(settings.data_dir / "store.db"))


EMBEDDING_KEYS = {"embedding_model", "voyage_api_key", "openai_api_key", "gemini_api_key",
                  "azure_openai_api_key", "azure_openai_endpoint", "ollama_base_url"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    store = get_store()
    settings = store.load()  # environment defaults + encrypted UI overrides
    if store.admin_hash() is None and settings.admin_password:
        store.set_admin_hash(hash_password(settings.admin_password))
        log.info("Admin password initialised from ADMIN_PASSWORD")
    log.info("Database: %s",
             "Postgres" if settings.is_postgres else f"SQLite ({settings.data_dir})")

    deps = build_deps(settings)
    knowledge.ensure_vector()

    async with AsyncExitStack() as stack:
        checkpointer = await stack.enter_async_context(checkpointer_for(settings))
        memory_store = await stack.enter_async_context(store_for(settings))
        await memory_store.setup()
        if settings.is_postgres:
            await checkpointer.setup()
        hub = Hub(deps, checkpointer, memory_store)
        hub.recover()
        hub.start_loops()
        ingestor = ActivityIngestor(deps)
        ingestor.start()
        snapshots = SnapshotScheduler(hub)
        snapshots.start()
        app.state.hub, app.state.ingestor, app.state.snapshots = hub, ingestor, snapshots
        app.state.store = memory_store
        background: set[asyncio.Task] = set()

        async def on_settings_change(new_settings, changed):
            await reconfigure(new_settings, changed)
            ingestor.kick()
            if changed & EMBEDDING_KEYS:
                job = asyncio.create_task(knowledge.reindex_all())
                background.add(job)
                job.add_done_callback(background.discard)
            await deps.bus.broadcast(hub.snapshot())  # mode badge, roster, etc.

        store.on_change(on_settings_change)
        try:
            yield
        finally:
            await snapshots.stop()
            await ingestor.stop()
            await hub.stop()
            await deps.marketo.aclose()
            dispose_engine()


app = FastAPI(title="Marketo AI Agent Hub", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
for router in (api.public, api.viewer, api.admin, agents.viewer, agents.admin, auth.router,
               config.router, insights.viewer, insights.admin, scene.viewer, scene.admin,
               approval_links.router, schedules.viewer, schedules.admin, data_health.viewer,
               design.viewer, design.admin, attachments.viewer, attachments.admin):
    app.include_router(router, prefix="/api")


@app.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    if not (get_settings().public_read_access or is_admin(websocket)):
        await websocket.close(code=4401, reason="sign in required")
        return
    hub: Hub = websocket.app.state.hub
    bus = hub.deps.bus
    await bus.connect(websocket)
    try:
        await bus.send(websocket, hub.snapshot())
        while True:
            await websocket.receive_text()  # client->server traffic is keep-alive only
    except WebSocketDisconnect:
        pass
    finally:
        await bus.disconnect(websocket)
