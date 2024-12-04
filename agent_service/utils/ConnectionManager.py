from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict

'''
ConnectionManager is a class that manages the connections to the websocket.
It allows for sending messages to a specific thread or broadcasting to all threads.
'''

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, thread_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[thread_id] = websocket
        print(f"Client connected: {thread_id}")

    def disconnect(self, thread_id: str):
        if thread_id in self.active_connections:
            del self.active_connections[thread_id]
            print(f"Client disconnected: {thread_id}")

    async def send_message(self, thread_id: str, message: str):
        websocket = self.active_connections.get(thread_id)
        if websocket:
            await websocket.send_text(message)
            print(f"Sent message to {thread_id}: {message}")
            
    async def send_message_json(self, thread_id: str, message: dict):
        websocket = self.active_connections.get(thread_id)
        if websocket:
            await websocket.send_json(message)
            print(f"Sent message to {thread_id}: {message}")

    async def broadcast(self, message: str):
        for thread_id, websocket in self.active_connections.items():
            await websocket.send_text(message)
            print(f"Broadcast message to {thread_id}: {message}")