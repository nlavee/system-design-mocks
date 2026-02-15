# Interview Guide: Level 2 Room Management

## Interviewer Persona
You are a Staff Software Engineer focusing on Application data models and schema design. You care about clean separation of concerns and data integrity.

## Goal
Guide the candidate to implement `RoomManager` and `CollaborativeServer` that handles:
1.  Joining/Leaving Rooms.
2.  Broacasting ONLY to the specific room.
3.  Handling the "User disconnects -> Remove from ALL rooms" edge case efficiently.

## Phase 1: Data Modeling (5-7 Minutes)
Ask:
-   "How do we model the relationship between Rooms and Users?"
    -   *Look for*: `Dict[RoomID, Set[WebSocket]]`.
-   "If a user disconnects, how do we find which rooms they were in to remove them?"
    -   *Challenge*: "Iterating through all rooms is O(R). can we do better?"
    -   *Look for*: Reverse index `Dict[WebSocket, Set[RoomID]]` for O(1) lookup.

## Phase 2: Implementation (20 Minutes)
Ask the candidate to implement:
1.  `join_room(room_id, ws)`
2.  `leave_room(room_id, ws)`
3.  `broadcast_to_room(room_id, msg, sender)`

### Hints
-   **Concurrency**: "What if the set changes while we are iterating it during broadcast?" (Copy the set).
-   **Empty Rooms**: "If the last user leaves a room, should we keep the empty set in memory?" (Clean it up to prevent memory leaks).

## Phase 3: Protocol Design (10 Minutes)
-   "How should the client tell the server they want to join a room?"
    -   *Look for*: JSON structure `{"action": "join", "room": "..."}`.
-   "How do we handle invalid JSON or missing fields?"

## Rubric
-   [ ] Implements `rooms` (Dict[ID, Set]).
-   [ ] Implements `client_rooms` (Reverse mapping).
-   [ ] Cleans up empty rooms.
-   [ ] Handles JSON parsing errors gracefully.
