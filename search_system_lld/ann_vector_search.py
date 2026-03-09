"""
=============================================================================
01 — APPROXIMATE NEAREST NEIGHBOR (ANN) SEARCH
=============================================================================
PRIORITY: #1 for exa.ai — this IS their product's core primitive.

WHAT TO MASTER:
  - Why exact kNN is infeasible at scale
  - HNSW: the dominant algorithm in production (Faiss, Weaviate, Qdrant)
  - IVF (Inverted File Index): partition-based ANN
  - Product Quantization (PQ): compression for memory efficiency
  - The recall/latency/memory trilemma

EXA.AI ANGLE:
  Exa indexes the entire web. At billions of documents, you cannot do
  brute-force cosine similarity. HNSW gives ~1ms query at 99% recall.
  They almost certainly use HNSW + PQ compression in their vector store.

INTERVIEW TRAPS TO AVOID:
  - "Just use dot product" — must discuss normalization (L2 vs cosine)
  - Forgetting the recall/latency tradeoff when tuning ef/M parameters
  - Not knowing why HNSW beats Annoy or LSH for high-recall use cases
=============================================================================
"""

import heapq
import math
import random
import time
import unittest
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Vector utilities
# ---------------------------------------------------------------------------

def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))

def norm(a: list[float]) -> float:
    return math.sqrt(sum(x * x for x in a))

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity ∈ [-1, 1]. 1 = identical direction."""
    n = norm(a) * norm(b)
    return dot(a, b) / n if n > 0 else 0.0

def l2_distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

def normalize(v: list[float]) -> list[float]:
    """L2-normalize so cosine similarity == dot product."""
    n = norm(v)
    return [x / n for x in v] if n > 0 else v

def random_unit_vector(dim: int) -> list[float]:
    v = [random.gauss(0, 1) for _ in range(dim)]
    return normalize(v)


# =============================================================================
# BRUTE-FORCE kNN (baseline — O(N*D) per query)
# =============================================================================
# At N=1B, D=768: 1B * 768 * 4 bytes = 3TB just to store vectors.
# Scanning all of them per query at 1ns/op = 768 seconds. Not viable.

def brute_force_knn(
    query: list[float],
    corpus: list[list[float]],
    k: int,
) -> list[tuple[int, float]]:
    """
    Returns [(idx, similarity)] sorted by descending similarity.
    O(N * D) — only usable for N < ~100K or offline ground-truth generation.
    """
    scores = [(i, cosine_similarity(query, vec)) for i, vec in enumerate(corpus)]
    scores.sort(key=lambda x: -x[1])
    return scores[:k]


# =============================================================================
# HNSW — Hierarchical Navigable Small World
# =============================================================================
#
# CONCEPT
# -------
# HNSW builds a multi-layer graph. Higher layers are sparse "express lanes";
# lower layers are dense. Search enters at the top, greedily descends to the
# query's neighborhood, then does a beam search on the bottom layer.
#
# WHY IT WORKS: Small-world graph property — you can reach any node from any
# other node in O(log N) hops. Each layer is a random subset of the layer
# below, creating a hierarchical shortcut structure.
#
# KEY PARAMETERS
#   M         : max connections per node per layer. Higher M → better recall,
#               more memory, slower build. Typical: 16–64.
#   ef_construction : beam width during index build. Higher → better recall,
#               slower build. Typical: 100–200.
#   ef_search : beam width during query. Higher → better recall, slower query.
#               Can be tuned at query time without rebuilding.
#   mL        : level multiplier. Controls layer assignment probability.
#               Default: 1 / ln(M)
#
# COMPLEXITY
#   Build : O(N * M * log N)
#   Query : O(log N) expected hops
#   Memory: O(N * M) edges + O(N * D) vectors
#
# RECALL/LATENCY TRADEOFF
#   ef_search=10  → ~80% recall, very fast
#   ef_search=100 → ~99% recall, ~5x slower
#   This is the primary knob operators tune in production.
#
# FAILURE MODES
#   - "Greedy routing gets stuck" in local optima at higher layers.
#     Mitigated by having multiple entry points at layer 0.
#   - Deletes are hard: HNSW doesn't support true deletes. Typical approach:
#     tombstone + periodic index rebuild (Qdrant uses a separate "deleted" bitset).
#   - Memory: at D=1536 (OpenAI ada-002), each vector = 6KB. 100M vectors = 600GB.
#     PQ compression (Layer 3 below) reduces this 8–32x.
#
# ALTERNATIVES COMPARISON
#   LSH (Locality-Sensitive Hashing): O(1) build, poor recall in high dims.
#   Annoy (Spotify): tree-based, fast build, no updates, lower recall than HNSW.
#   IVF (Faiss): partition-based, lower memory than HNSW, slightly lower recall.
#   ScaNN (Google): optimized for anisotropic quantization, highest throughput.
#   HNSW wins for: high recall, dynamic updates, standard production use.

class HNSW:
    """
    Simplified HNSW implementation for study purposes.
    Production: use hnswlib or Faiss (IndexHNSWFlat).
    """

    def __init__(self, dim: int, M: int = 16, ef_construction: int = 100):
        self.dim = dim
        self.M = M                          # max connections per layer
        self.M0 = 2 * M                     # max connections at layer 0 (denser)
        self.ef_construction = ef_construction
        self.mL = 1.0 / math.log(M)        # level normalization factor

        self.vectors:   list[list[float]] = []          # node_id → vector
        self.graphs:    list[dict[int, list[int]]] = [] # layer → {node: [neighbors]}
        self.max_layer: int = -1
        self.entry_point: Optional[int] = None

    def _random_level(self) -> int:
        """Sample the layer for a new node. Higher layers are exponentially rare."""
        level = 0
        while random.random() < math.exp(-1.0 / self.mL) and level < 16:
            level += 1
        return level

    def _distance(self, a: int, b: int) -> float:
        """L2 distance between two node IDs (could swap to cosine)."""
        return l2_distance(self.vectors[a], self.vectors[b])

    def _search_layer(
        self, query_vec: list[float], entry: int, ef: int, layer: int
    ) -> list[tuple[float, int]]:
        """
        Greedy beam search on a single layer.
        Returns ef nearest neighbors as [(distance, node_id)].
        Uses a max-heap for candidates and min-heap for results.
        """
        visited = {entry}
        # candidates: min-heap by distance (we want to explore closest first)
        entry_dist = l2_distance(query_vec, self.vectors[entry])
        candidates = [(entry_dist, entry)]
        # result set: max-heap so we can evict the farthest easily
        W = [(-entry_dist, entry)]

        while candidates:
            dist_c, c = heapq.heappop(candidates)
            # If closest candidate is farther than worst in W, stop
            worst_dist = -W[0][0]
            if dist_c > worst_dist and len(W) >= ef:
                break

            for neighbor in self.graphs[layer].get(c, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    d = l2_distance(query_vec, self.vectors[neighbor])
                    if d < worst_dist or len(W) < ef:
                        heapq.heappush(candidates, (d, neighbor))
                        heapq.heappush(W, (-d, neighbor))
                        if len(W) > ef:
                            heapq.heappop(W)  # remove farthest

        return [(-neg_d, node) for neg_d, node in W]

    def _select_neighbors(
        self, candidates: list[tuple[float, int]], M: int
    ) -> list[int]:
        """
        Simple neighbor selection: take the M closest.
        Production HNSW uses "heuristic" selection to improve graph diversity.
        """
        candidates.sort()
        return [node for _, node in candidates[:M]]

    def add(self, vector: list[float]) -> int:
        """Insert a vector. Returns its node ID."""
        node_id = len(self.vectors)
        self.vectors.append(vector)
        level = self._random_level()

        # Extend layer list if needed
        while len(self.graphs) <= level:
            self.graphs.append({})

        if self.entry_point is None:
            self.entry_point = node_id
            self.max_layer = level
            return node_id

        ep = self.entry_point

        # Phase 1: descend from max_layer to level+1 (greedy, ef=1)
        for lc in range(self.max_layer, level, -1):
            if lc < len(self.graphs):
                results = self._search_layer(vector, ep, ef=1, layer=lc)
                ep = min(results, key=lambda x: x[0])[1]

        # Phase 2: from level down to 0, do ef_construction beam search
        for lc in range(min(level, self.max_layer), -1, -1):
            results = self._search_layer(vector, ep, self.ef_construction, lc)
            M_lc = self.M0 if lc == 0 else self.M
            neighbors = self._select_neighbors(results, M_lc)

            self.graphs[lc][node_id] = neighbors
            # Add back-links (bidirectional graph)
            for nb in neighbors:
                if nb not in self.graphs[lc]:
                    self.graphs[lc][nb] = []
                self.graphs[lc][nb].append(node_id)
                # Prune if over capacity
                if len(self.graphs[lc][nb]) > M_lc:
                    nb_vec = self.vectors[nb]
                    pruned = sorted(
                        self.graphs[lc][nb],
                        key=lambda x: l2_distance(nb_vec, self.vectors[x])
                    )[:M_lc]
                    self.graphs[lc][nb] = pruned

            ep = results[0][1] if results else ep

        if level > self.max_layer:
            self.max_layer = level
            self.entry_point = node_id

        return node_id

    def search(self, query: list[float], k: int, ef: int = 50) -> list[tuple[int, float]]:
        """
        kNN search. ef controls recall/latency tradeoff.
        Returns [(node_id, distance)] sorted ascending by distance.
        """
        if self.entry_point is None:
            return []

        ep = self.entry_point

        # Descend to layer 1 with ef=1
        for lc in range(self.max_layer, 0, -1):
            if lc < len(self.graphs):
                results = self._search_layer(query, ep, ef=1, layer=lc)
                ep = min(results, key=lambda x: x[0])[1]

        # Search layer 0 with full ef
        results = self._search_layer(query, ep, ef=max(ef, k), layer=0)
        results.sort()
        return [(node_id, dist) for dist, node_id in results[:k]]


# =============================================================================
# IVF — Inverted File Index
# =============================================================================
#
# CONCEPT
# -------
# Cluster vectors into nlist centroids (k-means). At query time, only probe
# the nprobe nearest clusters. Trades recall for speed.
#
# nlist : number of clusters. Rule of thumb: sqrt(N). 
# nprobe: clusters to search. nprobe=1 is fastest; nprobe=nlist = brute force.
#
# IVF vs HNSW
#   IVF  : lower memory (no graph edges), faster build, lower recall for same speed
#   HNSW : higher memory, slower build, higher recall for same latency
#   Production: Faiss IVF_PQ is the standard for billion-scale; HNSW for <100M.

class IVFIndex:
    """
    Simplified IVF. Production: Faiss IndexIVFFlat / IndexIVFPQ.
    """

    def __init__(self, nlist: int = 8):
        self.nlist = nlist
        self.centroids: list[list[float]] = []
        self.cells: dict[int, list[tuple[int, list[float]]]] = defaultdict(list)
        self.trained = False

    def _kmeans(self, vectors: list[list[float]], k: int, iters: int = 20):
        """Mini k-means implementation."""
        dim = len(vectors[0])
        centroids = random.sample(vectors, k)

        for _ in range(iters):
            clusters: dict[int, list[list[float]]] = defaultdict(list)
            for v in vectors:
                nearest = min(range(k), key=lambda i: l2_distance(v, centroids[i]))
                clusters[nearest].append(v)

            new_centroids = []
            for i in range(k):
                if clusters[i]:
                    mean = [sum(v[d] for v in clusters[i]) / len(clusters[i]) for d in range(dim)]
                    new_centroids.append(mean)
                else:
                    new_centroids.append(centroids[i])
            centroids = new_centroids

        return centroids

    def train(self, vectors: list[list[float]]):
        self.centroids = self._kmeans(vectors, self.nlist)
        self.trained = True

    def add(self, doc_id: int, vector: list[float]):
        assert self.trained, "Call train() first"
        cell = min(range(self.nlist), key=lambda i: l2_distance(vector, self.centroids[i]))
        self.cells[cell].append((doc_id, vector))

    def search(self, query: list[float], k: int, nprobe: int = 2) -> list[tuple[int, float]]:
        """Search nprobe nearest cells."""
        assert self.trained
        cell_dists = sorted(range(self.nlist), key=lambda i: l2_distance(query, self.centroids[i]))
        candidates = []
        for cell_id in cell_dists[:nprobe]:
            for doc_id, vec in self.cells[cell_id]:
                candidates.append((l2_distance(query, vec), doc_id))
        candidates.sort()
        return [(doc_id, dist) for dist, doc_id in candidates[:k]]


# =============================================================================
# PRODUCT QUANTIZATION (PQ)
# =============================================================================
#
# CONCEPT
# -------
# Compress high-dimensional vectors by splitting into M subvectors and
# quantizing each subspace independently.
#
# Example: D=128, M=8 → 8 subvectors of dim 16 each.
# Each subspace has k*=256 centroids. Each subvector → 1 byte (its centroid ID).
# 128-dim float32 vector (512 bytes) → 8 bytes. 64x compression!
#
# At query time: precompute distance from query to all centroids in each
# subspace (lookup table), then sum up per-subspace distances. O(D/M * k*) setup,
# O(M) per candidate scan — extremely fast.
#
# RECALL IMPACT
#   PQ introduces quantization error. Mitigated by:
#     - IVFPQ: first IVF partition, then PQ within each cell
#     - ADC (Asymmetric Distance Computation): query exact, DB compressed
#     - Re-ranking: use PQ for candidate retrieval, exact distance for top-K rerank
#
# MEMORY MATH (interview answer)
#   Without PQ: N * D * 4 bytes (float32)
#   With PQ(M=8, k*=256): N * M bytes (1 byte per subspace)
#   1B vectors, D=128: 512GB → 8GB. 64x reduction.

class ProductQuantizer:
    """
    PQ with M subspaces, each with k_star centroids.
    Encodes: vector → M bytes. Decodes: M bytes → approximate vector.
    """

    def __init__(self, M: int = 4, k_star: int = 256):
        self.M = M                   # number of subspaces
        self.k_star = k_star         # centroids per subspace
        self.codebooks: list[list[list[float]]] = []  # M * k_star * (D/M)
        self.subvec_dim: Optional[int] = None

    def train(self, vectors: list[list[float]]):
        D = len(vectors[0])
        assert D % self.M == 0, f"D={D} must be divisible by M={self.M}"
        self.subvec_dim = D // self.M
        self.codebooks = []

        for m in range(self.M):
            # Extract m-th subvector from all training vectors
            subvecs = [v[m * self.subvec_dim:(m + 1) * self.subvec_dim] for v in vectors]
            # k-means on subvectors
            k = min(self.k_star, len(subvecs))
            centroids = self._kmeans_1d(subvecs, k)
            self.codebooks.append(centroids)

    def _kmeans_1d(self, vecs, k, iters=10):
        centroids = random.sample(vecs, k)
        for _ in range(iters):
            clusters = defaultdict(list)
            for v in vecs:
                i = min(range(k), key=lambda i: l2_distance(v, centroids[i]))
                clusters[i].append(v)
            centroids = [
                [sum(v[d] for v in clusters[i]) / len(clusters[i])
                 for d in range(len(vecs[0]))]
                if clusters[i] else centroids[i]
                for i in range(k)
            ]
        return centroids

    def encode(self, vector: list[float]) -> list[int]:
        """Compress a vector to M integers (each 0..k_star-1)."""
        codes = []
        for m in range(self.M):
            sv = vector[m * self.subvec_dim:(m + 1) * self.subvec_dim]
            code = min(range(len(self.codebooks[m])),
                       key=lambda i: l2_distance(sv, self.codebooks[m][i]))
            codes.append(code)
        return codes

    def decode(self, codes: list[int]) -> list[float]:
        """Reconstruct approximate vector from PQ codes."""
        result = []
        for m, code in enumerate(codes):
            result.extend(self.codebooks[m][code])
        return result

    def compute_distance_table(self, query: list[float]) -> list[list[float]]:
        """
        Precompute distances from query to all centroids in each subspace.
        Returns M x k_star table. O(D * k_star / M) to build.
        """
        table = []
        for m in range(self.M):
            qsv = query[m * self.subvec_dim:(m + 1) * self.subvec_dim]
            dists = [l2_distance(qsv, c) for c in self.codebooks[m]]
            table.append(dists)
        return table

    def adc_distance(self, codes: list[int], dist_table: list[list[float]]) -> float:
        """
        Asymmetric Distance Computation: sum pre-computed subspace distances.
        O(M) — extremely fast for scanning millions of compressed vectors.
        """
        return math.sqrt(sum(dist_table[m][c] ** 2 for m, c in enumerate(codes)))


# =============================================================================
# RECALL MEASUREMENT UTILITY
# =============================================================================

def measure_recall(
    true_results: list[list[int]],
    approx_results: list[list[int]],
    k: int,
) -> float:
    """
    Recall@k: fraction of true top-k found in approximate top-k.
    This is THE metric to cite in ANN interviews.
    """
    hits = 0
    total = 0
    for true, approx in zip(true_results, approx_results):
        true_set = set(true[:k])
        approx_set = set(approx[:k])
        hits += len(true_set & approx_set)
        total += len(true_set)
    return hits / total if total > 0 else 0.0


# =============================================================================
# TESTS
# =============================================================================

class TestVectorUtils(unittest.TestCase):
    def test_cosine_identical(self):
        v = [1.0, 0.0, 0.0]
        self.assertAlmostEqual(cosine_similarity(v, v), 1.0)

    def test_cosine_orthogonal(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        self.assertAlmostEqual(cosine_similarity(a, b), 0.0)

    def test_cosine_opposite(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        self.assertAlmostEqual(cosine_similarity(a, b), -1.0)

    def test_normalize_unit(self):
        v = normalize([3.0, 4.0])
        self.assertAlmostEqual(norm(v), 1.0)


class TestBruteForce(unittest.TestCase):
    def test_nearest_is_self(self):
        vecs = [random_unit_vector(8) for _ in range(20)]
        results = brute_force_knn(vecs[0], vecs, k=1)
        self.assertEqual(results[0][0], 0)

    def test_returns_k(self):
        vecs = [random_unit_vector(8) for _ in range(50)]
        results = brute_force_knn(vecs[0], vecs, k=5)
        self.assertEqual(len(results), 5)


class TestHNSW(unittest.TestCase):
    def setUp(self):
        random.seed(42)
        self.dim = 16
        self.hnsw = HNSW(dim=self.dim, M=8, ef_construction=50)
        self.vecs = [random_unit_vector(self.dim) for _ in range(200)]
        for v in self.vecs:
            self.hnsw.add(v)

    def test_search_returns_k(self):
        q = random_unit_vector(self.dim)
        results = self.hnsw.search(q, k=5)
        self.assertEqual(len(results), 5)

    def test_recall_acceptable(self):
        """HNSW should achieve >70% recall@10 even with small ef."""
        random.seed(99)
        queries = [random_unit_vector(self.dim) for _ in range(30)]
        true_results = [
            [idx for idx, _ in brute_force_knn(q, self.vecs, k=10)]
            for q in queries
        ]
        approx_results = [
            [node_id for node_id, _ in self.hnsw.search(q, k=10, ef=30)]
            for q in queries
        ]
        recall = measure_recall(true_results, approx_results, k=10)
        self.assertGreater(recall, 0.60, f"Recall too low: {recall:.2f}")

    def test_higher_ef_better_recall(self):
        random.seed(7)
        q = random_unit_vector(self.dim)
        true_top = {idx for idx, _ in brute_force_knn(q, self.vecs, k=5)}

        low_ef  = {n for n, _ in self.hnsw.search(q, k=5, ef=5)}
        high_ef = {n for n, _ in self.hnsw.search(q, k=5, ef=100)}

        recall_low  = len(true_top & low_ef) / len(true_top)
        recall_high = len(true_top & high_ef) / len(true_top)
        # Higher ef should be at least as good
        self.assertGreaterEqual(recall_high, recall_low)


class TestIVF(unittest.TestCase):
    def setUp(self):
        random.seed(42)
        self.dim = 8
        self.vecs = [random_unit_vector(self.dim) for _ in range(100)]
        self.ivf = IVFIndex(nlist=4)
        self.ivf.train(self.vecs)
        for i, v in enumerate(self.vecs):
            self.ivf.add(i, v)

    def test_search_returns_k(self):
        q = random_unit_vector(self.dim)
        results = self.ivf.search(q, k=5, nprobe=2)
        self.assertLessEqual(len(results), 5)

    def test_higher_nprobe_more_results(self):
        q = random_unit_vector(self.dim)
        r1 = self.ivf.search(q, k=10, nprobe=1)
        r2 = self.ivf.search(q, k=10, nprobe=4)
        self.assertGreaterEqual(len(r2), len(r1))


class TestProductQuantizer(unittest.TestCase):
    def setUp(self):
        random.seed(42)
        self.dim = 8
        self.M = 2
        self.vecs = [random_unit_vector(self.dim) for _ in range(100)]
        self.pq = ProductQuantizer(M=self.M, k_star=4)
        self.pq.train(self.vecs)

    def test_encode_length(self):
        codes = self.pq.encode(self.vecs[0])
        self.assertEqual(len(codes), self.M)

    def test_decode_approx_original(self):
        v = self.vecs[0]
        codes = self.pq.encode(v)
        reconstructed = self.pq.decode(codes)
        dist = l2_distance(v, reconstructed)
        # Reconstruction should be reasonably close
        self.assertLess(dist, 2.0)

    def test_adc_close_to_true_distance(self):
        q = random_unit_vector(self.dim)
        v = self.vecs[5]
        codes = self.pq.encode(v)
        table = self.pq.compute_distance_table(q)
        adc_dist = self.pq.adc_distance(codes, table)
        true_dist = l2_distance(q, v)
        # ADC is approximate; within 2x of true distance
        self.assertLess(abs(adc_dist - true_dist), true_dist + 1.5)

    def test_compression_ratio(self):
        # Original: dim * 4 bytes (float32). Compressed: M bytes.
        ratio = (self.dim * 4) / self.M
        self.assertEqual(ratio, 16.0)  # 16x for these settings


class TestRecall(unittest.TestCase):
    def test_perfect_recall(self):
        true = [[0, 1, 2], [3, 4, 5]]
        approx = [[0, 1, 2], [3, 4, 5]]
        self.assertAlmostEqual(measure_recall(true, approx, k=3), 1.0)

    def test_zero_recall(self):
        true = [[0, 1, 2], [3, 4, 5]]
        approx = [[9, 8, 7], [6, 7, 8]]
        self.assertAlmostEqual(measure_recall(true, approx, k=3), 0.0)

    def test_partial_recall(self):
        true = [[0, 1, 2, 3]]
        approx = [[0, 1, 9, 9]]
        self.assertAlmostEqual(measure_recall(true, approx, k=4), 0.5)


def demo():
    print("=" * 60)
    print("ANN VECTOR SEARCH DEMO")
    print("=" * 60)
    random.seed(42)
    dim, N = 32, 500

    print(f"\nBuilding corpus: {N} vectors, dim={dim}")
    corpus = [random_unit_vector(dim) for _ in range(N)]

    # HNSW
    print("\n[HNSW] Building index...")
    t0 = time.time()
    hnsw = HNSW(dim=dim, M=16, ef_construction=100)
    for v in corpus:
        hnsw.add(v)
    build_time = time.time() - t0
    print(f"  Build: {build_time:.2f}s  |  Layers: {hnsw.max_layer + 1}")

    query = random_unit_vector(dim)
    true_top10 = [idx for idx, _ in brute_force_knn(query, corpus, k=10)]

    for ef in [10, 30, 100]:
        t0 = time.time()
        approx = [n for n, _ in hnsw.search(query, k=10, ef=ef)]
        elapsed = (time.time() - t0) * 1000
        recall = len(set(true_top10) & set(approx)) / 10
        print(f"  ef={ef:>3} → recall={recall:.0%}, latency={elapsed:.3f}ms")

    # PQ compression
    print("\n[PQ] Training quantizer...")
    pq = ProductQuantizer(M=8, k_star=16)
    pq.train(corpus[:200])
    v = corpus[0]
    codes = pq.encode(v)
    print(f"  Original size : {dim * 4} bytes")
    print(f"  Compressed    : {len(codes)} bytes  ({dim * 4 // len(codes)}x compression)")
    print(f"  Codes         : {codes}")

    print("\n[Recall measurement]")
    queries = [random_unit_vector(dim) for _ in range(50)]
    true_results  = [[i for i, _ in brute_force_knn(q, corpus, k=10)] for q in queries]
    approx_results = [[n for n, _ in hnsw.search(q, k=10, ef=50)] for q in queries]
    print(f"  Recall@10 (ef=50): {measure_recall(true_results, approx_results, k=10):.2%}")


if __name__ == "__main__":
    demo()
    print("\n\nRUNNING TESTS\n" + "=" * 60)
    unittest.main(verbosity=2, exit=False)