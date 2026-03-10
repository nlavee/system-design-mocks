"""
================================================================================
  KAFKA — STAFF+ INTERVIEW PREP (Python)
  Topics: CDC/Outbox, Fan-out/Pub-Sub, Exactly-Once, Stream Joins & Aggregations
  Libraries: confluent-kafka-python, faust-streaming
================================================================================

  HOW TO USE THIS FILE:
  Read the large comment blocks before each section FIRST — they contain the
  mental models and vocabulary you need to sound fluent in the interview.
  The code then shows you what those concepts look like in practice.
  Inline comments explain the "why" behind each non-obvious line.

  KAFKA INTERNALS YOU MUST KNOW (foundation for all 4 sections):
  ─────────────────────────────────────────────────────────────
  Topic:     A named, ordered, durable log. Not a queue — messages are NOT
             deleted after consumption. They expire based on retention policy.

  Partition: The unit of parallelism and ordering. A topic with N partitions
             can be consumed by at most N consumers in parallel (per group).
             Ordering is guaranteed WITHIN a partition, not across partitions.
             This is why partition key selection is a critical design decision.

  Offset:    A monotonically increasing integer per partition. It's a cursor.
             Consumers track "how far I've read" by committing offsets.
             This is what enables replay, independent consumer groups, and
             the fan-out pattern.

  Broker:    A Kafka server. Usually deployed in clusters of 3+.
             Each partition has one "leader" broker (handles all reads/writes)
             and N-1 "follower" replicas (for durability).

  ISR:       In-Sync Replicas. The set of replicas that are caught up with the
             leader. acks="all" waits for all ISR replicas to acknowledge a
             write before returning success. This is your durability knob.

  Log Compaction: A background process that retains only the LATEST value per
             message key within a topic. Used for changelog topics (user profiles,
             configs). The mechanism behind tombstones — a null value for a key
             signals compaction to delete that key entirely from the log.

  Consumer Group: A set of consumers sharing the same group.id. Kafka distributes
             partitions across consumers in the group. Adding consumers up to the
             partition count increases parallelism. Beyond that, extras sit idle.
             CRITICAL INSIGHT: different groups each get ALL messages — this is
             what enables fan-out without message duplication across services.
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SECTION 1: EVENT STREAMING / CDC (Change Data Capture)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
#  WHAT IS CDC AND WHY DOES IT EXIST?
#  ────────────────────────────────────────────────────────────────────────────
#  CDC solves a fundamental problem in distributed systems: how do you propagate
#  changes from a database to other systems (search indexes, caches, analytics,
#  microservices) without coupling them together or risking data inconsistency?
#
#  The naive solution — write to both DB and Kafka in the same code path — is
#  called a dual-write, and it's a trap. Here's why it fails:
#
#    1. Your app writes to Postgres ✓
#    2. Your app crashes before writing to Kafka ✗
#    3. Postgres has the data. Kafka doesn't. Your downstream systems are stale.
#    4. There is no automatic recovery. You've silently corrupted your data pipeline.
#
#  Even without crashes, dual-writes have no ordering guarantees. Two concurrent
#  writes could arrive at Kafka in a different order than they landed in Postgres,
#  creating inconsistencies that are nearly impossible to debug in production.
#
#  THE TWO SAFE CDC APPROACHES
#  ────────────────────────────────────────────────────────────────────────────
#
#  APPROACH 1: LOG-BASED CDC (Debezium + WAL)
#  Every relational DB (Postgres, MySQL, etc.) maintains a Write-Ahead Log (WAL)
#  — an ordered, durable record of every change made to the database. The DB uses
#  it for crash recovery and replication. Debezium taps into this log as a
#  read replica would, and converts each WAL entry into a Kafka event.
#
#  Architecture:
#    DB (Postgres WAL) --> Debezium Kafka Connect Connector --> Kafka Topic --> Consumers
#
#  Why this is powerful:
#  - The WAL is already an ordered, durable log. You're not adding new infrastructure,
#    you're just re-routing an existing one.
#  - Captures ALL operations: INSERT, UPDATE, DELETE. Polling-based CDC misses deletes
#    entirely because once a row is deleted, there's nothing to poll.
#  - Near-zero additional DB load. Debezium reads the replication slot, not the table.
#  - Ordering guaranteed within a partition — the WAL IS the ordering source of truth.
#
#  Downsides:
#  - Requires DB superuser privileges to create a replication slot.
#  - Replication slots retain WAL segments until Debezium acknowledges them.
#    If Debezium falls behind or goes down, WAL grows unbounded -> disk full -> DB crash.
#    Mitigate with max_slot_wal_keep_size (Postgres 13+) and monitoring lag.
#  - Operationally complex: you're running Kafka Connect + managing connectors.
#  - Schema changes in the DB require careful management with Schema Registry.
#
#  APPROACH 2: OUTBOX PATTERN (application-level CDC)
#  Instead of writing to Kafka directly, the application writes an event row
#  to an `outbox` table in the SAME database transaction as the business write.
#  A separate "relay" process (or Debezium watching the outbox table) then
#  publishes those rows to Kafka.
#
#  Why this achieves atomicity:
#  - The DB transaction is the atomic unit. Either BOTH the business write AND
#    the outbox row commit, or NEITHER does. Kafka is only involved after the
#    DB transaction succeeds.
#  - No two-phase commit required. No distributed transaction. Just a DB transaction.
#
#  Architecture:
#    Application --> [BEGIN TX] write to orders + write to outbox [COMMIT TX]
#                         └--> OutboxRelay polls outbox --> Kafka --> Consumers
#
#  Downsides:
#  - Extra table to maintain and keep clean (delete published rows periodically).
#  - Relay adds latency (typically 50-200ms depending on polling interval).
#  - Relay must be highly available — if it dies, events pile up in outbox.
#  - Application code must remember to write to the outbox table on every mutation.
#    This is easy to forget and hard to enforce without tooling.
#
#  THE DEBEZIUM EVENT ENVELOPE — MEMORIZE THIS
#  ────────────────────────────────────────────────────────────────────────────
#  Every Debezium event follows this JSON structure (simplified):
#
#    {
#      "before": { ...row data before the change... },   // null for INSERT
#      "after":  { ...row data after the change... },    // null for DELETE
#      "op":     "c" | "u" | "d" | "r",
#              // c = create (INSERT)
#              // u = update (UPDATE)
#              // d = delete (DELETE)
#              // r = read   (snapshot -- full table scan on connector start)
#      "ts_ms":  1699000000000,   // event time in the SOURCE DB
#      "source": { "db": "...", "table": "...", "lsn": ... }
#    }
#
#  The "before" field is what makes CDC uniquely powerful vs polling.
#  On an UPDATE, you can see EXACTLY which fields changed without querying
#  the DB again. This enables delta computation, audit logs, and fine-grained
#  cache invalidation.
#
#  TOMBSTONE EVENTS — THE GOTCHA MOST CANDIDATES MISS
#  ────────────────────────────────────────────────────────────────────────────
#  When Kafka log compaction runs on a topic, it needs a way to mark a key
#  for deletion (i.e., "forget everything about user_id=42"). It does this
#  with a TOMBSTONE: a message where key=entity_id and value=None (null).
#
#  Debezium automatically sends a tombstone after every DELETE event.
#  The sequence for a hard delete is:
#    1. op="d" message (before=deleted row, after=null) -- the actual delete event
#    2. Tombstone message (key=entity_id, value=None) -- signals log compaction
#
#  If your consumer code does json.loads(msg.value()) without checking for None
#  first, you get a TypeError in production — but only after log compaction runs,
#  which may be hours or days after deployment. This is a classic "works in dev,
#  breaks in prod after a week" bug.
#
#  SCHEMA EVOLUTION — THE LONG-TERM PROBLEM
#  ────────────────────────────────────────────────────────────────────────────
#  In a running system, producers evolve over time: new fields get added,
#  old fields get renamed or removed. Without a contract, consumers break silently.
#
#  Solution: Avro serialization + Confluent Schema Registry.
#  - Schema Registry stores versioned Avro schemas.
#  - Producers register their schema before producing.
#  - Consumers deserialize using the schema version embedded in each message.
#  - Registry enforces compatibility rules (BACKWARD, FORWARD, FULL).
#
#  BACKWARD compatibility (default and most important):
#    New schema can read data written with OLD schema.
#    Rule: you can ADD optional fields with defaults. You can DELETE fields.
#    You CANNOT add required fields or change field types.
#    Why it matters: you upgrade consumers first, then producers.
#    Consumers must be able to read old messages still in the topic.
#
#  FORWARD compatibility:
#    Old schema can read data written with NEW schema.
#    Useful when you need to roll back consumers without re-processing.
#
#  FULL compatibility: both backward AND forward.
#
#  If you're using JSON in production, document your compatibility contract
#  explicitly and use tolerant reader pattern (ignore unknown fields).
#
#  CDC vs EVENT SOURCING — KNOW THE DIFFERENCE
#  ────────────────────────────────────────────────────────────────────────────
#  This question comes up in Staff+ interviews. They sound similar but are different:
#
#  CDC: Retrofitting event streaming onto an existing CRUD system.
#       The database is still the source of truth. Kafka is a derivative view.
#       Events are DB change records, not business domain events.
#       Bounded by what the DB schema captures.
#
#  Event Sourcing: The event log IS the source of truth.
#       You never store "current state" — you replay events to derive it.
#       Events are rich business domain events (OrderPlaced, PaymentProcessed).
#       The DB is derived FROM the event log, not the other way around.
#       Much higher complexity (CQRS, temporal queries, event versioning).
#       Use when audit history, temporal queries, or event replay are core requirements.
#
#  PARTITION KEY SELECTION — CRITICAL DESIGN DECISION
#  ────────────────────────────────────────────────────────────────────────────
#  The partition key determines two things:
#    1. Which partition the message lands on (determines ordering and co-location).
#    2. How evenly load is distributed across partitions (hot partition problem).
#
#  Rule: partition by the entity whose events need to be ORDERED relative to each other.
#  - For user events   --> user_id as key
#  - For order events  --> order_id as key
#  - For payment events --> order_id (not payment_id) if you need order+payment ordering
#
#  Hot partition problem: if your key has low cardinality or skewed distribution
#  (e.g., partitioning by country and 80% of traffic is "US"), one partition
#  becomes a bottleneck. Solutions: composite keys, virtual partitioning, or
#  accepting uneven distribution for the sake of ordering guarantees.
#
#  INTERVIEW TALKING POINTS — SAY THESE VERBATIM
#  ────────────────────────────────────────────────────────────────────────────
#  "For CDC I'd use log-based capture via Debezium reading the Postgres WAL.
#  The key insight is the WAL is already an ordered durable log — we're just
#  re-routing it. This gives us zero dual-write risk, captures deletes, and
#  adds minimal DB load. I'd partition by aggregate_id so all events for a
#  given entity land on the same partition and remain ordered."
#
#  "For atomicity during application writes, I'd use the outbox pattern:
#  the application writes both the business record AND an outbox event row
#  in the same DB transaction. The relay publishes from outbox to Kafka.
#  Atomicity comes from the DB transaction — not from hoping two separate
#  I/O calls both succeed."
#
#  "On schema evolution: I'd use Avro with the Confluent Schema Registry
#  enforcing BACKWARD compatibility. This means consumers can always read
#  messages produced with older schemas — which matters because the topic
#  may contain weeks of messages when a new consumer group is first deployed."
#
#  TRADEOFFS:
#  Log-based CDC (Debezium): near-zero DB load, captures deletes, ordered.
#    Requires WAL access, replication slot management, connector ops complexity.
#  Polling CDC: simple, no special DB privileges.
#    High latency, MISSES DELETES, hammers DB at scale.
#  Outbox Pattern: atomic, works with any DB, no WAL access needed.
#    Relay latency ~50-200ms, extra table, devs must remember to write outbox rows.
#  Direct dual-write: NEVER. No atomicity. Silent data corruption.

from confluent_kafka import Producer, Consumer, TopicPartition
import json
import hashlib


class OutboxRelay:
    """
    Outbox Pattern relay: reads unpublished rows from the outbox table
    and publishes them to Kafka.

    INVARIANT: A row is only marked published=TRUE AFTER Kafka has acknowledged
    receipt. This means we might publish a row to Kafka more than once
    (at-least-once), but we will NEVER lose an event.
    Consumers must be idempotent to handle the rare duplicate.

    SQL schema for the outbox table:
        CREATE TABLE outbox (
            id              BIGSERIAL PRIMARY KEY,
            aggregate_type  TEXT NOT NULL,        -- domain entity name, e.g. "Order"
            aggregate_id    TEXT NOT NULL,         -- entity PK, used as Kafka message key
            event_type      TEXT NOT NULL,         -- event name, e.g. "OrderPlaced"
            payload         JSONB NOT NULL,        -- the event data
            published       BOOLEAN DEFAULT FALSE, -- has this been sent to Kafka?
            created_at      TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX idx_outbox_unpublished ON outbox(created_at) WHERE published = FALSE;

    The index is critical — without it, the WHERE published=FALSE scan becomes
    a full table scan as the outbox grows, which compounds latency under load.
    """

    def __init__(self, db_conn, producer: Producer, topic: str):
        self.db = db_conn
        self.producer = producer
        self.topic = topic

    def poll_and_publish(self):
        """
        Fetch up to 100 unpublished rows, publish them all to Kafka,
        then mark them as published in a single batch UPDATE.

        The ORDER BY created_at ensures we publish events in the order they
        were written. Without this, a fast-produced batch could arrive at
        consumers out of order, breaking any downstream state machines that
        depend on event ordering (e.g., order lifecycle: Created -> Paid -> Shipped).

        WHY flush() BEFORE the UPDATE:
        We call producer.flush() which blocks until all messages have been
        acknowledged by Kafka (all delivery callbacks have fired). Only THEN
        do we mark rows as published in the DB. This ordering ensures:
          - If Kafka is down: flush() raises/times out, DB UPDATE never runs,
            rows stay unpublished, relay retries on next poll cycle. No data loss.
          - If DB UPDATE fails after flush(): rows are in Kafka but not marked
            published. Next poll will re-publish them (duplicate), but consumers
            handle this via idempotent upserts. Still no data loss.
        The alternative (UPDATE before flush) could mark rows published when
        Kafka never received them — unrecoverable data loss.
        """
        with self.db.cursor() as cur:
            cur.execute("""
                SELECT id, aggregate_type, aggregate_id, event_type, payload, created_at
                FROM outbox
                WHERE published = FALSE
                ORDER BY created_at
                LIMIT 100
                FOR UPDATE SKIP LOCKED
            """)
            # FOR UPDATE SKIP LOCKED explained:
            # FOR UPDATE: lock the selected rows so no other transaction can
            #   modify them while we're working on them.
            # SKIP LOCKED: if a row is ALREADY locked by another transaction
            #   (another relay instance), skip it rather than waiting.
            # Together, these allow multiple relay instances to run in parallel
            # without duplicate-publishing the same rows. Each instance claims
            # a non-overlapping set of rows atomically.
            rows = cur.fetchall()
            published_ids = []

            for row in rows:
                id_, agg_type, agg_id, event_type, payload, ts = row

                # Use aggregate_id as the Kafka partition key.
                # This guarantees all events for the same entity (e.g., order_id=42)
                # land on the same partition -> their relative order is preserved.
                # Without a consistent key, events for the same entity could land
                # on different partitions and be processed out of order by consumers.
                self.producer.produce(
                    topic=self.topic,
                    key=str(agg_id).encode(),
                    value=json.dumps({
                        # Debezium envelope format — using consistent structure
                        # allows consumers to handle both Debezium and outbox events
                        # with the same deserialization logic.
                        "before":     payload.get("before"),
                        "after":      payload.get("after"),
                        "op":         payload.get("op"),       # c/u/d/r
                        "ts_ms":      int(ts.timestamp() * 1000),
                        "event_type": event_type,
                        "source":     {"table": agg_type, "db": "prod"},
                    }).encode(),
                    # on_delivery is called asynchronously when Kafka acks or rejects.
                    # We use a default arg (oid=id_) to capture the loop variable —
                    # without this, all lambdas would capture the same final id_ value
                    # (classic Python closure-in-loop bug).
                    on_delivery=lambda err, msg, oid=id_: self._on_delivery(err, oid, published_ids),
                )

            # Block until all produce() calls above have been acked by Kafka.
            # After this returns, published_ids contains all successfully acked IDs.
            self.producer.flush()

            if published_ids:
                # Batch UPDATE is far more efficient than N individual UPDATE calls.
                # ANY(%s) with a list is idiomatic psycopg2 for "WHERE id IN (...)".
                cur.execute(
                    "UPDATE outbox SET published=TRUE WHERE id = ANY(%s)",
                    (published_ids,)
                )
                self.db.commit()

    def _on_delivery(self, err, outbox_id: int, published_ids: list):
        if err:
            # Don't swallow this. A delivery failure means Kafka rejected the
            # message after retries were exhausted. This is rare but needs alerting.
            raise Exception(f"Delivery failed for outbox_id={outbox_id}: {err}")
        published_ids.append(outbox_id)


class CDCConsumer:
    """
    Processes Debezium CDC events from a Kafka topic.

    Design principle: this consumer is stateless — all state lives in the
    downstream system (DB, cache, search index). This means it's safe to
    restart from any offset, and multiple instances can run in parallel
    (each handling different partitions).

    IDEMPOTENCY CONTRACT:
    Because we're using at-least-once delivery (manual commit after processing),
    each of the _on_* handlers must be idempotent:
    - _on_create: use INSERT ... ON CONFLICT DO NOTHING or upsert
    - _on_update: use UPDATE or upsert — applying the same update twice is safe
    - _on_delete: use DELETE WHERE id=X — deleting a non-existent row is safe
    - _on_snapshot: ALWAYS upsert — snapshot rows replay on connector restart

    Debezium operation codes:
      "c" = create  -> INSERT in source DB. before=null, after=new row.
      "u" = update  -> UPDATE in source DB. before=old row, after=new row.
                      The "before" field lets you compute exactly what changed
                      without re-querying the source DB. Use this for:
                      - Fine-grained cache invalidation (only bust changed keys)
                      - Audit logs ("field X changed from Y to Z")
                      - Conditional downstream actions ("only re-index if name changed")
      "d" = delete  -> DELETE in source DB. before=deleted row, after=null.
                      CRITICAL: this is followed by a tombstone (value=None).
      "r" = read    -> Full snapshot of a row during initial connector scan.
                      Behaves like "c" from the consumer's perspective,
                      but must be handled with upsert (not insert) because
                      snapshots replay when the connector restarts.
    """

    def __init__(self, bootstrap_servers: str, group_id: str, topic: str):
        self.consumer = Consumer({
            "bootstrap.servers":    bootstrap_servers,
            "group.id":             group_id,

            # earliest: start from the beginning of the topic on first run.
            # Use "latest" only if you explicitly don't care about historical events
            # and only want new changes going forward (e.g., a live notification service).
            "auto.offset.reset":    "earliest",

            # ALWAYS disable auto-commit for CDC consumers.
            # Auto-commit advances the offset on a timer, independent of whether
            # your processing succeeded. A crash after auto-commit but before your
            # downstream write completes = silent data loss.
            # Manual commit gives you control: only advance the offset once you
            # know the downstream write succeeded.
            "enable.auto.commit":   False,

            # If your processing logic takes longer than this (e.g., a slow DB write
            # or downstream HTTP call), Kafka declares you dead and triggers a rebalance.
            # The partition moves to another consumer, which will re-process messages
            # you already handled -> duplicates. Set this generously for slow consumers.
            # Note: this is NOT the same as session.timeout.ms (heartbeat timeout).
            "max.poll.interval.ms": 300000,   # 5 minutes
        })
        self.topic = topic

    def run(self):
        """
        Main poll loop. Processes one message at a time with sync offset commit.

        For higher throughput, batch N messages, process them all, then commit once.
        The tradeoff is that on failure, you re-process up to N messages.
        For CDC consumers where processing is fast (cache write, index update),
        message-by-message is fine. For heavy processing (ML inference, bulk DB writes),
        batch and commit at the batch boundary.
        """
        self.consumer.subscribe([self.topic])
        try:
            while True:
                msg = self.consumer.poll(timeout=1.0)
                # poll() returns None if no message arrived within the timeout.
                # This is normal — just loop and poll again.
                if msg is None:
                    continue
                if msg.error():
                    raise Exception(msg.error())

                # TOMBSTONE HANDLING
                # A tombstone is a message with a valid key but null value.
                # Debezium sends one after every DELETE event.
                # Purpose: tells Kafka log compaction "you may delete all records
                # for this key from the compacted log."
                #
                # If you don't check for None here:
                #   json.loads(None) -> TypeError -> consumer crashes -> rebalance
                #   -> another consumer picks up the partition and crashes again
                #   -> cascading failure that blocks all processing for this partition.
                #
                # Correct handling: treat tombstone as a soft delete signal.
                # Remove the entity from your search index, cache, read model, etc.
                if msg.value() is None:
                    self._handle_tombstone(msg.key().decode())
                else:
                    event = json.loads(msg.value())
                    op = event.get("op")

                    if   op == "c": self._on_create(event["after"])
                    elif op == "u": self._on_update(event["before"], event["after"])
                    elif op == "d": self._on_delete(event["before"])
                    elif op == "r": self._on_snapshot(event["after"])
                    # Unknown op? Log and continue — don't crash. Future Debezium
                    # versions may introduce new op codes.

                # Commit synchronously: offset advances ONLY after processing succeeds.
                # If processing raises an exception before this line, the offset does
                # NOT advance -> on restart, this message is reprocessed -> at-least-once.
                # This is the correct behavior for CDC consumers.
                self.consumer.commit(asynchronous=False)

        finally:
            # close() triggers a clean rebalance (cooperative leave group) and
            # commits any pending offsets. Always call this on shutdown.
            self.consumer.close()

    def _handle_tombstone(self, entity_id: str):
        # Remove the entity from any derived stores: Elasticsearch, Redis, read DB.
        print(f"Tombstone received — removing entity: {entity_id}")

    def _on_create(self, after: dict): ...
    def _on_update(self, before: dict, after: dict): ...
    # "before" lets you compute deltas without hitting the source DB:
    #   changed_fields = {k for k in after if after[k] != before.get(k)}
    # Use this for targeted cache invalidation and audit logging.
    def _on_delete(self, before: dict): ...
    def _on_snapshot(self, after: dict): ...


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SECTION 2: FAN-OUT / PUB-SUB
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
#  WHAT IS FAN-OUT AND WHY KAFKA IS UNIQUELY GOOD AT IT
#  ────────────────────────────────────────────────────────────────────────────
#  Fan-out = one producer event consumed independently by multiple services.
#  Example: an "OrderPlaced" event needs to:
#    - Decrement inventory (inventory-service)
#    - Send a confirmation email (notification-service)
#    - Update revenue dashboards (analytics-service)
#    - Trigger fraud screening (fraud-service)
#
#  With a traditional message queue (SQS, RabbitMQ): one consumer receives
#  the message and it's gone. To fan-out, you need SNS->multiple SQS queues,
#  which adds infra, cost, and operational complexity per new consumer.
#
#  With Kafka: each service creates its own consumer group. Kafka maintains
#  a separate offset pointer per group. Every group gets ALL messages,
#  independently, at their own pace. Adding a new consumer requires zero
#  changes to the producer or topic — just create a new consumer group.
#  This is the architectural superpower of Kafka's log-based model.
#
#  PARTITIONS, PARALLELISM, AND THE CEILING PROBLEM
#  ────────────────────────────────────────────────────────────────────────────
#  The number of partitions in a topic is a HARD CEILING on consumer parallelism
#  for any given consumer group. If a topic has 6 partitions:
#    - 1 consumer  -> handles all 6 partitions (low throughput)
#    - 3 consumers -> 2 partitions each (linear scaling)
#    - 6 consumers -> 1 partition each (maximum parallelism)
#    - 7 consumers -> 6 active, 1 idle (wasted resource)
#
#  This means partition count is a capacity planning decision made at topic creation.
#  You can increase partitions later, BUT increasing partitions breaks key-based
#  ordering: the same key might hash to a different partition after the change,
#  meaning messages for the same entity could be on different partitions,
#  processed out of order by different consumers.
#
#  Rule of thumb for initial partition count:
#    partitions = max(target_peak_throughput / single_partition_throughput,
#                     max_desired_consumer_parallelism)
#  A single partition can handle ~10-50MB/s on modern hardware.
#  Don't over-partition: each partition = file handles + memory on the broker.
#  Kafka has a soft limit of ~4000 partitions/broker before overhead compounds.
#
#  REBALANCING — THE PERFORMANCE KILLER
#  ────────────────────────────────────────────────────────────────────────────
#  A rebalance is triggered whenever a consumer group's membership changes:
#  - A consumer joins (new deployment, scaling up)
#  - A consumer leaves (shutdown, crash)
#  - A consumer is presumed dead (missed heartbeat, slow processing)
#
#  CLASSIC REBALANCE (RangeAssignor, RoundRobinAssignor — legacy default):
#  STOP THE WORLD. All consumers in the group stop processing. Kafka coordinator
#  waits for all consumers to check in (join request). Then redistributes ALL
#  partitions from scratch. All consumers restart from committed offsets.
#  During rebalance: ZERO throughput for the entire consumer group.
#  Rebalance duration: typically 10-30 seconds, can be minutes for large groups.
#
#  INCREMENTAL COOPERATIVE REBALANCE (CooperativeStickyAssignor — use this):
#  Only moves the MINIMUM number of partitions necessary to achieve balance.
#  Consumers that keep their partitions don't pause. Only the consumers
#  gaining/losing partitions pause briefly.
#  Result: near-zero throughput impact for most rebalances.
#  How to enable: "partition.assignment.strategy": "cooperative-sticky"
#
#  CAUSES OF ACCIDENTAL REBALANCES (operational landmines):
#  1. max.poll.interval.ms exceeded: your processing takes too long between poll()
#     calls. Broker assumes you're dead. Fix: reduce processing time, or increase
#     the interval. Better: process async and commit offsets separately.
#  2. Heartbeat missed: session.timeout.ms exceeded without a heartbeat. Usually
#     means your process is GC paused (JVM) or CPU starved. Fix: tune GC, or
#     increase timeout. Heartbeat runs in a background thread in most clients.
#  3. Rolling deployments: each pod restart triggers a rebalance. With cooperative
#     rebalance, this is low-impact. With classic, it's a thundering herd.
#
#  RULE: heartbeat.interval.ms must be less than session.timeout.ms / 3.
#  If session.timeout.ms = 30000, heartbeat.interval.ms must be <= 10000.
#  Violating this means Kafka might declare you dead before your next heartbeat.
#
#  OFFSET COMMIT STRATEGY — ASYNC VS SYNC
#  ────────────────────────────────────────────────────────────────────────────
#  Committing offsets is how consumers tell Kafka "I've processed up to here."
#  This is what enables consumer restart and rebalance recovery.
#
#  ASYNC commit (asynchronous=True):
#  - Non-blocking. Fire-and-forget. Very high throughput.
#  - On crash before Kafka acks the commit: offset not advanced.
#    Consumer restarts from last committed offset -> duplicate processing.
#  - Use during: the normal poll loop when throughput matters.
#
#  SYNC commit (asynchronous=False):
#  - Blocks until Kafka acks the commit. Lower throughput.
#  - Guarantees the commit happened before you move on.
#  - Use during: shutdown, rebalance revoke callbacks, end of a batch.
#
#  PRODUCTION PATTERN:
#    Normal operation: async commit after each poll batch.
#    On rebalance revoke: sync commit before returning (partitions move to
#      another consumer immediately after on_revoke returns — if your commit
#      is still in-flight, it races with the new consumer starting).
#    On shutdown: consumer.close() handles final sync commit automatically.
#
#  KAFKA VS SQS/SNS FOR FAN-OUT — KNOW WHEN TO USE WHICH
#  ────────────────────────────────────────────────────────────────────────────
#  Use Kafka when:
#  - You need replay (re-process historical events, bootstrap new consumers)
#  - Multiple independent consumers need the same event stream
#  - Ordering within a partition matters
#  - Very high throughput (millions of events/sec)
#  - You want to decouple event production from consumption lag
#
#  Use SQS/SNS when:
#  - Simpler ops (fully managed, zero broker management)
#  - Per-message cost is acceptable at your scale
#  - Push-based delivery is preferred over polling
#  - You don't need replay
#  - Your consumers can tolerate SNS's 10 consumer limit for fan-out
#
#  INTERVIEW TALKING POINTS
#  ────────────────────────────────────────────────────────────────────────────
#  "The key architectural property I'd leverage here is Kafka's consumer group
#  model. Each downstream service gets its own group with its own independent
#  offset pointer. Notification falling behind doesn't block inventory. Adding
#  fraud screening next quarter requires zero changes to the producer or topic.
#  That's the fan-out you can't easily get from a traditional queue."
#
#  "On partition count: I'd provision based on the most demanding consumer's
#  parallelism needs. But I'd avoid over-partitioning — each partition is a
#  file handle and some memory on the broker, and Kafka has a roughly 4000
#  partition/broker soft limit before leadership election overhead becomes
#  a problem. I'd also enable CooperativeStickyAssignor to avoid stop-the-world
#  rebalances during deployments."
#
#  "For the rebalance on_revoke callback: I'd always do a synchronous offset
#  commit there. The partitions move to another consumer the moment on_revoke
#  returns — an async commit that's still in-flight at that point could race
#  with the new consumer. Sync commit eliminates the race."
#
#  TRADEOFFS:
#  Partition count few vs many: Few = simpler, lower overhead. Many = more
#    parallelism, more broker load. Don't over-partition prematurely.
#  Classic vs Cooperative rebalance: Classic = stop-the-world on any change.
#    Cooperative = incremental, low impact. Always use cooperative in production.
#  Async vs sync offset commit: Async = high throughput, rare duplicates.
#    Sync = safe, lower throughput. Pattern: async in loop, sync on revoke.
#  Kafka vs SQS/SNS fan-out: Kafka = replay, ordering, high throughput.
#    SQS/SNS = simpler ops, push-based, managed.


class OrderProducer:
    """
    Produces order events with deterministic partition routing.

    The choice of partition key (user_id here) means:
    - All events for the same user land on the same partition
    - Events for a user are consumed in the order they were produced
    - A single consumer handles all of a user's events (no cross-partition state)

    This matters when downstream consumers maintain per-user state
    (e.g., a fraud model that looks at order history per user).
    If user events were spread across partitions, each instance would
    have an incomplete view of the user's history.
    """

    def __init__(self, bootstrap_servers: str):
        self.producer = Producer({
            "bootstrap.servers":  bootstrap_servers,

            # acks="all": wait for the partition leader AND all in-sync replicas
            # to write the message before returning. Maximum durability.
            # acks="1": only wait for leader. Faster, but if the leader crashes
            #   before replication, the message is lost even though you got an ack.
            # acks="0": fire-and-forget. Maximum throughput, zero durability.
            "acks":               "all",

            # Deduplicates messages within a single producer session.
            # Kafka assigns each producer a unique PID + sequence number per partition.
            # Broker rejects any message that duplicates a recent sequence number.
            # This eliminates duplicates from producer retries on network errors.
            # Note: this is NOT cross-session idempotence — a producer restart gets
            # a new PID. For cross-session dedup, you need transactions (EOS section).
            "enable.idempotence": True,

            # lz4 is the right default: fast compression, good ratio.
            # snappy: similar speed, slightly worse ratio.
            # gzip: best ratio, slowest. Use for cold storage or low-throughput topics.
            # zstd: best ratio + good speed in newer Kafka. Use if available.
            "compression.type":   "lz4",

            # linger.ms: wait up to 5ms for more messages to accumulate into a batch.
            # Without this, each produce() call would send a single-message request.
            # With linger.ms=5, Kafka batches all messages that arrive within 5ms.
            # This dramatically increases throughput at the cost of 5ms added latency.
            # For latency-sensitive producers (user-facing API calls), set to 0.
            "linger.ms":          5,

            # Maximum size of a single batch. If a batch fills up before linger.ms
            # expires, it's sent immediately. 64KB is a reasonable starting point.
            # Increase for very high throughput producers.
            "batch.size":         65536,
        })

    def publish_order(self, order: dict):
        partition = self._partition_for(order["user_id"], num_partitions=12)
        self.producer.produce(
            topic="order.placed",
            key=str(order["user_id"]).encode(),
            value=json.dumps(order).encode(),
            partition=partition,
            # NOTE: Explicitly specifying partition bypasses the client's built-in
            # sticky partitioner (which batches unkeyed messages on one partition
            # for better batching before rotating). Only specify partition explicitly
            # when you need deterministic, application-controlled routing.
        )
        # poll(0): process delivery callbacks without blocking.
        # Without this, callbacks only fire when you call poll() or flush().
        # Calling poll(0) frequently keeps callbacks current and frees memory
        # from the internal delivery queue.
        self.producer.poll(0)

    def flush(self):
        # flush() blocks until all queued messages have been delivered (or failed).
        # Call this on shutdown to avoid losing buffered messages.
        self.producer.flush()

    @staticmethod
    def _partition_for(user_id: int, num_partitions: int) -> int:
        # MD5 hash -> take first 4 bytes -> interpret as unsigned int -> modulo.
        # Gives uniform distribution across partitions regardless of user_id range.
        # MD5 is fine here — we don't need cryptographic security, just even distribution.
        # Kafka's default partitioner uses murmur2 hash on the key bytes.
        # Using our own hash gives us portability if we ever need to route messages
        # to the correct partition from outside Kafka (e.g., in a test harness).
        h = hashlib.md5(str(user_id).encode()).digest()
        return int.from_bytes(h[:4], "big") % num_partitions


class FanoutConsumer:
    """
    A consumer instance for one service in a fan-out topology.
    Each service instantiates this with its own service_name -> unique group_id
    -> independent offset tracking.

    Scaling: run multiple instances of this class (in different processes/pods)
    with the same service_name. Kafka will distribute partitions across them.
    Max useful instances = number of partitions in the topic.
    """

    def __init__(self, service_name: str, bootstrap_servers: str, handler):
        self.handler = handler
        self.consumer = Consumer({
            "bootstrap.servers":    bootstrap_servers,

            # group.id is the identity of this "independent consumer" in the fan-out.
            # Two services with different group.ids each get ALL messages.
            # Two instances with the SAME group.id share the topic (load-balanced).
            "group.id":             f"{service_name}-consumer-group",
            "auto.offset.reset":    "earliest",
            "enable.auto.commit":   False,

            # ALWAYS use cooperative-sticky in production.
            # This uses the incremental cooperative rebalance protocol, which only
            # moves the minimum number of partitions needed to achieve balance.
            # Without this, every deployment causes a stop-the-world rebalance
            # across ALL consumers in the group.
            "partition.assignment.strategy": "cooperative-sticky",

            "session.timeout.ms":    30000,
            # Heartbeat interval must be significantly less than session timeout.
            # The consumer sends heartbeats from a background thread. If the broker
            # doesn't receive a heartbeat within session.timeout.ms, it declares
            # the consumer dead and triggers a rebalance.
            # Rule: heartbeat.interval.ms < session.timeout.ms / 3
            "heartbeat.interval.ms": 10000,

            # max.poll.interval.ms: maximum time between poll() calls.
            # This is measured by the broker, not based on heartbeats.
            # If your message processing takes longer than this, the broker
            # kicks the consumer out of the group -> rebalance -> duplicate processing.
            # This is the MOST COMMON cause of unexpected rebalances in production.
            # Set it to (max expected processing time per batch) x (safety factor of 2).
            "max.poll.interval.ms":  600000,
        })

    def run(self, topics: list):
        self.consumer.subscribe(
            topics,
            on_assign=self._on_assign,
            # on_revoke is called BEFORE partitions are taken away during a rebalance.
            # This is your window to commit offsets and flush any in-flight work
            # for the partitions you're about to lose.
            # CRITICAL: commit synchronously here. on_revoke MUST complete before
            # Kafka proceeds with the rebalance. An async commit that's still in-flight
            # when on_revoke returns races with the new consumer's offset tracking.
            on_revoke=self._on_revoke,
            # on_lost is called when partitions are lost WITHOUT a clean revoke.
            # This happens during: network partitions, broker failover, or when
            # the consumer is kicked out of the group for missing heartbeats.
            # You CANNOT safely commit here (offset state is undefined).
            # Clean up local state only.
            on_lost=self._on_lost,
        )
        try:
            while True:
                # consume() with num_messages=100 is more efficient than 100x poll().
                # It returns up to 100 messages or waits up to timeout seconds,
                # whichever comes first. Batch processing is generally more efficient
                # than message-by-message for CPU and network overhead.
                messages = self.consumer.consume(num_messages=100, timeout=1.0)
                for msg in messages:
                    if msg.error():
                        continue
                    self.handler(json.loads(msg.value()))

                # Async commit after processing the full batch.
                # If we crash before this line, we'll reprocess this batch on restart.
                # That's at-least-once delivery — acceptable for most fan-out consumers.
                if messages:
                    self.consumer.commit(asynchronous=True)
        finally:
            self.consumer.close()

    def _on_assign(self, consumer, partitions):
        # Log assigned partitions for observability. In production you'd also:
        # - Initialize any per-partition local state
        # - Potentially seek to a specific offset for exactly-once scenarios
        print(f"[{self.__class__.__name__}] Assigned: {[p.partition for p in partitions]}")

    def _on_revoke(self, consumer, partitions):
        # SYNCHRONOUS commit before handing partitions back.
        # The new consumer that receives these partitions will start from the
        # last committed offset. If we don't commit here, it re-processes
        # everything since the last successful commit.
        consumer.commit(asynchronous=False)

    def _on_lost(self, consumer, partitions):
        # Partitions were lost without a clean revoke (network issue, GC pause, etc.)
        # We cannot commit — our epoch may already be superseded by a new consumer.
        # Just log and clean up any in-memory state for these partitions.
        print(f"Partitions lost unexpectedly: {[p.partition for p in partitions]}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SECTION 3: EXACTLY-ONCE SEMANTICS (EOS)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
#  THE THREE DELIVERY GUARANTEES — UNDERSTAND ALL THREE
#  ────────────────────────────────────────────────────────────────────────────
#  AT-MOST-ONCE:
#    Commit offset BEFORE processing. If you crash during processing, the message
#    is skipped forever. You lose data, but you never process a message twice.
#    Use case: metrics, logs, telemetry where losing a few events is acceptable.
#
#  AT-LEAST-ONCE:
#    Commit offset AFTER processing. If you crash between processing and committing,
#    the message is reprocessed on restart. You may process a message more than once,
#    but you never lose data (assuming idempotent consumers).
#    Use case: the correct default for most systems. Pair with idempotent writes.
#
#  EXACTLY-ONCE:
#    Processing and offset commit happen atomically — either both happen or neither.
#    Achieved via Kafka's transactional API (see below).
#    Use case: financial transactions, billing, inventory deductions where
#    processing a message twice causes real-world consequences that can't be undone.
#
#  HOW KAFKA EOS ACTUALLY WORKS (the mechanism)
#  ────────────────────────────────────────────────────────────────────────────
#  Kafka EOS is built from three primitives:
#
#  1. IDEMPOTENT PRODUCER:
#     Eliminates duplicates from producer retries within a session.
#     Mechanism: each producer gets a unique Producer ID (PID) assigned by the
#     broker. Each message gets a sequence number per partition. The broker tracks
#     the last sequence number it accepted per (PID, partition). If it receives
#     a message with a sequence number it's already seen, it deduplicates silently.
#     Limitation: PID changes on producer restart, so this only works within
#     a single producer session. A crashed and restarted producer gets a new PID.
#
#  2. TRANSACTIONS:
#     A transaction in Kafka wraps produce() calls AND consumer offset commits
#     into a single atomic unit managed by a Transaction Coordinator broker.
#     Either ALL operations in the transaction commit, or ALL are rolled back.
#     Key operation: send_offsets_to_transaction() — this is what makes EOS work.
#     It moves the consumer offset commit INSIDE the transaction, so offset advance
#     and message produce are a single atomic unit.
#
#  3. ZOMBIE FENCING (via transactional.id + epochs):
#     Problem: a producer crashes and restarts. The old (zombie) producer is still
#     alive on a slow network node and tries to commit its in-flight transaction.
#     The new producer also has a transaction in flight. Which one wins?
#     Without fencing: both commit -> duplicate messages.
#     With fencing:
#       - transactional.id is a deterministic, stable identifier for this "logical producer"
#       - The broker maintains an epoch counter per transactional.id
#       - When a new producer calls init_transactions() with the same transactional.id,
#         the broker increments the epoch. Any commit/produce from the old epoch
#         is rejected with a ProducerFencedException.
#       - This is why transactional.id MUST be deterministic (same across restarts).
#         A random UUID generates a new epoch on every restart, defeating fencing entirely.
#         Use a name like "payment-processor-pod-3" or derive it from pod identity.
#
#  THE CRITICAL LIMITATION: EOS IS KAFKA-TO-KAFKA ONLY
#  ────────────────────────────────────────────────────────────────────────────
#  Kafka's transaction protocol knows how to atomically wrap:
#    YES: Produce to an output Kafka topic
#    YES: Commit consumer offset on an input Kafka topic
#    YES: Both together, atomically
#
#  It does NOT know how to coordinate with:
#    NO: A Postgres database write
#    NO: An Elasticsearch index update
#    NO: A Redis cache write
#    NO: An HTTP API call
#
#  The moment you add a non-Kafka I/O operation inside a Kafka transaction,
#  you no longer have EOS. You have "Kafka transaction + external write with
#  no atomicity guarantee between them." A crash between the DB write and the
#  transaction commit leaves them inconsistent.
#
#  FOR KAFKA TO EXTERNAL SINK: use idempotent writes instead.
#  Design your sink writes to be idempotent using the Kafka offset as a
#  deduplication key. topic+partition+offset is globally unique per message.
#  Use an upsert with ON CONFLICT DO NOTHING. This gives you "effective
#  exactly-once" — the first write succeeds, all retries are no-ops.
#
#  read_committed ISOLATION LEVEL — OFTEN FORGOTTEN
#  ────────────────────────────────────────────────────────────────────────────
#  When a producer uses transactions, messages from in-flight (uncommitted)
#  transactions are written to Kafka but not yet committed. There are also
#  tombstone control messages marking transaction boundaries.
#
#  read_uncommitted (default): consumers see ALL messages including:
#    - Messages from aborted transactions (the producer rolled back)
#    - Messages from in-flight transactions (not yet committed)
#    - This means you process messages that may be rolled back -> duplicates
#
#  read_committed: consumers only see messages from COMMITTED transactions.
#    - Aborted transaction messages are filtered out by the broker
#    - In-flight messages are buffered at the Last Stable Offset (LSO)
#    - Consumer lag may appear larger than reality (LSO vs high watermark)
#    - This is what you want for EOS consumers
#
#  PERFORMANCE COST OF EOS — CHALLENGE WHEN APPROPRIATE
#  ────────────────────────────────────────────────────────────────────────────
#  EOS is not free. Transaction coordination adds:
#  - ~3-20% latency overhead per transaction (varies with batch size and topology)
#  - Extra broker RPCs (begin, commit/abort coordination with transaction coordinator)
#  - Increased broker memory (tracking active transactions, LSO computation)
#  - Additional Kafka internal topics (__transaction_state) that must be managed
#
#  At-least-once + idempotent consumers covers 95%+ of real-world use cases.
#  EOS is specifically for: financial ledgers, inventory deductions, billing,
#  and any scenario where duplicate processing causes irreversible real harm.
#
#  In the interview: push back on EOS when the interviewer asks for it.
#  "Do we actually need this, or can we achieve effective exactly-once with
#  idempotent writes? Let me walk you through what that would look like..."
#  This demonstrates Staff-level judgment, not just technical knowledge.
#
#  INTERVIEW TALKING POINTS
#  ────────────────────────────────────────────────────────────────────────────
#  "Exactly-once in Kafka is a transaction that atomically wraps produce to an
#  output topic + commit consumer offset on the input topic. The key operation
#  is send_offsets_to_transaction() — it moves the offset commit inside the
#  transaction boundary, so they're a single atomic unit. If commit_transaction()
#  fails, both the produce AND the offset advance roll back. The consumer
#  re-polls the same messages on the next iteration."
#
#  "But I'd first challenge whether EOS is actually needed. For most systems,
#  at-least-once with idempotent writes to the sink gives you effective
#  exactly-once at much lower complexity and cost. I'd use the Kafka offset as
#  the dedup key — topic+partition+offset is globally unique — and do an upsert
#  with ON CONFLICT DO NOTHING. EOS is specifically for Kafka->Kafka pipelines
#  where intermediate duplication has real downstream consequences."
#
#  "On transactional.id: it must be deterministic — derived from the pod identity
#  or instance name, not a random UUID. This is what enables zombie fencing.
#  When a new producer calls init_transactions() with the same transactional.id,
#  the broker bumps the epoch. Any commit attempt from the old epoch is rejected.
#  A random UUID gives you a new epoch on every restart — no fencing at all."
#
#  TRADEOFFS:
#  True EOS (Kafka transactions): strongest guarantee, atomic.
#    ~10-20% perf hit, Kafka->Kafka only, complex, requires deterministic tx.id.
#  At-least-once + idempotent consumer: simpler, works with external sinks,
#    lower overhead, correct for most cases. Requires idempotent sink design.
#  Deterministic transactional.id: zombie fencing works across restarts.
#    Must manage ID uniqueness per instance.
#  Random UUID transactional.id: no zombie fencing, orphaned tx state on broker,
#    defeats the purpose of EOS.
#  Small transaction batches: lower latency per message, more transaction overhead.
#  Large transaction batches: better throughput, higher latency, more data at risk.


class ExactlyOnceProcessor:
    """
    Transactional read-process-write pipeline (Kafka -> Kafka only).

    Reads from input_topic, transforms each message, writes to output_topic,
    and commits the consumer offset — all atomically within a single transaction.

    Failure model:
    - Crash before begin_transaction(): re-polls same messages, no harm done.
    - Crash during produce() calls: transaction not committed, broker cleans up.
      Consumer offset not advanced -> re-polls same messages on restart.
    - Crash before commit_transaction(): same as above. Idempotent retry.
    - Crash after commit_transaction(): transaction committed. Done.
    - commit_transaction() fails (network error): exception raised, we call
      abort_transaction(), consumer re-polls same messages. Idempotent retry.
    """

    def __init__(self, bootstrap_servers: str, group_id: str,
                 input_topic: str, output_topic: str):
        self.output_topic = output_topic
        self.group_id = group_id

        self.consumer = Consumer({
            "bootstrap.servers":  bootstrap_servers,
            "group.id":           group_id,
            "auto.offset.reset":  "earliest",
            # NEVER auto-commit in EOS. We commit inside the transaction.
            # Auto-commit would commit offsets outside the transaction boundary,
            # breaking the atomicity guarantee entirely.
            "enable.auto.commit": False,
            # Only read messages from committed transactions.
            # Without this, we'd process messages that might be rolled back by
            # another producer's aborted transaction.
            "isolation.level":    "read_committed",
        })

        self.producer = Producer({
            "bootstrap.servers":      bootstrap_servers,
            # Idempotent producer is a prerequisite for transactions.
            # It's automatically enabled when you set transactional.id,
            # but being explicit is clearer.
            "enable.idempotence":     True,

            # DETERMINISTIC ID — the most important EOS configuration.
            # This must be the same string across restarts of this logical producer.
            # Good: f"eos-processor-{hostname}" or f"eos-processor-{pod_name}"
            # Bad:  str(uuid.uuid4()) — new epoch every restart, no zombie fencing
            "transactional.id":       f"eos-processor-{group_id}",

            # If processing takes longer than this, the broker auto-aborts the
            # transaction. Your in-flight produces are rolled back and the consumer
            # offset is not committed. Set to (max expected batch processing time)
            # with a safety margin. Default is 60 seconds.
            "transaction.timeout.ms": 60000,
        })

        # init_transactions() MUST be called before begin_transaction().
        # It does two things:
        #   1. Registers this producer with the Transaction Coordinator broker.
        #   2. FENCES any prior producer instance with the same transactional.id
        #      by bumping the epoch. If a zombie from a previous crash tries to
        #      commit its transaction, it gets a ProducerFencedException and aborts.
        # This is the zombie fencing mechanism in action.
        self.producer.init_transactions()
        self.consumer.subscribe([input_topic])

    def run(self):
        while True:
            messages = self.consumer.consume(num_messages=50, timeout=1.0)
            if not messages:
                continue

            try:
                # Begin transaction. All produce() calls until commit or abort
                # are part of this transaction. The broker buffers them and only
                # makes them visible to read_committed consumers upon commit.
                self.producer.begin_transaction()

                for msg in messages:
                    if msg.error():
                        continue
                    result = self._transform(json.loads(msg.value()))
                    self.producer.produce(
                        topic=self.output_topic,
                        key=msg.key(),
                        value=json.dumps(result).encode(),
                    )

                # THIS IS THE KEY OPERATION FOR EOS.
                # send_offsets_to_transaction() registers the consumer offset
                # commit AS PART OF the current transaction.
                # When commit_transaction() succeeds, both the produced messages
                # AND the offset advance happen atomically.
                # When abort_transaction() is called, both are rolled back.
                # Without this, you'd have "at-least-once produce + at-least-once
                # offset commit" — NOT exactly-once.
                #
                # consumer_group_metadata() provides the group's generation ID
                # and member ID, which the broker uses to validate that this
                # consumer is still in the group (not a zombie from a rebalance).
                self.producer.send_offsets_to_transaction(
                    offsets=self._offsets_from_messages(messages),
                    group_metadata=self.consumer.consumer_group_metadata(),
                )

                # Atomic commit point. After this returns successfully,
                # the produced messages are visible to read_committed consumers,
                # and the consumer offset has advanced.
                self.producer.commit_transaction()

            except Exception as e:
                # abort_transaction() signals the broker to discard all buffered
                # produces from this transaction AND NOT advance the consumer offset.
                # The consumer will re-poll the same messages on the next iteration.
                # This makes the whole operation idempotent — retry is safe.
                self.producer.abort_transaction()
                print(f"Transaction aborted, will retry: {e}")

    def _transform(self, event: dict) -> dict:
        return {"processed": True, **event}

    @staticmethod
    def _offsets_from_messages(messages) -> list:
        offsets = {}
        for msg in messages:
            tp = (msg.topic(), msg.partition())
            # offset + 1 is the "next offset to consume", which is what Kafka
            # stores as the committed offset. This means "I have successfully
            # processed up to and including offset N, start me at N+1 next time."
            offsets[tp] = TopicPartition(msg.topic(), msg.partition(), msg.offset() + 1)
        return list(offsets.values())


def idempotent_upsert_to_db(conn, msg_topic: str, msg_partition: int,
                             msg_offset: int, payload: dict):
    """
    Idempotent write to an external DB sink.

    This is the correct pattern for Kafka->DB pipelines where true EOS
    (Kafka transactions) is not applicable. The deduplication key is derived
    from Kafka message metadata — globally unique per message across all time.

    Why topic+partition+offset is a perfect dedup key:
    - topic: globally unique topic name
    - partition: unique within the topic
    - offset: monotonically increasing, unique within a partition
    - Together: globally unique for every message ever produced

    The ON CONFLICT DO NOTHING clause makes duplicate delivery safe:
    - First delivery: INSERT succeeds, row written
    - Any subsequent delivery of same message: INSERT hits the UNIQUE constraint,
      DO NOTHING causes it to silently succeed (no error, no change)
    - Consumer commits offset -> no infinite retry

    Requires a unique constraint on the sink table:
        ALTER TABLE orders ADD COLUMN kafka_dedup_key TEXT;
        CREATE UNIQUE INDEX idx_orders_dedup ON orders(kafka_dedup_key);

    IMPORTANT NOTE ON CORRECTNESS:
    This achieves "effective exactly-once" from the perspective of your data model,
    but it's technically at-least-once delivery + idempotent consumer.
    The semantic difference: a true EOS system guarantees the message is processed
    exactly once at the system level. This approach processes it potentially many
    times, but only the first write has any effect. For most business requirements,
    these are equivalent.
    """
    dedup_key = f"{msg_topic}:{msg_partition}:{msg_offset}"
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO orders (id, user_id, amount, kafka_dedup_key)
            VALUES (%(id)s, %(user_id)s, %(amount)s, %(dedup_key)s)
            ON CONFLICT (kafka_dedup_key) DO NOTHING
        """, {**payload, "dedup_key": dedup_key})
        conn.commit()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SECTION 4: STREAM JOINS & AGGREGATIONS (Faust)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
#  TIME SEMANTICS — THE CONCEPTUAL FOUNDATION (KNOW THIS COLD)
#  ────────────────────────────────────────────────────────────────────────────
#  There are three different "times" in a streaming system, and they diverge
#  under real-world conditions. Which one you use determines whether your
#  analytics are correct.
#
#  EVENT TIME: when the event actually occurred (timestamp in the event payload).
#    Source: the device or service that generated the event.
#    Example: user clicked "Buy" at 14:32:07.
#    Characteristics: correct for analytics, but events arrive OUT OF ORDER.
#      A mobile user offline for 30 minutes might send events that are
#      30+ minutes old when their device reconnects.
#    Use for: revenue aggregation, user behavior analytics, billing,
#      anything where "when did this happen" matters for correctness.
#
#  PROCESSING TIME: when your consumer processed the message.
#    Source: the consumer's local clock at poll() time.
#    Characteristics: always monotonically increasing, no out-of-order events,
#      but WRONG for analytics when events arrive late.
#    Example: that "Buy" click from the offline user is processed at 15:02:00.
#      Processing time says it happened in the 15:00 window. Wrong.
#      It should be in the 14:30 window. Your revenue report is inaccurate.
#    Use for: SLA measurement (how fast is our pipeline?), monitoring lag.
#    NEVER use for: business metrics where historical accuracy matters.
#
#  INGESTION TIME: when the Kafka broker received the message.
#    Source: Kafka's broker timestamp (log.message.timestamp.type=LogAppendTime).
#    Characteristics: monotonically increasing within a partition (broker assigns it),
#      but still wrong for late-arriving events from offline devices.
#    Use for: debugging pipeline lag between event time and Kafka arrival time.
#
#  KEY INSIGHT FOR INTERVIEWS:
#  Event time is almost always what you want for analytics, but it requires you to
#  handle out-of-order events — which means watermarks and late data policy.
#  Processing time is what most simple implementations use by default, and most
#  interviewers will accept it unless you explicitly flag the limitation.
#  Flagging it proactively demonstrates Staff-level thinking.
#
#  WATERMARKS AND LATE DATA POLICY
#  ────────────────────────────────────────────────────────────────────────────
#  A watermark is a declaration: "I believe all events with timestamp < T have
#  arrived. I'm closing any windows that end before T."
#
#  Watermark = max_event_time_seen - allowed_lateness
#
#  Example: max event timestamp seen = 14:35:00, allowed lateness = 2 minutes
#    Watermark = 14:33:00
#    Any window ending before 14:33:00 can now be finalized and emitted.
#
#  WHAT HAPPENS TO LATE DATA (events that arrive after the watermark)?
#  Option 1: DROP late events. Simplest. Accept a small percentage of inaccuracy.
#            Right for: operational dashboards where approximate is fine.
#  Option 2: SIDE OUTPUT. Route late events to a separate topic/queue for
#            reconciliation. A batch job (Spark, Flink) periodically
#            reprocesses them and corrects the aggregate. Right for: billing,
#            financial reporting where correctness matters more than latency.
#  Option 3: UPDATE the window result. Re-emit a corrected aggregate when late data
#            arrives. More complex, requires downstream consumers to handle corrections.
#            Right for: real-time dashboards that need accuracy without batch jobs.
#
#  CHOOSING WATERMARK LATENESS:
#  Too tight (e.g., 10 seconds): many events arrive late -> high drop rate -> wrong results.
#  Too loose (e.g., 24 hours): windows stay open for a day -> enormous memory usage.
#  Typical production value: 1-5 minutes. Tune based on your p99 event delivery latency.
#
#  WINDOW TYPES — KNOW ALL THREE
#  ────────────────────────────────────────────────────────────────────────────
#  TUMBLING WINDOWS:
#    Fixed size, non-overlapping. Each event belongs to exactly ONE window.
#    [00:00-05:00) [05:00-10:00) [10:00-15:00) ...
#    Use for: periodic reports (revenue per 5 minutes), time-bucketed aggregations.
#    Example: "total orders per minute for billing"
#
#  HOPPING WINDOWS (Sliding Windows):
#    Fixed size, with a step interval smaller than the window size -> overlapping.
#    Window=10min, Hop=1min: [00:00-10:00) [01:00-11:00) [02:00-12:00) ...
#    Each event belongs to MULTIPLE windows (window_size/hop windows).
#    Use for: rolling averages, smoothed metrics for dashboards.
#    Example: "rolling 10-minute revenue, updated every minute"
#    Overhead: more state (window_size/hop x more windows to maintain).
#
#  SESSION WINDOWS:
#    Activity-based. A session starts with the first event and extends as long as
#    events keep arriving within the session gap (e.g., 30 minutes of inactivity
#    closes the session). Session lengths are variable.
#    Use for: user session analytics, click funnels, behavioral analysis.
#    Example: "user session duration" — session ends after 30min with no activity.
#    Hard to implement correctly in distributed streaming due to event ordering.
#
#  JOIN TYPES IN STREAMING — DIFFERENT FROM SQL
#  ────────────────────────────────────────────────────────────────────────────
#  SQL joins work on bounded datasets stored in memory. Streaming joins work on
#  UNBOUNDED data that arrives over time, potentially out of order. This changes
#  everything about how joins are implemented.
#
#  STREAM-STREAM JOIN:
#    Both sides are unbounded streams. Events arrive at different times.
#    Must buffer BOTH sides for a time window, waiting for the matching event.
#    Memory grows with the window size x event rate on both streams.
#    Co-partitioning REQUIRED: both streams must use the same partition key
#    (the join key) and the same number of partitions, so matching events for
#    the same key land on the same partition -> same consumer instance -> same state.
#    Use for: joining two event streams that may have different arrival times
#             but need to be correlated (orders + payments, clicks + impressions).
#
#  STREAM-TABLE JOIN (the better option for enrichment):
#    One side is a stream of events. The other side is a "table" — the latest
#    value per key, maintained by consuming a compacted Kafka topic.
#    The table lives in local memory/RocksDB on each consumer instance.
#    Join is an O(1) local lookup — no buffering, no window, no network hop.
#    Much cheaper than stream-stream for "enrichment" use cases.
#    Use for: enriching events with slowly-changing dimensions:
#             order stream + user profiles table, clickstream + product catalog.
#    GOTCHA: the table must bootstrap before events start arriving, or early
#    events are enriched with "unknown" values. Handle gracefully (see code).
#
#  CO-PARTITIONING — THE SILENT CORRECTNESS REQUIREMENT
#  ────────────────────────────────────────────────────────────────────────────
#  For stream-stream joins with local state, matching events MUST land on the
#  same partition, which means the same consumer instance's state store.
#
#  Two topics are co-partitioned when:
#    1. They have the same number of partitions.
#    2. They use the same partitioning scheme on the join key.
#       (i.e., order_id hashes to partition 3 in BOTH the orders and payments topics)
#
#  If topics are NOT co-partitioned:
#    - Order for order_id=42 lands on partition 3 of orders topic
#    - Payment for order_id=42 lands on partition 7 of payments topic
#    - They're processed by DIFFERENT consumer instances
#    - Each instance has only half the join — the join never fires
#    - Silently incorrect results (no error, just missing joins)
#
#  How to fix non-co-partitioned topics:
#    Use group_by() to repartition one or both streams by the join key.
#    group_by() produces to a new internal repartition topic with the correct
#    partition scheme, then continues processing from that topic.
#    Cost: one extra Kafka topic + extra produce/consume latency (~10-50ms).
#
#  STATE STORES (RocksDB) — OPERATIONAL CONSIDERATIONS
#  ────────────────────────────────────────────────────────────────────────────
#  Stream processing maintains state (join buffers, aggregation accumulators)
#  in a local state store. Faust uses RocksDB (an embedded LSM-tree key-value store).
#
#  RocksDB characteristics:
#  - Persists to local disk -> survives consumer restarts
#  - Backed up to Kafka changelog topics -> can be rebuilt on new instance
#  - Compaction runs in background -> write amplification, occasional latency spikes
#  - Memory usage = block cache size (tunable) + memtables
#
#  Key operational metrics to monitor:
#  - State store size (disk): should be bounded by window expiry settings
#  - RocksDB compaction lag: high compaction = processing latency spikes
#  - Changelog topic lag: how far behind the local state is from the changelog
#  - Restore time: how long to rebuild state on a new consumer instance
#    (matters for autoscaling speed and failure recovery time)
#
#  Common mistake: forgetting to set `expires` on windowed tables.
#  Without expiry, the state store grows indefinitely as windows accumulate.
#  On a busy topic, this can exhaust disk in hours.
#
#  FAUST VS KAFKA STREAMS VS FLINK — KNOW THE TRADEOFFS
#  ────────────────────────────────────────────────────────────────────────────
#  FAUST (Python, this file):
#  + Python-native, simple API, fast to prototype
#  + Asyncio-based, good for I/O-bound processing
#  - Not as battle-hardened as Kafka Streams at large scale
#  - Single-process (asyncio), not truly distributed (use multiple instances)
#  - Less mature windowing and join primitives
#  Use when: Python shop, simple joins/aggregations, moderate scale
#
#  KAFKA STREAMS (JVM / Java / Scala):
#  + Embedded library — no separate cluster, runs inside your app
#  + Production-grade, used at FAANG scale
#  + Rich windowing API (tumbling, hopping, session)
#  + First-class EOS support
#  - JVM only, Java/Scala API
#  - Embedded means you manage scaling (your app = the processing cluster)
#  Use when: JVM shop, production-grade stream processing, embedded preferred
#
#  APACHE FLINK:
#  + Distributed cluster — purpose-built for streaming at scale
#  + True event time with watermarks and out-of-order handling
#  + Complex Event Processing (CEP) — pattern matching across event streams
#  + First-class EOS, true exactly-once across heterogeneous sources/sinks
#  + Handles very large state (terabytes) with incremental checkpointing
#  - Separate cluster to operate (more infra complexity)
#  - Steeper learning curve, higher operational overhead at small scale
#  Use when: FAANG-scale, complex multi-stream joins, true event time matters,
#            CEP patterns, very large state
#
#  INTERVIEW ANSWER: name Flink for scale/correctness, Kafka Streams for
#  embedded/JVM, Faust for Python/simplicity. Show you know the tradeoffs.
#
#  INTERVIEW TALKING POINTS
#  ────────────────────────────────────────────────────────────────────────────
#  "The first thing I'd clarify is time semantics. If this is revenue aggregation
#  for billing, I need event time — processing time gives wrong numbers for mobile
#  users who go offline. That means I need watermarks to decide when to close
#  windows, and I need to define my late data policy up front. I'd use a 2-minute
#  watermark and route late events to a side output topic for batch reconciliation."
#
#  "For the orders + payments join, I'd verify both topics are co-partitioned by
#  order_id first. If they're not, I'd use group_by() to repartition — adds a
#  network hop but guarantees matching events land on the same consumer instance.
#  The join state lives in RocksDB locally, so the join lookup is O(1) local disk
#  read, not a network call."
#
#  "For enrichment with user profiles, I'd use a stream-table join rather than
#  stream-stream. The profiles topic is compacted — Kafka retains only the latest
#  value per user_id. I consume it to maintain a local table on each instance.
#  The join is an O(1) local dictionary lookup. The only gotcha is bootstrapping:
#  the table needs to be fully loaded before the order stream starts, or early
#  orders get enriched with 'unknown' profile data."
#
#  "For the processing framework choice at this scale: I'd recommend Flink over
#  Kafka Streams or Faust. Flink handles true event time with watermarks natively,
#  has robust exactly-once semantics across heterogeneous sources and sinks, and
#  its incremental checkpointing handles very large state without reprocessing
#  the entire log on recovery."
#
#  TRADEOFFS:
#  Event time vs processing time: event time = correct for analytics, requires
#    watermarks and OOO handling. Processing time = simple, wrong for late data.
#    Always flag this distinction in the interview.
#  Stream-stream vs stream-table join: stream-stream = bidirectional, higher memory,
#    requires co-partitioning. Stream-table = O(1) local lookup, cheaper, best for
#    enrichment with slow-changing data.
#  Tumbling vs hopping vs session: tumbling = non-overlapping, periodic reports.
#    Hopping = rolling averages, overlapping. Session = user activity, variable length.
#  Faust vs Kafka Streams vs Flink: Faust = Python, simple. KStreams = JVM, prod.
#    Flink = distributed, scale, event time, CEP. Know all three.
#  Tight vs loose watermark: tight = low latency, higher late data drop.
#    Loose = correct, higher memory. Tune to p99 event delivery latency.

import faust
from datetime import timedelta

app = faust.App(
    "order-analytics",
    broker="kafka://localhost:9092",
    # RocksDB: persistent state store backed by local disk + Kafka changelog.
    # Survives process restarts. Rebuilt from changelog on new instances.
    # Alternative: "memory://" for testing (lost on restart, no changelog).
    store="rocksdb://",
)


# ── Schema Definitions ────────────────────────────────────────────────────────
# Faust Records are typed dataclasses that handle serialization/deserialization.
# Define schemas here to catch field mismatches at consume time, not deep in logic.

class Order(faust.Record):
    order_id: str
    user_id:  str
    amount:   float
    # This is EVENT TIME — the timestamp from when the order was created on the client.
    # ALWAYS store this in your events. Without it, you cannot do event-time windowing.
    # If you only have processing time available, note this limitation explicitly.
    ts:       float  # epoch ms, event time (not processing time)


class Payment(faust.Record):
    payment_id: str
    order_id:   str
    status:     str  # "completed" | "failed" | "pending"
    ts:         float


class UserProfile(faust.Record):
    user_id: str
    tier:    str    # "gold" | "silver" | "standard"
    region:  str


orders_topic       = app.topic("orders",        value_type=Order)
payments_topic     = app.topic("payments",      value_type=Payment)
user_profile_topic = app.topic("user-profiles", value_type=UserProfile)
enriched_topic     = app.topic("enriched-orders")


# ── Stream-Stream Join: Orders + Payments ─────────────────────────────────────
#
# DESIGN: We maintain two state tables — one per stream.
# When an event arrives on EITHER stream, we write it to the corresponding table
# and check whether the matching event from the OTHER stream has already arrived.
# If both sides are present -> emit the joined result.
#
# This is a BIDIRECTIONAL join: either side can arrive first.
# Real world: payment webhooks often arrive before the order confirmation event
# (async payment processor + network timing). This handles both orderings.
#
# CO-PARTITIONING REQUIREMENT (CRITICAL):
# Both orders and payments topics MUST:
#   1. Have the same number of partitions (12 here)
#   2. Use order_id as the partition key with the same hash function
# This ensures order_id=42's order event AND payment event both land on partition 7,
# processed by the same consumer instance, stored in the same local RocksDB state.
# If they land on different partitions, different instances hold each half -> no join.
#
# STATE CLEANUP: after a successful join, we delete both sides from state.
# Without cleanup, state grows unbounded. In production, add a periodic TTL
# sweep to remove stale one-sided events (payment arrived but order never did).

order_state   = app.Table("order-state",   default=dict, partitions=12)
payment_state = app.Table("payment-state", default=dict, partitions=12)


@app.agent(orders_topic)
async def process_orders(orders):
    async for order in orders:
        # Write order to state store, keyed by order_id.
        # This makes it findable when the matching payment arrives later.
        order_state[order.order_id] = {"order": order.asdict()}

        # Check if payment for this order has already arrived.
        # If yes: emit the joined event immediately.
        # If no: the payment agent will check for the order when it arrives.
        if order.order_id in payment_state:
            await _emit_joined(order.order_id)


@app.agent(payments_topic)
async def process_payments(payments):
    async for payment in payments:
        payment_state[payment.order_id] = payment.asdict()

        if payment.order_id in order_state:
            await _emit_joined(payment.order_id)


async def _emit_joined(order_id: str):
    """
    Emit the joined event and clean up state.

    Called from whichever agent receives the SECOND side of the join.
    After emitting, delete both state entries to prevent state store bloat.

    PRODUCTION ADDITION: add a TTL-based cleanup sweep to handle cases where
    one side arrives but the other never does (payment for a cancelled order,
    order with no payment webhook). Without cleanup, these linger in state forever.
    """
    order   = order_state[order_id]["order"]
    payment = payment_state[order_id]
    await enriched_topic.send(
        key=order_id,
        value={**order, "payment": payment}
    )
    del order_state[order_id]
    del payment_state[order_id]


# ── Tumbling Window Aggregation: Revenue per User ─────────────────────────────
#
# Tumbling windows are non-overlapping, fixed-size time buckets.
# Each event belongs to exactly one window.
# [00:00-05:00) [05:00-10:00) [10:00-15:00) ...
#
# .tumbling(300) = 5-minute windows
# expires=timedelta(hours=1): Faust discards window state older than 1 hour.
#   This is ESSENTIAL to prevent RocksDB growing unbounded. Set expires to
#   at least 2x your longest expected event delivery latency.
#
# group_by(Order.user_id): repartitions the stream by user_id.
#   This creates a new internal Kafka topic (the repartition topic) and routes
#   all events for a given user_id to the same partition -> same consumer instance
#   -> same local state -> correct per-user aggregation without cross-instance coordination.
#   Cost: one extra Kafka produce+consume per event (~10-50ms latency).
#   Without group_by: events for the same user could land on different instances,
#   each seeing a partial view -> wrong aggregates.
#
# NOTE ON TIME SEMANTICS:
# Faust's tumbling windows use PROCESSING TIME by default (system clock at poll time).
# For production analytics where event time matters, you need a framework with
# native event-time windowing and watermark support (Flink, or Kafka Streams with
# TimeWindowedSerializer). Call this out in the interview and describe what you'd do.

revenue_per_user = (
    app.Table("revenue-per-user", default=float)
       .tumbling(300, expires=timedelta(hours=1))
)


@app.agent(orders_topic)
async def aggregate_revenue(orders):
    async for order in orders.group_by(Order.user_id):
        # += on a windowed table increments the current window's value.
        # Faust handles window selection based on processing time.
        revenue_per_user[order.user_id] += order.amount

        # .current() returns the value for the current processing-time window.
        current = revenue_per_user[order.user_id].current()

        # .delta(timedelta) returns the value from N time ago.
        # This is "what was the revenue 5 minutes ago in the previous window?"
        # Useful for growth rate calculations and anomaly detection.
        prev = revenue_per_user[order.user_id].delta(timedelta(minutes=5))

        if current > 10_000:
            # Alert: user has spent >$10K in the current 5-minute window.
            # In production: publish to an alerts topic, trigger fraud review.
            print(f"High-value user {order.user_id}: ${current:.2f} in 5min window")

        if prev and prev > 0:
            growth = (current - prev) / prev * 100
            print(f"User {order.user_id} revenue growth vs prev window: {growth:.1f}%")


# ── Stream-Table Join: Enrich Orders with User Profile ────────────────────────
#
# This is fundamentally different from the stream-stream join above.
# The user-profiles topic is LOG-COMPACTED:
#   Kafka retains only the LATEST value per user_id key, deleting older versions.
#   The topic acts as a persistent key-value store of "current profile per user."
#   This is the same mechanism as Kafka's table semantics in KSQL/Kafka Streams.
#
# We consume this compacted topic to build a local table (in RocksDB).
# Enrichment = O(1) local dictionary lookup. No network hop, no external DB query.
#
# This is MUCH cheaper than a stream-stream join because:
# - No windowed buffering needed (table always holds current value)
# - No co-partitioning required for the table (Faust handles it)
# - No state explosion (only one row per user, not N events per window)
#
# BOOTSTRAPPING PROBLEM:
# When the consumer starts, it must consume the ENTIRE user-profiles topic
# before it can correctly enrich orders. If we start enriching before the
# table is fully loaded, early orders get "unknown" profile data.
# Solutions:
#   1. Accept "unknown" and re-enrich later (simplest, acceptable for non-critical data)
#   2. Pause the orders consumer until the profile table is bootstrapped
#      (complex, but correct for billing/tier-based pricing)
#   3. Pre-load profiles from DB at startup, then keep updated via Kafka
#      (hybrid approach, good for moderate-sized datasets)

user_table = app.Table("user-profiles-table", default=UserProfile)


@app.agent(user_profile_topic)
async def maintain_user_table(profiles):
    """
    Keep the local user table current by consuming the compacted profiles topic.

    This agent runs continuously alongside the enrichment agent.
    When a user updates their profile, this agent updates the local table.
    The enrichment agent immediately sees the new value on next lookup.

    Because the profiles topic is compacted, bootstrapping this table on startup
    means consuming all retained records (one per user_id). Kafka ensures
    only the latest value per key is retained — no stale history to process.
    """
    async for profile in profiles:
        user_table[profile.user_id] = profile


@app.agent(orders_topic)
async def enrich_orders_with_profile(orders):
    """
    Enrich each incoming order with the user's tier and region.

    The user_table.get() call is a local RocksDB lookup — microsecond latency,
    no network call, no DB query. This is why stream-table join is the right
    pattern for enrichment: it scales linearly without any external dependency.

    HANDLING MISSING PROFILES:
    Use .get() (returns None if not found) rather than direct key access
    (raises KeyError if not found). A missing profile means either:
    1. The user-profiles table hasn't bootstrapped yet (startup race)
    2. The user profile was never created (data quality issue)
    3. The user_id in the order doesn't match any profile (join key mismatch)
    Log missing profiles for monitoring — a high miss rate indicates a problem.
    """
    async for order in orders:
        profile = user_table.get(order.user_id)

        if profile is None:
            print(f"WARNING: No profile found for user_id={order.user_id}. "
                  "Table may still be bootstrapping.")

        tier   = profile.tier   if profile else "unknown"
        region = profile.region if profile else "unknown"

        await enriched_topic.send(
            key=order.order_id,
            value={
                **order.asdict(),
                "user_tier":   tier,
                "user_region": region,
            }
        )


# ── Hopping Window: 10-minute rolling revenue, updated every minute ───────────
#
# Hopping (sliding) windows overlap. Each event contributes to MULTIPLE windows.
# Window=600s (10 min), Step=60s (1 min):
#   [00:00-10:00) updated at 01:00
#   [01:00-11:00) updated at 02:00
#   [02:00-12:00) updated at 03:00
#   ...
#
# This produces a new data point every minute showing "revenue over the past 10 minutes."
# Useful for: real-time dashboards, anomaly detection with smoothed signals,
#             rolling SLA calculations.
#
# Memory cost: hopping windows maintain window_size/step windows per key simultaneously.
# Here: 600/60 = 10 concurrent windows per user. At high user count, this adds up.
# Monitor state store size carefully with hopping windows on high-cardinality keys.

rolling_revenue = (
    app.Table("rolling-revenue", default=float)
       .hopping(size=600, step=60, expires=timedelta(hours=2))
)


@app.agent(orders_topic)
async def rolling_revenue_agg(orders):
    """
    Smoothed revenue signal: total revenue per user over the past 10 minutes,
    recalculated every minute. Downstream dashboards get a new data point every
    minute without the jagged spikes that come from tumbling windows.
    """
    async for order in orders.group_by(Order.user_id):
        # This increment applies to ALL active windows that contain the current time.
        # Faust handles the multi-window bookkeeping automatically.
        rolling_revenue[order.user_id] += order.amount


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PRODUCER CONFIG CHEAT SHEET
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
#  Choose your config based on the durability/throughput tradeoff for your use case.
#  High-throughput configs sacrifice some durability. High-durability configs
#  sacrifice some throughput. EOS configs sacrifice throughput for correctness.
#
#  TIMEOUT RELATIONSHIPS (memorize these — interviewers love to probe them):
#    heartbeat.interval.ms < session.timeout.ms / 3
#    max.poll.interval.ms  > (max processing time per poll batch) x 2
#
#  Example: processing each batch takes up to 30 seconds
#    max.poll.interval.ms  = 120000  (2 min — generous safety margin)
#    session.timeout.ms    = 30000   (heartbeat determines this, not processing time)
#    heartbeat.interval.ms = 10000   (must be < 30000/3 = 10000)

PRODUCER_CONFIGS = {
    "high_throughput": {
        # acks="1": only wait for the partition leader to write.
        # If leader crashes before replication, the message is lost.
        # Accept this risk for metrics, logs, and non-critical telemetry.
        "acks":             "1",
        "compression.type": "lz4",
        "linger.ms":        20,       # larger batch window = more batching
        "batch.size":       131072,   # 128KB batches
    },
    "high_durability": {
        # acks="all": wait for all ISR replicas. No data loss even if leader crashes.
        "acks":               "all",
        # Automatically sets acks=all and limits max.in.flight.requests.per.connection=5.
        # Deduplicates retries within a producer session using sequence numbers.
        "enable.idempotence": True,
        "retries":            10,
        "retry.backoff.ms":   500,
    },
    "exactly_once": {
        "enable.idempotence":     True,
        # DETERMINISTIC. Must be the same string across restarts of this logical producer.
        # Enables zombie fencing: new producer with same ID fences old zombie via epoch bump.
        "transactional.id":       "my-app-{instance-id}",
        "transaction.timeout.ms": 60000,
    },
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONSUMER CONFIG CHEAT SHEET
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CONSUMER_CONFIGS = {
    "standard": {
        # earliest: read from the beginning of the topic on first run.
        # latest: only read new messages arriving after subscription.
        # Use earliest for CDC, ETL, and any consumer that needs full history.
        # Use latest only for stateless real-time consumers (live notifications).
        "auto.offset.reset":             "earliest",
        # ALWAYS False. Auto-commit advances the offset on a timer regardless of
        # processing success. A crash after auto-commit but before downstream write
        # = silent data loss. Manual commit gives you control over the guarantee.
        "enable.auto.commit":            False,
        # Use cooperative-sticky for all production consumers.
        # Incremental rebalance: only moves minimum partitions needed for balance.
        # Avoids stop-the-world rebalances on every deployment.
        "partition.assignment.strategy": "cooperative-sticky",
        "session.timeout.ms":            30000,
        "heartbeat.interval.ms":         10000,   # must be < session.timeout / 3
        "max.poll.interval.ms":          300000,  # must be > max processing time per batch
    },
    "exactly_once_consumer": {
        "enable.auto.commit": False,
        # Skip messages from aborted transactions and in-flight uncommitted transactions.
        # Without this, you process messages that may be rolled back by their producer.
        # Adds a small amount of consumer lag (buffering at LSO instead of HW).
        "isolation.level":    "read_committed",
    },
    "high_throughput": {
        # fetch.min.bytes: wait until this many bytes are available before returning.
        # Reduces network round trips by fetching larger batches.
        "fetch.min.bytes":  65536,    # wait for at least 64KB
        # fetch.max.wait.ms: upper bound on how long to wait for fetch.min.bytes.
        # If 64KB isn't available after 500ms, return whatever is available.
        "fetch.max.wait.ms": 500,
        # Maximum messages returned per poll(). Set based on your processing capacity.
        "max.poll.records":  500,
    },
}