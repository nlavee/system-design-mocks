import asyncio
import websockets
import json
from typing import Dict, Set, Callable

class MockRedisPubSub:
    """
    Simulates an external Pub/Sub service like Redis.
    Shared singleton for simulation purposes across 'instances'.
    """
    _channels: Dict[str, Set[Callable]] = {}

    async def subscribe(self, channel: str, callback: Callable):
        if channel not in MockRedisPubSub._channels:
            MockRedisPubSub._channels[channel] = set()
        
        MockRedisPubSub._channels[channel].add(callback)

    async def unsubscribe(self, channel: str, callback: Callable):
        if channel in MockRedisPubSub._channels:
            MockRedisPubSub._channels[channel].discard(callback)
            if not MockRedisPubSub._channels[channel]:
                del MockRedisPubSub._channels[channel]

    async def publish(self, channel: str, message: str):
        if channel not in MockRedisPubSub._channels:
            return

        for callback in list(MockRedisPubSub._channels[channel]):
            asyncio.create_task(callback(channel, message))

class DistributedServer:
    def __init__(self, server_id: str, port):
        self.server_id = server_id
        self.port = port
        # Local connections only
        self.local_rooms: Dict[str, Set[websockets.WebSocketServerProtocol]] = {}
        self.pubsub = MockRedisPubSub()



    async def broadcast(self, room_id: str, message: dict):
        # TODO: Instead of sending directly, PUBLISH to PubSub
        await self.pubsub.publish(room_id, json.dumps(message))


    async def join_room(self, room_id, websocket):
        if room_id not in self.local_rooms:
            self.local_rooms[room_id] = set()
            await self.pubsub.subscribe(room_id, self._on_pubsub_message)
        self.local_rooms[room_id].add(websocket)

    async def leave_room(self, room_id, websocket):
        if room_id in self.local_rooms:
            self.local_rooms[room_id].discard(websocket)
            if not self.local_rooms[room_id]:
                del self.local_rooms[room_id]
                await self.pubsub.unsubscribe(room_id, self._on_pubsub_message)

    async def _on_pubsub_message(self, channel, message):
        if channel in self.local_rooms:
            to_remove = set()
            for client in self.local_rooms[channel]:
                try:
                    await client.send(message)
                except websockets.exceptions.ConnectionClosed:
                    to_remove.add(client)
            
            for dead in to_remove:
                self.local_rooms[channel].discard(dead)

    async def start(self, port):
        async with websockets.serve(self.handle_connection, "localhost", self.port):
            await asyncio.Future()
