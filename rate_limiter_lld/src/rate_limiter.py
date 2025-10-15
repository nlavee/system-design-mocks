from time import sleep
from strategy import RateLimitingStrategy


class RateLimiter:
    def __init__(self,
                 rate_limit_strategy: RateLimitingStrategy):
        self.strategy = rate_limit_strategy

    def is_allowed(self, client_id: str) -> bool:
        return self.strategy.allow_client(client_id)
