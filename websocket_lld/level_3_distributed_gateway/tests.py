import unittest
import asyncio
from starter import MockRedisPubSub, DistributedServer
from unittest.mock import MagicMock, AsyncMock

class TestDistributedServer(unittest.IsolatedAsyncioTestCase):
    async def test_pubsub_mock(self):
        broker = MockRedisPubSub()
        callback = AsyncMock()
        
        await broker.subscribe("room1", callback)
        await broker.publish("room1", "hello")
        
        # Give asyncio loop a moment to process the task created in publish
        await asyncio.sleep(0.01)
        
        callback.assert_called_with("room1", "hello")

    async def test_server_subscription_logic(self):
        # We need to test if the server subscribes/unsubscribes correctly
        server = DistributedServer("s1", 9000)
        # Mock the broker to track calls
        server.pubsub = MagicMock()
        server.pubsub.subscribe = AsyncMock()
        server.pubsub.unsubscribe = AsyncMock()
        server.pubsub.publish = AsyncMock()

        ws = AsyncMock()
        room_id = "global"

        # 1. Join Room -> Should Trigger Subscription
        await server.join_room(room_id, ws)
        server.pubsub.subscribe.assert_called_with(room_id, server._on_pubsub_message)
        
        # 2. Second user joins -> Should NOT Trigger Subscription (already subbed)
        server.pubsub.subscribe.reset_mock()
        ws2 = AsyncMock()
        await server.join_room(room_id, ws2)
        server.pubsub.subscribe.assert_not_called()

        # 3. Leave Room (ws1) -> Should NOT Unsubscribe (ws2 still there)
        await server.leave_room(room_id, ws)
        server.pubsub.unsubscribe.assert_not_called()

        # 4. Leave Room (ws2) -> Should Unsubscribe (Local room empty)
        await server.leave_room(room_id, ws2)
        server.pubsub.unsubscribe.assert_called_with(room_id, server._on_pubsub_message)

    async def test_integration_flow(self):
        # Test full flow with real MockBroker (not mocked mock) to ensure callbacks fire
        # This is closer to an integration test
        server = DistributedServer("s1", 9000)
        ws_local = AsyncMock()
        
        # Manually wire up a real broker
        real_broker = MockRedisPubSub()
        server.pubsub = real_broker
        
        await server.join_room("chat", ws_local)
        
        # Simulate a message coming from "Network" (another server publishing)
        await real_broker.publish("chat", "Remote Message")
        await asyncio.sleep(0.01)

        # Local client should receive it via _on_pubsub_message
        ws_local.send.assert_called() 
        # Exact args depend on implementation (json dumps vs raw string) 
        # checking called is enough for basic verification

if __name__ == "__main__":
    unittest.main()
