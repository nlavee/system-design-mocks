import asyncio
import websockets
from typing import Set
import logging

# Configure logging to see what's happening
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ChatServer")

class ChatServer:
    """
    A robust WebSocket server implementation demonstrating:
    1. Connection Management (register/unregister)
    2. Broadcasting logic
    3. Error handling for broken pipes
    """
    def __init__(self):
        # We use a Set for O(1) lookups and removals.
        # In a real system, this might be a Dict mapping IDs to sockets.
        self.connected_clients: Set[websockets.WebSocketServerProtocol] = set()

    async def register(self, websocket):
        """Adds a new connection to the registry."""
        self.connected_clients.add(websocket)
        logger.info(f"Client connected. Total clients: {len(self.connected_clients)}")

    async def unregister(self, websocket):
        """Removes a connection from the registry."""
        # Check carefully to avoid KeyErrors if unregister is called twice
        if websocket in self.connected_clients:
            self.connected_clients.remove(websocket)
            logger.info(f"Client disconnected. Total clients: {len(self.connected_clients)}")

    async def broadcast(self, message: str, sender_websocket):
        """
        Sends a message to all connected clients except the sender.
        """
        if not self.connected_clients:
            return

        # We need to handle the case where a client disconnects *during* the broadcast.
        # websockets.broadcast usually handles this, but implementing manually helps understand the loop.
        
        # Method 1: Manual Iteration (Interview Friendly)
        connections_to_remove = set()
        for client in self.connected_clients:
            if client != sender_websocket:
                try:
                    await client.send(message)
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("Detected dead connection during broadcast.")
                    connections_to_remove.add(client)
        
        # Cleanup dead connections found during broadcast
        for dead_client in connections_to_remove:
            await self.unregister(dead_client)

    async def handle_connection(self, websocket, path):
        """
        Main loop for a single client connection.
        This runs in its own Task (green thread) for each client.
        """
        await self.register(websocket)
        try:
            async for message in websocket:
                # 1. Receive message
                logger.info(f"Received: {message}")
                
                # 2. Process message (here, just broadcast)
                await self.broadcast(f"User says: {message}", websocket)
                
        except websockets.exceptions.ConnectionClosed:
            logger.info("Connection closed normally.")
        finally:
            # 3. Cleanup is critical in long-running servers
            await self.unregister(websocket)

    async def start(self, host="localhost", port=8765):
        # websockets.serve creates the server task
        async with websockets.serve(self.handle_connection, host, port):
            logger.info(f"Server started on ws://{host}:{port}")
            # Keep the loop running
            await asyncio.Future()

if __name__ == "__main__":
    server = ChatServer()
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("Server stopped manually.")
