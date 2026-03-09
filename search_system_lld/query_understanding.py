"""
=============================================================================
06 — QUERY UNDERSTANDING
=============================================================================
PRIORITY: #6 for exa.ai — query understanding is their differentiation.

WHAT TO MASTER:
  - Query classification (navigational / informational / transactional)
  - Query expansion: synonyms, pseudo-relevance feedback (PRF)
  - Query rewriting and normalization
  - Spell correction (edit distance, noisy channel model)
  - Entity recognition and linking in queries
  - Exa.ai's specific "natural language query" → neural model pipeline

EXA.AI ANGLE:
  Exa positions itself as "search the way you think" — natural language
  queries like "recent papers arguing against transformer scaling laws"
  instead of keyword soup. Their query understanding layer interprets
  intent, then routes to the right retriever or expands the query to
  capture synonymous concepts.

  Key exa.ai insight: Google-style keyword queries optimize for IDF matching.
  Exa's neural queries optimize for semantic intent matching.
  Query understanding bridges the user's intent and the retrieval model.
=============================================================================
"""

import heapq
import math
import re
import unittest
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


# =============================================================================
# QUERY CLASSIFICATION
# =============================================================================
#
# THREE CANONICAL QUERY INTENTS (Broder, 2002)
# ─────────────────────────────────────────────
# Navigational   : user wants a specific URL/resource
#                  "redis documentation", "github openai"
#                  → return the one right answer
# Informational  : user wants information / learning
#                  "how does HNSW work", "what is BM25"
#                  → return diverse, relevant content
# Transactional  : user wants to DO something (buy, download, sign up)
#                  "redis cloud free tier", "download pytorch"
#                  → return action-enabling pages
#
# WHY THIS MATTERS:
#   Navigational: optimize for precision@1 (one right answer)
#   Informational: optimize for recall and diversity (NDCG@10)
#   Transactional: optimize for CTR and conversion signals
#
# EXA.AI EXTENSION:
#   Exa adds "research" queries: "papers on neural scaling laws"
#   These need recency weighting + source diversity + citation signals.

class QueryIntent(Enum):
    NAVIGATIONAL   = auto()   # find a specific resource
    INFORMATIONAL  = auto()   # learn about a topic
    TRANSACTIONAL  = auto()   # perform an action
    RESEARCH       = auto()   # deep investigation (exa.ai specialty)

# Signal patterns for rule-based classification
_NAVIGATIONAL_SIGNALS = {
    "official", "website", "homepage", "login", "signin", "account",
    "github", "docs", "documentation", "download", "portal",
}
_TRANSACTIONAL_SIGNALS = {
    "buy", "price", "cost", "pricing", "free", "trial", "signup",
    "register", "install", "get", "download", "subscribe", "plan",
}
_RESEARCH_SIGNALS = {
    "paper", "papers", "research", "study", "studies", "arxiv",
    "survey", "literature", "review", "analysis", "recent", "latest",
    "compare", "comparison", "vs", "versus", "benchmark",
}


def classify_query(query: str) -> tuple[QueryIntent, float]:
    """
    Rule-based query classifier. Returns (intent, confidence).
    In production: fine-tuned BERT classifier trained on click-log data.
    """
    tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
    is_url_like = "." in query and " " not in query.strip()

    nav_score   = len(tokens & _NAVIGATIONAL_SIGNALS) / max(len(tokens), 1)
    trans_score = len(tokens & _TRANSACTIONAL_SIGNALS) / max(len(tokens), 1)
    res_score   = len(tokens & _RESEARCH_SIGNALS) / max(len(tokens), 1)

    if is_url_like or nav_score >= 0.15:
        return QueryIntent.NAVIGATIONAL, max(nav_score, 0.7)
    if res_score >= 0.1:
        return QueryIntent.RESEARCH, max(res_score * 3, 0.6)
    if trans_score >= 0.1:
        return QueryIntent.TRANSACTIONAL, max(trans_score * 3, 0.6)
    return QueryIntent.INFORMATIONAL, 0.7   # default


# =============================================================================
# SPELL CORRECTION (Edit Distance + Noisy Channel Model)
# =============================================================================
#
# NOISY CHANNEL MODEL
# ───────────────────
# P(intended | observed) ∝ P(observed | intended) * P(intended)
#   P(intended)            : language model probability (how likely the word is)
#   P(observed | intended) : error model (how likely this typo given intended)
#
# EDIT DISTANCE (Levenshtein)
# ────────────────────────────
# Min operations (insert, delete, substitute) to transform s1 → s2.
# Used to find candidate corrections: all dictionary words within edit dist 1-2.
# Dynamic programming: O(m*n) where m,n = string lengths.
#
# PRODUCTION: Google's spell correction uses:
#   1. Edit distance to generate candidates
#   2. N-gram language model to score candidates
#   3. Query log frequency as strong prior ("did you mean X?" shown if
#      X has 10x more queries than the misspelled form)

def edit_distance(s1: str, s2: str) -> int:
    """
    Levenshtein distance. O(m*n) time, O(m*n) space.
    Can be optimized to O(min(m,n)) space with rolling array.
    """
    m, n = len(s1), len(s2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if s1[i-1] == s2[j-1]:
                dp[i][j] = dp[i-1][j-1]
            else:
                dp[i][j] = 1 + min(dp[i-1][j], dp[i][j-1], dp[i-1][j-1])

    return dp[m][n]


class SpellCorrector:
    """
    Noisy-channel spell corrector using unigram language model + edit distance.
    """

    def __init__(self):
        self.word_freq: dict[str, int] = defaultdict(int)
        self.total = 0

    def fit(self, texts: list[str]):
        for text in texts:
            for word in re.findall(r"[a-z]+", text.lower()):
                self.word_freq[word] += 1
                self.total += 1

    def p_word(self, word: str) -> float:
        """P(word): unigram language model probability."""
        return (self.word_freq[word] + 1) / (self.total + len(self.word_freq))

    def candidates(self, word: str, max_edit: int = 2) -> list[tuple[str, int]]:
        """Return (candidate, edit_distance) pairs within max_edit."""
        result = []
        word_lower = word.lower()
        for vocab_word in self.word_freq:
            d = edit_distance(word_lower, vocab_word)
            if d <= max_edit:
                result.append((vocab_word, d))
        return result

    def correct(self, word: str) -> str:
        """Return most likely correction using noisy channel scoring."""
        if self.word_freq[word.lower()] > 0:
            return word  # already in vocab

        cands = self.candidates(word, max_edit=2)
        if not cands:
            return word

        def score(candidate: str, dist: int) -> float:
            # P(intended | observed) ∝ P(word) / (dist + 1)
            return self.p_word(candidate) / (dist + 1)

        return max(cands, key=lambda x: score(x[0], x[1]))[0]

    def correct_query(self, query: str) -> str:
        """Correct each token in a query."""
        tokens = re.findall(r"[a-z]+|\S+", query.lower())
        return " ".join(self.correct(t) if t.isalpha() else t for t in tokens)


# =============================================================================
# QUERY EXPANSION
# =============================================================================
#
# WHY EXPAND?
# ───────────
# User queries are short (~2-3 words average). They miss synonyms and related
# terms that appear in relevant documents. Expansion improves recall.
#
# THREE APPROACHES:
#
# 1. THESAURUS/SYNONYM EXPANSION
#    Add WordNet synonyms or domain-specific synonym lists.
#    Fast, deterministic, no model needed.
#    Risk: over-expansion (adding irrelevant synonyms hurts precision).
#    "bank" → adds "financial institution" AND "river bank" — ambiguous!
#
# 2. PSEUDO-RELEVANCE FEEDBACK (PRF)
#    Take top-K retrieved documents, extract their most discriminative terms,
#    add them to the query. Rocchio algorithm (classic), RM3 (modern).
#    Risk: query drift — if top-K results are wrong, expansion makes it worse.
#
# 3. NEURAL QUERY EXPANSION (exa.ai approach)
#    Use a generative model to rewrite/expand the query.
#    Example: "T5 query expansion" (doc2query) or GAR (Generation-Augmented Retrieval)
#    User query → LLM → expanded query with hypothetical document terms
#    Much higher quality but adds LLM inference latency.
#    Hyde (Hypothetical Document Embeddings): generate a fake answer, embed it,
#    use that embedding as the query vector. Very effective for exa.ai-style queries.

@dataclass
class ExpandedQuery:
    original:    str
    expanded:    str
    added_terms: list[str]
    method:      str


SYNONYM_MAP: dict[str, list[str]] = {
    "fast":        ["quick", "rapid", "speedy", "low-latency"],
    "slow":        ["latent", "high-latency", "sluggish"],
    "search":      ["retrieval", "lookup", "query", "find"],
    "index":       ["inverted-index", "catalog", "register"],
    "cache":       ["buffer", "store", "memorize", "memoize"],
    "distributed": ["clustered", "sharded", "partitioned", "federated"],
    "similarity":  ["relevance", "closeness", "proximity", "likeness"],
    "embedding":   ["vector", "representation", "encoding"],
    "document":    ["page", "record", "item", "text"],
    "query":       ["question", "search", "request", "prompt"],
}


def expand_with_synonyms(
    query: str,
    max_terms: int = 5,
    boost_original: bool = True,
) -> ExpandedQuery:
    """
    Synonym-based query expansion.
    In production: use WordNet or domain-specific ontology.
    """
    tokens = re.findall(r"[a-z]+", query.lower())
    added = []
    seen = set(tokens)

    for token in tokens:
        syns = SYNONYM_MAP.get(token, [])
        for syn in syns:
            if syn not in seen and len(added) < max_terms:
                added.append(syn)
                seen.add(syn)

    expanded = query + " " + " ".join(added) if added else query
    return ExpandedQuery(original=query, expanded=expanded.strip(),
                         added_terms=added, method="synonym")


def pseudo_relevance_feedback(
    query: str,
    top_docs: list[str],
    top_k_terms: int = 5,
    alpha: float = 1.0,    # Rocchio original query weight
    beta: float = 0.75,    # Rocchio relevant doc weight
) -> ExpandedQuery:
    """
    Rocchio PRF: expand query with discriminative terms from top-K docs.

    ROCCHIO FORMULA:
    q_new = α * q_orig + β * (1/|Dr|) * Σ_{d ∈ Dr} d_vec

    Here simplified to term frequency extraction instead of vector arithmetic.
    """
    if not top_docs:
        return ExpandedQuery(query, query, [], "prf")

    # Count terms across top docs (simulate document vector sum)
    query_terms = set(re.findall(r"[a-z]+", query.lower()))
    term_freq: dict[str, int] = defaultdict(int)

    for doc in top_docs:
        for term in re.findall(r"[a-z]+", doc.lower()):
            if term not in query_terms and len(term) > 3:
                term_freq[term] += 1

    # Select top discriminative terms (simplified: by frequency)
    expansion_terms = [
        term for term, _ in
        sorted(term_freq.items(), key=lambda x: -x[1])[:top_k_terms]
    ]

    expanded = query + " " + " ".join(expansion_terms)
    return ExpandedQuery(original=query, expanded=expanded.strip(),
                         added_terms=expansion_terms, method="prf")


def hyde_expansion(query: str, hypothetical_answer: str) -> ExpandedQuery:
    """
    HyDE: Hypothetical Document Embeddings.
    Instead of expanding the query text, generate a hypothetical document
    that WOULD answer the query, then embed that document as the query vector.

    In production:
      1. LLM generates hypothetical answer
      2. Embed the hypothetical answer
      3. Use that embedding for ANN retrieval (instead of embedding the query)

    Why it works: the hypothetical answer is in "document space" (similar
    length, similar vocabulary to indexed docs), so its embedding is a
    better query vector than the short, terse original query.
    """
    # Combine original query + hypothetical context for expanded retrieval
    expanded = f"{query} {hypothetical_answer}"
    added = re.findall(r"[a-z]+", hypothetical_answer.lower())
    added = [t for t in added if t not in set(re.findall(r"[a-z]+", query.lower()))]
    return ExpandedQuery(original=query, expanded=expanded.strip(),
                         added_terms=added[:10], method="hyde")


# =============================================================================
# QUERY REWRITING
# =============================================================================
#
# BEYOND EXPANSION: sometimes the query itself is restructured.
#
# USE CASES:
#   - "cheap hotels NYC" → "budget hotels New York City"
#     (abbreviation expansion, synonym substitution)
#   - "how does redis work" → "redis architecture internals"
#     (interrogative → descriptive for document matching)
#   - "Python vs Go performance" → "Python performance benchmark Go comparison"
#     (comparison query restructuring)
#
# EXA.AI'S APPROACH: their model is trained to rewrite natural language
# queries into forms that match their neural index's embedding space.

def rewrite_query(query: str, rewrite_rules: Optional[dict[str, str]] = None) -> str:
    """
    Apply deterministic rewrite rules to a query.
    In production: seq2seq model fine-tuned on query-rewrite pairs.
    """
    rules = rewrite_rules or {
        r"\bhow does (.+) work\b": r"\1 architecture internals",
        r"\bwhat is (.+)\b":       r"\1 definition overview",
        r"\b(\w+) vs (\w+)\b":    r"\1 \2 comparison benchmark",
        r"\bcheap\b":              "budget affordable",
        r"\bfast\b":               "high performance low latency",
    }
    result = query
    for pattern, replacement in rules.items():
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result.strip()


# =============================================================================
# ENTITY DETECTION (simple rule-based)
# =============================================================================
#
# IN PRODUCTION: Named entity recognition (NER) with a BERT-based tagger.
# Entities affect retrieval: "Apple" in a tech query ≠ "apple" in food query.
# Entity linking: map "Apple" → wikidata:Q312 for unambiguous matching.

@dataclass
class Entity:
    text:       str
    type:       str    # PRODUCT, ORG, PERSON, LOCATION, TECH
    start:      int
    end:        int

TECH_ENTITIES = {
    "redis", "postgres", "elasticsearch", "kafka", "kubernetes", "docker",
    "pytorch", "tensorflow", "bert", "gpt", "llama", "faiss", "hnsw",
    "python", "golang", "rust", "typescript", "react", "nodejs",
}
ORG_ENTITIES = {
    "google", "openai", "anthropic", "amazon", "microsoft", "apple",
    "meta", "twitter", "x", "netflix", "uber", "airbnb", "stripe",
    "exa", "pinecone", "weaviate", "qdrant", "elastic", "databricks",
}

def detect_entities(query: str) -> list[Entity]:
    """Simple dictionary-based entity detection."""
    entities = []
    for m in re.finditer(r"\b[a-zA-Z0-9]+\b", query):
        token = m.group().lower()
        if token in TECH_ENTITIES:
            entities.append(Entity(m.group(), "TECH", m.start(), m.end()))
        elif token in ORG_ENTITIES:
            entities.append(Entity(m.group(), "ORG", m.start(), m.end()))
    return entities


# =============================================================================
# COMPLETE QUERY UNDERSTANDING PIPELINE
# =============================================================================

@dataclass
class ProcessedQuery:
    original:         str
    rewritten:        str
    expanded:         str
    intent:           QueryIntent
    intent_confidence: float
    entities:         list[Entity]
    corrected:        bool
    expansion_terms:  list[str]


class QueryUnderstandingPipeline:
    """
    Full query understanding pipeline:
    1. Normalize
    2. Spell correct
    3. Classify intent
    4. Detect entities
    5. Rewrite
    6. Expand
    """

    def __init__(self):
        self.spell_corrector = SpellCorrector()
        self._trained = False

    def train(self, corpus: list[str]):
        self.spell_corrector.fit(corpus)
        self._trained = True

    def process(
        self,
        query: str,
        top_docs: Optional[list[str]] = None,
        use_prf: bool = False,
    ) -> ProcessedQuery:
        # 1. Normalize
        normalized = re.sub(r"\s+", " ", query.strip().lower())

        # 2. Spell correct
        corrected = self.spell_corrector.correct_query(normalized) if self._trained else normalized
        was_corrected = corrected != normalized

        # 3. Intent classification
        intent, confidence = classify_query(corrected)

        # 4. Entity detection
        entities = detect_entities(corrected)

        # 5. Query rewriting
        rewritten = rewrite_query(corrected)

        # 6. Query expansion
        if use_prf and top_docs:
            exp = pseudo_relevance_feedback(rewritten, top_docs)
        else:
            exp = expand_with_synonyms(rewritten)

        return ProcessedQuery(
            original=query,
            rewritten=rewritten,
            expanded=exp.expanded,
            intent=intent,
            intent_confidence=confidence,
            entities=entities,
            corrected=was_corrected,
            expansion_terms=exp.added_terms,
        )


# =============================================================================
# TESTS
# =============================================================================

class TestEditDistance(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(edit_distance("redis", "redis"), 0)

    def test_one_insert(self):
        self.assertEqual(edit_distance("redis", "rediss"), 1)

    def test_one_delete(self):
        self.assertEqual(edit_distance("redis", "redi"), 1)

    def test_one_substitute(self):
        self.assertEqual(edit_distance("redis", "redix"), 1)

    def test_empty_strings(self):
        self.assertEqual(edit_distance("", "abc"), 3)
        self.assertEqual(edit_distance("abc", ""), 3)
        self.assertEqual(edit_distance("", ""), 0)

    def test_symmetry(self):
        self.assertEqual(edit_distance("abc", "xyz"), edit_distance("xyz", "abc"))

    def test_classic_example(self):
        self.assertEqual(edit_distance("kitten", "sitting"), 3)


class TestSpellCorrector(unittest.TestCase):
    def setUp(self):
        self.sc = SpellCorrector()
        self.sc.fit([
            "redis cache distributed lock system",
            "index search query document embedding",
        ] * 100)

    def test_known_word_unchanged(self):
        self.assertEqual(self.sc.correct("redis"), "redis")

    def test_corrects_simple_typo(self):
        result = self.sc.correct("rediss")  # extra 's'
        self.assertEqual(result, "redis")

    def test_correct_query(self):
        result = self.sc.correct_query("rediss cach")
        self.assertIn("redis", result)


class TestQueryClassifier(unittest.TestCase):
    def test_navigational(self):
        intent, _ = classify_query("redis official documentation")
        self.assertEqual(intent, QueryIntent.NAVIGATIONAL)

    def test_research(self):
        intent, _ = classify_query("recent papers on neural scaling laws")
        self.assertEqual(intent, QueryIntent.RESEARCH)

    def test_transactional(self):
        intent, _ = classify_query("redis cloud free tier pricing")
        self.assertEqual(intent, QueryIntent.TRANSACTIONAL)

    def test_informational(self):
        intent, _ = classify_query("how to implement distributed cache")
        self.assertEqual(intent, QueryIntent.INFORMATIONAL)

    def test_confidence_positive(self):
        _, confidence = classify_query("anything")
        self.assertGreater(confidence, 0)


class TestQueryExpansion(unittest.TestCase):
    def test_synonym_expansion_adds_terms(self):
        result = expand_with_synonyms("fast search")
        self.assertGreater(len(result.added_terms), 0)

    def test_synonym_expansion_no_duplicates(self):
        result = expand_with_synonyms("fast fast search search")
        expanded_tokens = re.findall(r"[a-z\-]+", result.expanded)
        # No term from original should appear as expansion term
        orig_terms = set(re.findall(r"[a-z]+", result.original))
        for term in result.added_terms:
            self.assertNotIn(term, orig_terms)

    def test_prf_adds_doc_terms(self):
        docs = ["distributed systems consistency availability partition",
                "cap theorem trade-offs in distributed databases"]
        result = pseudo_relevance_feedback("distributed systems", docs)
        self.assertGreater(len(result.added_terms), 0)

    def test_hyde_combines_query_and_answer(self):
        result = hyde_expansion(
            "how does HNSW work",
            "HNSW is a graph-based algorithm that builds navigable small world graphs"
        )
        self.assertIn("hnsw", result.original.lower())
        self.assertGreater(len(result.added_terms), 0)


class TestEntityDetection(unittest.TestCase):
    def test_detects_tech_entities(self):
        entities = detect_entities("redis vs elasticsearch performance")
        types = {e.type for e in entities}
        self.assertIn("TECH", types)

    def test_detects_org_entities(self):
        entities = detect_entities("openai GPT vs anthropic Claude")
        types = {e.type for e in entities}
        self.assertIn("ORG", types)

    def test_no_false_positives(self):
        entities = detect_entities("the quick brown fox")
        self.assertEqual(entities, [])


class TestQueryPipeline(unittest.TestCase):
    def setUp(self):
        self.pipeline = QueryUnderstandingPipeline()
        self.pipeline.train([
            "redis cache distributed lock pub sub",
            "search index embedding vector query",
        ] * 50)

    def test_returns_processed_query(self):
        result = self.pipeline.process("fast redis cach")
        self.assertIsInstance(result, ProcessedQuery)

    def test_intent_assigned(self):
        result = self.pipeline.process("redis documentation")
        self.assertIsNotNone(result.intent)

    def test_entities_detected(self):
        result = self.pipeline.process("redis vs elasticsearch")
        self.assertGreater(len(result.entities), 0)

    def test_prf_expansion(self):
        docs = ["distributed lock contention retry backoff jitter"]
        result = self.pipeline.process(
            "distributed systems", top_docs=docs, use_prf=True
        )
        self.assertGreater(len(result.expansion_terms), 0)


def demo():
    print("=" * 60)
    print("QUERY UNDERSTANDING DEMO")
    print("=" * 60)

    pipeline = QueryUnderstandingPipeline()
    pipeline.train([
        "redis cache distributed lock pub sub streams",
        "elasticsearch search index query ranking",
        "embedding vector similarity nearest neighbor",
        "postgres database sql transaction",
    ] * 100)

    queries = [
        "redis official documentation",
        "how does HNSW index work",
        "rediss cach fast lookup",   # typos
        "recent papers on neural scaling laws",
        "redis cloud free tier pricing plans",
        "Python vs Go performance benchmark 2024",
    ]

    for q in queries:
        result = pipeline.process(q)
        print(f"\nQuery   : '{q}'")
        print(f"Intent  : {result.intent.name} ({result.intent_confidence:.0%})")
        if result.corrected:
            print(f"Corrected: '{result.rewritten}'")
        if result.entities:
            for e in result.entities:
                print(f"Entity  : '{e.text}' [{e.type}]")
        if result.expansion_terms:
            print(f"Expanded: +{result.expansion_terms[:5]}")

    print("\n[HyDE — Hypothetical Document Expansion]")
    query = "papers arguing transformer scaling will plateau"
    hypo  = ("Recent evidence suggests transformer performance improvements "
             "may slow as dataset and parameter counts reach physical limits, "
             "challenging the neural scaling hypothesis")
    result = hyde_expansion(query, hypo)
    print(f"  Original : {result.original}")
    print(f"  HyDE terms added: {result.added_terms[:8]}")
    print(f"  (embed the full expanded text as the query vector)")


if __name__ == "__main__":
    demo()
    print("\n\nRUNNING TESTS\n" + "=" * 60)
    unittest.main(verbosity=2, exit=False)