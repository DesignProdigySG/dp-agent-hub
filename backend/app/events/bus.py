import asyncio
import logging

from fastapi import WebSocket
from pydantic import BaseModel

log = logging.getLogger(__name__)


class EventBus:
    """Fan-out of server messages to every connected WebSocket client."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def send(self, ws: WebSocket, msg: BaseModel) -> None:
        await ws.send_text(msg.model_dump_json())

    async def broadcast(self, msg: BaseModel) -> None:
        payload = msg.model_dump_json()
        async with self._lock:
            clients = list(self._clients)
        dead = []
        for ws in clients:
            try:
                await ws.send_text(payload)
            except Exception:  # client went away mid-send
                dead.append(ws)
        if dead:
            async with self._lock:
                self._clients.difference_update(dead)
            log.debug("dropped %d dead websocket(s)", len(dead))
