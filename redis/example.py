"""
=============================================================================
REDIS PATTERNS IN PYTHON — Staff/Principal Level System Design Reference
=============================================================================

Seven production-grade Redis patterns, each with:
  - Concept overview
  - Python implementation
  - STAFF+ DEEP DIVE: Atomicity, CAP Theorem, Architecture tradeoffs
  - STAFF+ LLD: Implementation of Object-Oriented/SOLID patterns for concurrency
  - Failure modes & edge cases
  - Scaling & clustering considerations
  - Alternatives & tradeoffs

Prerequisites:
    pip install redis hiredis

Redis client setup & Core Constraints:
    - redis-py is the standard Python client
    - hiredis is a C-accelerated parser (~10x faster for bulk reads)
    - DEEP DIVE: Never create ephemeral TCP connections per request (socket exhaustion).
      Always use a persistent ConnectionPool to multiplex logic.
    - DEEP DIVE: Set `socket_timeout` and `socket_connect_timeout` (e.g., 2s). 
      Network partitions are inevitable; failing fast prevents thread starvation 
      cascading to API application layers.
=============================================================================
"""

import json
import math
import time
import uuid
import threading
from contextlib import contextmanager
from typing import Optional

import redis

# ---------------------------------------------------------------------------
# Shared connection pool
# ---------------------------------------------------------------------------
# GOTCHA: Never create a new Redis() client per request in production.
# Each Redis() call without a pool opens a new TCP connection.
# A pool reuses connections, reducing latency and avoiding fd exhaustion.
#
# CLUSTERING NOTE: For Redis Cluster, swap StrictRedis for RedisCluster
# from redis.cluster import RedisCluster. Key routing (hash slots) is then
# handled automatically by the client.

pool = redis.ConnectionPool(
    host="localhost",
    port=6379,
    db=0,
    max_connections=50,          # tune per service; default is unlimited
    decode_responses=True,       # return str instead of bytes
    socket_connect_timeout=1,    # fail fast on network partition
    socket_timeout=1,            # read/write timeout per command
)

def get_client() -> redis.Redis:
    return redis.Redis(connection_pool=pool)


# =============================================================================
# 1. REDIS AS A CACHE
# =============================================================================
#
# OVERVIEW & STAFF+ DEEP DIVE
# ---------------------------
# Redis is an in-memory store making the CAP tradeoff of yielding strong consistency 
# for extreme High Availability (AP) and high-throughput sub-millisecond latencies.
#
# PATTERNS
#   Cache-Aside (Lazy Loading): app checks cache → on miss, reads DB → writes
#     to cache. Most common. Subject to stale data windows.
#   Write-Through: every DB write also writes to cache. Higher write latency.
#   Write-Behind (Write-Back): writes go to cache first; async worker flushes. 
#     Fastest writes but massive data-loss risk.
#   Negative Caching (STAFF+): Crucial to prevent DDoS. Always cache `None` / empty 
#     values with short TTLs to prevent "cache miss attacks" dropping the DB.
#
# EVICTION POLICIES
#   noeviction      – writes fail when memory is full (safest, bad for caches)
#   allkeys-lru     – evict least-recently-used key
#   allkeys-lfu     – evict least-frequently-used. Mathematically vastly superior 
#                     for Zipfian/Pareto traffic distributions common in consumer apps.
#
# FAILURE MODES: THUNDERING HERD (CACHE STAMPEDE)
#   When a highly popular key (e.g. live game score) expires, thousands of threads
#   miss the cache simultaneously and slam the underlying database.
#   - Mitigation 1 (PER): Probabilistic Early Recomputation. Threads randomize 
#     early background refreshing BEFORE the hard TTL expires.
#   - Mitigation 2 (Async Lock): Only a single thread acquires a distributed lock 
#     to fetch the value, others wait or serve stale data.
#
# SCALING
#   - Horizontal sharding via Hash Slots (16384 slots).
#   - Always wrap core interactions in Interfaces (Dependency Inversion Principle) 
#     to cleanly decouple domain logic (e.g. Cache Strategy vs DB execution).

CACHE_TTL = 300  # seconds


def get_user(user_id: int) -> dict:
    """Cache-Aside pattern for a user object."""
    r = get_client()
    cache_key = f"user:{user_id}"

    # 1. Check cache
    cached = r.get(cache_key)
    if cached:
        return json.loads(cached)

    # 2. Cache miss — fetch from DB (simulated here)
    user = _fetch_user_from_db(user_id)
    if user is None:
        # GOTCHA: Cache negative results to prevent DB hammering for
        # non-existent keys. Use a short TTL so deletes eventually propagate.
        r.set(cache_key, json.dumps({}), ex=30)
        return {}

    # 3. Populate cache
    # GOTCHA: Use SET with EX atomically. Never do SET then EXPIRE — a crash
    # between the two leaves a key with no TTL (memory leak).
    r.set(cache_key, json.dumps(user), ex=CACHE_TTL)
    return user


def invalidate_user(user_id: int) -> None:
    """Called after a DB write to keep cache consistent."""
    r = get_client()
    r.delete(f"user:{user_id}")


def get_user_with_stampede_protection(user_id: int) -> dict:
    """
    Probabilistic Early Recomputation (PER) to prevent thundering herd.
    Instead of letting all threads miss at T=0, each thread independently
    decides to re-fetch early based on remaining TTL and a random factor.
    """
    r = get_client()
    cache_key = f"user:per:{user_id}"
    beta = 1.0  # higher = more eager recomputation; tune per use case

    cached = r.get(cache_key)
    ttl = r.ttl(cache_key)

    if cached and ttl > 0:
        # PER formula: recompute if (-beta * ln(random())) > remaining TTL
        import random
        if -beta * math.log(random.random()) < ttl:
            return json.loads(cached)  # serve from cache

    # Recompute (either expired or PER decided to refresh early)
    user = _fetch_user_from_db(user_id)
    r.set(cache_key, json.dumps(user), ex=CACHE_TTL)
    return user


def _fetch_user_from_db(user_id: int) -> Optional[dict]:
    """Stub: replace with your ORM / DB call."""
    if user_id <= 0:
        return None
    return {"id": user_id, "name": f"User {user_id}", "email": f"u{user_id}@example.com"}


# --- STAFF+ LLD: Object-Oriented Cache Pattern (SRP & Dependency Inversion) ---
from typing import Protocol, Optional

class IUserRepository(Protocol):
    """Dependency Inversion: Decouples reading logic from the specific DB."""
    def get_by_id(self, user_id: int) -> Optional[dict]: ...

class MockPostgresRepository:
    def get_by_id(self, user_id: int) -> Optional[dict]:
        import time
        time.sleep(0.05) # Simulated latency
        if user_id <= 0: return None
        return {"id": user_id, "name": f"User {user_id}", "status": "active"}

class RedisCacheStrategy:
    """SRP: Responsible exclusively for cache I/O and Stampede protection."""
    def __init__(self, db_repo: IUserRepository):
        self.db = db_repo
        self.r = get_client()

    def get_user_with_stampede_protection(self, user_id: int) -> dict:
        cache_key = f"user:per:{user_id}"
        beta = 1.0  

        cached = self.r.get(cache_key)
        ttl = self.r.ttl(cache_key)

        if cached and ttl > 0:
            import random
            # PER Mathematical Proof: Intercept TTL with log probability
            if -beta * math.log(random.random()) < ttl:
                return json.loads(cached) 

        user = self.db.get_by_id(user_id)
        if user is None:
            self.r.set(cache_key, json.dumps({}), ex=30)
            return {}

        self.r.set(cache_key, json.dumps(user), ex=CACHE_TTL)
        return user
# ------------------------------------------------------------------------------



# =============================================================================
# 2. REDIS AS A DISTRIBUTED LOCK
# =============================================================================
#
# OVERVIEW & STAFF+ DEEP DIVE
# ---------------------------
# Locks synchronize state mutation across multiple independently scaled stateless 
# servers. Redis achieves this via atomic `SET key val NX PX ttl`.
#
# STAFF+ THE FENCING TOKEN PROBLEM (Crucial L6 Concept)
#   Even a correct Redis lock cannot prevent a slow process from corrupting data.
#     1. Process A acquires lock, gets generic UUID token.
#     2. Process A enters 15-second JVM GC pause, pausing execution.
#     3. Lock TTL expires in Redis natively.
#     4. Process B trivially acquires the lock and writes to DB safely.
#     5. Process A wakes up out of GC and concurrently writes to DB, destroying B's work.
#   Fix: Use Monotonically increasing FENCING TOKENS. The lock authority generates 
#   an integer (`INCR seq`), and the underlying persistence layer (e.g. Postgres OCC,
#   Delta Lake) rejects writes with an older token.
#
# ALGORITHM & CAP THEOREM TRADEOFFS
#   Redlock aims to provide fault tolerance acquiring a lock across majority 
#   quorums (N=5 nodes). 
#   - System theorists criticize Redlock's dependency on synchronous clock assumptions.
#   - For absolute CP (Consistency/Partition Tolerance) correctness, architects 
#     must use ZooKeeper (ZAB protocol) or etcd (Raft) instead of Redis for locking.
#
# ATOMICITY
#   Releasing inherently requires checking identity AND deleting atomically via Lua. 
#   If broken into two steps, it suffers from severe Time-of-check to time-of-use (TOCTOU) bugs.

LOCK_TTL_MS = 10_000  # 10 seconds


@contextmanager
def redis_lock(lock_name: str, ttl_ms: int = LOCK_TTL_MS):
    """
    Acquire a Redis lock for the duration of the with-block.
    Raises RuntimeError if lock cannot be acquired.
    """
    r = get_client()
    token = str(uuid.uuid4())  # unique per acquisition to prevent foreign release
    key = f"lock:{lock_name}"

    # Atomic acquire: SET key token NX PX ttl
    acquired = r.set(key, token, nx=True, px=ttl_ms)
    if not acquired:
        raise RuntimeError(f"Could not acquire lock '{lock_name}'")

    # Lua script for atomic release: only delete if WE own the lock.
    # GOTCHA: If you just do DEL without checking, you might release a lock
    # that another process legitimately acquired after your TTL expired.
    release_script = """
        if redis.call("GET", KEYS[1]) == ARGV[1] then
            return redis.call("DEL", KEYS[1])
        else
            return 0
        end
    """
    try:
        yield token
    finally:
        r.eval(release_script, 1, key, token)


@contextmanager
def redis_lock_with_watchdog(lock_name: str, ttl_ms: int = LOCK_TTL_MS):
    """
    Lock with an auto-extending watchdog thread.
    Prevents expiry if work takes longer than expected.
    The watchdog extends the TTL at ttl/3 intervals.
    """
    r = get_client()
    token = str(uuid.uuid4())
    key = f"lock:{lock_name}"
    stop_event = threading.Event()

    acquired = r.set(key, token, nx=True, px=ttl_ms)
    if not acquired:
        raise RuntimeError(f"Could not acquire lock '{lock_name}'")

    extend_script = """
        if redis.call("GET", KEYS[1]) == ARGV[1] then
            return redis.call("PEXPIRE", KEYS[1], ARGV[2])
        else
            return 0
        end
    """

    def watchdog():
        interval = (ttl_ms / 1000) / 3  # extend at 1/3 of TTL
        while not stop_event.wait(timeout=interval):
            result = r.eval(extend_script, 1, key, token, ttl_ms)
            if result == 0:
                break  # lock was lost (e.g., Redis restarted), stop extending

    watcher = threading.Thread(target=watchdog, daemon=True)
    watcher.start()

    release_script = """
        if redis.call("GET", KEYS[1]) == ARGV[1] then
            return redis.call("DEL", KEYS[1])
        else
            return 0
        end
    """
    try:
        yield token
    finally:
        stop_event.set()
        r.eval(release_script, 1, key, token)


def demo_distributed_lock():
    """Example: only one worker processes a job at a time."""
    try:
        with redis_lock("job:invoice:42", ttl_ms=5000):
            print("Lock acquired — processing invoice 42")
            time.sleep(0.1)  # simulate work
            print("Done — lock will be released on context exit")
    except RuntimeError as e:
        print(f"Another worker is already processing this job: {e}")


# --- STAFF+ LLD: Fencing Token Integration Pattern ---
from typing import Generator

@contextmanager
def distributed_lock_with_fencing(lock_name: str, ttl_ms: int = LOCK_TTL_MS) -> Generator[str, None, None]:
    """
    Acquire a Redis lock and yield a globally distributed UNIQUE/MONOTONIC token.
    
    STAFF+ DEEP DIVE: Why INCR instead of UUID?
    A standard lock uses a random UUID just to ensure the process that acquired the 
    lock is the one releasing it. But a UUID cannot protect the UNDERLYING DATABASE.
    
    FAILURE SCENARIO (The GC Pause):
    1. Worker A acquires UUID lock. It begins processing but hits a 15s JVM GC Pause.
    2. Redis lock TTL expires natively (e.g. 10s).
    3. Worker B acquires the lock with a new UUID and safely writes to the DB.
    4. Worker A wakes up. Unaware its lock expired, it writes its payload to the DB,
       silently overwriting/corrupting Worker B's transaction!
       
    THE FIX: FENCING TOKENS
    By replacing the UUID with `r.incr()`, we generate a strictly monotonic integer 
    (1, 2, 3...). The lock yields this integer (the Fencing Token) to the caller.
    The caller passes this token into its Database transaction (Optimistic Concurrency Control):
      `UPDATE accounts SET balance=..., last_token=35 WHERE id=1 AND last_token < 35`
      
    Now, when Worker A wakes up and attempts to write with `last_token=34`, the 
    database natively rejects the write. We have decoupled system safety from Clock/TTL drift!
    """
    r = get_client()
    lock_key = f"lock:{lock_name}"
    
    # 1. Monotonically increasing Identity via atomic INCR (Fencing Token).
    # Provides sequential integrity for OCC underlying datastores.
    # Note: the namespace seq:fencing_tokens acts as our global lock sequence.
    token = str(r.incr(f"seq:fencing_tokens")) 

    acquired = r.set(lock_key, token, nx=True, px=ttl_ms)
    if not acquired:
        raise RuntimeError(f"Could not acquire lock '{lock_name}' - Resource Busy")

    release_script = """
        if redis.call("GET", KEYS[1]) == ARGV[1] then
            return redis.call("DEL", KEYS[1])
        else
            return 0
        end
    """
    try:
        # Yield the fencing token to the caller to append to their OCC DB transaction
        yield token
    finally:
        r.eval(release_script, 1, lock_key, token)
# ------------------------------------------------------------------------------



# =============================================================================
# 3. REDIS FOR LEADERBOARDS
# =============================================================================
#
# OVERVIEW
# --------
# Redis Sorted Sets (ZSET) are the ideal data structure for leaderboards.
# Internally a skip list + hash table. Every member has a floating-point score.
#
# KEY COMMANDS
#   ZADD key score member      – O(log N) insert or update
#   ZRANK key member           – O(log N) rank (0-indexed, ascending)
#   ZREVRANK key member        – O(log N) rank (0-indexed, descending / top-1 = 0)
#   ZRANGE key start stop WITHSCORES REV – O(log N + M) range query
#   ZINCRBY key delta member   – O(log N) atomic increment
#
# ATOMICITY
#   ZINCRBY is atomic — safe for concurrent score updates from multiple workers.
#
# FAILURE MODES
#   - Score precision: scores are IEEE 754 doubles. Safe for integers up to
#     2^53. For exact large integers, encode rank differently.
#   - Tie-breaking: members with equal scores are sorted lexicographically.
#     For true insertion-order ties, encode a tiebreaker in the score:
#       score = points * 1e12 + (MAX_TS - timestamp)  # higher points win; earlier time wins on tie
#   - Memory: each entry ≈ 64 bytes overhead. 10M users ≈ 640MB — plan ahead.
#
# SCALING
#   - For global leaderboards > 100M entries, shard by user segment (e.g., by
#     country or cohort) and merge top-K on read (union via ZUNIONSTORE).
#   - Weekly/monthly boards: use separate keys per time window. Archive and
#     delete old keys with EXPIRE or a cron job.
#   - ZUNIONSTORE / ZINTERSTORE let you combine multiple boards atomically.
#
# ALTERNATIVES
#   - Postgres with RANK() window function: correct, but full table scan
#     without a btree index on score. Works for < 1M rows.
#   - Cassandra: poor fit — no native sorted set; requires secondary indexes.
#   - Elasticsearch: supports ranked scoring but overkill for a simple counter.

LEADERBOARD_KEY = "leaderboard:global"


def update_score(user_id: str, delta: float) -> float:
    """Atomically increment a user's score. Returns new score."""
    r = get_client()
    return r.zincrby(LEADERBOARD_KEY, delta, user_id)


def get_top_n(n: int = 10) -> list[dict]:
    """Return the top-N players with scores, rank 1 = highest."""
    r = get_client()
    # ZRANGE with REV=True returns highest scores first (Redis 6.2+)
    results = r.zrange(LEADERBOARD_KEY, 0, n - 1, desc=True, withscores=True)
    return [
        {"rank": i + 1, "user_id": member, "score": score}
        for i, (member, score) in enumerate(results)
    ]


def get_user_rank(user_id: str) -> Optional[dict]:
    """Return a user's rank and score. Returns None if not on board."""
    r = get_client()
    # Pipeline two commands to avoid a round-trip for each
    pipe = r.pipeline(transaction=False)
    pipe.zrevrank(LEADERBOARD_KEY, user_id)
    pipe.zscore(LEADERBOARD_KEY, user_id)
    rank, score = pipe.execute()

    if rank is None:
        return None
    return {"rank": rank + 1, "score": score, "user_id": user_id}


def get_surrounding_players(user_id: str, window: int = 2) -> list[dict]:
    """Return the players ranked above and below a given user (contextual rank)."""
    r = get_client()
    rank = r.zrevrank(LEADERBOARD_KEY, user_id)
    if rank is None:
        return []

    start = max(0, rank - window)
    stop = rank + window

    results = r.zrange(LEADERBOARD_KEY, start, stop, desc=True, withscores=True)
    return [
        {"rank": start + i + 1, "user_id": member, "score": score}
        for i, (member, score) in enumerate(results)
    ]




# --- STAFF+ LLD: Object-Oriented Chronologically Fair Score Pattern ---
class LeaderboardManager:
    """SRP: Handles only the ranking domain logic."""
    def __init__(self):
        self.r = get_client()

    def update_score_chronologically_fair(self, user_id: str, points: int) -> float:
        """
        Embeds the inverse Epoch timestamp into the decimal space of the score.
        If Alice and Bob both have 5000 points, whoever achieved it EARLIER wins
        (unlike arbitrary lexicographical sort).
        """
        MAX_TIMESTAMP = 9999999999  # high ceiling
        fairness_decimal = (MAX_TIMESTAMP - time.time()) / MAX_TIMESTAMP
        compound_score = points + fairness_decimal
        
        self.r.zadd(LEADERBOARD_KEY, {user_id: compound_score})
        return compound_score
# ------------------------------------------------------------------------------

def demo_leaderboard():
    r = get_client()
    r.delete(LEADERBOARD_KEY)

    # Seed some scores
    scores = {"alice": 1500, "bob": 2200, "carol": 1800, "dave": 2200, "eve": 900}
    for user, score in scores.items():
        r.zadd(LEADERBOARD_KEY, {user: score})

    print("Top 3:", get_top_n(3))
    print("Alice rank:", get_user_rank("alice"))
    print("Bob surrounding:", get_surrounding_players("bob", window=1))

    # Tie-breaking: bob and dave both have 2200 → Redis sorts lexicographically
    # In production, encode: score = points * 1e9 + (MAX_TS - event_ts)


# =============================================================================
# 4. REDIS FOR RATE LIMITING
# =============================================================================
#
# OVERVIEW
# --------
# Rate limiting protects services from abuse and enforces fair usage.
# Three common algorithms:
#
#   Fixed Window Counter
#     Bucket per time window (e.g., minute). Simple but allows 2x burst at
#     window edges (last second of window N + first second of window N+1).
#
#   Sliding Window Log
#     Store every request timestamp in a sorted set; count entries in the last
#     T seconds. Exact but O(N) memory per user (N = requests in window).
#
#   Sliding Window Counter (hybrid — recommended)
#     Approximate sliding window using two fixed-window counters weighted by
#     the overlap fraction. O(1) memory, ~0.1% error in practice.
#
#   Token Bucket / Leaky Bucket
#     Allow bursting up to bucket capacity; tokens refill at a fixed rate.
#     Best for bursty-but-average-bounded traffic. Harder to implement
#     atomically in Redis without Lua.
#
# ATOMICITY
#   ALL check-and-increment operations MUST be atomic. Without atomicity,
#   two concurrent requests can both read count=99, both increment to 100,
#   and both get approved — exceeding the limit.
#   Use Lua scripts (eval) or pipelines with WATCH (optimistic locking).
#
# FAILURE MODES
#   - Redis unavailable: fail open (allow requests) or fail closed (block all).
#     Fail open is typical for rate limiters — prefer availability over strict
#     limiting. Track Redis errors and alert.
#   - Clock skew across app servers: use Redis server time (TIME command) as
#     the authoritative clock, not the application server clock.
#   - Key explosion: per-user + per-endpoint keys can number in the millions.
#     Set short TTLs; use SCAN to audit if needed.
#
# SCALING
#   - In Redis Cluster, a user's rate limit key must land on the same slot.
#     Use hash tags: {user:42}:ratelimit to pin all keys for user 42 to one slot.
#   - For global rate limits across regions, use a central Redis or accept
#     eventual consistency with per-region limits that sum to the global quota.
#
# ALTERNATIVES
#   - Nginx / Envoy rate limiting: handled at the proxy layer; no app code.
#   - Kafka consumer lag as a back-pressure mechanism.
#   - Token bucket in local memory with periodic Redis sync (approximate, fast).

RATE_LIMIT_WINDOW_SEC = 60
RATE_LIMIT_MAX = 100


def is_rate_limited_fixed_window(user_id: str, limit: int = RATE_LIMIT_MAX,
                                  window_sec: int = RATE_LIMIT_WINDOW_SEC) -> bool:
    """
    Fixed window counter using INCR + EXPIRE.
    Atomic: INCR is a single command; EXPIRE set on first request only.
    """
    r = get_client()
    # Use integer division to bucket into windows
    window_key = f"rl:fixed:{user_id}:{int(time.time()) // window_sec}"

    # Lua script ensures INCR and conditional EXPIRE are atomic
    lua_script = """
        local count = redis.call("INCR", KEYS[1])
        if count == 1 then
            redis.call("EXPIRE", KEYS[1], ARGV[1])
        end
        return count
    """
    count = r.eval(lua_script, 1, window_key, window_sec)
    return count > limit


def is_rate_limited_sliding_window(user_id: str, limit: int = RATE_LIMIT_MAX,
                                    window_sec: int = RATE_LIMIT_WINDOW_SEC) -> bool:
    """
    Sliding window log using Sorted Set of timestamps.
    Exact but O(N) memory where N = requests in window per user.
    """
    r = get_client()
    key = f"rl:sliding:{user_id}"
    now = time.time()
    window_start = now - window_sec

    lua_script = """
        local key = KEYS[1]
        local now = tonumber(ARGV[1])
        local window_start = tonumber(ARGV[2])
        local limit = tonumber(ARGV[3])
        local window_sec = tonumber(ARGV[4])

        -- Remove timestamps outside the window
        redis.call("ZREMRANGEBYSCORE", key, "-inf", window_start)

        -- Count current requests in window
        local count = redis.call("ZCARD", key)

        if count < limit then
            -- Admit: add this request's timestamp as both score and member
            redis.call("ZADD", key, now, now)
            redis.call("EXPIRE", key, window_sec + 1)
            return 0  -- not limited
        else
            return 1  -- limited
        end
    """
    result = r.eval(lua_script, 1, key, now, window_start, limit, window_sec)
    return result == 1


def is_rate_limited_token_bucket(user_id: str, capacity: int = 10,
                                   refill_rate: float = 1.0) -> bool:
    """
    Token bucket via Lua: capacity tokens max, refill_rate tokens/second.
    Allows short bursts up to 'capacity' while enforcing average rate.
    """
    r = get_client()
    key = f"rl:token:{user_id}"
    now = time.time()

    lua_script = """
        local key = KEYS[1]
        local now = tonumber(ARGV[1])
        local capacity = tonumber(ARGV[2])
        local refill_rate = tonumber(ARGV[3])

        local data = redis.call("HMGET", key, "tokens", "last_refill")
        local tokens = tonumber(data[1]) or capacity
        local last_refill = tonumber(data[2]) or now

        -- Refill tokens based on elapsed time
        local elapsed = now - last_refill
        tokens = math.min(capacity, tokens + elapsed * refill_rate)

        if tokens >= 1 then
            tokens = tokens - 1
            redis.call("HMSET", key, "tokens", tokens, "last_refill", now)
            redis.call("EXPIRE", key, math.ceil(capacity / refill_rate) + 1)
            return 0  -- allowed
        else
            return 1  -- rate limited
        end
    """
    result = r.eval(lua_script, 1, key, now, capacity, refill_rate)
    return result == 1




# --- STAFF+ LLD: Object-Oriented Token Bucket Pattern ---
class IRateLimiterStrategy(Protocol):
    def is_allowed(self, user_id: str, limit: int, window: int) -> bool: ...

class TokenBucketRateLimiter:
    """
    Token Bucket algorithm ensuring constant memory per user O(1).
    Allows short bursts up to capacity while enforcing mathematical average.
    """
    def __init__(self):
        self.r = get_client()
        # LUA script evaluated and cached inside Redis Engine
        self.script = self.r.register_script("""
            local key = KEYS[1]
            local capacity = tonumber(ARGV[1])
            local refill_rate = tonumber(ARGV[2])
            local now = tonumber(ARGV[3])

            local bucket = redis.call("HMGET", key, "tokens", "last_update")
            local tokens = tonumber(bucket[1]) or capacity
            local last_update = tonumber(bucket[2]) or now

            local elapsed = math.max(0, now - last_update)
            tokens = math.min(capacity, tokens + (elapsed * refill_rate))

            if tokens >= 1 then
                tokens = tokens - 1
                redis.call("HMSET", key, "tokens", tokens, "last_update", now)
                redis.call("EXPIRE", key, math.ceil(capacity / refill_rate) + 2)
                return 1 -- Authorized
            end
            return 0 -- Rejected
        """)

    def is_allowed(self, user_id: str, capacity: int = 10, refill_per_sec: float = 1.0) -> bool:
        result = self.script(keys=[f"rl:token:{user_id}"], args=[capacity, refill_per_sec, time.time()])
        return result == 1
# ------------------------------------------------------------------------------

def demo_rate_limiting():
    user = "user:demo"
    blocked = 0
    for i in range(115):
        if is_rate_limited_sliding_window(user, limit=100, window_sec=60):
            blocked += 1
    print(f"Blocked {blocked}/115 requests (expect ~15)")


# =============================================================================
# 5. REDIS FOR PROXIMITY SEARCH (Geospatial)
# =============================================================================
#
# OVERVIEW
# --------
# Redis Geo commands store lat/lon pairs as 52-bit geohash scores in a
# Sorted Set. This lets you query "all members within X km of a point"
# efficiently using the geohash approximation.
#
# KEY COMMANDS
#   GEOADD key lon lat member     – add/update a location
#   GEODIST key m1 m2 [unit]      – distance between two members
#   GEOPOS key member             – retrieve stored lon/lat
#   GEOSEARCH key FROMMEMBER/FROMLONLAT BYRADIUS/BYBOX ...  (Redis 6.2+)
#
# ACCURACY
#   Geohash has ~0.6m precision at the equator. Sufficient for most proximity
#   apps (ride-share, food delivery) but not centimeter-precision surveying.
#
# FAILURE MODES
#   - Stale locations: driver locations must be updated frequently (every 5s
#     for a ride-share). Old positions yield wrong matches. Use TTL on a
#     separate "active drivers" key, not on individual geo members.
#   - Large radius queries return O(N) results. Always use COUNT to cap results.
#   - Polar distortion: geohash cells near poles are distorted. Fine for most
#     use cases; note for global apps.
#
# SCALING
#   - Shard by city/region: "geo:drivers:SF", "geo:drivers:NYC". A driver
#     query only hits one shard. Re-sharding when a city grows is manual.
#   - For global at-scale (Uber/Lyft), H3 hexagonal hierarchical grid is more
#     sophisticated — but Redis Geo is excellent up to millions of members per key.
#
# ALTERNATIVES
#   - PostGIS (Postgres extension): full spatial SQL, polygon queries, road
#     network distances. Much more powerful but higher latency.
#   - Elasticsearch geo_point: good for combined geo + text search.
#   - S2 Geometry (Google): hierarchical spatial indexing, used by Google Maps.

GEO_KEY = "geo:drivers"


def add_driver_location(driver_id: str, lon: float, lat: float) -> None:
    """Register or update a driver's location."""
    r = get_client()
    r.geoadd(GEO_KEY, (lon, lat, driver_id))


def find_nearby_drivers(lon: float, lat: float, radius_km: float = 5.0,
                         count: int = 10) -> list[dict]:
    """Return up to `count` nearest drivers within `radius_km`."""
    r = get_client()
    # GEOSEARCH: Redis 6.2+. For older Redis use GEORADIUS (deprecated).
    results = r.geosearch(
        GEO_KEY,
        longitude=lon,
        latitude=lat,
        radius=radius_km,
        unit="km",
        sort="ASC",       # nearest first
        count=count,
        withcoord=True,
        withdist=True,
    )
    return [
        {
            "driver_id": member,
            "distance_km": round(dist, 3),
            "longitude": coord[0],
            "latitude": coord[1],
        }
        for member, dist, coord in results
    ]


def demo_proximity():
    r = get_client()
    r.delete(GEO_KEY)

    # San Francisco area drivers
    drivers = {
        "driver:1": (-122.4194, 37.7749),   # SF center
        "driver:2": (-122.4094, 37.7849),   # 1.2 km away
        "driver:3": (-122.2712, 37.8044),   # Oakland, ~14 km
        "driver:4": (-122.4312, 37.7549),   # 2.5 km away
    }
    for driver_id, (lon, lat) in drivers.items():
        add_driver_location(driver_id, lon, lat)

    nearby = find_nearby_drivers(-122.4194, 37.7749, radius_km=5.0)
    print("Drivers within 5km of SF center:")
    for d in nearby:
        print(f"  {d['driver_id']}: {d['distance_km']} km")


# =============================================================================
# 6. REDIS FOR EVENT SOURCING (Streams)
# =============================================================================
#
# OVERVIEW
# --------
# Redis Streams (XADD/XREAD) are an append-only log, similar to Kafka but
# embedded in Redis. Each entry is an auto-ID'd (timestamp-seq) map of fields.
#
# KEY CONCEPTS
#   Producer: XADD stream * field1 val1 field2 val2
#   Consumer: XREAD COUNT N BLOCK ms STREAMS stream last_id
#   Consumer Group: multiple consumers share the stream; each message delivered
#     to exactly one consumer in the group (competing consumers pattern).
#   ACK: XACK stream group message_id — marks message as processed.
#   Pending Entries List (PEL): unacknowledged messages that can be
#     reclaimed by another consumer if the original consumer crashes.
#
# ATOMICITY & DELIVERY GUARANTEES
#   At-least-once delivery within a consumer group (re-delivered if not ACK'd).
#   Idempotent consumers are REQUIRED — use the message ID as an idempotency key.
#
# FAILURE MODES
#   - Consumer crash: PEL holds messages; another consumer calls XAUTOCLAIM
#     (Redis 7+) or XCLAIM to take ownership after a timeout.
#   - Stream grows unboundedly: use MAXLEN ~ option to cap stream size.
#     MAXLEN ~ (approximate trimming) is much faster than exact trimming.
#   - Message ordering: guaranteed within a single stream shard; not across
#     multiple streams.
#
# SCALING
#   - Single Redis stream is single-threaded; throughput ~100K msg/sec.
#   - For higher throughput, partition into multiple streams:
#     stream:events:0, stream:events:1 ... (hash user_id % N).
#   - Redis Cluster doesn't natively "stripe" a stream — partitioning is manual.
#
# ALTERNATIVES vs KAFKA
#   Redis Streams   : low latency (sub-ms), in-memory, simpler ops.
#                     Max retention limited by RAM; no built-in replication lag.
#   Kafka           : durable, disk-backed, multi-TB retention, replay from any
#                     offset, exactly-once with transactions (Kafka ≥ 0.11).
#   Use Redis when  : you need fast event bus with moderate retention.
#   Use Kafka when  : you need durable event log, replay, large-scale analytics.
#
# INTERVIEW TIP: Redis Streams vs Pub/Sub:
#   Pub/Sub is fire-and-forget. If a subscriber is offline, messages are lost.
#   Streams persist messages and support consumer groups — use Streams for
#   reliable messaging, Pub/Sub only for ephemeral notifications.

STREAM_KEY = "stream:orders"
CONSUMER_GROUP = "order-processors"
CONSUMER_NAME = f"worker:{uuid.uuid4().hex[:8]}"


def produce_event(event_type: str, payload: dict) -> str:
    """Append an event to the stream. Returns the auto-generated message ID."""
    r = get_client()
    message_id = r.xadd(
        STREAM_KEY,
        {"event_type": event_type, "payload": json.dumps(payload), "ts": time.time()},
        maxlen=100_000,   # approximate trim: keep last ~100K messages
        approximate=True,
    )
    return message_id


def create_consumer_group() -> None:
    """Create the consumer group (idempotent — safe to call on startup)."""
    r = get_client()
    try:
        # "$" means start from new messages only; "0" would replay all history
        r.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="$", mkstream=True)
    except redis.exceptions.ResponseError as e:
        if "BUSYGROUP" in str(e):
            pass  # group already exists — that's fine
        else:
            raise


def consume_events(count: int = 10, block_ms: int = 2000) -> None:
    """
    Consume and process events from the stream.
    Demonstrates: read → process → ACK pattern.
    """
    r = get_client()

    # ">" means: give me new, undelivered messages
    messages = r.xreadgroup(
        CONSUMER_GROUP,
        CONSUMER_NAME,
        {STREAM_KEY: ">"},
        count=count,
        block=block_ms,
    )

    if not messages:
        return

    for stream_name, entries in messages:
        for message_id, fields in entries:
            try:
                _process_event(fields)
                # ACK only after successful processing
                r.xack(STREAM_KEY, CONSUMER_GROUP, message_id)
            except Exception as e:
                # Don't ACK — message stays in PEL for retry / dead-letter
                print(f"Failed to process {message_id}: {e}")


def reclaim_stale_messages(idle_ms: int = 30_000) -> None:
    """
    Reclaim messages that have been pending > idle_ms (e.g., crashed consumer).
    Uses XAUTOCLAIM (Redis 7+).
    """
    r = get_client()
    # XAUTOCLAIM transfers idle PEL entries to this consumer
    result = r.xautoclaim(
        STREAM_KEY, CONSUMER_GROUP, CONSUMER_NAME,
        min_idle_time=idle_ms,
        start_id="0-0",
        count=50,
    )
    # result = (next_start_id, [(id, fields), ...], [deleted_ids])
    _, entries, _ = result
    for message_id, fields in entries:
        try:
            _process_event(fields)
            r.xack(STREAM_KEY, CONSUMER_GROUP, message_id)
        except Exception as e:
            print(f"Reclaim processing failed for {message_id}: {e}")


def _process_event(fields: dict) -> None:
    """Stub: your business logic here. MUST be idempotent."""
    event_type = fields.get("event_type")
    payload = json.loads(fields.get("payload", "{}"))
    print(f"  Processing event: {event_type} — {payload}")



from concurrent.futures import ThreadPoolExecutor

# --- STAFF+ LLD: Object-Oriented Event Sourcing & Concurrency Thread Pools ---
class BoundedStreamConsumer:
    """
    Mandated Concurrent Design Pattern for CPU-heavy tasks.
    Offloads heavy blocking computations into a Bounded Thread Pool.
    """
    def __init__(self, threads: int = 4):
        self.r = get_client()
        self.worker_id = f"worker_node_{uuid.uuid4().hex[:6]}"
        # Bounded thread pool prevents resource exhaustion / thread starvation
        self.pool = ThreadPoolExecutor(max_workers=threads)
        
        try:
            self.r.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="$", mkstream=True)
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP" not in str(e): raise

    def publish_event(self, payload: dict):
        """Publisher defines `MAXLEN ~` to prevent Memory Exhaustion using rough approx."""
        self.r.xadd(STREAM_KEY, {"payload": json.dumps(payload)}, maxlen=50_000, approximate=True)

    def _execute_and_ack(self, message_id: str, field_map: dict):
        """Thread-local transaction sequence."""
        payload = json.loads(field_map["payload"])
        # MANDATE: Enforce idempotency check here before execution!
        print(f"    [THREAD-EXEC] Confirmed order transaction ID {message_id}: {payload}")
        # Acknowledge exactly once payload processing securely completes
        self.r.xack(STREAM_KEY, CONSUMER_GROUP, message_id)

    def consume_once(self):
        """Pull a batch, offload to computing pool."""
        messages = self.r.xreadgroup(
            CONSUMER_GROUP, self.worker_id, {STREAM_KEY: ">"}, count=5, block=2000
        )
        if not messages: return

        for stream, records in messages:
            for message_id, field_map in records:
                self.pool.submit(self._execute_and_ack, message_id, field_map)
# ------------------------------------------------------------------------------

def demo_streams():
    create_consumer_group()
    produce_event("order.placed", {"order_id": "ORD-1", "user_id": "u1", "total": 29.99})
    produce_event("order.placed", {"order_id": "ORD-2", "user_id": "u2", "total": 59.99})
    produce_event("order.cancelled", {"order_id": "ORD-1", "reason": "user request"})
    print("Consuming events:")
    consume_events(count=5, block_ms=100)


# =============================================================================
# 7. REDIS PUB/SUB
# =============================================================================
#
# OVERVIEW
# --------
# Redis Pub/Sub is a broadcast messaging mechanism. Publishers send messages
# to channels; all currently connected subscribers receive them instantly.
# Messages are NOT persisted — if a subscriber is offline, it misses messages.
#
# KEY COMMANDS
#   PUBLISH channel message        – broadcast to all subscribers
#   SUBSCRIBE channel [...]        – subscribe to exact channel(s)
#   PSUBSCRIBE pattern [...]       – subscribe by glob pattern (e.g., "order.*")
#   UNSUBSCRIBE / PUNSUBSCRIBE
#
# DELIVERY GUARANTEES
#   At-most-once. Fire-and-forget. No ACK, no retry, no persistence.
#   If you need reliability, use Streams (pattern 6) instead.
#
# FAILURE MODES
#   - Subscriber offline → message lost (no buffering).
#   - Slow subscriber: Redis doesn't buffer per-subscriber. A slow subscriber
#     that can't keep up will be disconnected (client-output-buffer-limit).
#   - One blocked Pub/Sub connection can't issue other Redis commands.
#     Use a DEDICATED connection for subscriptions (redis-py enforces this).
#
# USE CASES (where at-most-once is acceptable)
#   - Invalidating distributed caches across app servers ("user:42 changed")
#   - Live dashboard / websocket push notifications
#   - Service coordination signals (e.g., "config reloaded")
#   - Chat room messages (with a separate persistence layer for history)
#
# SCALING
#   - Pub/Sub is broadcast across the cluster — all nodes forward PUBLISH.
#     In Redis Cluster, PUBLISH is sent to all shards, not just the hash slot.
#     This creates O(nodes) overhead per PUBLISH. Fine up to ~100 nodes.
#   - For fan-out to millions of subscribers, a dedicated message broker
#     (Kafka, NATS, SNS) scales better than Redis Pub/Sub.
#
# ALTERNATIVES
#   - Redis Streams: durable, consumer groups, replay. Prefer over Pub/Sub
#     for reliability.
#   - NATS: purpose-built for low-latency pub/sub, ~2x throughput of Redis.
#   - Kafka: durable fan-out to many consumer groups.
#   - WebSockets + Redis Pub/Sub: a common pattern where app servers subscribe
#     to Redis channels and fan-out to connected WebSocket clients.

def publish_message(channel: str, payload: dict) -> int:
    """Publish a message. Returns number of subscribers that received it."""
    r = get_client()
    return r.publish(channel, json.dumps(payload))


def subscribe_to_channel(channel: str) -> None:
    """
    Subscribe to a channel and print received messages.
    NOTE: This BLOCKS — run in a separate thread or process.
    The pubsub connection cannot be reused for normal commands.
    """
    r = get_client()
    # get_message() is non-blocking; listen() blocks forever — prefer for daemons
    ps = r.pubsub(ignore_subscribe_messages=True)
    ps.subscribe(channel)

    print(f"Subscribed to '{channel}'. Waiting for messages...")
    try:
        for message in ps.listen():
            if message and message["type"] == "message":
                data = json.loads(message["data"])
                print(f"  Received on '{message['channel']}': {data}")
    except KeyboardInterrupt:
        ps.unsubscribe()


def subscribe_pattern(pattern: str) -> None:
    """Pattern subscription — e.g., 'order.*' matches 'order.placed', 'order.shipped'."""
    r = get_client()
    ps = r.pubsub(ignore_subscribe_messages=True)
    ps.psubscribe(pattern)

    print(f"Pattern-subscribed to '{pattern}'")
    try:
        for message in ps.listen():
            if message and message["type"] == "pmessage":
                data = json.loads(message["data"])
                print(f"  Pattern '{message['pattern']}' matched '{message['channel']}': {data}")
    except KeyboardInterrupt:
        ps.punsubscribe()


def demo_pubsub() -> None:
    """Subscriber runs in a background thread; main thread publishes."""
    channel = "notifications:user:42"

    sub_thread = threading.Thread(
        target=subscribe_to_channel,
        args=(channel,),
        daemon=True,
    )
    sub_thread.start()
    time.sleep(0.2)  # allow subscription to register

    n_received = publish_message(channel, {"type": "like", "from": "user:7", "post_id": "p99"})
    print(f"Published to {n_received} subscriber(s)")
    time.sleep(0.2)  # allow message to be received and printed


# =============================================================================
# CROSS-CUTTING CONCERNS (Staff-Level Discussion Points)
# =============================================================================
#
# PERSISTENCE
#   RDB (snapshotting): point-in-time snapshots at intervals. Fast restart,
#     up to [snapshot interval] seconds of data loss on crash.
#   AOF (Append-Only File): log every write. fsync every second → ~1s data loss.
#     fsync always → ~0 data loss, but ~2x write latency.
#   RDB + AOF: use both for safety; AOF used on restart, RDB for backups.
#   Redis 7.4+ AOFV2: more efficient AOF with periodic compaction.
#
# REPLICATION
#   Primary → Replica(s): async by default. Replica can serve reads.
#   WAIT command: force synchronous replication for critical writes.
#
# HIGH AVAILABILITY
#   Redis Sentinel: automatic failover for primary/replica setup.
#     ~30s failover time; suitable for most use cases.
#   Redis Cluster: built-in sharding + HA. 16384 hash slots across N primaries.
#     Each primary has 1+ replicas. Failover in ~10s.
#   Cluster limitation: multi-key commands (MSET, SUNION) only work if all
#     keys share the same hash slot (use hash tags: {prefix}).
#
# MEMORY MANAGEMENT
#   Redis is single-threaded for command processing (I/O is multi-threaded
#   since Redis 6). A slow Lua script or large KEYS scan blocks all commands.
#   Never use KEYS in production — use SCAN for iterative, non-blocking scans.
#
# OBSERVABILITY
#   INFO memory, INFO stats, INFO replication — essential health metrics.
#   MONITOR: real-time command log (dev only — massive throughput overhead).
#   Redis Slow Log: tracks commands > threshold_ms (SLOWLOG GET).
#   Keyspace notifications: subscribe to events like expired/evicted keys
#   (useful for building TTL-triggered workflows).
#
# SECURITY
#   Enable ACL (Redis 6+) for per-user command and key-pattern restrictions.
#   Enable TLS for in-transit encryption.
#   requirepass for auth (combined with ACL for fine-grained access).
#   Never expose Redis port to the public internet.

# =============================================================================
# DEMO RUNNER
# =============================================================================

if __name__ == "__main__":
    print("\n" + "="*60)
    print("STAFF+ LLD DEMO ACTIVATED")
    print("="*60)
    
    # 1. Staff Cache Demo
    repo = MockPostgresRepository()
    cache = RedisCacheStrategy(repo)
    print("\n[CACHE] PER Stampede Execution:", cache.get_user_with_stampede_protection(256))

    # 2. Staff Lock Demo
    try:
        with distributed_lock_with_fencing("billing_ledger_row_42") as fencing_token:
            print(f"\n[LOCK] Acquired mutually exclusive capability. Fencing Token: {fencing_token}")
    except RuntimeError as e:
        pass

    # 3. Staff Leaderboard Demo
    print("\n[LEADERBOARD] Populating concurrent game states...")
    lb = LeaderboardManager()
    lb.update_score_chronologically_fair("user_101", 1500)
    time.sleep(0.01) # Simulate chronology
    lb.update_score_chronologically_fair("user_202", 1500)
    print("[LEADERBOARD] Fair Chronological rankings:", lb.get_top_n(2))

    # 4. Staff Rate Limiting Demo
    rl = TokenBucketRateLimiter()
    print("\n[RATE] Valid Request:", rl.is_allowed("192.168.1.1", capacity=1))
    print("[RATE] Exhausted:", rl.is_allowed("192.168.1.1", capacity=1))

    # 5. Staff Stream Worker Demo
    print("\n[STREAMS] Validating multi-thread ingestors...")
    daemon = BoundedStreamConsumer(threads=2)
    daemon.publish_event({"type": "payment_approved", "amt": 55})
    daemon.consume_once()


    print("\n" + "="*60)
    print("DEMO: Cache")
    print("="*60)
    user = get_user(1)
    print("Fetched:", user)
    user_cached = get_user(1)
    print("Cached:", user_cached)

    print("\n" + "="*60)
    print("DEMO: Distributed Lock")
    print("="*60)
    demo_distributed_lock()

    print("\n" + "="*60)
    print("DEMO: Leaderboard")
    print("="*60)
    demo_leaderboard()

    print("\n" + "="*60)
    print("DEMO: Rate Limiting")
    print("="*60)
    demo_rate_limiting()

    print("\n" + "="*60)
    print("DEMO: Proximity Search")
    print("="*60)
    demo_proximity()

    print("\n" + "="*60)
    print("DEMO: Streams (Event Sourcing)")
    print("="*60)
    demo_streams()

    print("\n" + "="*60)
    print("DEMO: Pub/Sub")
    print("="*60)
    demo_pubsub()