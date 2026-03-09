"""
=============================================================================
03 — RE-RANKING: BI-ENCODER + CROSS-ENCODER (TWO-TOWER PATTERN)
=============================================================================
PRIORITY: #3 for exa.ai — their re-ranking layer is a key differentiator.

WHAT TO MASTER:
  - Why retrieval and ranking are separate stages
  - Bi-encoder: fast, precomputed, approximate
  - Cross-encoder: slow, joint encoding, high quality
  - The retrieve-then-rerank pipeline
  - Learning to Rank (LTR): pointwise, pairwise, listwise
  - NDCG, MRR, MAP — the metrics that matter

EXA.AI ANGLE:
  Exa fetches candidates with a bi-encoder (fast ANN), then re-ranks with a
  cross-encoder (quality). The cross-encoder jointly encodes query+document,
  capturing interaction signals the bi-encoder misses. For exa.ai's "neural
  search" product, re-ranking quality is a core moat.

KEY INSIGHT:
  Bi-encoder: encode(query) · encode(doc) — no interaction between Q and D
  Cross-encoder: encode(query + doc) — full attention over both, much richer
  But cross-encoder is O(N) at query time — only viable for small candidate sets.
  This is exactly why you need the two-stage pipeline.
=============================================================================
"""

import math
import random
import unittest
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Shared vector utilities
# ---------------------------------------------------------------------------

def dot(a, b): return sum(x * y for x, y in zip(a, b))
def norm(v):   return math.sqrt(sum(x * x for x in v))
def normalize(v):
    n = norm(v)
    return [x / n for x in v] if n > 0 else v
def cosine(a, b): return dot(normalize(a), normalize(b))


# =============================================================================
# STAGE 1: BI-ENCODER (fast retrieval)
# =============================================================================
#
# ARCHITECTURE
# ────────────
# Two separate encoder towers: one for queries, one for documents.
# Documents are encoded OFFLINE and stored in a vector index.
# At query time, ONLY the query is encoded (~10ms), then ANN search.
#
# TRAINING OBJECTIVE
# ──────────────────
# Contrastive learning with in-batch negatives:
#   For a batch of (query, positive_doc) pairs:
#     - positive: (query_i, doc_i) — should have high similarity
#     - negatives: (query_i, doc_j) for j≠i — should have low similarity
#   Loss = InfoNCE (NT-Xent):
#     L = -log( exp(sim(q,d+)/τ) / Σ_j exp(sim(q,dj)/τ) )
#   τ (temperature) controls how "peaky" the distribution is.
#
# WHY BI-ENCODER IS FAST:
#   doc embeddings precomputed → stored in HNSW
#   Query time: 1 forward pass + ANN lookup = O(log N)
#
# WHY BI-ENCODER IS APPROXIMATE:
#   No cross-attention between query and doc → misses interaction signals
#   "bank" (financial) vs "bank" (river) — bi-encoder gets context from
#   query OR doc, but not from their interaction.

@dataclass
class Document:
    doc_id:    int
    text:      str
    embedding: list[float]


class BiEncoderRetriever:
    """
    Simulates a bi-encoder retriever.
    Real implementation: SentenceTransformers (sentence-transformers library),
    trained with multiple negatives ranking loss.
    """

    def __init__(self, dim: int = 16):
        self.dim = dim
        self.docs: dict[int, Document] = {}
        # In production this would be backed by HNSW
        self._embeddings: list[tuple[int, list[float]]] = []

    def encode_query(self, text: str) -> list[float]:
        """
        Simulate query encoding. Real: transformer forward pass.
        Here we use a deterministic hash-based embedding for reproducibility.
        """
        random.seed(hash(text) % (2**32))
        return normalize([random.gauss(0, 1) for _ in range(self.dim)])

    def encode_doc(self, text: str) -> list[float]:
        """Separate encoder for documents (can share weights or not)."""
        random.seed(hash("doc:" + text) % (2**32))
        return normalize([random.gauss(0, 1) for _ in range(self.dim)])

    def add(self, doc_id: int, text: str, embedding: Optional[list[float]] = None):
        emb = embedding if embedding is not None else self.encode_doc(text)
        doc = Document(doc_id, text, emb)
        self.docs[doc_id] = doc
        self._embeddings.append((doc_id, emb))

    def search(self, query: str, top_k: int = 50) -> list[tuple[Document, float]]:
        """Returns (Document, similarity) pairs sorted by descending similarity."""
        q_emb = self.encode_query(query)
        scored = [(doc_id, cosine(q_emb, emb)) for doc_id, emb in self._embeddings]
        scored.sort(key=lambda x: -x[1])
        return [(self.docs[doc_id], score) for doc_id, score in scored[:top_k]]


# =============================================================================
# STAGE 2: CROSS-ENCODER (quality re-ranking)
# =============================================================================
#
# ARCHITECTURE
# ────────────
# A single encoder processes CONCATENATED query + document:
#   input = [CLS] query [SEP] document [SEP]
#   output = sigmoid(linear(CLS_embedding)) → relevance score ∈ [0,1]
#
# Because of cross-attention, the model can capture:
#   - "does the doc actually answer the question?"
#   - disambiguation (bank = financial vs river, given query context)
#   - subtle semantic signals
#
# TRAINING OBJECTIVE
# ──────────────────
# Pointwise: binary cross-entropy on (query, doc, label=0/1)
# Pairwise:  ranking loss — score(q, d+) > score(q, d-) by margin
# Listwise:  directly optimize NDCG (LambdaRank/LambdaLoss)
#
# LATENCY COST
# ────────────
# A BERT-base cross-encoder: ~50ms per (query, doc) pair on CPU.
# For 1000 candidates: 50 seconds. NOT viable.
# For 50 candidates: 2.5 seconds. Borderline.
# For 10-20 candidates: 0.5-1s. Acceptable with GPU/quantization.
# → This is why Stage 1 retrieval must aggressively cut to ~20-50 candidates.

class CrossEncoderReranker:
    """
    Simulates a cross-encoder re-ranker.
    Real implementation: ms-marco-MiniLM cross-encoder from sentence-transformers.
    """

    def __init__(self, score_fn: Optional[Callable] = None):
        """
        score_fn: (query, doc_text) → float ∈ [0, 1]
        In production: transformer forward pass on concatenated input.
        """
        self._score_fn = score_fn or self._default_score

    def _default_score(self, query: str, doc_text: str) -> float:
        """
        Simulated cross-encoder: uses token overlap as a weak proxy.
        Real cross-encoder: BERT joint encoding with learned relevance head.
        """
        import re
        def tok(t): return set(re.findall(r"[a-z0-9]+", t.lower()))
        q_terms = tok(query)
        d_terms = tok(doc_text)
        if not q_terms or not d_terms:
            return 0.0
        overlap = len(q_terms & d_terms)
        # Jaccard + length penalty (longer docs dilute relevance signal)
        jaccard = overlap / len(q_terms | d_terms)
        # Add small noise to simulate model variance
        random.seed(hash(query + doc_text) % (2**32))
        noise = random.uniform(-0.05, 0.05)
        return max(0.0, min(1.0, jaccard * 3 + noise))

    def rerank(
        self,
        query: str,
        candidates: list[tuple[Document, float]],
        top_k: int = 10,
    ) -> list[tuple[Document, float]]:
        """
        Re-score candidates with cross-encoder, return top_k.
        O(|candidates|) — must be small for latency to be acceptable.
        """
        reranked = []
        for doc, _bi_score in candidates:
            ce_score = self._score_fn(query, doc.text)
            reranked.append((doc, ce_score))

        reranked.sort(key=lambda x: -x[1])
        return reranked[:top_k]


# =============================================================================
# FULL TWO-STAGE PIPELINE
# =============================================================================

class TwoStagePipeline:
    """
    Retrieve → Rerank pipeline.

    Stage 1: bi-encoder ANN retrieval (fast, ~1ms, top-50 candidates)
    Stage 2: cross-encoder re-ranking (quality, ~100ms, top-10 final)

    TUNING KNOBS:
      fetch_k    : how many Stage 1 candidates to pass to Stage 2
                   Higher → better recall but slower Stage 2
                   Rule of thumb: 50-200 for production
      final_k    : final results returned to user
    """

    def __init__(self, dim: int = 16):
        self.retriever = BiEncoderRetriever(dim=dim)
        self.reranker  = CrossEncoderReranker()

    def add(self, doc_id: int, text: str):
        self.retriever.add(doc_id, text)

    def search(
        self,
        query: str,
        final_k: int = 10,
        fetch_k: int = 50,
    ) -> list[dict]:
        # Stage 1: fast retrieval
        candidates = self.retriever.search(query, top_k=fetch_k)

        # Stage 2: quality re-ranking
        reranked = self.reranker.rerank(query, candidates, top_k=final_k)

        return [
            {
                "doc_id":    doc.doc_id,
                "text":      doc.text,
                "ce_score":  round(score, 4),
                "bi_score":  round(
                    next(s for d, s in candidates if d.doc_id == doc.doc_id), 4
                ),
            }
            for doc, score in reranked
        ]


# =============================================================================
# LEARNING TO RANK (LTR)
# =============================================================================
#
# OVERVIEW
# ────────
# LTR trains a model to produce a ranked list, using human-judged
# relevance labels as training signal.
#
# THREE PARADIGMS
# ───────────────
# Pointwise: predict relevance score for each (query, doc) independently.
#   Loss: MSE or cross-entropy on grade (0-4 scale).
#   Problem: ignores relative ordering — a doc graded 3 that ranks below
#   a doc graded 1 is not penalized differently than vice versa.
#
# Pairwise: for each (query, d+, d-) triple, predict which is more relevant.
#   Loss: RankNet (cross-entropy on which doc should rank higher)
#   Problem: all pairs equally weighted — a swap at rank 1 vs rank 100
#   matters equally to the loss but not to NDCG.
#
# Listwise: directly optimize a list-level metric.
#   LambdaRank: compute ΔMetric for each swap → weight gradient by |ΔNDCG|
#   LambdaMART: gradient-boosted trees with LambdaRank gradients (default in
#               LightGBM/XGBoost rankers). State of the art for tabular LTR.
#   Problem: NDCG is not differentiable — LambdaRank uses a clever proxy.
#
# FEATURES (what LTR models use)
# ───────────────────────────────
# Query-doc features: BM25 score, TF-IDF, cosine similarity, edit distance
# Document features:  PageRank, domain authority, doc length, freshness
# Query features:     query length, query type (navigational/informational)
# Interaction:        click-through rate (CTR), dwell time
#
# LABELS
# ──────
# Explicit: human raters grade (query, doc) pairs on 0-4 scale (TREC/LETOR)
# Implicit: clicks, conversions, dwell time (noisy but abundant)
#           Position bias correction required for implicit labels.

@dataclass
class RankingExample:
    query_id: int
    doc_id:   int
    features: list[float]
    label:    int    # 0=not relevant, 1=relevant, 2=highly relevant, etc.


def ndcg_at_k(ranked_labels: list[int], k: int) -> float:
    """
    Normalized Discounted Cumulative Gain at k.

    DCG@k  = Σ_{i=1}^{k} (2^rel_i - 1) / log2(i + 1)
    NDCG@k = DCG@k / IDCG@k   where IDCG = DCG of perfect ranking

    PROPERTIES:
      - Position-aware: rank-1 error is more costly than rank-k error
      - Uses log2 discount: rank 1 / rank 2 difference >> rank 9 / rank 10
      - Normalized to [0,1]: easy to compare across queries
      - NDCG=1.0 means perfect ranking

    INTERVIEW: Why not just use Precision@k or MRR?
      Precision@k assumes binary relevance and ignores position.
      MRR only looks at rank of first relevant result.
      NDCG handles graded relevance AND position discount — best of both.
    """
    def dcg(labels: list[int], cutoff: int) -> float:
        return sum(
            (2 ** rel - 1) / math.log2(i + 2)   # i+2 because i is 0-indexed
            for i, rel in enumerate(labels[:cutoff])
        )

    ideal = sorted(ranked_labels, reverse=True)
    idcg = dcg(ideal, k)
    if idcg == 0:
        return 0.0
    return dcg(ranked_labels, k) / idcg


def mean_reciprocal_rank(ranked_relevances: list[list[int]]) -> float:
    """
    MRR = mean of 1/rank_of_first_relevant_doc across queries.
    Best for navigational queries where there's one right answer.
    """
    rr_sum = 0.0
    for rels in ranked_relevances:
        for rank, rel in enumerate(rels, start=1):
            if rel > 0:
                rr_sum += 1.0 / rank
                break
    return rr_sum / len(ranked_relevances) if ranked_relevances else 0.0


def average_precision(ranked_relevances: list[int]) -> float:
    """
    AP for a single query: mean of precision at each relevant doc's rank.
    MAP = mean AP across queries. Good when all relevant docs matter equally.
    """
    n_relevant = sum(1 for r in ranked_relevances if r > 0)
    if n_relevant == 0:
        return 0.0
    ap = 0.0
    hits = 0
    for rank, rel in enumerate(ranked_relevances, start=1):
        if rel > 0:
            hits += 1
            ap += hits / rank
    return ap / n_relevant


class PairwiseRanker:
    """
    Simplified pairwise LTR using logistic regression on feature differences.
    Real: LambdaMART (LightGBM) or XGBoost with rank objective.
    """

    def __init__(self, n_features: int):
        self.n_features = n_features
        self.weights = [0.0] * n_features
        self.lr = 0.01

    def score(self, features: list[float]) -> float:
        return sum(w * f for w, f in zip(self.weights, features))

    def _sigmoid(self, x: float) -> float:
        return 1.0 / (1.0 + math.exp(-max(-500, min(500, x))))

    def train_step(self, pos_features: list[float], neg_features: list[float]):
        """
        RankNet gradient step: maximize P(d+ ranks above d-).
        Loss = -log σ(s+ - s-) where s = model score.
        Gradient w.r.t. weights: (σ(s+ - s-) - 1) * (f+ - f-)
        """
        s_diff = self.score(pos_features) - self.score(neg_features)
        grad_factor = self._sigmoid(s_diff) - 1.0  # ∈ (-1, 0]

        for i in range(self.n_features):
            feature_diff = pos_features[i] - neg_features[i]
            self.weights[i] -= self.lr * grad_factor * feature_diff

    def fit(self, examples: list[RankingExample], epochs: int = 50):
        """Train on (query_id, doc_id, features, label) examples."""
        # Group by query
        by_query: dict[int, list[RankingExample]] = defaultdict(list)
        for ex in examples:
            by_query[ex.query_id].append(ex)

        for _ in range(epochs):
            for query_id, docs in by_query.items():
                # Generate all (pos, neg) pairs
                for i, d_pos in enumerate(docs):
                    for d_neg in docs[i+1:]:
                        if d_pos.label > d_neg.label:
                            self.train_step(d_pos.features, d_neg.features)
                        elif d_neg.label > d_pos.label:
                            self.train_step(d_neg.features, d_pos.features)

    def rank(self, examples: list[RankingExample]) -> list[RankingExample]:
        return sorted(examples, key=lambda ex: -self.score(ex.features))


# =============================================================================
# POSITION BIAS CORRECTION (important for exa.ai)
# =============================================================================
#
# When using click data as implicit relevance labels, position bias corrupts
# the signal: users click rank-1 results more regardless of relevance.
#
# INVERSE PROPENSITY SCORING (IPS):
#   Corrected_label(d, r) = click(d, r) / P(click | rank=r, not_relevant)
#   where P(click | rank) is the position propensity model.
#
# PROPENSITY ESTIMATION:
#   - Randomization: A/B test with shuffled results to measure position effects
#   - EM algorithm: estimate propensity and relevance jointly
#   - Regression-EM: most practical for production

def estimate_propensity(
    rank_click_rates: list[float],
    base_ctr: float = 0.3,
) -> list[float]:
    """
    Simple propensity model: propensity[r] = ctr[r] / base_ctr
    Real: use randomized swap experiments or regression-EM.
    """
    return [ctr / base_ctr for ctr in rank_click_rates]


def ips_corrected_labels(
    clicks: list[int],
    ranks: list[int],
    propensities: list[float],
) -> list[float]:
    """Apply IPS correction to click labels."""
    return [
        c / propensities[r - 1] if propensities[r - 1] > 0 else 0.0
        for c, r in zip(clicks, ranks)
    ]


# =============================================================================
# TESTS
# =============================================================================

class TestNDCG(unittest.TestCase):
    def test_perfect_ranking(self):
        self.assertAlmostEqual(ndcg_at_k([3, 2, 1, 0], k=4), 1.0)

    def test_worst_ranking(self):
        score = ndcg_at_k([0, 0, 0, 3], k=4)
        self.assertLess(score, 1.0)

    def test_better_ranking_higher_ndcg(self):
        good = ndcg_at_k([3, 2, 1, 0], k=4)
        bad  = ndcg_at_k([0, 1, 2, 3], k=4)
        self.assertGreater(good, bad)

    def test_ndcg_bounded_zero_to_one(self):
        for labels in [[3,0,2,1], [0,0,0,0], [1,1,1,1]]:
            score = ndcg_at_k(labels, k=4)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0 + 1e-9)

    def test_all_zero_labels(self):
        self.assertAlmostEqual(ndcg_at_k([0, 0, 0], k=3), 0.0)

    def test_k_cutoff(self):
        # Relevant doc at rank 1 counts at k=1 but irrelevant beyond doesn't matter
        self.assertAlmostEqual(ndcg_at_k([1, 0, 0, 0], k=1), 1.0)


class TestMRR(unittest.TestCase):
    def test_first_rank(self):
        self.assertAlmostEqual(mean_reciprocal_rank([[1, 0, 0]]), 1.0)

    def test_second_rank(self):
        self.assertAlmostEqual(mean_reciprocal_rank([[0, 1, 0]]), 0.5)

    def test_no_relevant(self):
        self.assertAlmostEqual(mean_reciprocal_rank([[0, 0, 0]]), 0.0)

    def test_average_across_queries(self):
        mrr = mean_reciprocal_rank([[1, 0], [0, 1]])
        self.assertAlmostEqual(mrr, 0.75)  # (1 + 0.5) / 2


class TestAP(unittest.TestCase):
    def test_perfect_ap(self):
        self.assertAlmostEqual(average_precision([1, 1, 1]), 1.0)

    def test_single_relevant_at_rank1(self):
        self.assertAlmostEqual(average_precision([1, 0, 0]), 1.0)

    def test_single_relevant_at_rank2(self):
        self.assertAlmostEqual(average_precision([0, 1, 0]), 0.5)


class TestTwoStagePipeline(unittest.TestCase):
    def setUp(self):
        self.pipeline = TwoStagePipeline(dim=16)
        self.corpus = [
            "Redis caching and in-memory storage",
            "PostgreSQL relational database",
            "Redis distributed lock implementation",
            "Elasticsearch full-text search engine",
            "Redis pub sub messaging system",
            "Python machine learning frameworks",
            "Docker container orchestration",
            "Kubernetes cluster management",
        ]
        for i, text in enumerate(self.corpus):
            self.pipeline.add(i, text)

    def test_returns_final_k(self):
        results = self.pipeline.search("redis cache", final_k=3)
        self.assertEqual(len(results), 3)

    def test_result_fields(self):
        results = self.pipeline.search("redis", final_k=2)
        for r in results:
            for field in ("doc_id", "text", "ce_score", "bi_score"):
                self.assertIn(field, r)

    def test_ce_score_bounded(self):
        results = self.pipeline.search("redis", final_k=5)
        for r in results:
            self.assertGreaterEqual(r["ce_score"], 0.0)
            self.assertLessEqual(r["ce_score"], 1.0)

    def test_reranking_can_change_order(self):
        """Cross-encoder can reorder the bi-encoder's ranking."""
        candidates = self.pipeline.retriever.search("redis", top_k=5)
        bi_order = [d.doc_id for d, _ in candidates]

        reranked = self.pipeline.reranker.rerank("redis", candidates, top_k=5)
        ce_order = [d.doc_id for d, _ in reranked]

        # They should cover the same docs but potentially different order
        self.assertEqual(set(bi_order), set(ce_order))


class TestPairwiseRanker(unittest.TestCase):
    def test_learns_correct_ordering(self):
        """Ranker should learn that feature[0] predicts relevance."""
        ranker = PairwiseRanker(n_features=2)
        examples = [
            RankingExample(0, 0, [1.0, 0.0], 2),
            RankingExample(0, 1, [0.5, 0.5], 1),
            RankingExample(0, 2, [0.0, 1.0], 0),
        ] * 20
        ranker.fit(examples, epochs=100)

        # After training, higher feature[0] should score higher
        self.assertGreater(ranker.score([1.0, 0.0]), ranker.score([0.0, 1.0]))

    def test_rank_returns_sorted(self):
        ranker = PairwiseRanker(n_features=2)
        ranker.weights = [1.0, -0.5]
        examples = [
            RankingExample(0, i, [random.random(), random.random()], 0)
            for i in range(5)
        ]
        ranked = ranker.rank(examples)
        scores = [ranker.score(e.features) for e in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))


def demo():
    print("=" * 60)
    print("TWO-STAGE RETRIEVAL + RE-RANKING DEMO")
    print("=" * 60)

    pipeline = TwoStagePipeline(dim=16)
    corpus = [
        "Redis is an in-memory data structure store for caching",
        "Redis distributed locks prevent concurrent access",
        "PostgreSQL is a relational database system",
        "Redis pub sub enables real-time messaging",
        "Elasticsearch full-text search with inverted indexes",
        "Redis cluster horizontal scaling of cache layer",
        "Docker container runtime for microservices",
        "Redis streams for event sourcing and queues",
        "Vector databases store embeddings for semantic search",
        "Redis sorted sets enable fast leaderboards",
    ]
    for i, text in enumerate(corpus):
        pipeline.add(i, text)

    query = "redis caching and memory storage"
    print(f"\nQuery: '{query}'\n")

    candidates = pipeline.retriever.search(query, top_k=8)
    print("[Stage 1 — Bi-encoder retrieval]")
    for doc, score in candidates:
        print(f"  doc {doc.doc_id} bi={score:.4f}: {doc.text[:55]}")

    results = pipeline.search(query, final_k=5, fetch_k=8)
    print("\n[Stage 2 — After cross-encoder re-ranking]")
    for r in results:
        print(f"  doc {r['doc_id']} ce={r['ce_score']:.4f} (bi={r['bi_score']:.4f}): {r['text'][:55]}")

    print("\n[Ranking Metrics]")
    # Simulate a ranked list with known relevance labels
    ranked = [3, 0, 2, 1, 0, 1]  # grades for retrieved docs in order
    print(f"  NDCG@3  : {ndcg_at_k(ranked, k=3):.4f}")
    print(f"  NDCG@6  : {ndcg_at_k(ranked, k=6):.4f}")
    print(f"  AP      : {average_precision(ranked):.4f}")
    print(f"  MRR     : {mean_reciprocal_rank([ranked]):.4f}")

    print("\n[Pairwise LTR Training]")
    ranker = PairwiseRanker(n_features=3)
    examples = [
        RankingExample(0, 0, [0.9, 0.1, 0.8], 2),
        RankingExample(0, 1, [0.5, 0.5, 0.5], 1),
        RankingExample(0, 2, [0.1, 0.9, 0.2], 0),
        RankingExample(1, 3, [0.8, 0.2, 0.7], 2),
        RankingExample(1, 4, [0.3, 0.7, 0.4], 0),
    ] * 30
    ranker.fit(examples, epochs=100)
    print(f"  Learned weights: {[round(w, 3) for w in ranker.weights]}")
    print(f"  Score(high-rel):  {ranker.score([0.9, 0.1, 0.8]):.3f}")
    print(f"  Score(low-rel):   {ranker.score([0.1, 0.9, 0.2]):.3f}")


if __name__ == "__main__":
    demo()
    print("\n\nRUNNING TESTS\n" + "=" * 60)
    unittest.main(verbosity=2, exit=False)