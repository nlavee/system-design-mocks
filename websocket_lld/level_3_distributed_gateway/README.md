# Level 3: Distributed Scale with Pub/Sub

## Problem Statement
In a real-world scenario (1M+ concurrent users), a single server cannot hold all connections.
You need to scale out to multiple server instances (e.g., behind a Load Balancer).
However, if User A is connected to Server 1 and User B is connected to Server 2, how do they talk?

**Answer**: You need a Pub/Sub mechanism (like Redis Pub/Sub, Kafka, or NATS).

## Core Requirements
1.  **Multiple Server Simulation**: Design a system that supports multiple `GameWebSocketServer` instances running logically.
2.  **Pub/Sub Integration**: When a message is sent to a room, it must be published to the Pub/Sub system.
3.  **Subscription**: Each server instance must subscribe to the rooms its local clients are interested in.
4.  **Graceful Shutdown**: Implement connection draining (notify clients before shutting down).

## Conceptual Focus
-   **Horizontal Scaling**: Stateless vs Stateful tiers.
-   **Pub/Sub Pattern**: Decoupling senders from receivers.
-   **Message Broker**: Redis (mocked here).

## Challenge
1.  Implement the `MockRedisPubSub` class in `starter.py` to simulate a broker.
2.  Update `DistributedServer` to:
    -   Publish messages to the broker instead of just local broadcast.
    -   Listen to the broker for messages from *other* servers and broadcast them locally.

## Diagram
```
[Client A] <-> [Server 1] <---> [Redis Pub/Sub] <---> [Server 2] <-> [Client B]
```
User A says "Hi" -> Server 1 Publishes "Hi" to Channel "Lobby" -> Redis pushes to Server 1 & Server 2 -> Both broadcast locally.
