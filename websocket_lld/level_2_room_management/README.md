# Level 2: Room Management and JSON Protocol

## Problem Statement
Build a multi-room chat application. Clients can join specific rooms and only receive messages sent to that room.
This simulates real-time collaboration tools (like Google Docs or Slack channels).

## Core Requirements
1.  **Protocol**: Messages are now JSON strings (e.g., `{"action": "join", "room": "general"}`).
2.  **Room Management**: A client can be in one (or multiple) rooms.
3.  **Scoped Broadcast**: Messages sent to a room are only received by members of that room.
4.  **State Cleanup**: When a client disconnects, remove them from *all* rooms they joined.

## Conceptual Focus
-   **Data Structures**: Managing complex state (nested dicts/sets: `Dict[RoomID, Set[WebSocket]]`).
-   **Protocol Design**: Parsing and validating messages.
-   **Separation of Concerns**: `RoomManager` vs `ConnectionManager`.

## Protocol Spec
-   **Join**: `{"action": "join", "room_id": "room1"}`
-   **Leave**: `{"action": "leave", "room_id": "room1"}`
-   **Message**: `{"action": "message", "room_id": "room1", "content": "Hello Room!"}`

## Challenge
Implement `RoomManager` logic in `starter.py` to handle the JSON protocol and manages the room state.
Ensure that if a socket disconnects abruptly, it is cleaned up from all rooms.
