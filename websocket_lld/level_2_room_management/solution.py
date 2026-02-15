import asyncio
import websockets
import json
import logging
from typing import Dict, Set

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RoomServer")

class RoomManager:
    """
    Manages the mapping between Rooms and Clients.
    Separating this logic from the Server class allows for better testing and organization.
    """
    def __init__(self):
        # Maps RoomID -> Set of WebSockets
        self.rooms: Dict[str, Set[websockets.WebSocketServerProtocol]] = {}
        # Maps WebSocket -> Set of RoomIDs (for fast cleanup on disconnect)
        self.client_rooms: Dict[websockets.WebSocketServerProtocol, Set[str]] = {}

    async def join_room(self, room_id: str, websocket):
        if room_id not in self.rooms:
            self.rooms[room_id] = set()
        
        self.rooms[room_id].add(websocket)
        
        # Track reverse mapping
        if websocket not in self.client_rooms:
            self.client_rooms[websocket] = set()
        self.client_rooms[websocket].add(room_id)
        
        logger.info(f"Socket joined {room_id}. Total room members: {len(self.rooms[room_id])}")

    async def leave_room(self, room_id: str, websocket):
        if room_id in self.rooms:
            self.rooms[room_id].discard(websocket)
            if not self.rooms[room_id]:
                del self.rooms[room_id] # Clean up empty rooms
        
        if websocket in self.client_rooms:
            self.client_rooms[websocket].discard(room_id)

    async def broadcast_to_room(self, room_id: str, message: dict, sender_websocket):
        if room_id not in self.rooms:
            return
            
        payload = json.dumps(message)
        # Iterate over a copy to avoid runtime errors if set changes during iteration (though strictly in asyncio single-thread strictness, it's safer)
        # In multi-threaded env, would need Lock. In asyncio, context switch only happens at 'await'.
        # Since 'await client.send' is a context switch, the set COULD change if another task runs.
        # So we MUST copy the set or handle changes.
        members = list(self.rooms[room_id])
        
        for client in members:
            if client != sender_websocket:
                try:
                    await client.send(payload)
                except websockets.exceptions.ConnectionClosed:
                    # Cleanup handled in main loop finally block usually, 
                    # but we can trigger it here too if we want robustness
                    pass

    async def remove_client_from_all_rooms(self, websocket):
        """
        Efficient cleanup using the reverse mapping.
        """
        if websocket in self.client_rooms:
            rooms_to_leave = list(self.client_rooms[websocket])
            for room_id in rooms_to_leave:
                await self.leave_room(room_id, websocket)
            del self.client_rooms[websocket]
        logger.info("Client fully removed from all rooms.")

class CollaborativeServer:
    def __init__(self):
        self.room_manager = RoomManager()

    async def handle_connection(self, websocket, path):
        """
        Handlers now expect JSON messages.
        """
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    await websocket.send({"error": "Invalid JSON"})
                    continue
                
                action = data.get("action")
                room_id = data.get("room_id")
                
                if action == "join":
                    if room_id:
                        await self.room_manager.join_room(room_id, websocket)
                        await websocket.send(json.dumps({"status": "joined", "room": room_id}))
                
                elif action == "leave":
                    if room_id:
                        await self.room_manager.leave_room(room_id, websocket)
                        await websocket.send(json.dumps({"status": "left", "room": room_id}))
                
                elif action == "message":
                    content = data.get("content")
                    if room_id and content:
                        await self.room_manager.broadcast_to_room(
                            room_id, 
                            {"user_message": content, "from": "someone"}, # In real app, use UserID
                            websocket
                        )
                
                else:
                    await websocket.send(json.dumps({"error": "Unknown action"}))

        except websockets.exceptions.ConnectionClosed:
            logger.info("Connection closed.")
        finally:
            await self.room_manager.remove_client_from_all_rooms(websocket)

    async def start(self):
        async with websockets.serve(self.handle_connection, "localhost", 8765):
            logger.info("Collaborative Server started on :8765")
            await asyncio.Future()

if __name__ == "__main__":
    server = CollaborativeServer()
    asyncio.run(server.start())
