"""WebSocket connection manager — shared singleton"""
from typing import Dict, List
from fastapi import WebSocket


class WSManager:
    def __init__(self):
        self.connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, ws: WebSocket, user_id: str):
        await ws.accept()
        self.connections.setdefault(user_id, []).append(ws)

    def disconnect(self, ws: WebSocket, user_id: str):
        if user_id in self.connections:
            self.connections[user_id] = [c for c in self.connections[user_id] if c != ws]

    async def broadcast_user(self, user_id: str, message: dict):
        if user_id in self.connections:
            dead = []
            for ws in self.connections[user_id]:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.append(ws)
            for d in dead:
                self.connections[user_id].remove(d)

    async def notify_user(self, user_id: str, msg: dict):
        for ws in self.connections.get(user_id, []):
            try:
                await ws.send_json(msg)
            except Exception:
                pass

    async def broadcast_all(self, msg: dict):
        for uid, conns in self.connections.items():
            for ws in conns:
                try:
                    await ws.send_json(msg)
                except Exception:
                    pass


ws_manager = WSManager()
