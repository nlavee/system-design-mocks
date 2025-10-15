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
            
            # Update last time
            client_data[1] = now

            # Consume a token if available
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
