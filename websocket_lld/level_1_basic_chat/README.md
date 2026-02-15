# Level 1: The Basic Chat Server

## Problem Statement
Design and implement a basic WebSocket server that supports a global chat room.
Any message sent by one client should be broadcast to *all* other connected clients immediately.

## Core Requirements
1.  **Handshake Handling**: Accept WebSocket connections.
2.  **Connection Management**: Maintain a registry of active connections.
3.  **Broadcasting**: When a message is received from Client A, send it to Clients B, C, D...
4.  **Disconnection Handling**: Gracefully handle clients dropping off (remove from registry).

## Conceptual Focus
-   **AsyncIO**: Understanding the Event Loop (Single-threaded concurrency).
-   **State Management**: Storing active sockets in a `set` or `dict`.
-   **Concurrency**: Handling multiple connections without blocking.

## Setup
Install the necessary library:
```bash
pip install websockets
```

## Challenge
Implement the `ChatServer` class in `starter.py` to make the tests pass (or to make the manual client work).
Then review `solution.py` for a detailed breakdown of best practices including:
-   Class-based detailed design.
-   Error handling (Connections closed, Network errors).
-   Proper resource cleanup.
