# LLD Challenge: Design a Rate Limiter

## Problem Category: Core Infrastructure Component

## Problem Description

Design a generic rate-limiting component that can be used to control the number of requests a user or service can make within a specified time window. This is a fundamental building block for protecting services from being overwhelmed and ensuring fair resource usage.

### Core Requirements

1.  **Core Functionality:** The component must expose a primary method, `is_allowed(client_id: str) -> bool`, which returns `True` if the request from the client should be processed and `False` if it should be rejected.
2.  **Configurability:** The rate limit (e.g., 100 requests per minute) must be configurable.
3.  **Abstraction:** The specific algorithm used for rate limiting should be interchangeable. The design must be able to support different strategies without requiring changes to the core component that uses the limiter.

### LLD Focus & Evaluation Criteria

*   **Strategy Pattern:** The design must use the **Strategy Pattern** to define an `IRateLimitingStrategy` interface. You should be prepared to discuss and implement at least two concrete strategies:
    *   **Token Bucket:** Each client has a bucket that refills with tokens at a steady rate. A request consumes a token. If the bucket is empty, the request is denied.
    *   **Sliding Window Counter/Log:** The system keeps a log of request timestamps for each client. A request is allowed only if the count of timestamps in the last `N` seconds is below the limit.
*   **Concurrency:** The rate limiter is a classic concurrency problem. It will be accessed by multiple threads simultaneously (representing concurrent requests). Your implementation must be thread-safe. You should be able to justify your choice of synchronization (e.g., a lock per client vs. a global lock).
*   **Data Structures:** The choice of data structures is critical for performance. You should be able to explain the trade-offs of using different structures (e.g., a `deque` or a timestamped list for a sliding window).

### The Databricks Edge: Distributed Rate Limiting at Scale

This is the most critical part of the Staff-level discussion. A single-instance rate limiter is not enough for a large-scale platform.

*   **The Distributed Problem:** How do you enforce a *global* rate limit for a single user when your service is running on a cluster of 100 servers? A request from the same user could land on any server.
*   **Shared State Management:** This requires a centralized, low-latency data store (like Redis or Memcached) to store the counters or token buckets for each client. You must discuss the trade-offs of this approach.
*   **Race Conditions and Consistency:** What happens when two requests for the same user arrive at different servers at nearly the same time? Both servers will read the current count, decide the request is allowed, and then increment the count. This can lead to exceeding the rate limit. How do you solve this? (This leads to a discussion of atomic operations like `INCR` in Redis).
*   **Fault Tolerance:** What is the system's behavior if the central data store becomes unavailable? Should you fail open (allow all requests) or fail closed (deny all requests)? Justify your choice in the context of protecting a critical backend service.
