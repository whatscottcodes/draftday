from __future__ import annotations

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
        stale: list[WebSocket] = []
        for ws in list(self._connections.get(league_id, ())):
            try:
                await ws.send_json(message)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(league_id, ws)


manager = ConnectionManager()