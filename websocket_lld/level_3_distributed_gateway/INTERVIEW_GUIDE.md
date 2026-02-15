# Interview Guide: Level 3 Distributed System

## Interviewer Persona
You are a Principal Architect. You are less concerned with syntax and more concerned with system guarantees, race conditions, and scalability patterns.

## Goal
Guide the candidate to mock a Pub/Sub system and use it to bridge multiple server instances.

## Phase 1: System Design (5 Minutes)
Ask:
-   "If we have 100 servers, and User A on Server 1 sends a message to Room X, how do users on Server 99 (also in Room X) get it?"
    -   *Look for*: Pub/Sub (Redis, Kafka, NATS).
-   "Why not just have every server talk to every other server (Full Mesh)?"
    -   *Look for*: O(N^2) connections, complexity, connection limits. Middleware decouples this.

## Phase 2: Implementation (25 Minutes)
Focus on `DistributedServer` class.
1.  **Mocking Pub/Sub**:
    -   Implement `MockRedisPubSub` with `subscribe(channel, callback)` and `publish(channel, msg)`.
    -   Use `asyncio.create_task` to simulate async delivery.
2.  **Wiring it up**:
    -   When `handle_connection` receives a msg -> `pubsub.publish()`.
    -   The server must *also* have a listener `_on_pubsub_message(channel, msg)` that broadcasts to local clients.
    -   CRITICAL: Ensure they don't create an infinite loop (e.g., Server -> PubSub -> Server -> PubSub...).
        -   *Hint*: "If I publish to a channel I am subscribed to, will I get my own message back? Is that okay?" (Yes, usually, but need to handle it or filter by sender ID).

## Phase 3: Optimizations (10 Minutes)
-   **Subscription granularity**:
    -   "Should the server subscribe to *every* active room in the system?"
    -   *Answer*: No, only rooms that have at least 1 local client.
    -   *Implementation check*: `join_room` should only `pubsub.subscribe` if it's the *first* local user in that room. `leave_room` should `pubsub.unsubscribe` if it's the *last* user.

## Rubric
-   [ ] Implements Pub/Sub interface (Mock).
-   [ ] Subscribes to room channels on demand.
-   [ ] Unsubscribes when room is empty (Optimization).
-   [ ] Correctly routes PubSub messages -> Local Websockets.
