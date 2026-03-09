"""
=============================================================================
04 — DISTRIBUTED INDEX ARCHITECTURE
=============================================================================
PRIORITY: #4 for exa.ai — they index the entire web (billions of docs).

WHAT TO MASTER:
  - Why a single machine can't hold the index for web-scale search
  - Document sharding strategies (hash, range, content-based)
  - Consistent hashing: avoiding reshuffling on node add/remove
  - Scatter-gather query pattern
  - Replication for fault tolerance and read throughput
  - Index update propagation (near-real-time indexing)
  - The CAP theorem applied to search indexes

EXA.AI ANGLE:
  Exa's index covers billions of web pages. At 1KB metadata + 1536-dim
  float32 embeddings per doc = ~7KB per doc → 7TB for 1B docs.
  No single machine holds this. Sharding and replication are non-negotiable.
  Their architecture almost certainly: shard by doc hash → replicate each
  shard → scatter-gather at query time → merge top-K by score.

KEY INSIGHT:
  Search is a "read-heavy, write-occasionally" workload.
  Replicas serve reads. Primary handles writes + replication.
  Merging partial results requires score normalization — or use RRF.
=============================================================================
"""

import hashlib
import heapq
import math
import random
import time
import unittest
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


# =============================================================================
# CONSISTENT HASHING
# =============================================================================
#
# PROBLEM WITH NAIVE HASH SHARDING
# ─────────────────────────────────
# If you shard by doc_id % N and add a node (N → N+1),
# almost EVERY key reassigns to a different shard → massive data movement.
#
# CONSISTENT HASHING SOLUTION
# ────────────────────────────
# Map nodes AND keys onto a ring of 2^32 positions (hash space).
# A key belongs to the first node clockwise from it on the ring.
# Adding a node: only keys between (new_node_predecessor, new_node] move.
# Removing a node: only keys on that node move to the next node.
# Expected keys moved: N_keys / N_nodes → much less than naive hashing.
#
# VIRTUAL NODES (vnodes)
# ──────────────────────
# Each physical node maps to K virtual positions on the ring.
# Purpose: even load distribution even with heterogeneous hardware.
# K=150 vnodes per node is typical (Cassandra default).
# Higher K → better balance, more memory for the ring map.
#
# FAILURE MODE: "Hot spots"
# A single viral document can put its shard under pressure.
# Mitigation: content-based sharding spreads similar docs together
# (good for cache locality), but creates hotspots for trending topics.
# Hash-based sharding distributes load but destroys locality.

class ConsistentHashRing:
    """
    Consistent hash ring with virtual nodes.
    Used for: routing doc storage, routing queries to shard owners.
    """

    def __init__(self, vnodes_per_node: int = 150):
        self.vnodes_per_node = vnodes_per_node
        self.ring: dict[int, str] = {}       # position → node_id
        self.sorted_positions: list[int] = []
        self.nodes: set[str] = set()

    def _hash(self, key: str) -> int:
        return int(hashlib.md5(key.encode()).hexdigest(), 16)

    def add_node(self, node_id: str):
        """Add a node with vnodes_per_node virtual positions."""
        self.nodes.add(node_id)
        for i in range(self.vnodes_per_node):
            vnode_key = f"{node_id}#vnode{i}"
            position = self._hash(vnode_key)
            self.ring[position] = node_id

        self.sorted_positions = sorted(self.ring.keys())

    def remove_node(self, node_id: str):
        """Remove a node and all its virtual positions."""
        self.nodes.discard(node_id)
        positions_to_remove = [
            pos for pos, nid in self.ring.items() if nid == node_id
        ]
        for pos in positions_to_remove:
            del self.ring[pos]

        self.sorted_positions = sorted(self.ring.keys())

    def get_node(self, key: str) -> Optional[str]:
        """Find which node owns this key (clockwise successor on ring)."""
        if not self.ring:
            return None
        position = self._hash(key)
        # Binary search for the first position >= hash(key)
        lo, hi = 0, len(self.sorted_positions)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.sorted_positions[mid] < position:
                lo = mid + 1
            else:
                hi = mid
        # Wrap around if past the last position
        idx = lo % len(self.sorted_positions)
        return self.ring[self.sorted_positions[idx]]

    def get_nodes_for_key(self, key: str, replicas: int = 3) -> list[str]:
        """
        Return `replicas` distinct nodes for a key (for replication).
        Walk clockwise, skipping duplicate physical nodes.
        """
        if not self.ring:
            return []
        position = self._hash(key)

        lo, hi = 0, len(self.sorted_positions)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.sorted_positions[mid] < position:
                lo = mid + 1
            else:
                hi = mid

        result = []
        seen_nodes = set()
        n = len(self.sorted_positions)

        for i in range(n):
            idx = (lo + i) % n
            node = self.ring[self.sorted_positions[idx]]
            if node not in seen_nodes:
                seen_nodes.add(node)
                result.append(node)
                if len(result) == replicas:
                    break

        return result

    def distribution(self) -> dict[str, int]:
        """Count virtual node assignments per physical node."""
        counts: dict[str, int] = defaultdict(int)
        for node in self.ring.values():
            counts[node] += 1
        return dict(counts)


# =============================================================================
# SHARD (individual index partition)
# =============================================================================

@dataclass
class SearchResult:
    doc_id:  int
    score:   float
    shard_id: str
    text:    str = ""


class Shard:
    """
    One shard of the distributed index.
    In production: each shard is an HNSW index (for dense) or Lucene segment (for sparse).
    """

    def __init__(self, shard_id: str, simulated_latency_ms: float = 0.0):
        self.shard_id = shard_id
        self.docs: dict[int, dict] = {}
        self.simulated_latency_ms = simulated_latency_ms
        # Simulated vector store
        self._vectors: dict[int, list[float]] = {}

    def add_document(self, doc_id: int, text: str, vector: list[float], metadata: dict = None):
        self.docs[doc_id] = {"text": text, "metadata": metadata or {}}
        self._vectors[doc_id] = vector

    def search(self, query_vector: list[float], top_k: int) -> list[SearchResult]:
        """Brute-force search within this shard (replace with HNSW in prod)."""
        if self.simulated_latency_ms > 0:
            time.sleep(self.simulated_latency_ms / 1000)

        def cosine(a, b):
            da = math.sqrt(sum(x*x for x in a))
            db = math.sqrt(sum(x*x for x in b))
            if da == 0 or db == 0: return 0.0
            return sum(x*y for x,y in zip(a,b)) / (da * db)

        results = [
            SearchResult(doc_id, cosine(query_vector, vec), self.shard_id, self.docs[doc_id]["text"])
            for doc_id, vec in self._vectors.items()
        ]
        results.sort(key=lambda r: -r.score)
        return results[:top_k]

    @property
    def doc_count(self) -> int:
        return len(self.docs)


# =============================================================================
# DISTRIBUTED INDEX COORDINATOR (Scatter-Gather)
# =============================================================================
#
# SCATTER-GATHER PATTERN
# ──────────────────────
# 1. SCATTER : coordinator sends query to ALL shards in parallel
# 2. GATHER  : collect top-K from each shard
# 3. MERGE   : merge-sort top-K results from all shards into global top-K
#
# WHY NOT JUST QUERY ONE SHARD?
# Relevant documents are spread across shards by doc hash.
# A top-10 result could be on any shard — must query all.
#
# OPTIMIZATION: If shards report score distributions (histograms), coordinator
# can estimate a score threshold and skip shards where all docs score below it.
# This is "index elimination" — saves latency at the cost of potential misses.
#
# MERGING TOP-K
# ─────────────
# Each shard returns its local top-K. Coordinator merges K*N_shards results
# into global top-K using a min-heap → O(K * N_shards * log K).
# No need to sort all K*N_shards results.
#
# SCORE NORMALIZATION ACROSS SHARDS
# ────────────────────────────────────
# Scores from different shards may not be comparable (IDF varies per shard).
# Fix: normalize scores per-shard to [0,1] before merging,
# or use rank-based merging (RRF), or ensure IDF is computed globally.
# Global IDF: expensive to maintain. Shards periodically sync doc-frequency stats.

class DistributedIndex:
    """
    Simulates a distributed search index with scatter-gather.

    PRODUCTION EQUIVALENT:
      - Coordinator = Elasticsearch coordinating node
      - Shards = Elasticsearch data nodes (Lucene indices)
      - Vector shards = Qdrant / Weaviate cluster nodes
    """

    def __init__(self, n_shards: int = 4, replication_factor: int = 2):
        self.n_shards = n_shards
        self.replication_factor = replication_factor
        self.ring = ConsistentHashRing(vnodes_per_node=50)
        self.shards: dict[str, Shard] = {}
        self.replicas: dict[str, list[Shard]] = defaultdict(list)  # primary → [replica]

        # Create primary shards
        for i in range(n_shards):
            shard_id = f"shard_{i}"
            self.ring.add_node(shard_id)
            self.shards[shard_id] = Shard(shard_id)

        # Create replica shards
        for i in range(n_shards):
            shard_id = f"shard_{i}"
            for r in range(replication_factor - 1):
                replica_id = f"shard_{i}_replica_{r}"
                self.replicas[shard_id].append(Shard(replica_id))

    def _get_primary_shard(self, doc_id: int) -> Shard:
        node_id = self.ring.get_node(str(doc_id))
        return self.shards[node_id]

    def add_document(self, doc_id: int, text: str, vector: list[float]):
        """Write to primary shard, then replicate."""
        primary = self._get_primary_shard(doc_id)
        primary.add_document(doc_id, text, vector)

        # Replicate to replica shards (sync replication shown here;
        # production often uses async for lower write latency)
        node_id = self.ring.get_node(str(doc_id))
        for replica in self.replicas.get(node_id, []):
            replica.add_document(doc_id, text, vector)

    def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        fetch_k_per_shard: Optional[int] = None,
    ) -> list[SearchResult]:
        """
        Scatter-gather search across all shards.
        fetch_k_per_shard: how many results each shard returns.
                           Must be >= top_k. Higher → better recall at
                           cost of more data transferred to coordinator.
        """
        if fetch_k_per_shard is None:
            fetch_k_per_shard = max(top_k, 20)

        # SCATTER: query all shards (in production: parallel async calls)
        all_results: list[SearchResult] = []
        for shard in self.shards.values():
            shard_results = shard.search(query_vector, top_k=fetch_k_per_shard)
            all_results.extend(shard_results)

        # GATHER + MERGE: take global top-K using min-heap (efficient)
        return heapq.nlargest(top_k, all_results, key=lambda r: r.score)

    def add_shard(self, shard_id: str):
        """
        Expand the cluster: add a new shard.
        In production: triggers rebalancing — documents reassigned to new shard.
        With consistent hashing, only 1/N_new keys need to move.
        """
        self.ring.add_node(shard_id)
        self.shards[shard_id] = Shard(shard_id)
        # NOTE: in production, a rebalancing job would scan existing shards
        # and move documents whose ring assignment now points to new_shard_id.

    def remove_shard(self, shard_id: str):
        """
        Shrink cluster: remove a shard.
        In production: drain documents to other shards first, then remove.
        NEVER remove without draining — you lose those documents.
        """
        self.ring.remove_node(shard_id)
        del self.shards[shard_id]

    def stats(self) -> dict:
        return {
            "n_shards": len(self.shards),
            "docs_per_shard": {sid: s.doc_count for sid, s in self.shards.items()},
            "total_docs": sum(s.doc_count for s in self.shards.values()),
            "replication_factor": self.replication_factor,
        }


# =============================================================================
# NEAR-REAL-TIME INDEXING (NRT)
# =============================================================================
#
# The challenge: new documents need to be searchable with minimal delay.
#
# LUCENE NRT MODEL (how Elasticsearch does it):
#   1. New docs written to an in-memory buffer (not yet searchable)
#   2. "Refresh" (every 1s default): flush buffer to a new immutable segment
#      → docs now searchable
#   3. "Flush/Commit" (on checkpoint): write segment to disk durably
#   4. "Merge" (background): combine small segments into larger ones
#      (too many segments → slow search; merges improve search speed)
#
# NRT vs REAL-TIME vs BATCH:
#   Batch  : rebuild entire index periodically (hours). Simplest. Used for
#             large static corpora or when freshness is unimportant.
#   NRT    : ~1s latency. Good enough for most use cases.
#   RT     : true real-time (<100ms). Requires more complex architecture
#             (write-ahead log, async propagation). Kafka + Flink → index.
#
# EXA.AI CONSIDERATION:
#   Web crawl → extract text → embed → add to index.
#   Crawl-to-searchable latency is a product metric.
#   At web scale, new pages are batch-indexed by crawl priority/freshness.

@dataclass
class IndexUpdate:
    doc_id:    int
    text:      str
    vector:    list[float]
    timestamp: float = field(default_factory=time.time)
    deleted:   bool = False     # tombstone for deletes


class NRTIndexManager:
    """
    Simulates near-real-time index update buffering.
    """

    def __init__(self, index: DistributedIndex, refresh_interval: float = 1.0):
        self.index = index
        self.refresh_interval = refresh_interval
        self._buffer: list[IndexUpdate] = []
        self._last_refresh = time.time()

    def write(self, doc_id: int, text: str, vector: list[float]):
        """Buffer a write. Not yet searchable until refresh."""
        self._buffer.append(IndexUpdate(doc_id, text, vector))

    def delete(self, doc_id: int):
        """Buffer a deletion (tombstone)."""
        self._buffer.append(IndexUpdate(doc_id, "", [], deleted=True))

    def refresh(self) -> int:
        """
        Flush buffered writes to the searchable index.
        Returns number of documents flushed.
        Called automatically or manually.
        """
        if not self._buffer:
            return 0

        flushed = 0
        for update in self._buffer:
            if not update.deleted:
                self.index.add_document(update.doc_id, update.text, update.vector)
                flushed += 1
            # Deletes: in production, set a tombstone bit in the shard
            # Documents are physically removed at merge time

        self._buffer.clear()
        self._last_refresh = time.time()
        return flushed

    def should_refresh(self) -> bool:
        return time.time() - self._last_refresh >= self.refresh_interval

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)


# =============================================================================
# TESTS
# =============================================================================

class TestConsistentHash(unittest.TestCase):
    def setUp(self):
        self.ring = ConsistentHashRing(vnodes_per_node=50)
        for i in range(4):
            self.ring.add_node(f"node_{i}")

    def test_all_keys_assigned(self):
        for i in range(100):
            node = self.ring.get_node(str(i))
            self.assertIsNotNone(node)

    def test_same_key_same_node(self):
        node1 = self.ring.get_node("my_doc_42")
        node2 = self.ring.get_node("my_doc_42")
        self.assertEqual(node1, node2)

    def test_remove_node_reassigns(self):
        key = "test_key"
        original = self.ring.get_node(key)
        # Add a fifth node
        self.ring.add_node("node_4")
        # The key may or may not move (consistent hashing minimizes moves)
        new_node = self.ring.get_node(key)
        # New node must be valid
        self.assertIn(new_node, self.ring.nodes)

    def test_minimal_reassignment_on_add(self):
        """Adding a node should reassign roughly 1/(N+1) fraction of keys."""
        keys = [str(i) for i in range(1000)]
        before = {k: self.ring.get_node(k) for k in keys}

        self.ring.add_node("node_new")
        after = {k: self.ring.get_node(k) for k in keys}

        changed = sum(1 for k in keys if before[k] != after[k])
        fraction_changed = changed / len(keys)
        # Should be roughly 1/5 = 20%; allow generous tolerance
        self.assertLess(fraction_changed, 0.5)

    def test_replication_returns_distinct_nodes(self):
        nodes = self.ring.get_nodes_for_key("key123", replicas=3)
        self.assertEqual(len(set(nodes)), len(nodes))  # all distinct

    def test_vnodes_even_distribution(self):
        dist = self.ring.distribution()
        counts = list(dist.values())
        # All nodes should have same number of vnodes
        self.assertEqual(len(set(counts)), 1)


class TestShard(unittest.TestCase):
    def setUp(self):
        self.shard = Shard("shard_0")
        for i in range(10):
            vec = [random.gauss(0, 1) for _ in range(8)]
            self.shard.add_document(i, f"document {i}", vec)

    def test_search_returns_k(self):
        q = [random.gauss(0, 1) for _ in range(8)]
        results = self.shard.search(q, top_k=5)
        self.assertEqual(len(results), 5)

    def test_scores_descending(self):
        q = [random.gauss(0, 1) for _ in range(8)]
        results = self.shard.search(q, top_k=5)
        scores = [r.score for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))


class TestDistributedIndex(unittest.TestCase):
    def setUp(self):
        random.seed(42)
        self.idx = DistributedIndex(n_shards=3, replication_factor=2)
        self.dim = 8
        for i in range(60):
            vec = [random.gauss(0, 1) for _ in range(self.dim)]
            self.idx.add_document(i, f"document {i}", vec)

    def test_docs_distributed_across_shards(self):
        stats = self.idx.stats()
        # Each shard should have some docs (not all on one shard)
        for count in stats["docs_per_shard"].values():
            self.assertGreater(count, 0)

    def test_search_returns_top_k(self):
        q = [random.gauss(0, 1) for _ in range(self.dim)]
        results = self.idx.search(q, top_k=10)
        self.assertEqual(len(results), 10)

    def test_search_scores_descending(self):
        q = [random.gauss(0, 1) for _ in range(self.dim)]
        results = self.idx.search(q, top_k=5)
        scores = [r.score for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_replication_copies_docs(self):
        """Each doc should exist on primary AND replica shards."""
        # Check a specific doc exists in the primary shard
        doc_id = 5
        primary_shard = self.idx._get_primary_shard(doc_id)
        self.assertIn(doc_id, primary_shard.docs)

        # Check replicas also have the doc
        shard_id = self.idx.ring.get_node(str(doc_id))
        replicas = self.idx.replicas.get(shard_id, [])
        for replica in replicas:
            self.assertIn(doc_id, replica.docs)

    def test_total_docs(self):
        self.assertEqual(self.idx.stats()["total_docs"], 60)


class TestNRTIndexManager(unittest.TestCase):
    def setUp(self):
        self.index = DistributedIndex(n_shards=2, replication_factor=1)
        self.nrt = NRTIndexManager(self.index, refresh_interval=1.0)

    def test_doc_not_searchable_before_refresh(self):
        vec = [1.0, 0.0, 0.0, 0.0]
        self.nrt.write(42, "test document", vec)
        # Not yet in index
        self.assertEqual(self.index.stats()["total_docs"], 0)
        # Buffer has it
        self.assertEqual(self.nrt.buffer_size, 1)

    def test_doc_searchable_after_refresh(self):
        vec = [1.0, 0.0, 0.0, 0.0]
        self.nrt.write(42, "test document", vec)
        flushed = self.nrt.refresh()
        self.assertEqual(flushed, 1)
        self.assertEqual(self.index.stats()["total_docs"], 1)
        self.assertEqual(self.nrt.buffer_size, 0)

    def test_buffer_cleared_after_refresh(self):
        for i in range(5):
            self.nrt.write(i, f"doc {i}", [float(i), 0.0])
        self.nrt.refresh()
        self.assertEqual(self.nrt.buffer_size, 0)


def demo():
    print("=" * 60)
    print("DISTRIBUTED INDEX DEMO")
    print("=" * 60)
    random.seed(42)

    # Consistent hashing demo
    print("\n[Consistent Hashing]")
    ring = ConsistentHashRing(vnodes_per_node=100)
    for i in range(4):
        ring.add_node(f"node_{i}")

    dist = ring.distribution()
    print(f"  Vnode distribution (4 nodes, 100 vnodes each):")
    for node, count in sorted(dist.items()):
        print(f"    {node}: {count} vnodes")

    # Measure reassignment on scale-out
    keys = [str(i) for i in range(10_000)]
    before = {k: ring.get_node(k) for k in keys}
    ring.add_node("node_4")
    after  = {k: ring.get_node(k) for k in keys}
    moved = sum(1 for k in keys if before[k] != after[k])
    print(f"\n  Added node_4: {moved}/{len(keys)} keys moved ({moved/len(keys):.1%})")
    print(f"  Expected ~{1/5:.0%} (1/N_new). Consistent hashing minimizes disruption.")

    # Distributed index
    print("\n[Distributed Index — scatter-gather]")
    dim = 8
    idx = DistributedIndex(n_shards=4, replication_factor=2)
    nrt = NRTIndexManager(idx)

    docs = [
        "Redis caching layer for high throughput",
        "Distributed lock with Redis sentinel",
        "PostgreSQL full-text search with trigrams",
        "HNSW index for approximate nearest neighbors",
        "BM25 ranking for keyword retrieval",
        "Cross-encoder re-ranking improves precision",
        "Product quantization compresses embeddings",
        "Reciprocal rank fusion for hybrid search",
    ]
    for i, text in enumerate(docs):
        vec = [random.gauss(0, 1) for _ in range(dim)]
        nrt.write(i, text, vec)

    print(f"  Buffered {nrt.buffer_size} docs (not yet searchable)")
    flushed = nrt.refresh()
    print(f"  After refresh: {flushed} docs searchable")

    stats = idx.stats()
    print(f"\n  Total docs: {stats['total_docs']}")
    print(f"  Per shard:  {stats['docs_per_shard']}")

    q = [random.gauss(0, 1) for _ in range(dim)]
    results = idx.search(q, top_k=3)
    print(f"\n  Top-3 results (scatter-gather across {idx.n_shards} shards):")
    for r in results:
        print(f"    doc {r.doc_id} ({r.shard_id}) score={r.score:.4f}: {r.text[:50]}")


if __name__ == "__main__":
    demo()
    print("\n\nRUNNING TESTS\n" + "=" * 60)
    unittest.main(verbosity=2, exit=False)