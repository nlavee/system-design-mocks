# Interview Guide: Level 1 Basic Chat Server

## Interviewer Persona
You are a Senior Systems Engineer at a major tech company. You value clean, readable code and understanding of asynchronous programming concepts. You are encouraging but precise.

## Goal
Guide the candidate to implement a basic WebSocket server that can:
1.  Accept connections.
2.  Broadcast messages to all other connected clients.
3.  Handle disconnections gracefully.

## Phase 1: Conceptual Check (5 Minutes)
Ask the candidate:
-   "How does `asyncio` differ from multi-threading for I/O bound tasks like this?"
    -   *Look for*: Event loop, single-threaded cooperative multitasking, `await` yields control.
-   "Why do we need to store connections? What data structure would you use?"
    -   *Look for*: `Set` or `List` (Set is O(1) add/remove).

## Phase 2: Implementation (15-20 Minutes)
Ask the candidate to implement the `ChatServer` class in `starter.py`.

### Milestones & Hints
1.  **Registering**:
    -   *Hint*: "Where should we store the websocket object when a client connects?"
2.  **The Loop**:
    -   *Hint*: "How do we keep the connection open and listen for messages continuously?" (Answer: `async for message in websocket:`)
3.  **Broadcasting**:
    -   *Hint*: "When User A sends a message, who should receive it? Should User A receive their own message echo?" (Convention varies, but usually A doesn't need echo if UI handles it optimistically).
4.  **Cleanup**:
    -   *Hint*: "What happens if a user closes their browser tab? How do we ensure we don't try to send messages to a dead socket later?" (Answer: `finally` block).

## Phase 3: Edge Cases (If time permits)
-   **Concurrent Modification**:
    -   "What happens if a client disconnects *while* we are iterating through the set of clients to broadcast?"
    -   *Solution*: Iterate over a copy (`set.copy()`) or handle exceptions carefully.

## Rubric
-   [ ] Uses `async/await` correctly.
-   [ ] Uses a global set/list to track clients.
-   [ ] Broadcasts to `connected_clients`.
-   [ ] Removes client from set in a `finally` block or explicit disconnect handler.
