import unittest
import asyncio
import websockets
from starter import RoomManager
from unittest.mock import MagicMock, AsyncMock

class TestRoomManager(unittest.IsolatedAsyncioTestCase):
    async def test_join_leave(self):
        manager = RoomManager()
        ws = AsyncMock()
        room_id = "general"

        await manager.join_room(room_id, ws)
        self.assertIn(room_id, manager.rooms)
        self.assertIn(ws, manager.rooms[room_id])
        
        # Check reverse index if implemented
        if hasattr(manager, 'client_rooms'):
             self.assertIn(ws, manager.client_rooms)
             self.assertIn(room_id, manager.client_rooms[ws])

        await manager.leave_room(room_id, ws)
        # Check cleanup of empty room
        if room_id in manager.rooms:
            self.assertEqual(len(manager.rooms[room_id]), 0)
        else:
            # If they deleted the key, that's also valid (and better)
            pass

    async def test_cleanup_on_disconnect(self):
        manager = RoomManager()
        ws = AsyncMock()
        
        await manager.join_room("room1", ws)
        await manager.join_room("room2", ws)

        await manager.remove_client_from_all_rooms(ws)
        
        # Should be removed from both rooms
        if "room1" in manager.rooms:
            self.assertNotIn(ws, manager.rooms["room1"])
        if "room2" in manager.rooms:
             self.assertNotIn(ws, manager.rooms["room2"])

    async def test_scoped_broadcast(self):
        manager = RoomManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock() # In room
        ws3 = AsyncMock() # Not in room

        await manager.join_room("gossip", ws1)
        await manager.join_room("gossip", ws2)
        # ws3 is not joined

        await manager.broadcast_to_room("gossip", {"msg": "secret"}, ws1)

        # ws1 (sender) -> might receive or not depending on implementation logic, checking not called for now as standard optimization
        # ws2 (receiver) -> MUST receive
        # ws3 (outsider) -> MUST NOT receive
        
        # Validate ws2 call args
        # Since implementation does json.dumps, we check if send was called
        self.assertTrue(ws2.send.called)
        self.assertFalse(ws3.send.called)

if __name__ == "__main__":
    unittest.main()
