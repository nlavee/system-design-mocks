"""
=============================================================================
INVERTED INDEX — From Simple to Production-Grade
=============================================================================

This file builds an inverted index in four layers, each adding more power:

  Layer 1 — SimpleIndex      : term → [doc_ids]          (boolean search)
  Layer 2 — TFIndex          : term → {doc_id: tf}        (ranked by count)
  Layer 3 — PositionalIndex  : term → {doc_id: [pos,...]} (phrase queries)
  Layer 4 — FullIndex        : positions + char offsets + TF-IDF + BM25

Each layer has its own test suite at the bottom. Run with:
    python inverted_index.py
=============================================================================
"""

import math
import re
import unittest
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Shared tokenizer (used by all layers)
# ---------------------------------------------------------------------------

def tokenize(text: str) -> list[str]:
    """
    Lowercase and split on non-alphanumeric characters.
    Returns a flat list of tokens in document order.

    >>> tokenize("Hello, World! Hello Redis.")
    ['hello', 'world', 'hello', 'redis']
    """
    return re.findall(r"[a-z0-9]+", text.lower())


def tokenize_with_offsets(text: str) -> list[tuple[str, int, int]]:
    """
    Returns (token, char_start, char_end) for each match.
    char_end is exclusive (Python slice convention).

    >>> tokenize_with_offsets("Hello World")
    [('hello', 0, 5), ('world', 6, 11)]
    """
    return [
        (m.group().lower(), m.start(), m.end())
        for m in re.finditer(r"[a-zA-Z0-9]+", text)
    ]


# =============================================================================
# LAYER 1 — Simple Boolean Index
# =============================================================================
#
# Structure:
#   index: dict[term, set[doc_id]]
#
# Supports:
#   - Single-term lookup       : search("redis")
#   - AND queries              : search("redis AND cache")
#   - OR queries               : search("redis OR memcached")
#   - NOT queries              : search("cache NOT redis")
#
# Limitations:
#   - No ranking — all matching docs are equal
#   - No phrase queries ("distributed lock" ≠ "lock distributed")
#   - No relevance scoring

class SimpleIndex:
    def __init__(self):
        # term → set of doc_ids that contain it
        self.index: dict[str, set[int]] = defaultdict(set)
        self.docs:  dict[int, str] = {}           # doc_id → original text
        self._next_id = 0

    # ------------------------------------------------------------------ build

    def add_document(self, text: str, doc_id: Optional[int] = None) -> int:
        if doc_id is None:
            doc_id = self._next_id
            self._next_id += 1

        self.docs[doc_id] = text
        for token in set(tokenize(text)):          # set: deduplicate per doc
            self.index[token].add(doc_id)
        return doc_id

    # ----------------------------------------------------------------- search

    def search(self, query: str) -> set[int]:
        """
        Supports AND / OR / NOT operators (uppercase).
        Single word → same as AND over all docs.
        """
        tokens = query.split()

        # Simple single-term case
        if len(tokens) == 1:
            return set(self.index.get(tokens[0].lower(), set()))

        # Multi-term: process left-to-right with AND/OR/NOT operators
        result: Optional[set[int]] = None
        op = "AND"

        for token in tokens:
            if token in ("AND", "OR", "NOT"):
                op = token
                continue

            posting = set(self.index.get(token.lower(), set()))

            if result is None:
                result = posting
            elif op == "AND":
                result = result & posting
            elif op == "OR":
                result = result | posting
            elif op == "NOT":
                result = result - posting

        return result or set()

    def __repr__(self):
        return f"SimpleIndex(terms={len(self.index)}, docs={len(self.docs)})"


# =============================================================================
# LAYER 2 — TF Index (Term Frequency)
# =============================================================================
#
# Structure:
#   index: dict[term, dict[doc_id, tf]]
#   tf = raw count of term occurrences in document
#
# Ranking: score(doc) = sum of tf for each query term in doc
#
# Why TF matters:
#   A doc mentioning "redis" 10 times is likely more relevant than one
#   mentioning it once. But TF alone over-weights long documents.
#   Layer 4 adds IDF and length normalization to fix this.
#
# Limitation: "redis" in a 3-word doc vs a 1000-word doc has the same TF=1
# even though the short doc is much more "about" redis. → TF-IDF fixes this.

class TFIndex:
    def __init__(self):
        # term → {doc_id: raw_count}
        self.index: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self.docs:  dict[int, str] = {}
        self._next_id = 0

    def add_document(self, text: str, doc_id: Optional[int] = None) -> int:
        if doc_id is None:
            doc_id = self._next_id
            self._next_id += 1

        self.docs[doc_id] = text
        for token in tokenize(text):               # keep duplicates for counting
            self.index[token][doc_id] += 1
        return doc_id

    def search(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        """
        Returns [(doc_id, score)] sorted by descending score.
        Score = sum of raw TF for each query term.
        """
        query_terms = tokenize(query)
        scores: dict[int, float] = defaultdict(float)

        for term in query_terms:
            for doc_id, tf in self.index.get(term, {}).items():
                scores[doc_id] += tf

        return sorted(scores.items(), key=lambda x: -x[1])[:top_k]

    def tf(self, term: str, doc_id: int) -> int:
        return self.index.get(term, {}).get(doc_id, 0)

    def __repr__(self):
        return f"TFIndex(terms={len(self.index)}, docs={len(self.docs)})"


# =============================================================================
# LAYER 3 — Positional Index
# =============================================================================
#
# Structure:
#   index: dict[term, dict[doc_id, list[int]]]
#   positions are 0-indexed token positions within the document.
#
# New capability: PHRASE QUERIES
#   "distributed lock" → both words must appear, with "lock" at pos+1 of
#   "distributed". Works by finding position lists that have consecutive hits.
#
# Also supports proximity queries:
#   "redis cache"~3 → "redis" and "cache" within 3 positions of each other.
#
# Implementation detail:
#   Phrase matching is O(P1 * P2) naïve, or O(P1 + P2) with merge on sorted lists.
#   The merge approach (shown below) is what Lucene uses.

@dataclass
class Posting:
    doc_id: int
    positions: list[int] = field(default_factory=list)

    @property
    def tf(self) -> int:
        return len(self.positions)


class PositionalIndex:
    def __init__(self):
        # term → {doc_id: Posting}
        self.index: dict[str, dict[int, Posting]] = defaultdict(dict)
        self.docs:  dict[int, str] = {}
        self.doc_lengths: dict[int, int] = {}   # token count per doc
        self._next_id = 0

    def add_document(self, text: str, doc_id: Optional[int] = None) -> int:
        if doc_id is None:
            doc_id = self._next_id
            self._next_id += 1

        self.docs[doc_id] = text
        tokens = tokenize(text)
        self.doc_lengths[doc_id] = len(tokens)

        for pos, token in enumerate(tokens):
            if doc_id not in self.index[token]:
                self.index[token][doc_id] = Posting(doc_id)
            self.index[token][doc_id].positions.append(pos)

        return doc_id

    # ------------------------------------------------------- boolean search

    def search(self, query: str) -> list[int]:
        """AND search across all query terms."""
        terms = tokenize(query)
        if not terms:
            return []

        result_sets = [set(self.index.get(t, {}).keys()) for t in terms]
        matched = result_sets[0]
        for s in result_sets[1:]:
            matched &= s
        return list(matched)

    # ------------------------------------------------------- phrase search

    def phrase_search(self, phrase: str) -> list[int]:
        """
        Exact phrase match. Returns doc_ids where all tokens appear
        consecutively in the given order.

        Algorithm: for each candidate doc (from AND of all terms),
        check if there exists a starting position p such that term[i]
        appears at position p+i for all i.

        O(D * P) where D = matching docs, P = avg positions per term.
        """
        terms = tokenize(phrase)
        if not terms:
            return []

        # Candidate docs: must contain ALL terms
        candidate_docs = set(self.index.get(terms[0], {}).keys())
        for term in terms[1:]:
            candidate_docs &= set(self.index.get(term, {}).keys())

        results = []
        for doc_id in candidate_docs:
            # Get positions for first term; check if subsequent terms follow
            first_positions = self.index[terms[0]][doc_id].positions
            for start_pos in first_positions:
                if all(
                    (start_pos + i) in set(self.index[terms[i]][doc_id].positions)
                    for i in range(1, len(terms))
                ):
                    results.append(doc_id)
                    break  # found a match in this doc — no need to check more starts

        return results

    # ------------------------------------------------------- proximity search

    def proximity_search(self, term1: str, term2: str, max_distance: int) -> list[int]:
        """
        Returns docs where term1 and term2 appear within max_distance tokens.
        Useful for: "redis"~5"lock" → redis and lock within 5 positions.

        Uses sorted-list merge: O(P1 + P2) per document.
        """
        t1, t2 = term1.lower(), term2.lower()
        candidates = set(self.index.get(t1, {}).keys()) & set(self.index.get(t2, {}).keys())
        results = []

        for doc_id in candidates:
            pos1 = self.index[t1][doc_id].positions  # already sorted (insertion order)
            pos2 = self.index[t2][doc_id].positions

            # Two-pointer merge to find if any pair is within max_distance
            i, j = 0, 0
            found = False
            while i < len(pos1) and j < len(pos2):
                dist = abs(pos1[i] - pos2[j])
                if dist <= max_distance:
                    found = True
                    break
                elif pos1[i] < pos2[j]:
                    i += 1
                else:
                    j += 1

            if found:
                results.append(doc_id)

        return results

    def __repr__(self):
        return f"PositionalIndex(terms={len(self.index)}, docs={len(self.docs)})"


# =============================================================================
# LAYER 4 — Full Index: Positions + Offsets + TF-IDF + BM25
# =============================================================================
#
# This is the layer closest to how Elasticsearch / Lucene work.
#
# NEW IN LAYER 4
# ──────────────
# 1. Character offsets: (start, end) per occurrence → enables hit highlighting
# 2. IDF (Inverse Document Frequency): down-weights common terms
#      idf(t) = log((N - df(t) + 0.5) / (df(t) + 0.5) + 1)   [BM25 variant]
# 3. TF-IDF scoring: tf * idf
# 4. BM25 scoring: the de-facto standard ranking function used by
#    Lucene/Elasticsearch/Solr.
#
# BM25 FORMULA (Robertson & Zaragoza, 2009)
# ──────────────────────────────────────────
#   score(D, Q) = Σ IDF(qi) * [tf(qi,D) * (k1+1)] / [tf(qi,D) + k1*(1 - b + b*|D|/avgdl)]
#
#   k1 ∈ [1.2, 2.0]  — controls TF saturation. High k1 → TF keeps mattering more.
#   b  ∈ [0, 1]      — length normalization. b=0 → no normalization; b=1 → full.
#   Default: k1=1.2, b=0.75
#
# WHY BM25 BEATS PLAIN TF-IDF
# ────────────────────────────
#   TF-IDF: score grows linearly with TF. A doc with TF=100 scores 100x
#     a doc with TF=1. Unrealistic — more occurrences = diminishing returns.
#   BM25:   TF contribution is asymptotic — score plateaus. Also normalizes
#     by document length (a 10-word doc with TF=2 is more relevant than a
#     1000-word doc with TF=2).
#
# HIGHLIGHTING
# ────────────
#   With character offsets we can reconstruct:
#     "...the <em>redis</em> cache implementation..."
#   Lucene calls these "term vectors" when stored at index time.


@dataclass
class FullPosting:
    doc_id: int
    positions:  list[int]          = field(default_factory=list)
    offsets:    list[tuple[int,int]] = field(default_factory=list)  # (char_start, char_end)

    @property
    def tf(self) -> int:
        return len(self.positions)


class FullIndex:
    def __init__(self, k1: float = 1.2, b: float = 0.75):
        self.k1 = k1
        self.b  = b

        # term → {doc_id: FullPosting}
        self.index:       dict[str, dict[int, FullPosting]] = defaultdict(dict)
        self.docs:        dict[int, str] = {}
        self.doc_lengths: dict[int, int] = {}   # token count
        self._next_id = 0

    # ------------------------------------------------------------------ build

    def add_document(self, text: str, doc_id: Optional[int] = None) -> int:
        if doc_id is None:
            doc_id = self._next_id
            self._next_id += 1

        self.docs[doc_id] = text
        tokens_with_offsets = tokenize_with_offsets(text)
        self.doc_lengths[doc_id] = len(tokens_with_offsets)

        for pos, (token, char_start, char_end) in enumerate(tokens_with_offsets):
            if doc_id not in self.index[token]:
                self.index[token][doc_id] = FullPosting(doc_id)
            p = self.index[token][doc_id]
            p.positions.append(pos)
            p.offsets.append((char_start, char_end))

        return doc_id

    # ----------------------------------------------------------------- stats

    @property
    def N(self) -> int:
        """Total number of documents."""
        return len(self.docs)

    @property
    def avgdl(self) -> float:
        """Average document length in tokens."""
        if not self.doc_lengths:
            return 0.0
        return sum(self.doc_lengths.values()) / len(self.doc_lengths)

    def df(self, term: str) -> int:
        """Document frequency: number of docs containing term."""
        return len(self.index.get(term, {}))

    def idf(self, term: str) -> float:
        """
        BM25 IDF variant. Smoothed to avoid log(0) and handle terms
        appearing in all docs gracefully.
          idf = log((N - df + 0.5) / (df + 0.5) + 1)
        """
        n = self.N
        d = self.df(term)
        return math.log((n - d + 0.5) / (d + 0.5) + 1)

    def tf_idf(self, term: str, doc_id: int) -> float:
        tf = self.index.get(term, {}).get(doc_id, FullPosting(doc_id)).tf
        return tf * self.idf(term)

    # ----------------------------------------------------------------- BM25

    def bm25_score(self, term: str, doc_id: int) -> float:
        """BM25 score contribution of a single term for a document."""
        posting = self.index.get(term, {}).get(doc_id)
        if posting is None:
            return 0.0

        tf   = posting.tf
        dl   = self.doc_lengths[doc_id]
        k1, b, avgdl = self.k1, self.b, self.avgdl

        tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))
        return self.idf(term) * tf_norm

    def search(self, query: str, top_k: int = 10,
               scorer: str = "bm25") -> list[dict]:
        """
        Ranked search using BM25 (default) or tf_idf.
        Returns list of result dicts sorted by descending score.
        """
        query_terms = tokenize(query)
        if not query_terms:
            return []

        scores: dict[int, float] = defaultdict(float)
        for term in query_terms:
            for doc_id in self.index.get(term, {}):
                if scorer == "bm25":
                    scores[doc_id] += self.bm25_score(term, doc_id)
                else:
                    scores[doc_id] += self.tf_idf(term, doc_id)

        ranked = sorted(scores.items(), key=lambda x: -x[1])[:top_k]
        return [
            {"doc_id": doc_id, "score": round(score, 4), "text": self.docs[doc_id]}
            for doc_id, score in ranked
        ]

    # -------------------------------------------------------------- phrase

    def phrase_search(self, phrase: str) -> list[dict]:
        """Exact phrase search with BM25 scoring of matched docs."""
        terms = tokenize(phrase)
        if not terms:
            return []

        candidates = set(self.index.get(terms[0], {}).keys())
        for t in terms[1:]:
            candidates &= set(self.index.get(t, {}).keys())

        results = []
        for doc_id in candidates:
            first_positions = self.index[terms[0]][doc_id].positions
            for start_pos in first_positions:
                if all(
                    (start_pos + i) in set(self.index[terms[i]][doc_id].positions)
                    for i in range(1, len(terms))
                ):
                    score = sum(self.bm25_score(t, doc_id) for t in terms)
                    results.append({
                        "doc_id": doc_id,
                        "score": round(score, 4),
                        "text": self.docs[doc_id],
                    })
                    break

        return sorted(results, key=lambda x: -x["score"])

    # ------------------------------------------------------------- highlight

    def highlight(self, doc_id: int, query: str,
                  pre_tag: str = "<em>", post_tag: str = "</em>") -> str:
        """
        Returns the document text with query terms wrapped in highlight tags.
        Uses stored character offsets — no re-scanning of original text.

        Example:
          "Redis is fast" with query "redis" →
          "<em>Redis</em> is fast"
        """
        text = self.docs.get(doc_id, "")
        query_terms = set(tokenize(query))

        # Collect all (start, end) offsets for matching terms
        hit_offsets: list[tuple[int, int]] = []
        for term in query_terms:
            posting = self.index.get(term, {}).get(doc_id)
            if posting:
                hit_offsets.extend(posting.offsets)

        if not hit_offsets:
            return text

        # Sort by start position; build highlighted string
        hit_offsets.sort()
        result = []
        last = 0
        for start, end in hit_offsets:
            result.append(text[last:start])       # text before match
            result.append(pre_tag)
            result.append(text[start:end])        # matched text (original case)
            result.append(post_tag)
            last = end
        result.append(text[last:])                # trailing text

        return "".join(result)

    # ----------------------------------------------------------- term vectors

    def term_vector(self, doc_id: int) -> dict[str, dict]:
        """
        Returns all terms in a document with their TF, IDF, positions, and offsets.
        Equivalent to Elasticsearch's _termvectors API.
        """
        if doc_id not in self.docs:
            return {}

        result = {}
        for term, postings in self.index.items():
            if doc_id in postings:
                p = postings[doc_id]
                result[term] = {
                    "tf":        p.tf,
                    "idf":       round(self.idf(term), 4),
                    "tf_idf":    round(self.tf_idf(term, doc_id), 4),
                    "bm25":      round(self.bm25_score(term, doc_id), 4),
                    "positions": p.positions,
                    "offsets":   p.offsets,
                }
        return result

    def __repr__(self):
        return (
            f"FullIndex(terms={len(self.index)}, docs={self.N}, "
            f"avgdl={self.avgdl:.1f}, k1={self.k1}, b={self.b})"
        )


# =============================================================================
# TESTS
# =============================================================================

class TestSimpleIndex(unittest.TestCase):

    def setUp(self):
        self.idx = SimpleIndex()
        self.d0 = self.idx.add_document("Redis is an in-memory data store")
        self.d1 = self.idx.add_document("Redis supports pub sub and streams")
        self.d2 = self.idx.add_document("Postgres is a relational database")
        self.d3 = self.idx.add_document("Memcached is another in-memory store")

    def test_single_term(self):
        self.assertEqual(self.idx.search("redis"), {self.d0, self.d1})

    def test_and_query(self):
        result = self.idx.search("redis AND memory")
        self.assertEqual(result, {self.d0})

    def test_or_query(self):
        result = self.idx.search("redis OR postgres")
        self.assertEqual(result, {self.d0, self.d1, self.d2})

    def test_not_query(self):
        # in-memory docs that are NOT redis
        result = self.idx.search("memory NOT redis")
        self.assertIn(self.d3, result)
        self.assertNotIn(self.d0, result)

    def test_missing_term(self):
        self.assertEqual(self.idx.search("mongodb"), set())

    def test_case_insensitive(self):
        self.assertEqual(self.idx.search("REDIS"), self.idx.search("redis"))


class TestTFIndex(unittest.TestCase):

    def setUp(self):
        self.idx = TFIndex()
        # d0 mentions "redis" 3 times — should rank first for "redis" query
        self.d0 = self.idx.add_document("redis redis redis is very fast")
        self.d1 = self.idx.add_document("redis is great for caching")
        self.d2 = self.idx.add_document("postgres is a relational database")

    def test_tf_count(self):
        self.assertEqual(self.idx.tf("redis", self.d0), 3)
        self.assertEqual(self.idx.tf("redis", self.d1), 1)
        self.assertEqual(self.idx.tf("redis", self.d2), 0)

    def test_ranking_by_tf(self):
        results = self.idx.search("redis")
        self.assertEqual(results[0][0], self.d0)   # highest TF ranks first
        self.assertEqual(results[1][0], self.d1)

    def test_multi_term_scoring(self):
        results = self.idx.search("redis caching")
        # d1 has both "redis" and "caching" → higher combined TF than d0
        self.assertEqual(results[0][0], self.d1)

    def test_no_match(self):
        results = self.idx.search("mongodb")
        self.assertEqual(results, [])


class TestPositionalIndex(unittest.TestCase):

    def setUp(self):
        self.idx = PositionalIndex()
        self.d0 = self.idx.add_document("the distributed lock pattern uses redis")
        self.d1 = self.idx.add_document("redis lock is a distributed system tool")
        self.d2 = self.idx.add_document("redis is fast and lock free designs exist")

    def test_positions_recorded(self):
        # "distributed" is at position 1 in d0
        self.assertIn(1, self.idx.index["distributed"][self.d0].positions)

    def test_tf_from_positions(self):
        self.idx.add_document("redis redis redis")
        # The new doc (d3) should have tf=3 for "redis"
        d3 = 3
        self.assertEqual(self.idx.index["redis"][d3].tf, 3)

    def test_phrase_match_exact(self):
        # "distributed lock" appears in d0 consecutively
        result = self.idx.phrase_search("distributed lock")
        self.assertIn(self.d0, result)

    def test_phrase_no_match_wrong_order(self):
        # "lock distributed" does NOT appear consecutively in any doc
        result = self.idx.phrase_search("lock distributed")
        self.assertEqual(result, [])

    def test_phrase_not_in_d1(self):
        # d1 has "distributed" and "lock" but NOT consecutively
        result = self.idx.phrase_search("distributed lock")
        self.assertNotIn(self.d1, result)

    def test_proximity_within_range(self):
        # d2: "redis" at pos 0, "lock" at pos 4 → distance=4 ≤ 5
        result = self.idx.proximity_search("redis", "lock", max_distance=5)
        self.assertIn(self.d2, result)

    def test_proximity_outside_range(self):
        # d2: distance=4, requesting ≤ 2 → no match
        result = self.idx.proximity_search("redis", "lock", max_distance=2)
        self.assertNotIn(self.d2, result)


class TestFullIndex(unittest.TestCase):

    def setUp(self):
        self.idx = FullIndex(k1=1.2, b=0.75)
        # Short docs — redis is highly specific in each
        self.d0 = self.idx.add_document("Redis is an in-memory data structure store")
        self.d1 = self.idx.add_document("Redis supports pub sub messaging")
        self.d2 = self.idx.add_document("Postgres is a powerful relational database system")
        self.d3 = self.idx.add_document(
            "Redis Redis Redis is mentioned many times in this redis benchmark document"
        )

    def test_idf_lower_for_common_terms(self):
        # "is" appears in all docs → lower IDF than "redis"
        self.assertLess(self.idx.idf("is"), self.idx.idf("redis"))

    def test_bm25_tf_saturation(self):
        # d3 has tf=5 for "redis", d0 has tf=1
        # BM25 score for d3 should be higher but NOT 5x higher (saturation)
        score_d0 = self.idx.bm25_score("redis", self.d0)
        score_d3 = self.idx.bm25_score("redis", self.d3)
        self.assertGreater(score_d3, score_d0)
        self.assertLess(score_d3, score_d0 * 5)   # saturation: not 5x

    def test_search_returns_ranked_results(self):
        results = self.idx.search("redis")
        doc_ids = [r["doc_id"] for r in results]
        # Postgres doc should not appear (doesn't contain "redis")
        self.assertNotIn(self.d2, doc_ids)

    def test_search_bm25_vs_tfidf(self):
        bm25_results  = self.idx.search("redis", scorer="bm25")
        tfidf_results = self.idx.search("redis", scorer="tf_idf")
        # Both should rank the same top docs (just different scores)
        self.assertEqual(
            {r["doc_id"] for r in bm25_results},
            {r["doc_id"] for r in tfidf_results},
        )

    def test_offsets_stored_correctly(self):
        # "Redis" starts at char 0 in d0
        posting = self.idx.index["redis"][self.d0]
        self.assertEqual(posting.offsets[0], (0, 5))

    def test_highlight(self):
        highlighted = self.idx.highlight(self.d0, "redis")
        self.assertIn("<em>Redis</em>", highlighted)
        # Non-query words should not be tagged
        self.assertNotIn("<em>is</em>", highlighted)

    def test_highlight_multiple_terms(self):
        highlighted = self.idx.highlight(self.d0, "redis memory")
        self.assertIn("<em>Redis</em>", highlighted)
        self.assertIn("<em>memory</em>", highlighted)

    def test_phrase_search(self):
        results = self.idx.phrase_search("pub sub")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["doc_id"], self.d1)

    def test_phrase_search_no_match(self):
        results = self.idx.phrase_search("memory redis")  # wrong order
        self.assertEqual(results, [])

    def test_term_vector_keys(self):
        tv = self.idx.term_vector(self.d0)
        self.assertIn("redis", tv)
        for field_name in ("tf", "idf", "tf_idf", "bm25", "positions", "offsets"):
            self.assertIn(field_name, tv["redis"])

    def test_avgdl(self):
        self.assertGreater(self.idx.avgdl, 0)

    def test_empty_query(self):
        self.assertEqual(self.idx.search(""), [])


# =============================================================================
# DEMO — print a walkthrough of all four layers
# =============================================================================

def demo():
    separator = "=" * 60

    print(f"\n{separator}")
    print("LAYER 1: Simple Boolean Index")
    print(separator)
    idx = SimpleIndex()
    idx.add_document("Redis is an in-memory data store",            doc_id=0)
    idx.add_document("Redis supports pub sub and streams",          doc_id=1)
    idx.add_document("Postgres is a relational database",           doc_id=2)
    idx.add_document("Memcached is another in-memory store",        doc_id=3)
    print("search('redis')            →", idx.search("redis"))
    print("search('redis AND memory') →", idx.search("redis AND memory"))
    print("search('redis OR postgres')→", idx.search("redis OR postgres"))
    print("search('memory NOT redis') →", idx.search("memory NOT redis"))

    print(f"\n{separator}")
    print("LAYER 2: TF Index (ranked by term frequency)")
    print(separator)
    idx2 = TFIndex()
    idx2.add_document("redis redis redis is very fast",         doc_id=0)
    idx2.add_document("redis is great for caching",             doc_id=1)
    idx2.add_document("postgres is a relational database",      doc_id=2)
    print("search('redis') →", idx2.search("redis"))
    print("  (doc 0 first — highest TF=3 for 'redis')")

    print(f"\n{separator}")
    print("LAYER 3: Positional Index (phrase + proximity)")
    print(separator)
    idx3 = PositionalIndex()
    idx3.add_document("the distributed lock pattern uses redis",         doc_id=0)
    idx3.add_document("redis lock is a distributed system tool",         doc_id=1)
    idx3.add_document("redis is fast and lock free designs exist",       doc_id=2)
    print("phrase_search('distributed lock') →", idx3.phrase_search("distributed lock"))
    print("  (only doc 0 — consecutive in order)")
    print("proximity_search('redis','lock', 5) →",
          idx3.proximity_search("redis", "lock", max_distance=5))

    print(f"\n{separator}")
    print("LAYER 4: Full Index (BM25 + offsets + highlighting)")
    print(separator)
    idx4 = FullIndex()
    d0 = idx4.add_document("Redis is an in-memory data structure store")
    d1 = idx4.add_document("Redis supports pub sub messaging and pub sub events")
    d2 = idx4.add_document("Postgres is a powerful relational database system")
    d3 = idx4.add_document("Redis Redis Redis mentioned many times as a redis benchmark")

    print("\nBM25 search('redis'):")
    for r in idx4.search("redis"):
        print(f"  doc {r['doc_id']} score={r['score']:>7.4f}  \"{r['text'][:50]}\"")

    print(f"\nidf('redis') = {idx4.idf('redis'):.4f}  (specific term)")
    print(f"idf('is')    = {idx4.idf('is'):.4f}  (common term — lower IDF)")

    print("\nHighlight doc 0 for query 'redis memory':")
    print(" ", idx4.highlight(d0, "redis memory"))

    print("\nPhrase search 'pub sub':")
    for r in idx4.phrase_search("pub sub"):
        print(f"  doc {r['doc_id']}  \"{r['text'][:50]}\"")

    print("\nTerm vector for doc 0 (key fields):")
    tv = idx4.term_vector(d0)
    for term in sorted(tv):
        t = tv[term]
        print(f"  {term:<12} tf={t['tf']}  idf={t['idf']:.3f}  "
              f"bm25={t['bm25']:.4f}  positions={t['positions']}  offsets={t['offsets']}")


if __name__ == "__main__":
    demo()
    print("\n\n" + "=" * 60)
    print("RUNNING TESTS")
    print("=" * 60 + "\n")
    unittest.main(verbosity=2, exit=False)