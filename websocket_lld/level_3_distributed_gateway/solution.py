import asyncio
import websockets
import json
import logging
from typing import Dict, Set, Callable, List

logging.basicConfig(level=logging.INFO)

class MockRedisPubSub:
    """
    A simple in-memory implementation of a Pub/Sub broker.
    In production, this would be `aioredis` connecting to a real Redis instance.
    """
    def __init__(self):
        # Map Channel -> List of Callback functions (subscribers)
        self._subscribers: Dict[str, Set[Callable]] = {}

    async def subscribe(self, channel: str, callback: Callable):
        if channel not in self._subscribers:
            self._subscribers[channel] = set()
        self._subscribers[channel].add(callback)

    async def unsubscribe(self, channel: str, callback: Callable):
        if channel in self._subscribers:
            self._subscribers[channel].discard(callback)

    async def publish(self, channel: str, message: str):
        if channel in self._subscribers:
            # Notify all subscribers
            for callback in self._subscribers[channel]:
                # In real Redis, this happens over network.
                # Here we just schedule the callback.
                asyncio.create_task(callback(channel, message))

# Global broker for simulation
GLOBAL_BROKER = MockRedisPubSub()

class DistributedServer:
    def __init__(self, server_id: str, port: int):
        self.server_id = server_id
        self.port = port
        self.local_rooms: Dict[str, Set[websockets.WebSocketServerProtocol]] = {}
        self.pubsub = GLOBAL_BROKER
        self.logger = logging.getLogger(f"Server-{server_id}")

    async def _on_pubsub_message(self, channel: str, message: str):
        """
        Callback triggered when the Broker has a message for a channel we are subscribed to.
        """
        self.logger.info(f"Received PubSub msg on {channel}: {message}")
        
        # Broadcast to LOCAL clients in this room
        if channel in self.local_rooms:
            # We don't need to exclude the sender here because the sender might be on another server.
            # Ideally, we include a 'sender_id' in the message to filter out echo if sender is local.
            # For simplicity, we just broadcast to all.
            to_remove = set()
            for client in self.local_rooms[channel]:
                try:
                    await client.send(message)
                except websockets.exceptions.ConnectionClosed:
                    to_remove.add(client)
            
            for dead in to_remove:
                self.local_rooms[channel].discard(dead)

    async def join_room(self, room_id: str, websocket):
        if room_id not in self.local_rooms:
            self.local_rooms[room_id] = set()
            # This server is now interested in this room. Subscribe to Broker.
            await self.pubsub.subscribe(room_id, self._on_pubsub_message)
            
        self.local_rooms[room_id].add(websocket)

    async def leave_room(self, room_id: str, websocket):
        if room_id in self.local_rooms:
            self.local_rooms[room_id].discard(websocket)
            if not self.local_rooms[room_id]:
                # No more local clients in this room. Unsubscribe from Broker to save bandwidth.
                del self.local_rooms[room_id]
                await self.pubsub.unsubscribe(room_id, self._on_pubsub_message)

    async def handle_connection(self, websocket, path):
        current_rooms = set()
        try:
            async for message in websocket:
                data = json.loads(message)
                action = data.get("action")
                room_id = data.get("room_id")

                if action == "join":
                    await self.join_room(room_id, websocket)
                    current_rooms.add(room_id)
                elif action == "message":
                    # PUBLISH to the broker. Do not broadcast locally directly.
                    # The broker will echo it back to us (since we are subscribed), 
                    # and we will handle it in _on_pubsub_message.
                    # This ensures order consistency across servers.
                    payload = json.dumps({
                        "room": room_id,
                        "content": data.get("content"),
                        "from_server": self.server_id
                    })
                    await self.pubsub.publish(room_id, payload)

        finally:
            for room_id in current_rooms:
                await self.leave_room(room_id, websocket)

    async def start(self):
        self.logger.info(f"Starting on port {self.port}")
        async with websockets.serve(self.handle_connection, "localhost", self.port):
            await asyncio.Future()

async def simulate_multiple_servers():
    """
    Run two server instances in the same process to demonstrate distributed messaging.
    """
    server1 = DistributedServer("S1", 8765)
    server2 = DistributedServer("S2", 8766)
    
    await asyncio.gather(
        server1.start(),
        server2.start()
    )

if __name__ == "__main__":
    # To run this simulation:
    # 1. Connect Client A to ws://localhost:8765
    # 2. Connect Client B to ws://localhost:8766
    # 3. Client A join "lobby", Client B join "lobby"
    # 4. Client A sends message -> Server 1 -> Broker -> Server 2 -> Client B
    try:
        asyncio.run(simulate_multiple_servers())
    except KeyboardInterrupt:
        pass
