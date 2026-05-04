import uuid
from typing import Dict
from fastapi import WebSocket
import json


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.usernames: Dict[str, str] = {}
        self.strikes: Dict[str, int] = {}
        self.muted: Dict[str, bool] = {}

    async def connect(self, websocket: WebSocket, username: str):
        user_id = str(uuid.uuid4())

        self.active_connections[user_id] = websocket
        self.usernames[user_id] = username
        self.strikes[user_id] = 0
        self.muted[user_id] = False

        await self.broadcast_users()

        return user_id

    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            del self.usernames[user_id]
            del self.strikes[user_id]
            del self.muted[user_id]

    async def send_personal(self, message: dict, user_id: str):
        try:
            if user_id in self.active_connections:
                await self.active_connections[user_id].send_text(json.dumps(message))
        except:
            self.disconnect(user_id)

    async def broadcast(self, message: dict):
        disconnected = []

        for user_id, connection in self.active_connections.items():
            try:
                await connection.send_text(json.dumps(message))
            except:
                disconnected.append(user_id)

        # 🔥 limpiar sockets muertos
        for user_id in disconnected:
            self.disconnect(user_id)

    async def broadcast_users(self):
        users = list(self.usernames.values())

        await self.broadcast({
            "type": "users",
            "data": users
        })

    async def broadcast_typing(self, username: str):
        await self.broadcast({
            "type": "typing",
            "data": username
        })