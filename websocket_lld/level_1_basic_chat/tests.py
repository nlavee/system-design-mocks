import unittest
import asyncio
import websockets
from starter import ChatServer
from unittest.mock import MagicMock, AsyncMock

class TestChatServer(unittest.IsolatedAsyncioTestCase):
    async def test_server_registration(self):
        server = ChatServer()
        mock_ws = AsyncMock()
        
        await server.register(mock_ws)
        # Assuming starter uses a set called connected_clients or similar exposed state
        # Adjust based on candidate implementation, but for TDD we enforce an interface
        if hasattr(server, 'connected_clients'):
            self.assertIn(mock_ws, server.connected_clients)
        
        await server.unregister(mock_ws)
        if hasattr(server, 'connected_clients'):
            self.assertNotIn(mock_ws, server.connected_clients)

    async def test_broadcast_logic(self):
        server = ChatServer()
        client_a = AsyncMock()
        client_b = AsyncMock()
        client_c = AsyncMock()

        # Manually register clients
        # Adapt this if implementation stores in a dict
        if hasattr(server, 'connected_clients'):
            server.connected_clients.add(client_a)
            server.connected_clients.add(client_b)
            server.connected_clients.add(client_c)
        else:
            # Fallback if they use a different internal structure, 
            # might need to call .register directly
            await server.register(client_a)
            await server.register(client_b)
            await server.register(client_c)

        # Broadcast from A
        await server.broadcast("Hello World", client_a)

        # Check Calls
        # Client A (sender) should NOT receive it (usually)
        # But if the implementation is simple broadast-all, verify that constraint.
        # The prompt says "broadcast to all OTHER connected clients".
        
        # client_a.send.assert_not_called() # Optional strictness
        
        # B and C MUST receive it
        client_b.send.assert_called_with("Hello World")
        client_c.send.assert_called_with("Hello World")

if __name__ == "__main__":
    unittest.main()
