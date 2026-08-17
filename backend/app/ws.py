from __future__ import annotations

import asyncio
from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, league_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[league_id].add(websocket)

    def disconnect(self, league_id: int, websocket: WebSocket) -> None:
        self._connections[league_id].discard(websocket)
        if not self._connections[league_id]:
            self._connections.pop(league_id, None)

    async def broadcast(self, league_id: int, message: dict) -> None:
        sockets = list(self._connections.get(league_id, ()))
        if not sockets:
            return
        stale: list[WebSocket] = []

        async def send_one(ws: WebSocket) -> None:
            try:
                await asyncio.wait_for(ws.send_json(message), timeout=5)
            except Exception:
                stale.append(ws)

        await asyncio.gather(*(send_one(ws) for ws in sockets))
        for ws in stale:
            self.disconnect(league_id, ws)


manager = ConnectionManager()