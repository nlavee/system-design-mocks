import asyncio
import websockets
import json
from typing import Dict, Set

class RoomManager:
    def __init__(self):
        # TODO: Store rooms and their members
        # Hint: self.rooms: Dict[str, Set[websockets.WebSocketServerProtocol]]
        self.rooms : Dict[str, Set[websockets.WebSocketServerProtocol]] = dict()
        self.client_rooms: Dict[websockets.WebSocketServerProtocol, set()] = dict()

    async def join_room(self, room_id: str, websocket):
        if room_id not in self.rooms:
            self.rooms[room_id] = set()

        self.rooms[room_id].add(websocket)

        if websocket not in self.client_rooms:
            self.client_rooms[websocket] = set()

        self.client_rooms[websocket].add(room_id)
            

    async def leave_room(self, room_id: str, websocket):
        # TODO: Remove websocket from room
        if room_id not in self.rooms:
            pass

        if websocket in self.rooms[room_id]:
            self.rooms[room_id].remove(websocket)
            if not self.rooms[room_id]:
                del self.rooms[room_id]

        if websocket in self.client_rooms and room_id in self.client_rooms[websocket]:
            self.client_rooms[websocket].remove(room_id)
            if not self.client_rooms[websocket]:
                del self.client_rooms[websocket]


    async def broadcast_to_room(self, room_id: str, message: str, sender_websocket):
        if room_id not in self.rooms:
            return 

        if sender_websocket in self.client_rooms and room_id not in self.client_rooms[sender_websocket]:
            # User not in room, just return 
            return 

        current_room_websockets = self.rooms[room_id]
        for websocket in current_room_websockets.copy():
            if websocket == sender_websocket:
                continue

            await websocket.send(json.dumps(message))
        

    async def remove_client_from_all_rooms(self, websocket):
        if not websocket in self.client_rooms:
            pass

        websocket_rooms = self.client_rooms[websocket].copy()
        for room_id in websocket_rooms:
            await self.leave_room(room_id, websocket)
        


class CollaborativeServer:
    def __init__(self):
        self.room_manager = RoomManager()

    async def handle_connection(self, websocket, path):
        try:
            async for message in websocket:
                data = json.loads(message)
                action = data.get("action")

                # Values from README.md
                if action == "join":
                    room_id = data.get("room_id")
                    await self.room_manager.join_room(room_id, websocket)
                elif action == "leave":
                    room_id = data.get("room_id")
                    await self.room_manager.leave_room(room_id, websocket)
                elif action == "message":
                    room_id = data.get("room_id")
                    message = data.get("content")
                    await self.room_manager.broadcast_to_room(room_id, message, websocket)

        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            await self.room_manager.remove_client_from_all_rooms(websocket)

    async def start(self):
        # Boilerplate start
        async with websockets.serve(self.handle_connection, "localhost", 8765):
            await asyncio.Future()

if __name__ == "__main__":
    server = CollaborativeServer()
    asyncio.run(server.start())
