"""
================================================================================
  SCHEDULED / DELAYED JOB EXECUTION
  Patterns: Redis Sorted Set Delay Queue + Kafka Scheduled Execution
  Interview level: Staff+
================================================================================

  THE CORE PROBLEM
  ────────────────────────────────────────────────────────────────────────────
  A standard job queue delivers jobs as fast as possible (FIFO).
  Scheduled execution means: "hold this job and deliver it at time T."
  That requires a different primitive — a DELAY QUEUE or SCHEDULED QUEUE.

  Neither Kafka nor Redis has a native "execute at time T" mechanism.
  Both require you to architect around the gap. The patterns below are
  the production-grade approaches used at scale.

  TWO FUNDAMENTAL APPROACHES
  ────────────────────────────────────────────────────────────────────────────
  1. POLLING MODEL (Redis Sorted Set):
     - Jobs stored with scheduled_time as sort key
     - A poller wakes up every N seconds, claims jobs where score <= now
     - Worker executes claimed jobs
     - Simple, low latency, well-understood operationally

  2. FORWARDING MODEL (Kafka):
     - Jobs produced to a "scheduled" topic with a target timestamp in the payload
     - A "scheduler" service consumes the topic, buffers jobs in memory
     - At the right time, it forwards the job to the "ready" execution topic
     - Workers consume the "ready" topic and execute
     - More complex, but gives you Kafka's replay and fan-out benefits

  INTERVIEW INSIGHT:
  For pure scheduled job execution, Redis Sorted Set is almost always
  the simpler and better answer. Kafka shines when you need the scheduled
  jobs to be part of a larger event-driven pipeline with replay, fan-out,
  or audit requirements. Know when to use which.
"""

import time
import json
import uuid
import threading
from datetime import datetime, timedelta

import redis

from confluent_kafka import Producer, Consumer


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PATTERN 1: REDIS SORTED SET DELAY QUEUE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
#  HOW SORTED SETS WORK AS A DELAY QUEUE
#  ────────────────────────────────────────────────────────────────────────────
#  Redis Sorted Sets (ZSET) store members with a floating-point SCORE.
#  Members are always sorted by score. This makes them perfect for scheduling:
#    - Score = Unix timestamp of when the job should run
#    - ZADD: enqueue a job with its scheduled time as the score
#    - ZRANGEBYSCORE key 0 <now>: find all jobs due right now
#    - ZREM: remove the job after claiming it (prevents duplicate execution)
#
#  DATA STRUCTURE:
#    sorted_set "scheduled_jobs":
#      member: "<job_json_or_id>"   score: 1699500000.0  (unix timestamp)
#      member: "<job_json_or_id>"   score: 1699500060.0  (1 minute later)
#      member: "<job_json_or_id>"   score: 1699500120.0  (2 minutes later)
#
#  ZRANGEBYSCORE key 0 now() returns all jobs whose score <= now,
#  i.e., all jobs that are due or overdue. This is your "ready to run" set.
#
#  THE RACE CONDITION PROBLEM
#  ────────────────────────────────────────────────────────────────────────────
#  With multiple workers polling the same sorted set, you get a race:
#    Worker A: ZRANGEBYSCORE -> sees job_123
#    Worker B: ZRANGEBYSCORE -> also sees job_123
#    Worker A: ZREM job_123  -> success, executes
#    Worker B: ZREM job_123  -> fails (already removed), skips
#
#  This works correctly IF you use ZRANGEBYSCORE + ZREM atomically.
#  Non-atomic approach (two separate commands) has a window where both
#  workers see the job, both try to ZREM, both succeed in theory... wait,
#  only one ZREM can succeed since Redis is single-threaded. So actually:
#  the worker that wins ZREM gets the job, the other gets "0 removed" and skips.
#
#  BUT: two separate commands still have a tiny window where you do
#  ZRANGEBYSCORE, network stalls, another worker steals the job, your
#  ZREM removes nothing, you don't know you lost the race unless you
#  check the return value of ZREM.
#
#  CORRECT APPROACH: Lua script (atomic) or ZPOPMIN (Redis 5.0+).
#  Lua scripts run atomically on the Redis server — no other command
#  can execute between your ZRANGEBYSCORE and ZREM. This eliminates the race.
#
#  ZPOPMIN (Redis 5.0+): atomically pops the member with the lowest score.
#  But it doesn't let you filter by score <= now easily for batches.
#  The Lua approach is more flexible for claiming multiple jobs at once.
#
#  POLLER INTERVAL TRADEOFF
#  ────────────────────────────────────────────────────────────────────────────
#  Polling every 100ms: low latency (<100ms job start delay), higher Redis load.
#  Polling every 1s: ~1s max delay, much lower Redis load.
#  Polling every 5s: 5s max delay, minimal Redis load.
#
#  For most scheduled job systems, 1-second polling is the right default.
#  Sub-second scheduling accuracy rarely matters for business jobs.
#  If you need millisecond accuracy, you need a different architecture
#  (dedicated timer infrastructure, not a polling model).
#
#  DURABILITY REMINDER
#  ────────────────────────────────────────────────────────────────────────────
#  As discussed: Redis with AOF (appendfsync=always) gives you near-durable
#  storage. For scheduled jobs that MUST run (billing, SLA-sensitive alerts),
#  use AOF + a fallback: also write job metadata to Postgres so you can
#  rebuild the sorted set if Redis is lost. This hybrid approach is common
#  in production systems that need both Redis performance and DB durability.
#
#  INTERVIEW TALKING POINTS
#  ────────────────────────────────────────────────────────────────────────────
#  "For scheduled job execution I'd use a Redis Sorted Set where the score
#  is the Unix timestamp. A poller claims ready jobs using a Lua script for
#  atomicity — that's the key to preventing duplicate execution across
#  multiple worker instances. Polling every second gives you ~1s scheduling
#  accuracy which is fine for most business jobs."
#
#  "For durability I'd enable Redis AOF with appendfsync=everysec and also
#  write the job definition to Postgres in the same transaction as scheduling.
#  If Redis is lost, the scheduler can rebuild the sorted set from Postgres
#  on startup. Belt and suspenders."
#
#  "The limitation of this pattern is that it doesn't give you event replay
#  or audit history. If you need to know 'what jobs ran last Tuesday and what
#  were their payloads', you need Kafka or a job history table."


SCHEDULED_JOBS_KEY  = "scheduled_jobs"    # sorted set: score=run_at timestamp
PROCESSING_JOBS_KEY = "processing_jobs"   # sorted set: score=claimed_at (for timeout detection)
JOB_DATA_PREFIX     = "job:"              # hash: job_id -> full job payload


class RedisScheduler:
    """
    Enqueues jobs with a scheduled execution time.

    Separates the JOB DATA (stored in a Redis Hash) from the SCHEDULING INDEX
    (stored in a Sorted Set). This pattern avoids storing large payloads as
    sorted set members, which are less efficient for large values.

    Data layout:
      ZSET "scheduled_jobs":        job_id -> score=run_at_timestamp
      HASH "job:{job_id}":          {type, payload, run_at, created_at, ...}
    """

    def __init__(self, redis_client: redis.Redis):
        self.r = redis_client

    def schedule(self, job_type: str, payload: dict,
                 run_at: datetime) -> str:
        """
        Schedule a job to run at a specific datetime.

        Returns the job_id, which can be used to cancel or inspect the job.

        WHY store job data in a separate Hash:
        Sorted set members are the sort key + a single string value.
        Storing the full JSON payload as the member works, but makes
        ZRANGEBYSCORE results large and harder to work with.
        Storing just job_id as the member keeps the sorted set lean —
        it's just an index. The actual data lives in a Hash.
        """
        job_id = str(uuid.uuid4())
        run_at_ts = run_at.timestamp()

        job_data = {
            "job_id":     job_id,
            "type":       job_type,
            "payload":    json.dumps(payload),
            "run_at":     run_at_ts,
            "created_at": time.time(),
            "status":     "scheduled",
        }

        pipe = self.r.pipeline()
        # Store full job data in a Hash. TTL = run_at + 7 days (cleanup old jobs).
        pipe.hset(f"{JOB_DATA_PREFIX}{job_id}", mapping=job_data)
        pipe.expireat(f"{JOB_DATA_PREFIX}{job_id}",
                      int(run_at_ts) + 7 * 24 * 3600)
        # Add to the scheduling index. Score = run_at timestamp.
        # ZRANGEBYSCORE 0 <now> will return this job_id once now >= run_at.
        pipe.zadd(SCHEDULED_JOBS_KEY, {job_id: run_at_ts})
        pipe.execute()

        return job_id

    def schedule_in(self, job_type: str, payload: dict,
                    delay: timedelta) -> str:
        """Schedule a job to run after a relative delay from now."""
        return self.schedule(job_type, payload,
                             run_at=datetime.utcnow() + delay)

    def cancel(self, job_id: str) -> bool:
        """
        Cancel a scheduled job before it runs.
        Returns True if the job was found and cancelled, False if already run/missing.

        GOTCHA: there's a small window where a poller has claimed the job_id
        from the sorted set but hasn't started execution yet. In this case,
        ZREM returns 0 (job already removed from index) but the job hasn't
        actually run. You'd need a "claimed" state and worker acknowledgement
        to handle this edge case for critical jobs.
        """
        pipe = self.r.pipeline()
        pipe.zrem(SCHEDULED_JOBS_KEY, job_id)
        pipe.hset(f"{JOB_DATA_PREFIX}{job_id}", "status", "cancelled")
        results = pipe.execute()
        return results[0] == 1  # 1 = job was in the set and removed


# Lua script for atomic claim: find jobs due now, claim up to `count` of them.
# Runs entirely on the Redis server — no other commands execute between
# ZRANGEBYSCORE and ZREM. This eliminates the duplicate execution race condition.
#
# Script logic:
#   1. ZRANGEBYSCORE: get up to `count` job_ids with score (run_at) <= now
#   2. If none found: return empty list
#   3. ZREM: atomically remove claimed job_ids from the scheduled set
#   4. Return claimed job_ids
#
# Why Lua and not a Redis transaction (MULTI/EXEC)?
# MULTI/EXEC in Redis does NOT allow conditional logic — you can't use the
# result of ZRANGEBYSCORE inside the same transaction to decide what to ZREM.
# Lua scripts execute as a single atomic unit AND support conditional logic.
CLAIM_JOBS_SCRIPT = """
local jobs = redis.call('ZRANGEBYSCORE', KEYS[1], 0, ARGV[1], 'LIMIT', 0, ARGV[2])
if #jobs == 0 then return {} end
redis.call('ZREM', KEYS[1], unpack(jobs))
return jobs
"""


class RedisWorker:
    """
    Polls the scheduled jobs sorted set and executes due jobs.

    Multiple worker instances can run in parallel safely — the Lua script
    ensures each job_id is claimed by exactly one worker.

    STUCK JOB DETECTION:
    Workers should write to a "processing" sorted set (score=claimed_at)
    when they start a job, and remove from it when done. A watchdog process
    checks for jobs that have been "processing" for too long (> job timeout)
    and re-enqueues them. This handles worker crashes mid-execution.
    """

    def __init__(self, redis_client: redis.Redis, handlers: dict):
        self.r = redis_client
        # handlers maps job_type -> callable
        # e.g., {"send_email": send_email_fn, "charge_card": charge_fn}
        self.handlers = handlers
        self._claim_script = self.r.register_script(CLAIM_JOBS_SCRIPT)
        self._running = False

    def run(self, poll_interval_seconds: float = 1.0):
        """
        Main poll loop. Runs until stop() is called.

        poll_interval_seconds: how often to check for due jobs.
        Lower = lower scheduling latency, higher Redis load.
        1 second is the right default for most business job schedulers.
        Sub-100ms polling is only warranted for real-time systems.
        """
        self._running = True
        print(f"Worker started. Polling every {poll_interval_seconds}s.")

        while self._running:
            self._poll_and_execute()
            time.sleep(poll_interval_seconds)

    def _poll_and_execute(self):
        now = time.time()

        # Atomically claim up to 10 jobs due right now.
        # The Lua script returns job_ids as bytes.
        claimed_ids = self._claim_script(
            keys=[SCHEDULED_JOBS_KEY],
            args=[now, 10]   # now = score upper bound, 10 = max jobs to claim
        )

        for job_id_bytes in claimed_ids:
            job_id = job_id_bytes.decode()
            self._execute_job(job_id)

    def _execute_job(self, job_id: str):
        # Fetch full job data from the Hash
        job_data = self.r.hgetall(f"{JOB_DATA_PREFIX}{job_id}")
        if not job_data:
            # Job data expired or was deleted (e.g., cancelled race condition)
            print(f"Job {job_id} has no data — skipping.")
            return

        # Redis hgetall returns bytes keys/values
        job_type = job_data[b"type"].decode()
        payload  = json.loads(job_data[b"payload"].decode())

        handler = self.handlers.get(job_type)
        if not handler:
            print(f"No handler registered for job type: {job_type}")
            self.r.hset(f"{JOB_DATA_PREFIX}{job_id}", "status", "failed_no_handler")
            return

        try:
            # Mark as running BEFORE execution.
            # This lets a watchdog detect stuck jobs if the worker crashes here.
            self.r.hset(f"{JOB_DATA_PREFIX}{job_id}", mapping={
                "status":     "running",
                "started_at": time.time(),
            })

            handler(job_id, payload)

            # Mark as completed AFTER successful execution.
            self.r.hset(f"{JOB_DATA_PREFIX}{job_id}", mapping={
                "status":       "completed",
                "completed_at": time.time(),
            })
            print(f"Job {job_id} ({job_type}) completed.")

        except Exception as e:
            # Mark as failed with error details for debugging.
            # In production: implement retry logic with exponential backoff.
            # Re-enqueue with run_at = now + backoff, increment attempt count.
            self.r.hset(f"{JOB_DATA_PREFIX}{job_id}", mapping={
                "status": "failed",
                "error":  str(e),
            })
            print(f"Job {job_id} ({job_type}) failed: {e}")

    def stop(self):
        self._running = False


# ── RETRY WITH EXPONENTIAL BACKOFF ────────────────────────────────────────────
#
# Production job queues need retry logic. The scheduler re-enqueues failed
# jobs with increasing delays. MAX_ATTEMPTS prevents infinite retry loops.
# Exponential backoff prevents thundering herd when a downstream system recovers.

MAX_ATTEMPTS = 5
BASE_BACKOFF_SECONDS = 30


def retry_job(r: redis.Redis, job_id: str):
    """
    Re-enqueue a failed job with exponential backoff.
    Called from the worker's exception handler.

    Backoff schedule (base=30s):
      attempt 1 -> retry in 30s
      attempt 2 -> retry in 60s
      attempt 3 -> retry in 120s
      attempt 4 -> retry in 240s
      attempt 5 -> dead letter queue (no more retries)
    """
    job_data = r.hgetall(f"{JOB_DATA_PREFIX}{job_id}")
    attempt  = int(job_data.get(b"attempt", b"0").decode()) + 1

    if attempt >= MAX_ATTEMPTS:
        # Move to dead letter queue for manual inspection.
        # Dead letter queue is another sorted set, or just a Redis List.
        r.lpush("dead_letter_queue", job_id)
        r.hset(f"{JOB_DATA_PREFIX}{job_id}", "status", "dead_lettered")
        print(f"Job {job_id} dead-lettered after {attempt} attempts.")
        return

    backoff = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
    retry_at = time.time() + backoff

    pipe = r.pipeline()
    pipe.zadd(SCHEDULED_JOBS_KEY, {job_id: retry_at})
    pipe.hset(f"{JOB_DATA_PREFIX}{job_id}", mapping={
        "status":  "scheduled",
        "attempt": attempt,
        "run_at":  retry_at,
    })
    pipe.execute()
    print(f"Job {job_id} re-enqueued for retry #{attempt} in {backoff}s.")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PATTERN 2: KAFKA SCHEDULED EXECUTION (FORWARDING MODEL)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
#  WHY BOTHER WITH KAFKA FOR SCHEDULING?
#  ────────────────────────────────────────────────────────────────────────────
#  Redis Sorted Set is simpler for pure scheduling. But Kafka scheduling
#  makes sense when:
#  - You need the scheduled job to be part of an auditable event log
#  - You need to replay "what was scheduled last Tuesday and did it run?"
#  - The scheduler is part of a larger event-driven pipeline
#  - You want fan-out: one scheduled event triggers multiple downstream consumers
#  - You want Kafka's durability guarantees without managing Redis AOF
#
#  THE FORWARDING MODEL
#  ────────────────────────────────────────────────────────────────────────────
#  Kafka has no native "hold this message until time T" feature.
#  Messages are delivered to consumers as fast as possible.
#  To implement scheduling, you need a forwarding layer:
#
#    Producer --> [scheduled_jobs topic]
#                       |
#                  Scheduler Service
#                  (buffers in memory,
#                   checks every second)
#                       |
#               [ready_jobs topic] --> Workers
#
#  The Scheduler Service:
#  1. Consumes from scheduled_jobs topic (no consumer lag — reads fast)
#  2. Holds unready jobs in an in-memory heap (priority queue by run_at)
#  3. Every second: pops all jobs from the heap where run_at <= now
#  4. Produces them to ready_jobs topic
#  5. Workers consume ready_jobs and execute
#
#  KEY DESIGN QUESTIONS FOR INTERVIEWS
#  ────────────────────────────────────────────────────────────────────────────
#  Q: What happens if the Scheduler Service crashes?
#  A: It committed offsets to scheduled_jobs as it processed them. On restart,
#     it re-reads from the last committed offset. BUT: jobs it had buffered
#     in memory (consumed but not yet forwarded) are lost from the heap.
#     It will re-consume them from Kafka (at-least-once) and re-forward them.
#     Workers must be idempotent to handle the occasional duplicate.
#
#     Alternatively: DON'T commit offsets until after forwarding to ready_jobs.
#     Then a crash always replays buffered jobs safely. Trade-off: slower commits,
#     larger memory buffer if the scheduler falls behind.
#
#  Q: What if there are millions of future-scheduled jobs?
#  A: The in-memory heap can't hold them all. Solution: only keep jobs due
#     within the next N minutes (e.g., 10 minutes) in the heap. Use a
#     secondary sorted set or DB table for jobs further out, and load them
#     into the heap in a rolling window. This is the "two-tier scheduling"
#     pattern used by systems like Quartz Scheduler.
#
#  Q: What about job ordering?
#  A: Kafka guarantees ordering within a partition. If you partition by job_type
#     or tenant_id, jobs of the same type/tenant are forwarded in order.
#     But across the heap, execution order is only guaranteed to be "close to
#     run_at" — not exact, because the poller has a 1-second resolution.
#
#  Q: Why not just use Kafka consumer seek() to delay consumption?
#  A: seek() moves the consumer offset to a specific position — it's for
#     replaying historical messages, not delaying future ones. You can't
#     tell Kafka "deliver this message in 5 minutes." The forwarding model
#     is the correct approach.
#
#  INTERVIEW TALKING POINTS
#  ────────────────────────────────────────────────────────────────────────────
#  "For Kafka-native scheduling, I'd use a two-topic forwarding model.
#  Jobs are produced to a 'scheduled' topic with run_at in the payload.
#  A scheduler service consumes that topic, buffers upcoming jobs in a
#  min-heap keyed by run_at, and forwards them to a 'ready' topic when
#  their time comes. Workers consume 'ready' and execute."
#
#  "The key resilience question is: what happens when the scheduler crashes?
#  If I commit offsets eagerly (before forwarding), I need to handle the case
#  where buffered-but-not-forwarded jobs are lost. I'd use at-least-once
#  forwarding and make workers idempotent — a job_id dedup key in the DB
#  prevents double execution on the rare replay."
#
#  "For very large future job sets (millions of jobs months out), I'd add
#  a two-tier model: an outer Postgres/Redis store for far-future jobs, and
#  the Kafka heap only loads jobs due in the next 15 minutes. A loading
#  cron job tops it up continuously."


import heapq
from dataclasses import dataclass, field


@dataclass(order=True)
class ScheduledJob:
    """
    A job entry in the in-memory min-heap.
    order=True makes dataclass compare by fields in declaration order.
    run_at is first, so the heap orders by run_at (earliest first).

    The job_data field is excluded from comparison (compare=False)
    to avoid comparing dicts when two jobs have the same run_at.
    """
    run_at:   float
    job_data: dict = field(compare=False)


class KafkaSchedulerService:
    """
    Consumes from a 'scheduled_jobs' topic and forwards due jobs to 'ready_jobs'.

    This is the "brain" of the Kafka scheduling pipeline. It's a single-threaded
    service (or a small cluster with partition-based sharding) that:
      1. Reads all scheduled jobs from Kafka into a min-heap
      2. Every second, pops due jobs and forwards them to the ready topic
      3. Workers consuming 'ready_jobs' execute the jobs

    SCALING: This service is the bottleneck. If you have very high scheduling
    volume, shard by partitioning scheduled_jobs by a routing key (e.g., tenant_id
    or job_type) and run one scheduler instance per partition group.
    Each instance only manages jobs for its assigned partitions.
    """

    def __init__(self, bootstrap_servers: str):
        self.consumer = Consumer({
            "bootstrap.servers":  bootstrap_servers,
            "group.id":           "kafka-scheduler-service",
            "auto.offset.reset":  "earliest",
            # Disable auto-commit. We commit only after forwarding to ready_jobs.
            # This ensures a crash during forwarding replays the job safely.
            "enable.auto.commit": False,
        })

        self.producer = Producer({
            "bootstrap.servers": bootstrap_servers,
            "acks":              "all",           # durable forwarding
            "enable.idempotence": True,
        })

        # Min-heap ordered by run_at. heapq is a min-heap by default.
        # Smallest run_at = soonest job = top of heap.
        self._heap: list[ScheduledJob] = []
        self._heap_lock = threading.Lock()
        self._running = False

    def start(self):
        self.consumer.subscribe(["scheduled_jobs"])
        self._running = True

        # Thread 1: continuously consume from Kafka into the heap
        consumer_thread = threading.Thread(target=self._consume_loop, daemon=True)
        consumer_thread.start()

        # Thread 2 (main): every second, pop due jobs and forward them
        self._forward_loop()

    def _consume_loop(self):
        """
        Reads scheduled jobs from Kafka as fast as they arrive.
        Adds them to the in-memory heap.

        NOTE: We commit offsets AFTER forwarding (in _forward_loop), not here.
        This means on restart, we re-consume jobs that were in the heap but
        not yet forwarded. Workers handle the resulting duplicates via dedup.
        """
        while self._running:
            msg = self.consumer.poll(timeout=1.0)
            if msg is None or msg.error():
                continue

            job = json.loads(msg.value())
            run_at = job["run_at"]

            # OPTIMIZATION: skip jobs that should have run in the past
            # (e.g., on restart after a long outage). Forward them immediately
            # rather than queuing in the heap.
            if run_at <= time.time():
                self._forward_job(job)
            else:
                with self._heap_lock:
                    heapq.heappush(self._heap, ScheduledJob(run_at=run_at, job_data=job))

    def _forward_loop(self):
        """
        Runs every second. Pops all due jobs from the heap and forwards them
        to the 'ready_jobs' topic for worker consumption.
        """
        while self._running:
            now = time.time()
            due_jobs = []

            with self._heap_lock:
                # Pop all jobs where run_at <= now
                while self._heap and self._heap[0].run_at <= now:
                    due_jobs.append(heapq.heappop(self._heap).job_data)

            for job in due_jobs:
                self._forward_job(job)

            if due_jobs:
                # Commit offsets after forwarding this batch.
                # Tells Kafka "I've processed everything up to this point."
                # A crash after forwarding but before commit = duplicate forward
                # on restart. Workers handle this with idempotent execution.
                self.consumer.commit(asynchronous=False)

            time.sleep(1.0)

    def _forward_job(self, job: dict):
        """Forward a due job to the ready_jobs topic."""
        self.producer.produce(
            topic="ready_jobs",
            # Partition key = job_type ensures all jobs of the same type
            # are processed in order by the same worker instance.
            key=job.get("job_type", "default").encode(),
            value=json.dumps({
                **job,
                "forwarded_at": time.time(),
            }).encode(),
        )
        self.producer.poll(0)
        print(f"Forwarded job {job['job_id']} (type={job['job_type']}) to ready_jobs")

    def stop(self):
        self._running = False
        self.producer.flush()
        self.consumer.close()


class KafkaJobProducer:
    """
    Schedules jobs by producing to the 'scheduled_jobs' Kafka topic.

    The job payload includes run_at (Unix timestamp). The scheduler service
    reads this and holds the job until the right time.
    """

    def __init__(self, bootstrap_servers: str):
        self.producer = Producer({
            "bootstrap.servers": bootstrap_servers,
            "acks":              "all",
            "enable.idempotence": True,
        })

    def schedule(self, job_type: str, payload: dict, run_at: datetime) -> str:
        job_id = str(uuid.uuid4())
        self.producer.produce(
            topic="scheduled_jobs",
            key=job_id.encode(),
            value=json.dumps({
                "job_id":     job_id,
                "job_type":   job_type,
                "payload":    payload,
                "run_at":     run_at.timestamp(),
                "created_at": time.time(),
            }).encode(),
        )
        self.producer.poll(0)
        return job_id

    def schedule_in(self, job_type: str, payload: dict, delay: timedelta) -> str:
        return self.schedule(job_type, payload, datetime.utcnow() + delay)

    def flush(self):
        self.producer.flush()


class KafkaJobWorker:
    """
    Consumes from the 'ready_jobs' topic and executes jobs.

    This is the terminal consumer in the pipeline. Jobs arrive here only
    after the scheduler service has determined they're due.

    IDEMPOTENCY REQUIREMENT:
    Because the scheduler uses at-least-once forwarding, a job may be
    forwarded more than once in rare cases (scheduler crash + restart).
    Workers MUST be idempotent. The simplest approach: track executed job_ids
    in a DB with a unique constraint and ignore duplicates.
    """

    def __init__(self, bootstrap_servers: str, handlers: dict):
        self.consumer = Consumer({
            "bootstrap.servers":  bootstrap_servers,
            "group.id":           "job-workers",
            "auto.offset.reset":  "earliest",
            "enable.auto.commit": False,
        })
        self.handlers = handlers

    def run(self):
        self.consumer.subscribe(["ready_jobs"])
        try:
            while True:
                msg = self.consumer.poll(timeout=1.0)
                if msg is None or msg.error():
                    continue

                job = json.loads(msg.value())
                job_id   = job["job_id"]
                job_type = job["job_type"]
                payload  = job["payload"]

                handler = self.handlers.get(job_type)
                if not handler:
                    print(f"No handler for job type: {job_type}")
                    self.consumer.commit(asynchronous=False)
                    continue

                try:
                    handler(job_id, payload)
                    # Commit AFTER successful execution.
                    # On crash before commit: job replayed by another worker
                    # instance -> handler called again -> must be idempotent.
                    self.consumer.commit(asynchronous=False)
                    print(f"Executed job {job_id} ({job_type})")

                except Exception as e:
                    print(f"Job {job_id} failed: {e}")
                    # Don't commit on failure — let another worker retry.
                    # For dead-lettering after N failures, track attempt count
                    # in job payload and route to a dead_letter_jobs topic.

        finally:
            self.consumer.close()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PATTERN 3: HYBRID (recommended for production)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
#  Most production systems at scale use a combination:
#
#    [Application] --(schedule)--> [Postgres jobs table]  <-- source of truth
#                                         |
#                              [Loader cron, every 1 min]
#                                         |
#                                  [Redis Sorted Set]     <-- execution index
#                                         |
#                              [Workers poll every 1s]
#                                         |
#                              [Execute + mark complete in Postgres]
#
#  Why this hybrid wins:
#  - Postgres: durable source of truth, queryable, auditable, handles millions
#    of jobs without memory pressure
#  - Redis Sorted Set: fast O(log N) polling, low latency, atomic claiming
#  - If Redis is lost: loader cron rebuilds the sorted set from Postgres
#    by querying WHERE status='scheduled' AND run_at <= NOW() + 10 minutes
#  - No AOF complexity needed — Redis is a cache here, not a store
#
#  This is the architecture behind Sidekiq Pro, Celery Beat, and most
#  enterprise job schedulers. Know this pattern cold.
#
#  INTERVIEW DECISION TREE
#  ────────────────────────────────────────────────────────────────────────────
#  "Do you need scheduled/delayed execution?"
#    YES --> Do you need event replay / audit log of all scheduled jobs?
#              YES --> Kafka forwarding model (or Kafka + Redis hybrid)
#              NO  --> Redis Sorted Set + Postgres for durability
#
#  "Do you need fan-out? (one scheduled event triggers multiple services)"
#    YES --> Kafka (consumer groups give you fan-out for free)
#    NO  --> Redis (simpler, lower latency)
#
#  "Do you need sub-second scheduling accuracy?"
#    YES --> Neither Redis polling nor Kafka forwarding is ideal.
#            Consider a dedicated timer system or OS-level scheduling.
#    NO  --> 1-second polling on Redis is fine for 99% of use cases.


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  COMPARISON TABLE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
#  Feature                  | Redis Sorted Set    | Kafka Forwarding     | Hybrid
#  ─────────────────────────┼─────────────────────┼──────────────────────┼─────────────────────
#  Native scheduling        | No (polling model)  | No (forwarding model)| No (loader cron)
#  Scheduling accuracy      | ~1s (tunable)       | ~1s (tunable)        | ~1s (tunable)
#  Durability               | AOF (opt-in)        | Yes (Kafka log)      | Yes (Postgres)
#  Replay / audit           | No                  | Yes                  | Yes (Postgres)
#  Fan-out                  | No (single consumer)| Yes (consumer groups)| No
#  Ops complexity           | Low                 | High                 | Medium
#  Memory pressure          | High (all jobs in   | Low (heap is small,  | Low (Redis is
#                           | sorted set in RAM)  | Kafka stores rest)   | just a window)
#  Retry / dead letter      | Manual (re-zadd)    | Manual (re-produce)  | Native (Postgres)
#  Best for                 | Simple job queues   | Event-driven pipelines| Production default