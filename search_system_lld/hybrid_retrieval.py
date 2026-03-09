"""
=============================================================================
02 — HYBRID RETRIEVAL + RECIPROCAL RANK FUSION (RRF)
=============================================================================
PRIORITY: #2 for exa.ai — they explicitly combine neural + keyword signals.

WHAT TO MASTER:
  - Why neither BM25 nor dense retrieval alone is sufficient
  - Reciprocal Rank Fusion (RRF): the dominant late-fusion algorithm
  - Score normalization pitfalls (min-max, softmax)
  - Hybrid retrieval architectures: early vs late fusion
  - When to weight one retriever over the other

EXA.AI ANGLE:
  Exa is "neural-first" but still needs exact-match signals (URLs, product
  names, code identifiers). Their search likely fuses a dense embedding
  retriever with a sparse BM25/SPLADE retriever. RRF is the standard way
  to do this without needing to tune score scales.

KEY INSIGHT FOR INTERVIEW:
  BM25 and dense scores live on DIFFERENT scales and have DIFFERENT
  distributions. You cannot simply add them: BM25 score=12.3 is not
  comparable to cosine_sim=0.82. RRF sidesteps this entirely by
  working only on RANKS, not raw scores.
=============================================================================
"""

import math
import random
import unittest
from collections import defaultdict
from typing import Optional


# ---------------------------------------------------------------------------
# Minimal inverted index (BM25) — pulled from previous script
# ---------------------------------------------------------------------------

def tokenize(text: str) -> list[str]:
    import re
    return re.findall(r"[a-z0-9]+", text.lower())

def normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n > 0 else v

def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class BM25Retriever:
    """Thin BM25 retriever (see inverted_index.py for deep implementation)."""

    def __init__(self, k1: float = 1.2, b: float = 0.75):
        self.k1, self.b = k1, b
        self.index: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self.docs: dict[int, str] = {}
        self.doc_lengths: dict[int, int] = {}

    def add(self, doc_id: int, text: str):
        self.docs[doc_id] = text
        tokens = tokenize(text)
        self.doc_lengths[doc_id] = len(tokens)
        for t in tokens:
            self.index[t][doc_id] += 1

    @property
    def avgdl(self):
        return sum(self.doc_lengths.values()) / max(len(self.doc_lengths), 1)

    def idf(self, term: str) -> float:
        N = len(self.docs)
        df = len(self.index.get(term, {}))
        return math.log((N - df + 0.5) / (df + 0.5) + 1)

    def score(self, term: str, doc_id: int) -> float:
        tf = self.index.get(term, {}).get(doc_id, 0)
        dl = self.doc_lengths.get(doc_id, 0)
        tf_norm = (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
        return self.idf(term) * tf_norm

    def search(self, query: str, top_k: int = 20) -> list[tuple[int, float]]:
        scores: dict[int, float] = defaultdict(float)
        for t in tokenize(query):
            for doc_id in self.index.get(t, {}):
                scores[doc_id] += self.score(t, doc_id)
        return sorted(scores.items(), key=lambda x: -x[1])[:top_k]


# =============================================================================
# Dense (Embedding) Retriever
# =============================================================================
# In production this wraps a vector index (HNSW/Faiss).
# Here we simulate with random embeddings for testing.

class DenseRetriever:
    """
    Cosine-similarity retriever over stored unit vectors.
    In production: backed by HNSW (see 01_ann_vector_search.py).
    """

    def __init__(self, dim: int = 16):
        self.dim = dim
        self.vectors: dict[int, list[float]] = {}

    def add(self, doc_id: int, vector: list[float]):
        self.vectors[doc_id] = normalize(vector)

    def search(self, query_vector: list[float], top_k: int = 20) -> list[tuple[int, float]]:
        q = normalize(query_vector)
        scores = [(doc_id, dot(q, v)) for doc_id, v in self.vectors.items()]
        scores.sort(key=lambda x: -x[1])
        return scores[:top_k]


# =============================================================================
# SCORE FUSION METHODS
# =============================================================================

# ── Method 1: Reciprocal Rank Fusion (RRF) ──────────────────────────────────
#
# ALGORITHM (Cormack, Clarke & Buettcher, 2009)
#   RRF_score(d) = Σ_r 1 / (k + rank_r(d))
#   k = 60  (constant; empirically robust, rarely needs tuning)
#
# WHY RRF WORKS:
#   - Rank-based: immune to score scale differences between retrievers
#   - Top-ranked docs get high contribution (1/61); low-ranked docs get tiny contribution
#   - Docs appearing in multiple lists get additive boosts
#   - k=60 dampens the advantage of rank-1 — prevents any single list from dominating
#
# WHEN RRF FAILS:
#   - Can't express "I trust the dense retriever 3x more" (no weights)
#   - If one retriever returns 1000 results and another returns 10, the 10-result
#     list dominates the top ranks (cardinality mismatch)
#   - Solution: weighted RRF (wRRF) = Σ_r w_r / (k + rank_r(d))

def reciprocal_rank_fusion(
    ranked_lists: list[list[int]],
    k: int = 60,
    weights: Optional[list[float]] = None,
) -> list[tuple[int, float]]:
    """
    Fuse multiple ranked lists via RRF.

    Args:
        ranked_lists : list of ranked doc_id lists (index 0 = rank 1)
        k            : smoothing constant (default 60)
        weights      : per-list weights for weighted RRF (default uniform)

    Returns:
        [(doc_id, rrf_score)] sorted by descending score
    """
    if weights is None:
        weights = [1.0] * len(ranked_lists)
    assert len(weights) == len(ranked_lists)

    scores: dict[int, float] = defaultdict(float)
    for ranked, w in zip(ranked_lists, weights):
        for rank, doc_id in enumerate(ranked, start=1):
            scores[doc_id] += w / (k + rank)

    return sorted(scores.items(), key=lambda x: -x[1])


# ── Method 2: Normalized Score Fusion ───────────────────────────────────────
#
# Normalize each retriever's scores to [0,1] then combine.
# PROBLEM: min-max normalization is query-dependent and sensitive to outliers.
# A single very high BM25 score compresses all others toward 0.
# Use only when you have carefully calibrated score distributions.

def min_max_normalize(scores: list[tuple[int, float]]) -> list[tuple[int, float]]:
    if not scores:
        return []
    vals = [s for _, s in scores]
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return [(doc_id, 1.0) for doc_id, _ in scores]
    return [(doc_id, (s - lo) / (hi - lo)) for doc_id, s in scores]


def score_fusion(
    *score_lists: list[tuple[int, float]],
    weights: Optional[list[float]] = None,
) -> list[tuple[int, float]]:
    """
    Normalize each score list to [0,1] and linearly combine.
    More sensitive to outliers than RRF but allows fine-grained weighting.
    """
    if weights is None:
        weights = [1.0] * len(score_lists)

    combined: dict[int, float] = defaultdict(float)
    for score_list, w in zip(score_lists, weights):
        for doc_id, score in min_max_normalize(score_list):
            combined[doc_id] += w * score

    return sorted(combined.items(), key=lambda x: -x[1])


# ── Method 3: Convex Combination (requires calibrated scores) ───────────────
#
# final_score = α * dense_score + (1 - α) * sparse_score
# ONLY valid when both score distributions are calibrated.
# For cosine similarity (bounded [-1,1]) + BM25 (unbounded), this is unsafe.
# After min-max normalization it becomes safe but loses outlier information.


# =============================================================================
# HYBRID RETRIEVER (puts it all together)
# =============================================================================

class HybridRetriever:
    """
    Two-stage hybrid retrieval:
      Stage 1: BM25 retrieval (sparse, exact-match)
      Stage 1: Dense retrieval (semantic, embedding-based)
      Stage 2: RRF fusion
      Stage 3: (Optional) re-ranking (see 03_reranking.py)

    ARCHITECTURE NOTE (exa.ai style):
      In production you'd run both retrievers in parallel (fan-out),
      then merge results. Latency = max(BM25_latency, Dense_latency)
      not their sum — this is why parallelism is critical.
    """

    def __init__(
        self,
        dim: int = 16,
        rrf_k: int = 60,
        dense_weight: float = 1.0,
        sparse_weight: float = 1.0,
    ):
        self.sparse = BM25Retriever()
        self.dense  = DenseRetriever(dim=dim)
        self.dim = dim
        self.rrf_k = rrf_k
        self.dense_weight  = dense_weight
        self.sparse_weight = sparse_weight

    def add(self, doc_id: int, text: str, vector: list[float]):
        self.sparse.add(doc_id, text)
        self.dense.add(doc_id, vector)

    def search(
        self,
        query_text: str,
        query_vector: list[float],
        top_k: int = 10,
        fetch_k: int = 50,         # how many candidates each retriever fetches
        method: str = "rrf",       # "rrf" | "score_fusion"
    ) -> list[dict]:
        """
        Hybrid search with configurable fusion strategy.

        fetch_k > top_k is important: each retriever may miss relevant docs
        that the other finds. Fetching more candidates improves final recall.
        Rule of thumb: fetch_k = 3-5x top_k.
        """
        # Parallel retrieval (in production: asyncio / threading)
        sparse_results = self.sparse.search(query_text, top_k=fetch_k)
        dense_results  = self.dense.search(query_vector, top_k=fetch_k)

        if method == "rrf":
            sparse_ranked = [doc_id for doc_id, _ in sparse_results]
            dense_ranked  = [doc_id for doc_id, _ in dense_results]
            fused = reciprocal_rank_fusion(
                [dense_ranked, sparse_ranked],
                k=self.rrf_k,
                weights=[self.dense_weight, self.sparse_weight],
            )
        else:  # score_fusion
            fused = score_fusion(
                dense_results, sparse_results,
                weights=[self.dense_weight, self.sparse_weight],
            )

        return [
            {"doc_id": doc_id, "score": round(score, 6)}
            for doc_id, score in fused[:top_k]
        ]


# =============================================================================
# SPLADE — Sparse Learned Attention for Document Expansion
# =============================================================================
#
# CONCEPT (important for exa.ai interview)
# ─────────────────────────────────────────
# SPLADE is a learned sparse retriever that uses a BERT-style encoder to
# expand both queries and documents into sparse vectors over the vocabulary.
# Unlike BM25 (exact match), SPLADE can match "dog" to "canine".
#
# Unlike dense retrievers, SPLADE outputs are SPARSE (most vocab weights = 0)
# so they can use inverted index infrastructure — O(1) lookup, not O(N) scan.
#
# In production: SPLADE models output a dict {token_id: weight} where most
# weights are 0 (via ReLU). The inverted index stores these sparse vectors.
#
# Simplified simulation below (real SPLADE needs a trained transformer).

class SPLADERetriever:
    """
    Simulates SPLADE-style sparse vector retrieval.
    Real SPLADE: inference through BERT + log(1 + ReLU(output)) aggregation.
    """

    def __init__(self, vocab_size: int = 100):
        self.vocab_size = vocab_size
        # Sparse inverted index: token_id → {doc_id: weight}
        self.index: dict[int, dict[int, float]] = defaultdict(dict)
        self.doc_vectors: dict[int, dict[int, float]] = {}

    def _encode(self, text: str, sparsity: float = 0.95) -> dict[int, float]:
        """
        Simulate SPLADE encoding: sparse vector over vocabulary.
        Real: BERT forward pass → max-pool over tokens → ReLU → log(1+x).
        """
        random.seed(hash(text) % (2**32))
        vec = {}
        for token_id in range(self.vocab_size):
            if random.random() > sparsity:
                weight = random.uniform(0.1, 2.0)
                vec[token_id] = weight
        return vec

    def add(self, doc_id: int, text: str):
        vec = self._encode(text)
        self.doc_vectors[doc_id] = vec
        for token_id, weight in vec.items():
            self.index[token_id][doc_id] = weight

    def search(self, query: str, top_k: int = 20) -> list[tuple[int, float]]:
        """Dot product between sparse query vector and sparse doc vectors."""
        q_vec = self._encode(query)
        scores: dict[int, float] = defaultdict(float)
        for token_id, q_weight in q_vec.items():
            for doc_id, d_weight in self.index.get(token_id, {}).items():
                scores[doc_id] += q_weight * d_weight
        return sorted(scores.items(), key=lambda x: -x[1])[:top_k]


# =============================================================================
# TESTS
# =============================================================================

def _make_hybrid(n_docs=30):
    random.seed(42)
    dim = 8
    h = HybridRetriever(dim=dim)
    for i in range(n_docs):
        text = f"document {i} about redis cache distributed systems" if i % 3 == 0 \
               else f"document {i} about postgres database relational"
        vec = [random.gauss(0, 1) for _ in range(dim)]
        h.add(i, text, vec)
    return h, dim


class TestRRF(unittest.TestCase):
    def test_doc_in_both_lists_ranks_higher(self):
        list_a = [1, 2, 3, 4, 5]
        list_b = [6, 2, 7, 8, 9]
        # doc 2 is in both lists; should rank high
        results = reciprocal_rank_fusion([list_a, list_b])
        top_ids = [doc_id for doc_id, _ in results[:3]]
        self.assertIn(2, top_ids)

    def test_rrf_score_decreases_with_rank(self):
        results = reciprocal_rank_fusion([[0, 1, 2, 3]])
        scores = [s for _, s in results]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_weighted_rrf_amplifies_preferred_list(self):
        list_dense  = [99, 1, 2]
        list_sparse = [1, 2, 99]
        # Upweight dense → doc 99 (rank 1 in dense) should win
        r_dense  = dict(reciprocal_rank_fusion([list_dense, list_sparse], weights=[10.0, 1.0]))
        r_sparse = dict(reciprocal_rank_fusion([list_dense, list_sparse], weights=[1.0, 10.0]))
        # When dense is upweighted, doc 99 should score highest
        self.assertEqual(max(r_dense, key=r_dense.get), 99)
        # When sparse is upweighted, doc 1 (rank 1 in sparse) should score highest
        self.assertEqual(max(r_sparse, key=r_sparse.get), 1)

    def test_k_parameter_dampens_rank1_advantage(self):
        # With k=1, rank-1 doc has score 1/(1+1)=0.5, rank-2 has 1/(1+2)=0.33
        # With k=60, rank-1 = 1/61=0.016, rank-2 = 1/62=0.016 (much closer)
        r_low_k  = dict(reciprocal_rank_fusion([[0, 1]], k=1))
        r_high_k = dict(reciprocal_rank_fusion([[0, 1]], k=60))
        gap_low  = r_low_k[0]  - r_low_k[1]
        gap_high = r_high_k[0] - r_high_k[1]
        self.assertGreater(gap_low, gap_high)

    def test_empty_lists(self):
        self.assertEqual(reciprocal_rank_fusion([[], []]), [])


class TestNormalization(unittest.TestCase):
    def test_min_max_bounds(self):
        scores = [(0, 1.0), (1, 5.0), (2, 3.0)]
        normed = dict(min_max_normalize(scores))
        self.assertAlmostEqual(normed[0], 0.0)
        self.assertAlmostEqual(normed[1], 1.0)

    def test_min_max_all_equal(self):
        scores = [(0, 5.0), (1, 5.0)]
        normed = dict(min_max_normalize(scores))
        self.assertAlmostEqual(normed[0], 1.0)
        self.assertAlmostEqual(normed[1], 1.0)


class TestHybridRetriever(unittest.TestCase):
    def setUp(self):
        self.h, self.dim = _make_hybrid()

    def test_rrf_returns_top_k(self):
        q_vec = [random.gauss(0, 1) for _ in range(self.dim)]
        results = self.h.search("redis cache", q_vec, top_k=5, method="rrf")
        self.assertEqual(len(results), 5)

    def test_score_fusion_returns_top_k(self):
        q_vec = [random.gauss(0, 1) for _ in range(self.dim)]
        results = self.h.search("redis cache", q_vec, top_k=5, method="score_fusion")
        self.assertEqual(len(results), 5)

    def test_results_have_required_fields(self):
        q_vec = [random.gauss(0, 1) for _ in range(self.dim)]
        results = self.h.search("redis", q_vec, top_k=3)
        for r in results:
            self.assertIn("doc_id", r)
            self.assertIn("score", r)

    def test_fetch_k_affects_results(self):
        """More candidates fetched → potentially different final top-k."""
        random.seed(5)
        q_vec = [random.gauss(0, 1) for _ in range(self.dim)]
        r1 = self.h.search("redis cache", q_vec, top_k=5, fetch_k=5)
        r2 = self.h.search("redis cache", q_vec, top_k=5, fetch_k=30)
        # Results may differ — this tests the code path, not a correctness property
        self.assertEqual(len(r1), 5)
        self.assertEqual(len(r2), 5)

    def test_hybrid_finds_more_than_either_alone(self):
        """
        A document that ranks low in one retriever but high in the other
        should still appear in hybrid results. This is the core value prop.
        """
        # Add a doc that exactly matches the query text (BM25 wins)
        # but has a random vector (dense won't find it)
        random.seed(99)
        self.h.add(999, "unique_keyword_xyzzy rare term", [random.gauss(0, 1) for _ in range(self.dim)])

        q_vec = [random.gauss(0, 1) for _ in range(self.dim)]
        sparse_only = self.h.sparse.search("unique_keyword_xyzzy", top_k=5)
        hybrid = self.h.search("unique_keyword_xyzzy", q_vec, top_k=10)

        sparse_ids = {d for d, _ in sparse_only}
        hybrid_ids = {r["doc_id"] for r in hybrid}
        # The keyword-matching doc should appear in both
        self.assertIn(999, sparse_ids)
        self.assertIn(999, hybrid_ids)


class TestSPLADE(unittest.TestCase):
    def setUp(self):
        self.splade = SPLADERetriever(vocab_size=50)
        for i in range(20):
            self.splade.add(i, f"document {i} content words here")

    def test_returns_results(self):
        results = self.splade.search("document content", top_k=5)
        self.assertGreater(len(results), 0)

    def test_scores_positive(self):
        for _, score in self.splade.search("query", top_k=5):
            self.assertGreater(score, 0)


def demo():
    print("=" * 60)
    print("HYBRID RETRIEVAL + RRF DEMO")
    print("=" * 60)
    random.seed(42)
    dim = 8

    h = HybridRetriever(dim=dim)
    corpus = [
        (0,  "Redis is an in-memory data store used for caching"),
        (1,  "PostgreSQL is a relational database with ACID guarantees"),
        (2,  "Redis supports pub/sub and distributed locks"),
        (3,  "Elasticsearch uses inverted indexes for full-text search"),
        (4,  "Redis cluster enables horizontal scaling of in-memory data"),
        (5,  "Vector databases store embeddings for semantic search"),
        (6,  "BM25 is a ranking function used in information retrieval"),
        (7,  "Neural search uses embeddings to find semantically similar docs"),
    ]
    for doc_id, text in corpus:
        vec = [random.gauss(0, 1) for _ in range(dim)]
        h.add(doc_id, text, vec)

    q_text = "redis cache memory"
    q_vec  = [random.gauss(0, 1) for _ in range(dim)]

    print(f"\nQuery: '{q_text}'")
    print("\n[Sparse BM25 only]")
    for doc_id, score in h.sparse.search(q_text, top_k=5):
        print(f"  doc {doc_id} ({score:.3f}): {corpus[doc_id][1][:50]}")

    print("\n[Dense only]")
    for doc_id, score in h.dense.search(q_vec, top_k=5):
        print(f"  doc {doc_id} ({score:.3f}): {corpus[doc_id][1][:50]}")

    print("\n[Hybrid RRF]")
    for r in h.search(q_text, q_vec, top_k=5, method="rrf"):
        print(f"  doc {r['doc_id']} ({r['score']:.6f}): {corpus[r['doc_id']][1][:50]}")

    print("\n[RRF internals — showing rank contribution]")
    sparse_ranked = [d for d, _ in h.sparse.search(q_text, top_k=8)]
    dense_ranked  = [d for d, _ in h.dense.search(q_vec, top_k=8)]
    for doc_id, score in reciprocal_rank_fusion([dense_ranked, sparse_ranked])[:5]:
        s_rank = sparse_ranked.index(doc_id) + 1 if doc_id in sparse_ranked else "—"
        d_rank = dense_ranked.index(doc_id)  + 1 if doc_id in dense_ranked  else "—"
        print(f"  doc {doc_id}: rrf={score:.5f}  dense_rank={d_rank}  sparse_rank={s_rank}")


if __name__ == "__main__":
    demo()
    print("\n\nRUNNING TESTS\n" + "=" * 60)
    unittest.main(verbosity=2, exit=False)