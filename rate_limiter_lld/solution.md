# LLD Solution: Rate Limiter

This document summarizes the design and implementation of the Rate Limiter component, including the final code and the discussion on scaling it to a distributed environment.

## 1. Final Code Implementation

The final implementation of the strategies features per-client locking for concurrency and correct, just-in-time logic for state updates.

```python
# /rate_limiter_lld/src/strategy.py

from abc import ABC, abstractmethod
from collections import defaultdict, deque
from threading import Lock
from time import time


class RateLimitingStrategy(ABC):
    """Abstract base class for a rate limiting strategy."""
    @abstractmethod
    def allow_client(self, client_id: str) -> bool:
        pass


class TokenBucketStrategy(RateLimitingStrategy):
    """
    Implements a token bucket algorithm with per-client locking.
    """
    def __init__(self, refill_rate: float, max_capacity: int):
        """
        Initializes the TokenBucketStrategy.
        :param refill_rate: Tokens to add per second.
        :param max_capacity: Maximum number of tokens in the bucket.
        """
        self.refill_rate = refill_rate
        self.max_capacity = max_capacity
        # Each client gets their own data ([tokens, last_time]) and their own Lock
        self.clients = defaultdict(lambda: ([self.max_capacity, time()], Lock()))

    def allow_client(self, client_id: str) -> bool:
        client_data, client_lock = self.clients[client_id]

        with client_lock:
            current_tokens, last_time = client_data
            
            # Refill tokens based on elapsed time
            now = time()
            elapsed = now - last_time
            new_tokens = elapsed * self.refill_rate
            
            current_tokens += new_tokens
            current_tokens = min(current_tokens, self.max_capacity) # Cap the tokens
            
            # Update last time for the next calculation
            client_data[1] = now

            # Consume a token only if available
            if current_tokens >= 1:
                current_tokens -= 1
                client_data[0] = current_tokens
                return True
            else:
                client_data[0] = current_tokens
                return False


class SlidingWindowCounterStrategy(RateLimitingStrategy):
    """
    Implements a sliding window counter algorithm with per-client locking.
    """
    def __init__(self, count_limit: int, time_limit: int):
        """
        Initializes the SlidingWindowCounterStrategy.
        :param count_limit: Max requests per window.
        :param time_limit: Window size in seconds.
        """
        self.count_limit = count_limit
        self.time_limit = time_limit
        # Each client gets their own deque and their own Lock
        self.clients = defaultdict(lambda: (deque(), Lock()))

    def allow_client(self, client_id: str) -> bool:
        client_deque, client_lock = self.clients[client_id]

        with client_lock:
            now = time()
            
            # Remove timestamps older than the time limit
            while client_deque and client_deque[0] <= now - self.time_limit:
                client_deque.popleft()

            # Check if the count exceeds the limit
            if len(client_deque) < self.count_limit:
                client_deque.append(now)
                return True
            else:
                return False
```

## 2. LLD Design Walkthrough

### Strategy Pattern
The design uses the Strategy Pattern to decouple the `RateLimiter` class from the concrete limiting algorithms. This allows us to easily add new algorithms in the future without changing the client-facing code.

### Concurrency Model: Per-Client Locking
- **Initial Problem**: The initial design used a single, global `Lock` for all clients. This was identified as a major performance bottleneck, as it would serialize all requests, regardless of which client they were for.
- **Solution**: The final design implements **fine-grained locking**. The `defaultdict` is configured to create a tuple containing both the client's data structure (a `list` or `deque`) and a unique `Lock` object for that client. When a request comes in, we retrieve the specific lock for that client and only lock the critical section for that single user. This allows requests for different clients to be processed in parallel, making the component scalable on a multi-core machine.

### State Update Logic: Just-in-Time
- **Initial Problem**: An early design considered using a background "janitor" thread to periodically clean up old timestamps or refill tokens.
- **Solution**: We moved this logic inside the `allow_client` method. State is updated "just-in-time" when a request arrives. This is more efficient (no wasted CPU cycles), less complex (no background thread to manage), and more correct as it makes the state check and update an atomic operation within the client's lock.

## 3. Distributed Architecture (The "System Design Edge")

### The Challenge: Global State
To enforce a global rate limit, the state (timestamps or token counts) must be moved from local memory to a centralized data store that is accessible by all servers in the cluster.

- **Solution**: Use a low-latency, in-memory key-value store. **Redis** is the ideal choice.

### Distributed Concurrency: Atomic Operations
- **Problem**: Using simple `GET` and `SET` commands on Redis would create a "read-modify-write" race condition between servers.
- **Solution**: Use Redis's built-in features for atomic operations.
    1.  **Transactions (`MULTI`/`EXEC`)**: Group multiple commands into a single, uninterruptible transaction.
    2.  **Lua Scripting (`EVAL`)**: The preferred method. An entire script containing all the rate-limiting logic is sent to Redis, which guarantees the script is executed atomically. This is more flexible and often more performant.

## 4. Failure Modes & Advanced Bottlenecks

### Redis Failure
- **Decision**: **Fail closed**. If the Redis instance is unavailable, we deny all requests. This prioritizes the stability of our backend services over the availability of the rate-limiting feature.
- **Recovery**: Recovery is automatic. Since the data is transient, when Redis comes back online, the system will start fresh with empty rate limits, effectively healing itself.

### The "Hot Key" Bottleneck
- **Problem**: Even with Redis, if a single `client_id` is extremely active, all requests for that client are serialized to a single key on a single Redis core, creating a new bottleneck.
- **Solution**: Shed load before it hits Redis. We discussed implementing a **local, in-memory pre-filter** on each application server.
- **The Trade-Off**: This solution knowingly sacrifices the strict accuracy of the global limit in exchange for much greater scalability and stability. For example, with a global limit of 1000 and 10 servers, the true effective limit will be higher, but it prevents the central store from being overwhelmed, which is often the correct engineering trade-off.
