import asyncio
import websockets
from typing import Set

class ChatServer:
    def __init__(self):
        self.connected_clients = set()

    async def register(self, websocket):
        self.connected_clients.add(websocket)

    async def unregister(self, websocket):
        self.connected_clients.remove(websocket)

    async def broadcast(self, message: str, sender_websocket):
        # TODO: Send message to all connected clients except sender
        for websocket in self.connected_clients.copy():
            if websocket == sender_websocket:
                continue
            await websocket.send(message)

    async def handle_connection(self, websocket, path):
        # TODO:
        # 1. Register connection
        # 2. Listen for messages loop
        # 3. Broadcast received messages
        # 4. Unregister on disconnect (finally block)
        await self.register(websocket)
        try:
            async for message in websocket:
                await self.broadcast(message, websocket)
        finally:
            await self.unregister(websocket)

    async def start(self, host="localhost", port=8765):
        async with websockets.serve(self.handle_connection, host, port):
            print(f"Server started on ws://{host}:{port}")
            await asyncio.Future()  # Run forever

if __name__ == "__main__":
    server = ChatServer()
    asyncio.run(server.start())
