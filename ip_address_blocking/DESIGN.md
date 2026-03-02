# Global IP Address Blocking System — Staff-Level System Design

## Table of Contents

1. [Requirements Clarification](#1-requirements-clarification)
2. [Back-of-the-Envelope Estimation](#2-back-of-the-envelope-estimation)
3. [High-Level Architecture](#3-high-level-architecture)
4. [Detailed Component Design](#4-detailed-component-design)
5. [Data Structures for IP Matching](#5-data-structures-for-ip-matching)
6. [Data Flow & Propagation](#6-data-flow--propagation)
7. [API Design](#7-api-design)
8. [Storage & Schema Design](#8-storage--schema-design)
9. [Operational Concerns](#9-operational-concerns)
10. [Trade-offs & Alternative Approaches](#10-trade-offs--alternative-approaches)
11. [Interview Discussion Extensions](#11-interview-discussion-extensions)

---

## 1. Requirements Clarification

Before diving into design, we need to establish clear functional and non-functional requirements. In an interview, this phase demonstrates structured thinking and ensures alignment with the interviewer.

### Functional Requirements

| # | Requirement | Details |
|---|-------------|---------|
| FR-1 | **Government API Integration** | Ingest IP blocklists from multiple government APIs (per-country). Each government may provide its own API format, authentication method, and update cadence. |
| FR-2 | **IPv4 and IPv6 Support** | Handle the full IPv4 (32-bit) and IPv6 (128-bit) address spaces. Blocklists may contain individual IPs, CIDR ranges (e.g., `203.0.113.0/24`), or prefix ranges. |
| FR-3 | **Region-Specific Blocking** | Different regions/countries have different blocklists. A request entering via a Tokyo PoP may have different blocking rules than one entering via a Frankfurt PoP. |
| FR-4 | **Request-Level Enforcement** | Every inbound request must be checked against the applicable blocklist before any further processing. Blocked requests receive an appropriate HTTP response (e.g., `403 Forbidden`). |
| FR-5 | **Policy Management** | Product/compliance teams can review, approve, or reject government-submitted blocklist updates before enforcement. Manual overrides (allowlisting) must be supported. |
| FR-6 | **Audit Trail** | Every block action and every policy change must be logged immutably for regulatory compliance and forensic analysis. |

### Non-Functional Requirements

| # | Requirement | Target |
|---|-------------|--------|
| NFR-1 | **Latency on hot path** | < 1ms added per request for the IP lookup. The blocking check must not perceptibly degrade user-facing latency. |
| NFR-2 | **Global propagation time** | Blocklist updates must reach all edge PoPs within 30–60 seconds of approval. |
| NFR-3 | **Availability** | 99.99%+ uptime for the enforcement layer. The blocking system must not become a single point of failure that takes down all traffic. |
| NFR-4 | **Scale** | Handle millions of requests per second across hundreds of global PoPs. Support blocklists of up to 500K CIDR entries per region. |
| NFR-5 | **Consistency model** | Eventual consistency for edge propagation is acceptable (bounded staleness window of seconds, not minutes). |
| NFR-6 | **Safety** | Fail-open by default (see discussion in §9). A broken blocklist update must not accidentally block all traffic. |

### Out of Scope

- Application-layer filtering (URL paths, headers, request body).
- DDoS mitigation beyond IP blocking (rate limiting, challenge pages).
- DNS-level blocking.

---

## 2. Back-of-the-Envelope Estimation

### Address Space

- **IPv4**: 2^32 = 4,294,967,296 addresses (~4.3 billion). Defined in RFC 791.
- **IPv6**: 2^128 ≈ 3.4 × 10^38 addresses. Defined in RFC 8200.
- CIDR notation allows blocking ranges: a `/24` IPv4 block covers 256 addresses; a `/48` IPv6 block covers 2^80 addresses.

### Blocklist Size

- Government-mandated blocklists realistically contain 10,000–500,000 CIDR entries per region.
  - Reference: Spamhaus DROP list contains ~1,000–1,500 entries. FireHOL Level 1 aggregated list contains ~15,000–30,000 entries. Country-level IP allocations from RIRs (ARIN, RIPE, APNIC) typically contain 8,000–15,000 CIDR blocks for a large country.
- A single Patricia trie for 500K IPv4 CIDRs requires at most 2N − 1 ≈ 1M nodes, each ~32–64 bytes → **~32–64 MB of memory**. Well within the capacity of any edge server.
- IPv6 tries are deeper (128-bit keys) but in practice contain far fewer entries because blocklists use large prefix blocks (e.g., `/48`, `/64`).

### Traffic Volume

- A major CDN like Cloudflare handles **tens of millions of HTTP requests per second** globally.
- Assuming 300+ PoPs (Cloudflare operates in 310+ cities as of 2024), each PoP handles roughly 50K–200K RPS on average, with significant variance (major metros handle far more).
- Each IP lookup must complete in < 1ms. A Patricia trie lookup is O(W) where W = 32 for IPv4 / 128 for IPv6, which resolves in **nanoseconds** on modern hardware — well within budget.

### Propagation Budget

- Target: all PoPs updated within 30–60 seconds.
- Reference: Cloudflare's Quicksilver distributed KV store propagates configuration changes to their entire global network in approximately 2–5 seconds on average. AWS WAF rule changes take "several minutes."
- Our design targets the Cloudflare-class performance tier.

### Storage for Audit Logs

- Assume 1% of global traffic is blocked → ~100K–1M block events/second.
- Each log entry ~200 bytes → ~200 KB–200 MB/s of log ingestion.
- At scale, this is a moderate write throughput for a time-series / append-only store.

---

## 3. High-Level Architecture

The system is divided into two planes: a **Control Plane** (where policy is managed and distributed) and a **Data Plane** (where enforcement happens at the edge on every request).

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           CONTROL PLANE                                  │
│                                                                          │
│  ┌──────────────┐    ┌──────────────────┐    ┌────────────────────────┐  │
│  │  Government   │───▶│  Ingestion       │───▶│  Policy Management     │  │
│  │  API Adapters │    │  Service          │    │  Service               │  │
│  │  (per-country)│    │  (normalize,      │    │  (review, approve,     │  │
│  └──────────────┘    │   validate, diff)  │    │   allowlist, override) │  │
│                      └──────────────────┘    └─────────┬──────────────┘  │
│                                                        │                 │
│                                                        ▼                 │
│                                              ┌─────────────────────┐     │
│                                              │  Blocklist Store    │     │
│                                              │  (versioned,        │     │
│                                              │   per-region)       │     │
│                                              └─────────┬───────────┘     │
│                                                        │                 │
│                                                        ▼                 │
│                                              ┌─────────────────────┐     │
│                                              │  Distribution       │     │
│                                              │  Service            │     │
│                                              │  (global push)      │     │
│                                              └─────────┬───────────┘     │
│                                                        │                 │
└────────────────────────────────────────────────────────┼─────────────────┘
                                                         │
                    ┌────────────────────────────────────┼──────────────┐
                    │              DATA PLANE             │              │
                    │                                    ▼              │
                    │  ┌─────────────────────────────────────────────┐  │
                    │  │           Edge PoP (one of 300+)            │  │
                    │  │                                             │  │
                    │  │  ┌──────────┐  ┌────────────┐  ┌────────┐  │  │
                    │  │  │ Request  │─▶│ IP Blocking │─▶│ Proxy  │  │  │
                    │  │  │ Arrives  │  │ Module      │  │ / App  │  │  │
                    │  │  └──────────┘  │             │  └────────┘  │  │
                    │  │                │ ┌─────────┐ │              │  │
                    │  │                │ │Patricia │ │              │  │
                    │  │                │ │Trie     │ │              │  │
                    │  │                │ │(in-mem) │ │              │  │
                    │  │                │ └─────────┘ │              │  │
                    │  │                └──────┬──────┘              │  │
                    │  │                       │                     │  │
                    │  │                       ▼                     │  │
                    │  │               ┌──────────────┐             │  │
                    │  │               │ Audit Logger │             │  │
                    │  │               │ (async, local│             │  │
                    │  │               │  buffer)     │             │  │
                    │  │               └──────────────┘             │  │
                    │  └─────────────────────────────────────────────┘  │
                    └──────────────────────────────────────────────────┘
```

### Key Architectural Decisions

1. **Separate Control Plane from Data Plane**: The control plane can go down temporarily without affecting edge enforcement. Edge nodes continue serving with their last-known-good blocklist.
2. **Push-based propagation**: The control plane pushes updates to edges (not edge polling). This reduces propagation latency from minutes (polling interval) to seconds (push + apply).
3. **In-memory enforcement at the edge**: The blocklist is compiled into an optimized in-memory trie on each edge server. No disk I/O or network call is needed on the hot path.
4. **Versioned blocklists**: Every blocklist state has a monotonically increasing version number. This enables atomic swaps, rollback, and consistency verification.

---

## 4. Detailed Component Design

### 4.1 Government API Adapters (Ingestion Layer)

Each government provides its own API with different formats, authentication, and delivery mechanisms. The adapter layer normalizes this diversity.

**Design Pattern: Adapter + Strategy**

```
GovernmentAPIAdapter (interface)
├── fetch_blocklist() → RawBlocklist
├── get_last_modified() → timestamp
└── validate_credentials() → bool

USGovernmentAdapter implements GovernmentAPIAdapter
EUGovernmentAdapter implements GovernmentAPIAdapter
JPGovernmentAdapter implements GovernmentAPIAdapter
...
```

**Key behaviors:**

- **Polling with backoff**: Each adapter polls its government API on a configurable interval (e.g., every 5 minutes). If the API returns "no changes" (via HTTP `304 Not Modified` or a version/ETag check), no processing occurs.
- **Retry with exponential backoff**: Transient failures (5xx, timeouts) trigger retries. Permanent failures (4xx, revoked credentials) trigger alerts.
- **Normalization**: Each adapter converts the government-specific format into a canonical internal format:

```
CanonicalBlockEntry {
    cidr: string          // e.g., "203.0.113.0/24" or "2001:db8::/32"
    ip_version: enum      // IPv4 | IPv6
    region: string        // ISO 3166-1 alpha-2 country code
    source: string        // e.g., "US-OFAC", "EU-COUNCIL"
    reason_code: string   // opaque identifier from government
    effective_date: timestamp
    expiry_date: timestamp | null
}
```

- **Diff computation**: After fetching, the adapter computes a diff against the last-known blocklist version for that government source (additions and removals). Only the diff is forwarded to the Policy Management Service, reducing downstream processing.

**Concurrency model**: Each adapter runs as an independent worker process (or async task). Since adapters are I/O-bound (HTTP calls to government APIs), `asyncio` or a thread pool is appropriate. Adapters are stateless and horizontally scalable — multiple instances can run for high-priority governments with shorter polling intervals.

### 4.2 Policy Management Service

This is the human-in-the-loop component. Government blocklist changes are not blindly applied — they go through a review pipeline.

**Workflow:**

```
Government Update → Ingestion → Pending Review Queue
                                        │
                                        ▼
                              ┌──────────────────┐
                              │  Compliance Team  │
                              │  Dashboard        │
                              │                   │
                              │  - View diff      │
                              │  - Approve / Reject│
                              │  - Add allowlist  │
                              │  - Set effective   │
                              │    time           │
                              └────────┬─────────┘
                                       │
                                       ▼
                              ┌──────────────────┐
                              │  Safety Checks    │
                              │  - Blast radius   │
                              │  - Overlap check  │
                              │  - Rate of change │
                              └────────┬─────────┘
                                       │
                                       ▼
                              ┌──────────────────┐
                              │  Approved Version │
                              │  → Blocklist Store│
                              └──────────────────┘
```

**Safety checks (automated gates before enforcement):**

| Check | Description |
|-------|-------------|
| **Blast radius** | If a single update would block > N% of a region's traffic (configurable threshold, e.g., 5%), require manual escalation. This prevents a compromised government API or a misparse from accidentally blocking a large IP range like `0.0.0.0/0`. |
| **Overlap detection** | Flag if a newly blocked range overlaps with known CDN ranges (e.g., Cloudflare, AWS, GCP IP ranges), major ISPs, or the company's own infrastructure. |
| **Rate-of-change** | If the blocklist grows by more than X% in a single update, flag for review. This catches bulk poisoning attacks. |
| **CIDR sanity** | Reject nonsensical CIDRs: `/0` blocks (entire internet), host routes in IPv6 (`/128` — usually a mistake in a blocklist context), CIDRs that don't align to network boundaries. |

**Allowlisting**: Compliance teams can maintain per-region allowlists (e.g., "never block this CDN range, regardless of government input"). Allowlists take precedence during trie compilation.

### 4.3 Blocklist Store (Source of Truth)

The blocklist store is the versioned, durable source of truth for all active blocking rules.

**Choice: Relational database (PostgreSQL) + Object storage for snapshots.**

- **PostgreSQL** stores the current state: active rules, their metadata, approval status, version numbers.
- **Object storage (S3/GCS)** stores compiled trie snapshots (serialized binary) for fast edge bootstrap.

**Why PostgreSQL:**
- ACID transactions ensure that an approval atomically transitions a blocklist version.
- Supports complex queries for the compliance dashboard (e.g., "show me all rules added in the last 24 hours for region EU").
- The write rate is low (rule changes happen at most every few minutes per region, not per request). Read rate is also low (only the Distribution Service reads, not edge nodes).

**Versioning scheme:**

```
blocklist_version {
    version_id: uint64          // monotonically increasing
    region: string              // ISO country code or "GLOBAL"
    created_at: timestamp
    approved_by: string         // operator ID
    parent_version_id: uint64   // for rollback chain
    status: enum                // ACTIVE | ROLLED_BACK | SUPERSEDED
    entry_count: uint32
    sha256_checksum: string     // integrity check for the compiled trie
}
```

Each version is immutable once created. Rollback is achieved by creating a new version that points to a previous parent version's entry set.

### 4.4 Distribution Service (Global Propagation)

This is the bridge between the control plane and the data plane. When a new blocklist version is approved, the distribution service pushes it to all relevant edge PoPs.

**Architecture: Hierarchical fan-out with a distributed KV store.**

Rather than the control plane pushing directly to each of 300+ PoPs (which would be slow and fragile), we use a **two-tier distribution tree**:

```
Control Plane (writes new version)
         │
         ▼
┌─────────────────────┐
│  Regional Hubs      │  (5-10 regional hubs: US-East, US-West,
│  (L1 Distribution)  │   EU-West, EU-Central, APAC-East, etc.)
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Edge PoPs          │  (each hub fans out to 30-60 PoPs
│  (L2 Distribution)  │   in its region)
└─────────────────────┘
```

**Distribution protocol:**

1. **Control plane** writes the new compiled trie snapshot to object storage (S3/GCS) and publishes a version update notification to regional hubs.
2. **Regional hubs** pull the snapshot from object storage (one read per hub, not per PoP) and fan it out to their edge PoPs via persistent connections (gRPC streams or WebSocket).
3. **Edge PoPs** receive the notification containing: `{region, version_id, checksum, snapshot_url}`. Each edge server:
   - Downloads the compiled trie from the nearest regional hub's cache (or directly from object storage as fallback).
   - Validates the checksum.
   - Performs an **atomic pointer swap** to replace the in-memory trie. The old trie is kept for a configurable TTL (for rollback) before being garbage collected.

**Why this works within 30 seconds:**
- Object storage writes: ~1–2 seconds.
- Hub notification + download: ~2–5 seconds (hubs are nearby in the same region).
- Hub → PoP fan-out: ~2–10 seconds (persistent connections, parallel fan-out).
- Edge server apply: < 1 second (deserialize + atomic swap).
- Total: **~5–20 seconds** typical, well within the 30–60 second budget.

**Consistency and version protocol:**
- Each edge server reports its current blocklist version to the control plane via periodic heartbeats (every 10 seconds).
- The control plane maintains a **version convergence dashboard** showing which PoPs are on which version.
- If a PoP fails to update within the SLA (e.g., 60 seconds), an alert fires and the PoP is flagged. Traffic can optionally be drained from that PoP via DNS/anycast adjustments.

### 4.5 Edge Enforcement Module (Data Plane Hot Path)

This is the most performance-critical component. It runs on every edge server and evaluates every inbound request.

**Request flow (hot path):**

```
1. TCP/TLS connection established, HTTP request parsed.
2. Extract source IP from the connection (IP header, not X-Forwarded-For —
   we are the first hop).
3. Determine applicable region from the PoP's location.
4. Lookup source IP in the in-memory Patricia trie for that region:
   a. If MATCH → return 403 Forbidden. Log block event (async).
   b. If NO MATCH → continue to next processing stage (proxy to origin,
      serve from cache, etc.).
```

**Critical design details:**

- **No network calls on the hot path.** The trie is entirely in local memory. The lookup is a pure CPU operation.
- **Two tries per edge server**: One for IPv4, one for IPv6. The IP version is determined from the connection's address family (AF_INET vs AF_INET6).
- **Region resolution**: Each PoP serves a known set of regions. Typically, a PoP in Tokyo enforces the Japan blocklist plus a global blocklist. The region → trie mapping is a small in-memory lookup table.
- **Atomic swap for updates**: When a new trie version arrives, the edge server builds the new trie in a separate memory allocation, then atomically swaps the pointer (using an atomic reference/RCU pattern). In-flight requests on the old trie complete safely; no locking is needed on the hot path.

**Latency budget:**

| Operation | Time |
|-----------|------|
| Extract source IP | ~0 (already parsed) |
| Patricia trie lookup (32-bit IPv4, 500K entries) | ~100–500 nanoseconds |
| Patricia trie lookup (128-bit IPv6, 100K entries) | ~200–800 nanoseconds |
| Total added latency | **< 1 microsecond** |

This is orders of magnitude below the 1ms budget. The lookup is not the bottleneck — it's invisible in the overall request latency.

### 4.6 Audit Logger

Every block decision and every policy change must be logged for compliance.

**Two audit streams:**

1. **Block event log** (high volume, from edge):

```
BlockEvent {
    timestamp: uint64           // nanosecond precision
    pop_id: string              // which PoP
    source_ip: bytes            // 4 or 16 bytes
    matched_cidr: string        // the CIDR rule that matched
    blocklist_version: uint64
    region: string
    action: enum                // BLOCKED | ALLOWED_BY_OVERRIDE
    request_metadata: {         // minimal metadata, no PII
        method: string
        host: string
        user_agent_hash: string // hashed for privacy
    }
}
```

- **Buffered locally** on the edge server (in a ring buffer or local file).
- **Shipped asynchronously** to a centralized log store (e.g., Kafka → cold storage). The log shipping is not on the hot path.
- **Retention**: Configurable per regulation (e.g., 7 years for certain compliance regimes).

2. **Policy change log** (low volume, from control plane):

```
PolicyChangeEvent {
    timestamp: timestamp
    operator_id: string
    action: enum                // APPROVE | REJECT | OVERRIDE | ROLLBACK
    region: string
    old_version: uint64
    new_version: uint64
    diff_summary: string        // "+1432 entries, -12 entries"
    justification: string       // operator-provided reason
}
```

- Written synchronously to the policy database (PostgreSQL) as part of the approval transaction.
- Immutable: append-only table, no UPDATEs or DELETEs allowed.

---

## 5. Data Structures for IP Matching

This section is the core algorithmic depth that distinguishes a staff-level answer. The choice of data structure directly impacts the hot-path latency, memory footprint, and update complexity.

### 5.1 Problem Definition

Given a set of CIDR blocks (e.g., `{192.168.1.0/24, 10.0.0.0/8, 203.0.113.128/25}`), and a query IP address, determine whether the IP falls within any of the CIDR blocks. This is a **longest prefix match (LPM)** problem — the same problem that IP routers solve billions of times per second.

### 5.2 Option Analysis

| Data Structure | Lookup Complexity | Space | CIDR Support | Update Cost | Verdict |
|---------------|-------------------|-------|-------------|-------------|---------|
| **Hash Set** | O(1) average | O(N) per IP | No (must expand CIDRs to individual IPs) | O(1) per IP | Impractical for CIDRs. A `/8` block = 16M IPv4 entries. |
| **Sorted Array + Binary Search** | O(log N) | O(N) | With range representation | O(N) rebuild | Decent for static lists but O(N) rebuild on update. |
| **Binary Trie** | O(W), W=32 or 128 | O(N × W) | Yes, natively | O(W) per entry | Correct but space-inefficient. Many single-child nodes. |
| **Patricia Trie (Radix Trie)** | O(W) worst, often faster | O(N) | Yes, natively | O(W) per entry | **Best overall balance.** Compressed, cache-friendly, proven in production (Linux kernel `fib_trie.c`). |
| **LC-Trie** | O(log log N) expected | O(N) + arrays | Yes | More complex rebuild | Better lookup for dense distributions, but more complex to implement and update. |
| **DPDK-style Two-Level Table** | O(1) for ≤/24 prefixes | ~64 MB for IPv4 | Partial | O(1) update | Excellent for IPv4 if memory is available. Not practical for IPv6 (2^48 first-level for /48 blocks). |

### 5.3 Chosen Approach: Patricia Trie (with per-version immutable snapshots)

**Why Patricia Trie:**

1. **O(W) lookup** where W = 32 for IPv4 — this resolves in nanoseconds. For IPv6, W = 128 but practical traversals are much shorter because blocklists use large prefixes.
2. **O(N) space** — at most 2N − 1 nodes for N prefixes. 500K entries ≈ 1M nodes × ~64 bytes/node ≈ 64 MB. Trivial for modern servers.
3. **Native CIDR support** — a CIDR like `192.168.0.0/16` is represented by a single node at depth 16 in the trie. Lookup traverses bit-by-bit; a match at any depth indicates the IP falls within a blocked range.
4. **Production-proven** — the Linux kernel has used Patricia/LC-trie variants for IP routing since the early 2000s (`net/ipv4/fib_trie.c`). This is the same fundamental problem.
5. **Supports longest prefix match** — if both `10.0.0.0/8` (block) and `10.1.0.0/16` (allowlist override) exist, the trie naturally finds the most specific match.

**Trie structure (simplified):**

```
Node {
    bit_position: uint8          // which bit this node tests (0-31 for IPv4)
    prefix: bytes                // the prefix bits stored at this node
    prefix_length: uint8         // length of the prefix in bits
    is_terminal: bool            // true if this node represents a blocking rule
    rule_metadata: RuleMetadata  // region, source, reason (only if terminal)
    children: [Node; 2]          // left (bit=0), right (bit=1)
}
```

**Lookup algorithm:**

```
function lookup(root, ip_address):
    node = root
    bit_index = 0
    last_match = null

    while node is not null and bit_index <= 32:  // or 128 for IPv6
        // Check if current node's prefix matches
        if not prefix_matches(node, ip_address):
            break

        if node.is_terminal:
            last_match = node  // remember most specific match so far

        bit_index = node.bit_position + node.prefix_length
        if bit_index > 31:
            break

        // Branch based on the next bit of the IP address
        next_bit = get_bit(ip_address, bit_index)
        node = node.children[next_bit]

    return last_match  // null means no match (allow), non-null means blocked
```

### 5.4 Immutable Trie + Atomic Swap

A critical design decision: **tries are immutable snapshots, not mutated in place.**

**Rationale:**
- In-place mutation of a trie during active lookups requires locking or complex lock-free concurrency (CAS loops on every node), which adds latency to the hot path.
- Instead, the Distribution Service delivers a **pre-compiled, serialized trie snapshot**. The edge server deserializes it into a new memory region and atomically swaps the pointer.
- This is the **Read-Copy-Update (RCU)** pattern, widely used in the Linux kernel for exactly this use case (routing table updates).
- Old trie versions are kept briefly (for in-flight requests that hold a reference) and then freed via epoch-based reclamation or simple reference counting.

**Update flow on edge server:**

```
1. Receive new trie snapshot (binary blob, ~10-50 MB)
2. Deserialize into new memory region → new_trie
3. Validate checksum
4. atomic_store(&current_trie_ptr, new_trie)
   // All new requests now use new_trie
   // In-flight requests still hold reference to old_trie
5. After grace period (e.g., 5 seconds), free old_trie memory
```

### 5.5 IPv6 Considerations

IPv6 tries have 128-bit keys, making the theoretical worst-case depth 4× deeper than IPv4. In practice:

- Government blocklists use large IPv6 prefixes (`/32`, `/48`, `/64`). The trie is much shallower than 128 levels.
- Patricia compression means most paths are short (skipping long runs of common prefix bits).
- Separate tries for IPv4 and IPv6 are maintained. The IP version is determined at the network layer, so the correct trie is selected with zero overhead (a single branch on the address family).

### 5.6 Region-Specific Trie Composition

Each edge PoP loads one or more tries based on its region:

```
PoP "Tokyo-01":
  - trie_global_v4     (rules that apply everywhere)
  - trie_japan_v4      (Japan-specific rules)
  - trie_global_v6
  - trie_japan_v6

Lookup order: region-specific first, then global.
Result: BLOCK if any trie matches.
```

In practice, for simplicity and speed, the control plane **pre-merges** the global and region-specific rules into a single compiled trie per region. This way, the edge server performs exactly one lookup (in the merged trie) rather than two sequential lookups. The merging happens during trie compilation in the control plane, not on the hot path.

---

## 6. Data Flow & Propagation

### 6.1 End-to-End Update Flow

```
 Time
  │
  ▼
  t=0     Government API publishes updated blocklist
  │
  t=0-5m  Ingestion adapter polls, detects change, computes diff
  │
  t=5m    Diff submitted to Policy Management as pending review
  │
  t=5m-?  Compliance team reviews and approves (human latency; can
  │       be auto-approved for trusted sources within safety limits)
  │
  t=T     Approval event triggers:
  │       1. New blocklist version written to PostgreSQL
  │       2. Trie compiled and serialized
  │       3. Snapshot uploaded to object storage
  │       4. Version notification pushed to regional hubs
  │
  t=T+5s  Regional hubs pull snapshot, cache locally
  │
  t=T+10s Hubs push to edge PoPs via persistent connections
  │
  t=T+15s Edge servers download, validate, atomic-swap trie
  │
  t=T+20s All PoPs enforcing new version (typical case)
  │
  t=T+30s Version convergence confirmed via heartbeats
```

### 6.2 Auto-Approval Path (for trusted, low-risk updates)

For government sources with established track records and updates that pass all safety checks (low blast radius, small diff size), the system supports configurable **auto-approval**:

```
Auto-approval criteria (all must be true):
  - Source is in the trusted-sources list
  - Diff size < configurable threshold (e.g., 100 entries)
  - Blast radius check passes (< 0.1% of estimated traffic affected)
  - No overlap with infrastructure CIDRs
  - No /0 through /8 blocks (overly broad)
```

When auto-approval is enabled, the human review step is skipped and the update flows directly from ingestion to compilation. This reduces the end-to-end latency to **under 60 seconds** from government API publication to global enforcement.

---

## 7. API Design

### 7.1 Control Plane API (Internal, for compliance teams and automation)

```
POST   /api/v1/blocklists/{region}/reviews
  Body: { entries: [...], source: "US-OFAC", effective_date: "..." }
  → 201 Created { review_id: "...", status: "PENDING" }

GET    /api/v1/blocklists/{region}/reviews/{review_id}
  → 200 { review_id, status, diff_summary, safety_check_results }

POST   /api/v1/blocklists/{region}/reviews/{review_id}/approve
  Body: { justification: "Quarterly OFAC update, reviewed by legal" }
  → 200 { version_id: 42, propagation_started: true }

POST   /api/v1/blocklists/{region}/reviews/{review_id}/reject
  Body: { reason: "Contains CDN IP ranges, likely erroneous" }
  → 200 { status: "REJECTED" }

POST   /api/v1/blocklists/{region}/rollback
  Body: { target_version: 41 }
  → 200 { new_version_id: 43, based_on: 41 }

GET    /api/v1/blocklists/{region}/versions
  Query: ?limit=10&status=ACTIVE
  → 200 [{ version_id, created_at, entry_count, status }]

GET    /api/v1/blocklists/{region}/versions/{version_id}/entries
  Query: ?page=1&page_size=100&search=203.0.113
  → 200 { entries: [...], total_count, page }

# Manual overrides
POST   /api/v1/allowlist/{region}
  Body: { cidr: "198.51.100.0/24", reason: "Company VPN range" }
  → 201 Created

DELETE /api/v1/allowlist/{region}/{entry_id}
  → 204 No Content

# Observability
GET    /api/v1/propagation/status
  → 200 { version_by_region: { "US": 42, "JP": 41 },
           convergence: { "US": { total_pops: 45, on_latest: 43, lagging: 2 } } }

GET    /api/v1/audit/blocks
  Query: ?region=US&start=2024-01-01&end=2024-01-02&source_ip=203.0.113.5
  → 200 { events: [...] }
```

### 7.2 Edge PoP Internal API (gRPC, between Distribution Service and edge)

```protobuf
service BlocklistDistribution {
    // Persistent stream: hub pushes version updates to edge
    rpc SubscribeUpdates(SubscribeRequest) returns (stream VersionUpdate);

    // Edge pulls a specific snapshot (fallback if push fails)
    rpc GetSnapshot(SnapshotRequest) returns (SnapshotResponse);

    // Edge reports its current version
    rpc ReportVersion(VersionReport) returns (Ack);
}

message VersionUpdate {
    string region = 1;
    uint64 version_id = 2;
    string snapshot_url = 3;      // URL to download compiled trie
    string sha256_checksum = 4;
    bool is_rollback = 5;
}

message SnapshotRequest {
    string region = 1;
    uint64 version_id = 2;
}

message SnapshotResponse {
    bytes compiled_trie = 1;      // serialized Patricia trie
    string sha256_checksum = 2;
}
```

---

## 8. Storage & Schema Design

### 8.1 PostgreSQL Schema (Control Plane)

```sql
-- Core blocklist versioning
CREATE TABLE blocklist_versions (
    version_id      BIGSERIAL PRIMARY KEY,
    region          VARCHAR(10) NOT NULL,       -- ISO country code or "GLOBAL"
    parent_version  BIGINT REFERENCES blocklist_versions(version_id),
    status          VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
                    -- ACTIVE, ROLLED_BACK, SUPERSEDED
    entry_count     INTEGER NOT NULL,
    sha256_checksum VARCHAR(64) NOT NULL,
    snapshot_url    TEXT,                        -- S3/GCS URL of compiled trie
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by      VARCHAR(100) NOT NULL        -- operator or "auto-approve"
);

CREATE INDEX idx_versions_region_status ON blocklist_versions(region, status);

-- Individual blocklist entries (for queryability and auditing)
CREATE TABLE blocklist_entries (
    entry_id        BIGSERIAL PRIMARY KEY,
    version_id      BIGINT NOT NULL REFERENCES blocklist_versions(version_id),
    cidr            INET NOT NULL,              -- PostgreSQL native INET type
                                                -- supports both IPv4 and IPv6 CIDRs
    ip_version      SMALLINT NOT NULL,          -- 4 or 6
    source          VARCHAR(50) NOT NULL,       -- "US-OFAC", "EU-COUNCIL", etc.
    reason_code     VARCHAR(100),
    effective_date  TIMESTAMPTZ NOT NULL,
    expiry_date     TIMESTAMPTZ
);

CREATE INDEX idx_entries_version ON blocklist_entries(version_id);
CREATE INDEX idx_entries_cidr ON blocklist_entries USING GIST (cidr inet_ops);

-- Allowlist overrides
CREATE TABLE allowlist_entries (
    entry_id        BIGSERIAL PRIMARY KEY,
    region          VARCHAR(10) NOT NULL,
    cidr            INET NOT NULL,
    reason          TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by      VARCHAR(100) NOT NULL,
    active          BOOLEAN NOT NULL DEFAULT TRUE
);

-- Policy audit log (append-only)
CREATE TABLE policy_audit_log (
    log_id          BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    operator_id     VARCHAR(100) NOT NULL,
    action          VARCHAR(20) NOT NULL,       -- APPROVE, REJECT, ROLLBACK, etc.
    region          VARCHAR(10) NOT NULL,
    old_version_id  BIGINT,
    new_version_id  BIGINT,
    diff_summary    TEXT,
    justification   TEXT
);
```

**Note on PostgreSQL's `INET` type:** PostgreSQL natively supports IPv4 and IPv6 addresses and CIDR notation through the `inet` and `cidr` data types. The GiST index on `inet` supports containment queries (`>>`, `<<` operators), enabling efficient queries like "find all rules that contain this IP" or "find all rules within this range." This is well-documented in the PostgreSQL official documentation.

### 8.2 Edge PoP Local Storage

Edge servers maintain minimal local state:

```
/var/lib/ip-blocker/
├── current_v4.trie          # current active IPv4 Patricia trie (mmap'd)
├── current_v6.trie          # current active IPv6 Patricia trie (mmap'd)
├── previous_v4.trie         # previous version (for fast rollback)
├── previous_v6.trie
├── version.json             # { "v4_version": 42, "v6_version": 42, "region": "JP" }
└── block_events.log         # local ring buffer, shipped async to Kafka
```

On startup, if no local trie exists, the edge server pulls the latest snapshot from the Distribution Service before accepting traffic.

---

## 9. Operational Concerns

### 9.1 Fail-Open vs. Fail-Closed

This is one of the most critical operational decisions and a frequent interview discussion point.

| Strategy | Behavior on Failure | Risk |
|----------|-------------------|------|
| **Fail-open** | If the blocking system is broken or unavailable, allow all traffic through. | Temporarily not blocking mandated IPs. Regulatory risk. |
| **Fail-closed** | If the blocking system is broken, block all traffic. | Complete outage. Business/availability risk. |

**Our choice: Fail-open with aggressive monitoring.**

**Rationale:**
- Blocking all traffic because of a system failure is a self-inflicted denial of service. For most businesses, a brief window where some IPs are not blocked is far less damaging than a total outage.
- The blocking system itself should be simple enough (an in-memory trie lookup) that failures are extraordinarily rare on the hot path. The failure modes are in the control plane (propagation failures), not the data plane.
- Regulatory frameworks typically require "best effort" enforcement with audit trails, not mathematically guaranteed zero-latency enforcement. The audit log demonstrates compliance intent.

**Exception: Fail-closed for specific high-severity regions** where regulation explicitly demands it (e.g., sanctions compliance). This is configurable per region.

### 9.2 Rollback

Rollback must be fast — faster than the original propagation, because a bad blocklist is actively causing damage.

**Rollback procedure:**

1. Operator issues rollback via API: `POST /api/v1/blocklists/{region}/rollback`.
2. Control plane creates a new version pointing to the previous version's entry set.
3. Since the previous trie snapshot is still cached on regional hubs and edge servers (`previous_*.trie`), rollback is **near-instant**: the edge server swaps back to the previous trie pointer.
4. A "rollback" notification via the Distribution Service tells edges to swap to their locally cached previous version. No download needed.
5. Target: rollback completes globally in **< 10 seconds**.

### 9.3 Canary Deployment

Blocklist updates should not go to all PoPs simultaneously. Instead:

```
Phase 1 (t=0):    Deploy to 2-3 canary PoPs (low-traffic, internal-facing)
                   Monitor error rates, block rates, latency for 5 minutes.

Phase 2 (t=5m):   If canary is healthy, deploy to 10% of PoPs.
                   Monitor for 2 minutes.

Phase 3 (t=7m):   Full rollout to remaining PoPs.
```

**Automated rollback trigger**: If the block rate at canary PoPs exceeds a configurable threshold (e.g., > 50% of traffic being blocked, which would indicate a bad rule like `0.0.0.0/1`), automatically halt the rollout and alert.

This canary process adds latency to full propagation but significantly reduces the blast radius of bad updates. It can be bypassed for emergency/critical updates via an operator override.

### 9.4 Monitoring & Alerting

| Metric | Alert Threshold | Description |
|--------|----------------|-------------|
| `blocklist_version_lag` | > 60 seconds | A PoP is behind the latest version for too long. |
| `block_rate_per_pop` | > X% sudden change | Detects bad rules or poisoned blocklists. |
| `trie_lookup_latency_p99` | > 500µs | Trie is too large or memory-pressured. |
| `propagation_convergence_time` | > 30 seconds | Distribution pipeline is slow. |
| `government_api_fetch_failures` | > 3 consecutive | Credential expiry, API deprecation, or outage. |
| `trie_memory_usage` | > 80% of budget | Blocklist growing unexpectedly. |

### 9.5 Security Considerations

- **Government API credential management**: Credentials stored in a secrets manager (e.g., HashiCorp Vault, AWS Secrets Manager). Rotated on schedule. Each adapter has its own credentials with least-privilege access.
- **Trie integrity**: Every compiled trie snapshot is signed (HMAC or digital signature) by the control plane. Edge servers verify the signature before loading. This prevents a compromised distribution channel from injecting malicious rules.
- **Supply chain attack on government APIs**: The safety checks in §4.2 (blast radius, overlap detection, rate-of-change) serve as defense-in-depth against a compromised government API that starts injecting overly broad blocks.
- **Access control on the Policy Management API**: Role-based access control. Approvals require dual authorization (two operators) for high-impact changes.

---

## 10. Trade-offs & Alternative Approaches

### 10.1 Push vs. Pull Propagation

| Approach | Propagation Latency | Complexity | Resilience |
|----------|-------------------|-----------|------------|
| **Push (chosen)** | Seconds | Higher (persistent connections, fan-out) | Dependent on push infrastructure availability |
| **Pull (polling)** | Minutes (polling interval) | Lower | Self-healing (edge pulls when ready) |
| **Hybrid** | Seconds (push) with pull fallback | Highest | Best resilience |

**Our design uses hybrid**: push for normal operation (low latency), with a pull fallback (each edge server polls every 60 seconds as a safety net in case a push is missed).

### 10.2 Pre-compiled Trie vs. Edge-Side Compilation

| Approach | Pros | Cons |
|----------|------|------|
| **Pre-compiled (chosen)** | Consistent across all edges; compilation errors caught centrally; faster edge apply. | Larger payloads to distribute. |
| **Edge-side compilation** | Smaller payloads (just the entry list); edges compile locally. | Inconsistent trie structures across edges; compilation bugs harder to debug; wasted CPU at edge. |

We chose pre-compiled because consistency is critical for a compliance system. We need to guarantee that every PoP enforces the exact same ruleset.

### 10.3 Single Merged Trie vs. Layered Tries

| Approach | Pros | Cons |
|----------|------|------|
| **Single merged trie (chosen)** | One lookup per request (fastest hot path). | Must recompile on any change to any source. |
| **Layered tries** | Can update one layer without touching others. | Multiple lookups per request; more complex edge logic. |

The single merged trie is preferred because the hot path is the most constrained resource. Compilation is a background task that can tolerate seconds of latency.

### 10.4 Network-Layer vs. Application-Layer Blocking

| Level | Mechanism | Pros | Cons |
|-------|-----------|------|------|
| **Application layer (chosen)** | In-process trie lookup | Full control, rich logging, fine-grained rules | Must process at application level |
| **Network layer** | BGP Flowspec (RFC 8955), iptables/nftables, router ACLs | Blocks before packets reach application; efficient for volumetric attacks | Limited rule capacity in router TCAM (thousands, not hundreds of thousands); less granular logging; harder to manage programmatically |

**Our primary approach is application-layer.** However, for extremely high-volume scenarios (e.g., a known DDoS source range), network-layer blocking via BGP Flowspec can supplement it:

- **BGP Flowspec** (defined in RFC 5575, revised in RFC 8955) allows injecting traffic filtering rules via BGP. Rules propagate to all participating routers within seconds.
- Router TCAM capacity limits Flowspec to thousands of rules (hardware-dependent), so it's used for the highest-priority blocks, not the full blocklist.
- The application-layer trie handles the full blocklist with no capacity constraints.

---

## 11. Interview Discussion Extensions

These are topics the interviewer may probe. Having prepared answers demonstrates staff-level depth.

### 11.1 "What if a government sends `0.0.0.0/0`?"

This would block the entire IPv4 internet. Our safety checks catch this:
- The blast radius check would flag that 100% of traffic is affected (far above any threshold).
- The CIDR sanity check rejects `/0` blocks.
- Even if auto-approval is on, these checks run before compilation. The update would be rejected and flagged for human review.

### 11.2 "How do you handle a PoP that's permanently disconnected?"

- The PoP continues operating with its last-known-good blocklist (fail-open with stale data).
- The version convergence dashboard shows this PoP as lagging.
- After a configurable timeout (e.g., 1 hour of stale data), the PoP can be removed from DNS/anycast rotation so traffic is redirected to other PoPs with current data.
- When the PoP reconnects, it pulls the latest snapshot and resumes.

### 11.3 "How do you test blocklist changes before deployment?"

- **Dry-run mode**: The control plane can compile a trie and evaluate it against a sample of recent traffic logs (replayed offline) to predict the impact: "This update would have blocked X requests in the last hour."
- **Shadow mode**: Deploy the new trie alongside the current trie. Both evaluate every request, but only the current trie's decision is enforced. The shadow trie's decisions are logged for comparison. Differences are flagged.

### 11.4 "What about performance at IPv6 scale?"

- IPv6 blocklists in practice use large prefixes (`/32`, `/48`, `/64`), so the effective trie depth is 32–64 bits, comparable to IPv4.
- If IPv6 blocklists grow to millions of entries (unlikely for government blocklists, but possible for threat intelligence), an LC-trie (level-compressed trie, per Nilsson & Karlsson 1999) can provide O(log log N) expected lookup time.
- For ultra-high-performance requirements, a DPDK-style direct lookup table can be used for common prefix lengths, with a trie fallback for longer prefixes.

### 11.5 "How do you ensure consistency across PoPs during a rolling update?"

- **Bounded inconsistency**: During the propagation window (5–30 seconds), different PoPs may enforce different versions. This is acceptable because:
  - The inconsistency window is brief (seconds).
  - A single client's requests typically hit the same PoP (anycast routing stability), so they see consistent enforcement.
  - For regulatory purposes, the audit log records which version was active at each PoP at each point in time, providing a clear compliance record.
- **If strict consistency is required**: We can enforce a two-phase deployment where all PoPs acknowledge receipt of the new trie, then a "activate" signal triggers simultaneous atomic swaps. This adds latency (~10–30 seconds for acknowledgment) but ensures all PoPs switch at roughly the same time. In practice, this is rarely needed for IP blocking.

### 11.6 "What happens during a trie compilation failure?"

- Compilation is idempotent: the same input always produces the same output. A failure is retried.
- If compilation fails repeatedly (e.g., corrupt input data), the current version remains active. No update is propagated.
- The incident is logged and an alert fires. The operator can inspect the raw input data and fix the issue.
- Edge servers are unaffected — they continue with their current trie.

### 11.7 "How would you evolve this to support more complex rules?"

The Patricia trie handles IP/CIDR matching. If the system needs to evolve to include:
- **ASN-based blocking**: Maintain a separate ASN → IP range mapping table (sourced from RIR data). Resolve ASN to IP ranges at compilation time.
- **Geo-based blocking**: Already handled by region-specific tries.
- **Rate limiting per blocked range**: Add a secondary data structure (e.g., token bucket per CIDR) for ranges that should be rate-limited rather than hard-blocked.
- **Complex rule expressions** (IP + port + protocol): Move toward a rule evaluation engine (similar to Cloudflare's wirefilter). This is a significant architectural evolution — the trie becomes one component in a larger rule evaluation pipeline.

---

## Summary

| Dimension | Design Choice |
|-----------|--------------|
| **Hot path data structure** | Patricia trie, pre-compiled, in-memory, atomic-swapped |
| **Propagation model** | Push-based with pull fallback; hierarchical fan-out via regional hubs |
| **Consistency** | Eventual consistency at edge; strong consistency in control plane |
| **Failure mode** | Fail-open by default; configurable fail-closed per region |
| **Update safety** | Blast radius checks, overlap detection, canary deployment, instant rollback |
| **Propagation SLA** | < 30 seconds typical; < 10 seconds for rollback |
| **Lookup latency** | < 1 microsecond (nanosecond-range for IPv4) |
| **Audit** | Dual streams: high-volume block events (async) + low-volume policy changes (sync) |
