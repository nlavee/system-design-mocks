# Log Storage Service — System Design

## Table of Contents

1. [Requirements Clarification](#1-requirements-clarification)
2. [Back-of-Envelope Estimation](#2-back-of-envelope-estimation)
3. [API Design](#3-api-design)
4. [High-Level Architecture](#4-high-level-architecture)
5. [Detailed Design](#5-detailed-design)
6. [Deep Dives](#6-deep-dives)
7. [Failure Modes and Reliability](#7-failure-modes-and-reliability)
8. [Operational Concerns](#8-operational-concerns)

---

## 1. Requirements Clarification

### Functional Requirements

| Requirement | Detail |
|---|---|
| **Ingest logs** | Applications push structured or semi-structured log entries (timestamp, severity, service name, message, metadata). |
| **Query by time range** | "Give me all logs from service X between 10:00 and 10:15." |
| **Full-text search** | Keyword search within log messages (e.g., `"NullPointerException"`). |
| **Filtered queries** | Filter by structured fields: severity, service, host, region, custom tags. |
| **Aggregations / analytics** | Count errors per service over the last hour, P99 latency of log ingestion, time-series histograms. |
| **Retention policies** | Per-tenant configurable retention (e.g., 7 days hot, 30 days warm, 90 days cold archive). |
| **Tail / live streaming** | Ability to tail logs in near-real-time for debugging. |

### Non-Functional Requirements

| Requirement | Target |
|---|---|
| **Write availability** | Logs must never be dropped under normal operation. Prefer availability over consistency (AP system for writes). |
| **Write latency** | End-to-end ingest ≤ 5 seconds from emission to queryable. |
| **Query latency** | Simple time-range queries < 1 second. Full-text search < 5 seconds over a 1-hour window. |
| **Throughput** | Support 10 million log lines/second at peak across all tenants. |
| **Durability** | Zero data loss once acknowledged by the ingestion layer. |
| **Cost efficiency** | Storage cost must decrease as data ages (tiered storage). |
| **Multi-tenancy** | Strong isolation between tenants for both performance and data access. |

### Out of Scope

- Metrics collection (Prometheus/Datadog-style numeric time series).
- Distributed tracing (Jaeger/Zipkin-style span trees).
- Alerting engine (assumed to be a separate downstream consumer).

---

## 2. Back-of-Envelope Estimation

### Traffic

| Parameter | Value | Reasoning |
|---|---|---|
| Number of services | 5,000 | Large company with microservice architecture |
| Instances per service | 50 (average) | 250,000 total producers |
| Logs per instance per second | 40 (average) | Varies wildly; some services are chatty, some quiet |
| **Total ingestion rate** | **10 million logs/sec** | 250,000 × 40 |
| Average log line size | 500 bytes | Timestamp (8B) + severity (1B) + service (32B) + host (32B) + message (~300B) + metadata (~127B) |
| **Raw write throughput** | **5 GB/s** | 10M × 500B |

### Storage

| Parameter | Value |
|---|---|
| Raw data per day | 5 GB/s × 86,400 = **432 TB/day** |
| Compression ratio (zstd) | ~8:1 for log data (logs are highly repetitive) |
| Compressed data per day | **~54 TB/day** |
| Hot tier (7 days) | ~378 TB |
| Warm tier (30 days) | ~1.6 PB |
| Cold archive (90 days) | ~4.9 PB |
| Index overhead | ~15-20% of compressed data for inverted index |

> **Note on compression:** Log data compresses exceptionally well because of repeated patterns (timestamps, service names, severity levels, boilerplate messages). A ratio of 5:1 to 10:1 is typical with dictionary-based codecs like zstd. I'll use 8:1 as a reasonable middle estimate.

### Query Load

- ~10,000 queries/second across all tenants (mix of dashboards, manual searches, automated reports).
- Heavy tail: most queries hit the last 1-4 hours of data.

---

## 3. API Design

### Ingestion API

```
POST /v1/logs/ingest
Authorization: Bearer <api-key>
Content-Type: application/json

{
  "logs": [
    {
      "timestamp": "2025-01-15T10:32:01.123Z",
      "severity": "ERROR",
      "service": "payment-service",
      "host": "payment-prod-us-east-3a-i-0abc",
      "tags": {
        "region": "us-east-1",
        "version": "2.14.3",
        "trace_id": "abc123def456"
      },
      "message": "Failed to process payment: timeout after 30s connecting to stripe API"
    }
  ]
}
```

**Design decisions:**
- Batch endpoint (array of logs) to amortize HTTP overhead. Clients buffer locally and flush every ~1 second or every ~1000 lines.
- Returns `202 Accepted` — logs are durably enqueued but not yet queryable. This decouples ingestion latency from indexing latency.
- `timestamp` is provided by the client. The server records a separate `received_at` for clock-skew analysis but trusts client timestamps for ordering.

### Query API

```
POST /v1/logs/search
Authorization: Bearer <api-key>
Content-Type: application/json

{
  "start_time": "2025-01-15T10:00:00Z",
  "end_time": "2025-01-15T10:15:00Z",
  "query": "timeout AND service:payment-service AND severity:ERROR",
  "limit": 100,
  "cursor": "eyJvZmZzZXQiOjEwMH0=",
  "sort": "timestamp_desc"
}
```

**Response:**
```json
{
  "logs": [ ... ],
  "next_cursor": "eyJvZmZzZXQiOjIwMH0=",
  "total_matched": 4832,
  "scanned_bytes": "2.1 GB",
  "elapsed_ms": 342
}
```

**Design decisions:**
- Cursor-based pagination, not offset-based, because the underlying data is append-only and new logs arrive continuously.
- `scanned_bytes` returned for cost attribution in multi-tenant environments (similar to how BigQuery charges per bytes scanned).
- Time range is **required**. Unbounded scans are prohibitively expensive and are rejected at the API layer.

### Aggregation API

```
POST /v1/logs/aggregate
{
  "start_time": "2025-01-15T09:00:00Z",
  "end_time": "2025-01-15T10:00:00Z",
  "filter": "severity:ERROR",
  "group_by": ["service"],
  "aggregation": "count",
  "interval": "5m"
}
```

Returns time-bucketed counts grouped by service — the kind of data that powers dashboards.

### Live Tail API

```
GET /v1/logs/tail?filter=service:payment-service&severity=ERROR
Upgrade: websocket
```

Server-sent events (SSE) or WebSocket stream of matching log lines as they are ingested.

---

## 4. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          APPLICATION LAYER                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                              │
│  │ Service A │  │ Service B │  │ Service C │  ...  (250,000 instances)   │
│  │ + Agent   │  │ + Agent   │  │ + Agent   │                            │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                              │
└───────┼──────────────┼──────────────┼───────────────────────────────────┘
        │              │              │
        ▼              ▼              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        INGESTION LAYER                                  │
│                                                                         │
│   ┌──────────────────────────────────────────────────────────┐          │
│   │              Load Balancer (L4 / NLB)                    │          │
│   └──────────────────────┬───────────────────────────────────┘          │
│                          │                                              │
│   ┌──────────────────────▼───────────────────────────────────┐          │
│   │           Ingestion Gateway (stateless, N replicas)      │          │
│   │   - Authentication / rate limiting                       │          │
│   │   - Schema validation                                    │          │
│   │   - Tenant identification                                │          │
│   │   - Assigns partition key (tenant + service + minute)    │          │
│   └──────────────────────┬───────────────────────────────────┘          │
│                          │                                              │
│   ┌──────────────────────▼───────────────────────────────────┐          │
│   │                  Kafka Cluster                            │          │
│   │   - Topic: "raw-logs" (partitioned by tenant+service)    │          │
│   │   - Replication factor: 3                                │          │
│   │   - Retention: 72 hours (buffer for reprocessing)        │          │
│   │   - Multiple clusters across regions                     │          │
│   └──────────────────────┬───────────────────────────────────┘          │
└──────────────────────────┼──────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        PROCESSING LAYER                                 │
│                                                                         │
│   ┌──────────────────────────────────────────────────────────┐          │
│   │           Indexing Workers (consumer group)               │          │
│   │   - Parse and normalize log fields                       │          │
│   │   - Build inverted index segments                        │          │
│   │   - Build columnar segments (for aggregations)           │          │
│   │   - Write to hot storage                                 │          │
│   └──────────────────────┬───────────────────────────────────┘          │
│                          │                                              │
│   ┌──────────────────────▼───────────────────────────────────┐          │
│   │           Compaction Workers (background)                 │          │
│   │   - Merge small segments into larger ones                │          │
│   │   - Optimize indexes                                     │          │
│   │   - Tier data from hot → warm → cold                     │          │
│   └──────────────────────────────────────────────────────────┘          │
└──────────────────────────┼──────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         STORAGE LAYER                                   │
│                                                                         │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────────┐           │
│  │   HOT TIER     │  │   WARM TIER    │  │   COLD TIER      │           │
│  │ (Local SSD +   │  │ (Object Store  │  │ (Object Store    │           │
│  │  memory cache) │  │  e.g. S3)      │  │  + Glacier/IA)   │           │
│  │ Last 4-24 hrs  │  │ 1-30 days      │  │ 30-90+ days      │           │
│  │ Fast queries   │  │ Moderate speed  │  │ Slow, cheap      │           │
│  └────────────────┘  └────────────────┘  └──────────────────┘           │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────┐           │
│  │              Metadata Store (PostgreSQL / ZooKeeper)      │           │
│  │   - Segment catalog: which segments exist, time ranges   │           │
│  │   - Tenant configs: retention, quotas                    │           │
│  │   - Schema registry: field mappings                      │           │
│  └──────────────────────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          QUERY LAYER                                    │
│                                                                         │
│   ┌──────────────────────────────────────────────────────────┐          │
│   │              Query Frontend                               │          │
│   │   - Parse query, plan execution                          │          │
│   │   - Identify which segments to scan (time-based pruning) │          │
│   │   - Fan out to Query Workers                             │          │
│   └──────────────────────┬───────────────────────────────────┘          │
│                          │                                              │
│   ┌──────────────────────▼───────────────────────────────────┐          │
│   │           Query Workers (stateless, N replicas)           │          │
│   │   - Scan segments in parallel                            │          │
│   │   - Apply filters, full-text matching                    │          │
│   │   - Compute partial aggregations                         │          │
│   │   - Return results to frontend for merge                 │          │
│   └──────────────────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Why This Architecture?

**Separation of write and read paths.** Logs are a write-heavy workload (10M writes/sec vs ~10K queries/sec). By decoupling ingestion from query serving, we can scale each independently and optimize them for their respective access patterns.

**Kafka as the durable buffer.** Kafka provides:
- **Durability** — once a log is acknowledged by Kafka (acks=all, replication factor 3), it will not be lost even if downstream indexing workers crash.
- **Backpressure absorption** — traffic spikes (e.g., a bug causing a service to log 100x more) are absorbed by Kafka without overwhelming the indexing pipeline.
- **Replayability** — if we discover a bug in the indexing logic, we can replay from Kafka's 72-hour retention window to rebuild indexes.
- **Fan-out** — multiple consumers can read the same data (indexing workers, live-tail service, anomaly detection, etc.).

**Time-partitioned segments.** All data is organized into segments by time (e.g., 10-minute or 1-hour chunks). This is the single most important design decision because:
- Queries almost always include a time range, so we can prune entire segments without reading them.
- Retention is trivially implemented by deleting old segments.
- Compaction and tiering operate on entire segments.

---

## 5. Detailed Design

### 5.1 Log Collection Agent

Each application host runs a lightweight agent (think Fluentd, Vector, or Filebeat).

**Responsibilities:**
1. **Buffer locally** — writes to a local write-ahead log (WAL) on disk before sending. If the network is down, the agent retains logs locally and retries with exponential backoff.
2. **Batch and compress** — accumulates logs for up to 1 second or 1 MB (whichever comes first), compresses with LZ4 (chosen for its fast compression speed — ~4 GB/s encode rate on modern CPUs — since the agent runs alongside application workloads and must not steal CPU).
3. **Add metadata** — stamps each log with host ID, region, availability zone from instance metadata.
4. **Backpressure signaling** — if the local WAL exceeds a threshold (e.g., 1 GB), the agent signals the application to reduce log verbosity (e.g., drop DEBUG logs). This prevents disk exhaustion.

**Why an agent instead of direct SDK calls?**
- The agent isolates the application from networking concerns (retries, buffering, batching).
- A single agent per host reduces the number of connections to the ingestion gateway (50 connections per host vs. 50 per process).
- The agent can be updated independently of application deploys.

### 5.2 Ingestion Gateway

Stateless HTTP/gRPC service behind a load balancer.

**Request processing pipeline:**
1. **Authenticate** — validate API key, resolve tenant ID. Use a local cache of API keys refreshed every 30 seconds to avoid per-request database lookups.
2. **Rate limit** — per-tenant token bucket. If a tenant exceeds their quota, return `429 Too Many Requests`. Rate limit state is stored in a shared Redis cluster using the token bucket algorithm. We allow short bursts (bucket size = 2× sustained rate) because log traffic is inherently bursty.
3. **Validate** — check required fields (timestamp, message). Reject malformed logs with `400 Bad Request`. Do not silently drop.
4. **Assign partition key** — `hash(tenant_id + service_name) % num_partitions`. This ensures logs from the same tenant+service land on the same Kafka partition, which preserves ordering within a service and enables efficient segment building downstream.
5. **Produce to Kafka** — with `acks=all` and `min.insync.replicas=2`. Return `202 Accepted` to the client only after Kafka acknowledges.

**Scaling:** The gateway is stateless. Scale horizontally behind an L4 load balancer. At 5 GB/s raw throughput, with each gateway instance handling ~500 MB/s (limited by network), we need ~10 gateway instances (plus headroom).

### 5.3 Indexing Pipeline

Consumer group reading from Kafka. Each consumer builds **segments**.

#### Segment Structure

A segment is the fundamental storage unit. Each segment covers a specific **time window** (e.g., 10 minutes) for a specific **tenant + service** combination.

```
segment/
├── meta.json              # time range, tenant, service, row count, size
├── data.parquet           # columnar storage of all log fields
├── index/
│   ├── inverted_index.idx # term → [row_ids] for full-text search
│   ├── bloom_filters.bf   # per-field bloom filters for quick negative lookups
│   └── min_max.idx        # min/max per column per row group (for predicate pushdown)
└── timestamps.idx         # sorted timestamp index for binary search
```

**Why this hybrid format?**

- **Columnar (Parquet)** for aggregation queries: "count errors per service" only reads the `severity` and `service` columns, skipping the bulky `message` column entirely. Parquet's columnar layout also compresses far better than row-oriented formats because values within a column are similar (e.g., a column of severity values is mostly "INFO" with occasional "ERROR").
- **Inverted index** for full-text search: maps each unique term to the set of row IDs containing it. This is the same approach used by Lucene/Elasticsearch. For a query like `"NullPointerException AND payment-service"`, we intersect the posting lists for both terms.
- **Bloom filters** for structured field lookups: before scanning a segment for `host:web-prod-42`, check the bloom filter. If it says the host isn't in this segment, skip entirely. Bloom filters use ~10 bits per element for a 1% false positive rate — negligible space for significant I/O savings.
- **Min/max index** for range pruning: each row group stores the min and max timestamp. A query for 10:05–10:10 can skip row groups whose max timestamp < 10:05 or min timestamp > 10:10.

#### Indexing Flow

```
Kafka consumer reads batch of messages
    │
    ▼
Parse and validate each log line
    │
    ▼
Buffer in memory, grouped by (tenant, service, time_window)
    │
    ▼
When buffer reaches threshold (size ≥ 64 MB or time_window closes):
    │
    ▼
Build segment:
  1. Sort rows by timestamp
  2. Write columnar data (Parquet)
  3. Build inverted index from message + tag fields
  4. Compute bloom filters for structured fields
  5. Compute min/max indexes
  6. Compress everything with zstd (level 3 — good compression/speed tradeoff)
    │
    ▼
Upload segment to storage:
  1. Write to local SSD (hot tier)
  2. Register segment in metadata store (PostgreSQL)
  3. Commit Kafka offset
```

**Critical correctness point:** We commit the Kafka offset **after** the segment is durably written and registered. If the indexing worker crashes before committing, it will re-read and re-index the same messages — this is safe because segment writes are idempotent (same input produces the same segment, and we use a deterministic segment ID based on content hash).

### 5.4 Storage Tiers

| Tier | Medium | Data Age | Query Latency | Cost/TB/month | Access Pattern |
|---|---|---|---|---|---|
| **Hot** | Local NVMe SSD + memory-mapped files | 0–24 hours | < 100 ms | ~$100 (provisioned SSD) | Random reads for search, sequential for tail |
| **Warm** | Object store (S3 Standard) | 1–30 days | 200 ms – 2 s | ~$23 | Mostly sequential scans with predicate pushdown |
| **Cold** | Object store (S3 IA / Glacier IR) | 30–90+ days | 2–60 s | ~$4–10 | Rare, large forensic scans |

> Cost estimates are based on publicly listed AWS S3 pricing as of 2024. Actual costs vary by region and negotiated discounts.

**Tier transition (compaction workers):**
- A background compaction process monitors segment age.
- When a segment ages past the hot tier threshold, the compaction worker:
  1. Merges small segments from the same time window into larger ones (improves query efficiency by reducing the number of segments to scan).
  2. Re-compresses with zstd level 9 (slower to compress but ~20% smaller than level 3 — worth it for data that will sit in storage for weeks).
  3. Uploads the merged segment to S3.
  4. Updates the metadata store to point to the new segment location.
  5. Deletes the old hot-tier segments from local SSD.
- For cold tier transitions, the compaction worker additionally drops the inverted index (full-text search on 90-day-old logs is rare; if needed, we rebuild it on-demand) and moves to cheaper storage classes.

### 5.5 Query Execution

The query layer follows a **scatter-gather** pattern.

#### Query Frontend

1. **Parse query** — extract time range, structured filters, free-text terms.
2. **Consult metadata store** — find all segments overlapping the query's time range for the target tenant.
3. **Prune segments** — use bloom filters and min/max indexes (cached in memory at the query frontend) to eliminate segments that cannot possibly match.
4. **Plan execution** — divide remaining segments among query workers. Assign segments to workers that have them in local cache when possible (affinity-based routing).
5. **Fan out** — send sub-queries to query workers in parallel.
6. **Merge results** — merge-sort partial results by timestamp, apply limit, return to client.

#### Query Worker

Each query worker:
1. Fetches the segment (from local SSD cache, or downloads from S3 with range reads).
2. Applies **predicate pushdown**: use bloom filters and min/max to skip row groups.
3. For full-text queries: intersects posting lists from the inverted index.
4. For structured filters: uses Parquet column statistics and dictionary encoding for fast evaluation.
5. For aggregations: computes partial aggregates and returns them (not raw rows).

#### Query Optimization Techniques

**Caching:**
- Query workers maintain an LRU cache of recently accessed segments on local SSD.
- The query frontend uses consistent hashing to route queries about the same time range to the same set of workers, maximizing cache hit rate.
- Aggregation results for completed time windows (e.g., "errors per minute for 10:00–10:01" which will never change) are cached at the frontend level.

**Early termination:**
- For `LIMIT N` queries, once N results are found, cancel remaining sub-queries.
- For `COUNT` aggregations with no group-by, use segment metadata (row count, bloom filters) to answer without scanning data.

**Concurrency control:**
- Each tenant gets a query concurrency limit (e.g., 20 concurrent queries). This prevents one tenant from monopolizing cluster resources.
- Queries that scan too much data (> configurable threshold, e.g., 100 GB) are rejected or queued for batch execution.

### 5.6 Live Tail

For the real-time log tailing feature:

```
Client (WebSocket) ──→ Tail Service ──→ Kafka Consumer (dedicated group)
```

The Tail Service:
1. Subscribes to the relevant Kafka partitions for the tenant+service being tailed.
2. Applies the user's filter in-memory as logs flow through.
3. Pushes matching logs to the client over WebSocket.

This reads directly from Kafka rather than the indexed storage, so there's no indexing delay. The tail service is stateless — if it crashes, the client reconnects and resumes from the latest offset.

**Resource protection:** Each tail session consumes one Kafka consumer connection and CPU for filtering. We limit each tenant to a reasonable number of concurrent tail sessions (e.g., 10).

### 5.7 Multi-Tenancy

Multi-tenancy is a staff-level concern because it touches every layer:

| Layer | Isolation Mechanism |
|---|---|
| Ingestion Gateway | Per-tenant rate limiting (token bucket in Redis) |
| Kafka | Separate Kafka topics per large tenant; shared topics with partition-level isolation for smaller tenants |
| Indexing | Segments are always tenant-scoped — a segment never mixes data from different tenants |
| Storage | Tenant ID is part of the segment path: `s3://logs/{tenant_id}/{service}/{date}/{segment_id}` |
| Query | Per-tenant concurrency limits; query cost tracking (bytes scanned) |
| Metadata | Row-level security in the metadata store; all queries include `WHERE tenant_id = ?` |

**Noisy neighbor mitigation:**
- If a tenant is ingesting at 10× their normal rate (e.g., a runaway debug log), the ingestion gateway enforces their rate limit.
- If a tenant's query is consuming excessive resources, the query worker can preempt it in favor of other tenants' queries (using a fair-share scheduler).

---

## 6. Deep Dives

### 6.1 Handling Write Spikes and Backpressure

Log traffic is inherently bursty. A single deployment, incident, or retry storm can cause 10-100× normal volume.

**Multi-layered defense:**

```
Layer 1: Agent local buffer (1 GB disk WAL)
         ↓ overflows after minutes
Layer 2: Ingestion gateway rate limiter (per-tenant)
         ↓ rejects excess with 429
Layer 3: Kafka (72-hour retention, partitioned)
         ↓ absorbs hours of backlog
Layer 4: Indexing workers (auto-scaled consumer group)
         ↓ scales up to work through backlog
Layer 5: Degraded mode — drop DEBUG/TRACE severity, keep ERROR/WARN
```

**Auto-scaling the indexing pipeline:**
- Indexing workers monitor their Kafka consumer lag (how far behind they are).
- If lag exceeds a threshold (e.g., 5 minutes behind), the orchestrator (Kubernetes HPA with custom metrics) scales up worker pods.
- Workers are stateless (they write segments to storage, not local state), so scaling is fast — a new worker just picks up unassigned Kafka partitions.

**Graceful degradation:**
- When total system load exceeds capacity, the ingestion gateway activates **severity-based shedding**: accept all ERROR and WARN logs, sample INFO logs at 10%, drop DEBUG and TRACE entirely.
- This is configured per-tenant so that a spike from one tenant doesn't affect others.
- Shedding decisions are recorded in a special metadata field so that query results can indicate "this time period had sampling applied."

### 6.2 Storage Engine: Segment Design Deep Dive

The segment format is inspired by approaches used in Apache Druid (time-partitioned columnar segments) and Elasticsearch (inverted indexes), combined into a single unit.

#### Why Not Just Use Elasticsearch?

Elasticsearch is a powerful choice, but at this scale it has limitations:
- **JVM heap pressure** — Elasticsearch stores field data and segment metadata on the JVM heap. At petabyte scale, the heap management becomes a significant operational burden.
- **Storage coupling** — Elasticsearch tightly couples compute and storage. Each node stores its own shard data. Scaling storage requires adding nodes (and therefore compute). A disaggregated design (stateless compute + object store) is more cost-efficient at this scale.
- **Index-everything model** — Elasticsearch indexes every field by default, which is wasteful for high-cardinality fields like trace IDs or request IDs that are rarely searched.

Our custom segment design allows:
- **Selective indexing** — only build inverted indexes for fields that are actually searched. A trace ID field can be stored in Parquet (for retrieval) without an inverted index (for search).
- **Disaggregated compute/storage** — segments on S3 can be read by any query worker. No shard assignment, no rebalancing.
- **Optimized for append-only** — logs are never updated or deleted individually. Segments are immutable once written. This simplifies concurrency (no locking, no MVCC) and enables aggressive caching.

#### Segment Compaction Strategy

Small segments (from frequent flushes during spikes) hurt query performance because each segment requires a separate file open + index lookup. Compaction merges them:

```
Before compaction (10-minute window, one service):
  seg_001.parquet  (12 MB, 50K rows)
  seg_002.parquet  (8 MB, 35K rows)
  seg_003.parquet  (15 MB, 60K rows)
  ... 20 more small segments

After compaction:
  seg_merged_001.parquet  (180 MB, 800K rows)
  (single segment with rebuilt indexes)
```

Compaction is triggered when the number of segments for a given time window exceeds a threshold (e.g., > 10 segments). It runs as a background job with lower priority than ingestion.

### 6.3 Query Execution Deep Dive

Let's trace a realistic query:

**Query:** "Show me all ERROR logs from `payment-service` in `us-east-1` containing 'timeout' in the last 2 hours."

```sql
-- Internally translated to:
SELECT * FROM logs
WHERE tenant_id = 'acme'
  AND timestamp >= NOW() - INTERVAL '2 hours'
  AND severity = 'ERROR'
  AND service = 'payment-service'
  AND tags.region = 'us-east-1'
  AND message CONTAINS 'timeout'
ORDER BY timestamp DESC
LIMIT 100
```

**Execution plan:**

1. **Time pruning:** 2-hour window → ~12 segments (10-min segments) for this tenant+service.
2. **Bloom filter check:** For each segment, check bloom filters for `severity=ERROR`, `service=payment-service`, `region=us-east-1`. Segments where any bloom filter returns negative are skipped. This might eliminate 2-3 segments that only contain INFO/DEBUG logs.
3. **Remaining ~9 segments** are assigned to query workers (3 workers, 3 segments each).
4. Each query worker, per segment:
   a. Opens the inverted index, looks up the posting list for "timeout" → `[row_15, row_42, row_88, ...]`
   b. Opens the Parquet file, reads only the `severity`, `service`, `tags.region` columns for those row IDs.
   c. Filters to rows where `severity=ERROR AND service=payment-service AND region=us-east-1`.
   d. For matching rows, reads the full row (all columns) to return to the client.
5. **Query frontend** merge-sorts results from all workers by timestamp descending, takes top 100.

**Performance estimate:**
- 9 segments × ~180 MB each = ~1.6 GB total data.
- With column pruning (only read 3 columns out of ~8): ~400 MB actually read.
- With inverted index (only scan rows containing "timeout"): ~40 MB actually read.
- From hot-tier SSD at 3 GB/s read speed: ~13 ms for I/O.
- Total with CPU overhead for decompression and filtering: ~100-300 ms.

### 6.4 Schema Evolution

Over time, services add new fields to their logs. The system must handle this gracefully.

**Schema-on-read approach:**
- Segments are self-describing (Parquet files embed their schema).
- New fields appear in new segments without requiring migration of old segments.
- Queries against old segments simply return `null` for fields that didn't exist yet.
- The schema registry in the metadata store tracks the union of all observed fields per service, enabling autocomplete in the query UI.

**Field type conflicts:**
- If service A logs `user_id` as a string and service B logs `user_id` as an integer, the ingestion pipeline detects the conflict and either:
  - Coerces to string (the universal type), or
  - Namespaces the field: `serviceA.user_id` (string) vs `serviceB.user_id` (integer).
- The schema registry flags conflicts for operators to resolve.

---

## 7. Failure Modes and Reliability

### Failure Scenarios and Mitigations

| Failure | Impact | Mitigation |
|---|---|---|
| **Agent crashes** | Logs on that host are temporarily unbuffered | Agent WAL is on disk; on restart, it replays unsent logs. Application can also write to stdout, which a host-level log collector captures as a fallback. |
| **Ingestion gateway down** | Agents cannot send logs | Multiple gateway instances behind LB. Agents retry with exponential backoff. Agent WAL prevents data loss during outage. |
| **Kafka broker failure** | Partition temporarily unavailable | Replication factor 3, min.insync.replicas=2. Can tolerate 1 broker failure per partition with no data loss. Automatic leader election recovers in seconds. |
| **Indexing worker crash** | Backlog builds in Kafka | Consumer group rebalances partitions to remaining workers. No data loss because Kafka offset is committed only after segment write. HPA scales up replacements. |
| **Hot storage (SSD) failure** | Recently indexed data unavailable | Segments are uploaded to S3 asynchronously. After SSD failure, queries fall back to S3 (higher latency). On recovery, repopulate SSD cache from S3. |
| **S3 outage** | Warm/cold tier queries fail | S3 has 99.99% availability SLA. For critical tenants, replicate segments to a second region. During outage, hot tier queries (last 24h) still work. |
| **Metadata store (PostgreSQL) down** | Cannot discover segments for queries | PostgreSQL runs in HA configuration (primary + synchronous standby). Failover in ~30 seconds. Query layer caches recent metadata to serve queries during brief outages. |
| **Query worker overload** | Queries time out | Circuit breaker pattern: if a query worker exceeds capacity, the frontend routes to others. Shed load by rejecting low-priority (batch) queries first. |

### Data Durability Guarantees

The write path provides **at-least-once delivery** with **exactly-once semantics** for storage:

1. Agent → Gateway: retried until `202 Accepted`. Duplicate detection via log ID (hash of timestamp + host + message).
2. Gateway → Kafka: `acks=all` ensures the message is replicated before acknowledgment.
3. Kafka → Indexing → Storage: offset committed after segment write. Re-processing produces identical segments (idempotent).

---

## 8. Operational Concerns

### 8.1 Monitoring the Monitor

A log storage service must monitor itself without creating a circular dependency (logging about logging).

**Approach:**
- **Separate, lightweight metrics pipeline** for internal monitoring (Prometheus + Grafana or equivalent). This is a numeric time-series system, not the log system itself.
- Key metrics:
  - `ingestion_rate` (logs/sec, bytes/sec) per tenant
  - `kafka_consumer_lag` per partition (triggers auto-scaling)
  - `segment_build_duration_p99` (tracks indexing performance)
  - `query_latency_p50/p99` by query type
  - `storage_usage_bytes` by tier and tenant
  - `error_rate` at each layer

- **Alerting triggers:**
  - Consumer lag > 10 minutes → page on-call
  - Ingestion error rate > 1% → page on-call
  - Storage usage > 80% capacity → warning to capacity planning

### 8.2 Cost Optimization

At petabyte scale, storage cost dominates.

| Strategy | Savings |
|---|---|
| Tiered storage (hot → warm → cold) | 5-10× reduction as data ages |
| Zstd compression (level 3 hot, level 9 warm) | 8:1 compression vs raw |
| Columnar format (Parquet) | Queries read only needed columns, reducing I/O and compute |
| Dropping inverted indexes in cold tier | ~15-20% storage savings per segment |
| Per-tenant retention policies | Tenants pay for what they use |
| Sampling on ingest (for high-volume tenants) | Reduce volume at source |

### 8.3 Security

| Concern | Approach |
|---|---|
| **Authentication** | API keys scoped per tenant. Keys rotated periodically. mTLS between internal services. |
| **Authorization** | RBAC: viewers can query, admins can configure retention/quotas. Tenant data is strictly isolated at every layer. |
| **Encryption at rest** | S3 server-side encryption (AES-256). Hot-tier SSDs use dm-crypt / LUKS. |
| **Encryption in transit** | TLS 1.3 everywhere — agent to gateway, gateway to Kafka, query frontend to workers. |
| **PII in logs** | Ingestion pipeline can run a configurable redaction step (regex-based or ML-based) to mask sensitive fields (credit card numbers, emails, etc.) before indexing. |
| **Audit trail** | All queries are logged (who queried what, when) for compliance. |

### 8.4 Multi-Region Deployment

For global organizations:

```
Region A (us-east-1)              Region B (eu-west-1)
┌──────────────────┐              ┌──────────────────┐
│ Ingestion        │              │ Ingestion        │
│ Kafka            │              │ Kafka            │
│ Indexing          │              │ Indexing          │
│ Hot Storage      │              │ Hot Storage      │
│ Query Layer      │              │ Query Layer      │
└────────┬─────────┘              └────────┬─────────┘
         │                                 │
         └────────┬────────────────────────┘
                  │
         ┌────────▼─────────┐
         │  Shared S3       │
         │  (warm + cold)   │
         │  Cross-region    │
         │  replication     │
         └──────────────────┘
```

- Logs are ingested and indexed in the region where they originate (data locality).
- The warm/cold tier on S3 can be cross-region replicated for disaster recovery.
- Queries are served by the local region's query layer. Cross-region queries (rare) are federated: the query frontend fans out to query workers in both regions.
- Data residency compliance (e.g., GDPR): European logs stay in `eu-west-1` and are never replicated to US regions. This is enforced by tenant configuration in the metadata store.

---

## Summary

| Design Decision | Rationale |
|---|---|
| Kafka as ingestion buffer | Durability, backpressure absorption, replayability |
| Time-partitioned immutable segments | Efficient time-range pruning, simple retention, cache-friendly |
| Hybrid columnar + inverted index format | Optimized for both analytics (aggregations) and search (full-text) |
| Disaggregated compute and storage | Scale independently, cost-efficient at PB scale |
| Multi-tiered storage (hot/warm/cold) | Match storage cost to access frequency |
| Scatter-gather query execution | Parallel scanning, horizontal scalability |
| Per-tenant isolation at every layer | Prevent noisy neighbors, enable per-tenant billing |
| Schema-on-read | Handle evolving log formats without migrations |
| Agent-based collection with local WAL | Never lose logs, decouple app from transport |
