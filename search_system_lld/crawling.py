"""
=============================================================================
07 — CRAWLING & DEDUPLICATION
=============================================================================
PRIORITY: #7 for exa.ai — they built their OWN web index (not Bing/Google).

WHAT TO MASTER:
  - Web crawl architecture: frontier, fetcher, parser, scheduler
  - URL normalization and canonicalization
  - Bloom filters: probabilistic set membership (seen URLs)
  - SimHash: near-duplicate document detection (O(1) per comparison)
  - MinHash + LSH: fuzzy deduplication at scale
  - Crawl politeness: robots.txt, rate limiting, crawl budget
  - Freshness vs coverage tradeoffs

EXA.AI ANGLE:
  Unlike most neural search products (Cohere, etc.) that buy Bing's index,
  exa.ai built their own crawler and index. This is their moat.
  At Staff level, you should be able to discuss:
  - How they decide what to crawl (crawl prioritization)
  - How they detect near-duplicate pages (SimHash)
  - How they avoid recrawling seen URLs (Bloom filter)
  - How they keep the index fresh (recrawl scheduling)

KEY INSIGHT:
  The web has ~50B pages but ~80% are near-duplicate or low-quality.
  Deduplication before indexing saves 80% of storage and improves
  result quality. SimHash is the standard tool (used by Google).
=============================================================================
"""

import hashlib
import math
import random
import re
import time
import unittest
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse


# =============================================================================
# BLOOM FILTER
# =============================================================================
#
# PROBLEM: Track which URLs have been seen without storing all URLs.
# At 100B URLs, a hash set would need ~8-16 bytes per URL = 800GB-1.6TB.
#
# BLOOM FILTER: probabilistic set membership in O(1) time, O(m) space.
# m bits, k hash functions. Insert: set k bits. Query: check k bits.
# False positive rate: ~(1 - e^(-kn/m))^k where n = items inserted.
# FALSE NEGATIVES ARE IMPOSSIBLE — if it says "not seen", it wasn't seen.
#
# OPTIMAL PARAMETERS:
#   m = -n * ln(p) / ln(2)^2   where p = desired false positive rate
#   k = m/n * ln(2)             optimal number of hash functions
#
# FAILURE MODE: As n grows beyond design capacity, false positive rate rises.
# Fix: use a counting Bloom filter (supports deletes) or a scalable Bloom filter
# (adds new layers when capacity exceeded).
#
# PRODUCTION: Crawlers use Bloom filters to avoid re-fetching URLs.
# Google uses distributed Bloom filters partitioned across machines.
# A 1% FP rate on 100B URLs: m ≈ 958GB — much better than storing URLs.

class BloomFilter:
    """
    Space-efficient probabilistic set. False positives possible; false negatives impossible.
    """

    def __init__(self, capacity: int, false_positive_rate: float = 0.01):
        self.capacity = capacity
        self.fpr = false_positive_rate

        # Optimal bit array size and number of hash functions
        self.m = self._optimal_m(capacity, false_positive_rate)
        self.k = self._optimal_k(self.m, capacity)
        self.bits = bytearray(math.ceil(self.m / 8))
        self._count = 0

    @staticmethod
    def _optimal_m(n: int, p: float) -> int:
        return max(1, int(-n * math.log(p) / (math.log(2) ** 2)))

    @staticmethod
    def _optimal_k(m: int, n: int) -> int:
        return max(1, round((m / n) * math.log(2)))

    def _hashes(self, item: str) -> list[int]:
        """Generate k independent hash values for item."""
        positions = []
        # Double-hashing: h_i(x) = (h1(x) + i * h2(x)) % m
        h1 = int(hashlib.md5(item.encode()).hexdigest(), 16)
        h2 = int(hashlib.sha256(item.encode()).hexdigest(), 16)
        for i in range(self.k):
            positions.append((h1 + i * h2) % self.m)
        return positions

    def add(self, item: str):
        for pos in self._hashes(item):
            byte_idx, bit_idx = divmod(pos, 8)
            self.bits[byte_idx] |= (1 << bit_idx)
        self._count += 1

    def __contains__(self, item: str) -> bool:
        """Check membership. May return True for items not added (false positive)."""
        for pos in self._hashes(item):
            byte_idx, bit_idx = divmod(pos, 8)
            if not (self.bits[byte_idx] & (1 << bit_idx)):
                return False  # definitely not present
        return True  # probably present

    @property
    def estimated_fpr(self) -> float:
        """Estimated current false positive rate based on fill ratio."""
        fill = sum(bin(b).count("1") for b in self.bits) / self.m
        return fill ** self.k

    @property
    def memory_bytes(self) -> int:
        return len(self.bits)

    def __repr__(self):
        return (f"BloomFilter(capacity={self.capacity}, m={self.m}b, k={self.k}, "
                f"count={self._count}, est_fpr={self.estimated_fpr:.4%})")


# =============================================================================
# SIMHASH — Near-Duplicate Detection
# =============================================================================
#
# ALGORITHM (Charikar, 2002)
# ───────────────────────────
# 1. Tokenize document into n-grams
# 2. Hash each n-gram to a b-bit fingerprint
# 3. Initialize a vector V of b integers to 0
# 4. For each n-gram hash:
#      For each bit position i:
#        If bit i is 1: V[i] += weight
#        If bit i is 0: V[i] -= weight
# 5. SimHash = sign(V): bit i is 1 if V[i] > 0
#
# SIMILARITY: two documents are near-duplicates if Hamming(sim1, sim2) ≤ threshold.
# Hamming distance = number of bit positions that differ.
# Threshold 3 → docs differ in ≤ 3 bits → ~95% similar content.
#
# WHY SIMHASH WORKS: similar documents share many n-grams. Each shared n-gram
# votes for the same bit positions. The majority vote (sign) captures the
# "centroid" of the document's n-gram distribution.
#
# SCALING: Google reportedly uses 64-bit SimHash + 3-bit Hamming threshold.
# For fast lookup: split the 64-bit hash into 4 blocks of 16 bits.
# For near-duplicates, at least 1 block must match exactly.
# Index by block → O(1) candidate lookup → verify Hamming distance.

class SimHash:
    """
    64-bit SimHash fingerprint for near-duplicate detection.
    """

    def __init__(self, bits: int = 64, ngram_size: int = 3):
        self.bits = bits
        self.ngram_size = ngram_size

    def _hash_token(self, token: str) -> int:
        """Hash a token to b-bit fingerprint."""
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        return h & ((1 << self.bits) - 1)

    def _ngrams(self, text: str) -> list[str]:
        """Character n-grams (more robust than word n-grams for near-dupes)."""
        text = re.sub(r"\s+", " ", text.lower())
        return [text[i:i+self.ngram_size] for i in range(len(text) - self.ngram_size + 1)]

    def fingerprint(self, text: str) -> int:
        """Compute SimHash fingerprint for text. Returns b-bit integer."""
        tokens = self._ngrams(text)
        if not tokens:
            return 0

        # Weighted bit vector
        v = [0] * self.bits
        for token in tokens:
            h = self._hash_token(token)
            for i in range(self.bits):
                v[i] += 1 if (h >> i) & 1 else -1

        # Convert to bit fingerprint
        result = 0
        for i in range(self.bits):
            if v[i] > 0:
                result |= (1 << i)
        return result

    def hamming_distance(self, fp1: int, fp2: int) -> int:
        """Number of differing bits between two fingerprints."""
        xor = fp1 ^ fp2
        return bin(xor).count("1")

    def is_near_duplicate(self, text1: str, text2: str, threshold: int = 3) -> bool:
        """Returns True if texts are near-duplicates (Hamming ≤ threshold)."""
        fp1 = self.fingerprint(text1)
        fp2 = self.fingerprint(text2)
        return self.hamming_distance(fp1, fp2) <= threshold


# =============================================================================
# MINHASH + LSH — Fuzzy Deduplication
# =============================================================================
#
# SIMHASH vs MINHASH:
#   SimHash  : order-sensitive, good for near-duplicate PAGES (same content, minor edits)
#   MinHash  : set-based Jaccard similarity, good for documents with SHARED CONTENT
#              (two articles drawing from same source → high Jaccard, diff order)
#
# MINHASH ALGORITHM
# ─────────────────
# Represent document as set of k-shingles (k-grams).
# For each of n hash functions h_i, compute min(h_i(shingle)) over all shingles.
# This gives a signature vector of n integers.
#
# KEY PROPERTY: P(min_hash_i(A) == min_hash_i(B)) = Jaccard(A, B)
# So signature similarity ≈ Jaccard similarity!
#
# LSH (Locality-Sensitive Hashing for MinHash)
# ─────────────────────────────────────────────
# Divide n-hash signature into b bands of r rows each.
# Two docs are candidate duplicates if ANY band is identical.
# P(candidate | Jaccard=s) ≈ 1 - (1 - s^r)^b
# Tune b and r to get the desired threshold.

class MinHash:
    """
    MinHash signature with LSH banding for approximate Jaccard similarity.
    """

    def __init__(self, n_hashes: int = 128, shingle_size: int = 5):
        self.n_hashes = n_hashes
        self.shingle_size = shingle_size
        # Pre-generate hash function parameters (a, b) for h(x) = (ax + b) % p
        random.seed(42)
        self.p = (1 << 31) - 1  # Mersenne prime
        self.a = [random.randint(1, self.p - 1) for _ in range(n_hashes)]
        self.b = [random.randint(0, self.p - 1) for _ in range(n_hashes)]

    def _shingles(self, text: str) -> set[int]:
        text = re.sub(r"\s+", " ", text.lower())
        result = set()
        for i in range(max(1, len(text) - self.shingle_size + 1)):
            shingle = text[i:i+self.shingle_size]
            result.add(int(hashlib.md5(shingle.encode()).hexdigest(), 16) % self.p)
        return result

    def signature(self, text: str) -> list[int]:
        """Compute MinHash signature vector."""
        shingles = self._shingles(text)
        if not shingles:
            return [0] * self.n_hashes

        sig = []
        for i in range(self.n_hashes):
            min_hash = min(
                (self.a[i] * s + self.b[i]) % self.p
                for s in shingles
            )
            sig.append(min_hash)
        return sig

    def jaccard_estimate(self, sig1: list[int], sig2: list[int]) -> float:
        """Estimate Jaccard similarity from signatures."""
        matches = sum(a == b for a, b in zip(sig1, sig2))
        return matches / self.n_hashes

    def true_jaccard(self, text1: str, text2: str) -> float:
        """Exact Jaccard for validation."""
        s1 = self._shingles(text1)
        s2 = self._shingles(text2)
        if not s1 or not s2:
            return 0.0
        return len(s1 & s2) / len(s1 | s2)


class LSHIndex:
    """
    LSH-based approximate deduplication using MinHash.
    Candidate pairs found in O(1); verified with full signature comparison.
    """

    def __init__(self, minhash: MinHash, bands: int = 16):
        self.mh = minhash
        self.bands = bands
        self.rows = minhash.n_hashes // bands
        # band_id → {band_hash → [doc_ids]}
        self.buckets: list[dict[int, list[int]]] = [defaultdict(list) for _ in range(bands)]
        self.signatures: dict[int, list[int]] = {}

    def add(self, doc_id: int, text: str):
        sig = self.mh.signature(text)
        self.signatures[doc_id] = sig

        for band_idx in range(self.bands):
            band = tuple(sig[band_idx * self.rows:(band_idx + 1) * self.rows])
            band_hash = hash(band)
            self.buckets[band_idx][band_hash].append(doc_id)

    def find_candidates(self, doc_id: int) -> set[int]:
        """Find candidate near-duplicates for a document."""
        sig = self.signatures.get(doc_id)
        if sig is None:
            return set()

        candidates = set()
        for band_idx in range(self.bands):
            band = tuple(sig[band_idx * self.rows:(band_idx + 1) * self.rows])
            band_hash = hash(band)
            for candidate_id in self.buckets[band_idx][band_hash]:
                if candidate_id != doc_id:
                    candidates.add(candidate_id)
        return candidates

    def find_near_duplicates(self, doc_id: int, threshold: float = 0.8) -> list[tuple[int, float]]:
        """Return (candidate_doc_id, similarity) pairs above threshold."""
        candidates = self.find_candidates(doc_id)
        sig1 = self.signatures[doc_id]
        results = []
        for cand_id in candidates:
            sim = self.mh.jaccard_estimate(sig1, self.signatures[cand_id])
            if sim >= threshold:
                results.append((cand_id, sim))
        return sorted(results, key=lambda x: -x[1])


# =============================================================================
# URL NORMALIZATION
# =============================================================================
#
# The same page can appear under many URLs. Without normalization,
# the crawler fetches duplicates and the index has multiple entries per page.
#
# CANONICAL FORMS:
#   - Lowercase scheme and host: HTTP://Redis.IO → http://redis.io
#   - Remove default ports: http://redis.io:80/docs → http://redis.io/docs
#   - Remove trailing slash: http://redis.io/docs/ → http://redis.io/docs
#   - Remove URL fragments: http://redis.io/docs#section → http://redis.io/docs
#   - Remove tracking params: ?utm_source=... → removed
#   - Sort query params: ?b=2&a=1 → ?a=1&b=2
#   - Decode percent-encoding: %20 → space (then re-encode consistently)

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "msclkid", "ref", "referrer", "source",
}

def normalize_url(url: str) -> str:
    """
    Canonicalize a URL to prevent duplicate fetches.
    Critical for crawler efficiency: ~30% of web URLs are duplicates.
    """
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return url

    # Lowercase scheme and host
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    # Remove default ports
    if ":" in netloc:
        host, port = netloc.rsplit(":", 1)
        if (scheme == "http" and port == "80") or (scheme == "https" and port == "443"):
            netloc = host

    # Remove trailing slash from path (but keep root /)
    path = parsed.path
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    # Remove fragment
    fragment = ""

    # Filter tracking query params and sort remaining
    query_parts = []
    if parsed.query:
        for part in parsed.query.split("&"):
            if "=" in part:
                key, val = part.split("=", 1)
                if key.lower() not in TRACKING_PARAMS:
                    query_parts.append((key.lower(), val))
        query_parts.sort()
    query = "&".join(f"{k}={v}" for k, v in query_parts)

    return urlunparse((scheme, netloc, path, parsed.params, query, fragment))


# =============================================================================
# CRAWL SCHEDULER (priority queue)
# =============================================================================
#
# CRAWL PRIORITIZATION
# ─────────────────────
# Not all pages are equal. A good scheduler prioritizes:
#   1. High PageRank / authority domains
#   2. Fresh pages (recently modified)
#   3. Linked-from-many pages (hub score)
#   4. Pages matching target topics (focused crawl)
#   5. Pages not crawled recently (freshness)
#
# POLITENESS
#   robots.txt: must respect Disallow directives
#   Crawl-delay: honor per-domain delay
#   User-Agent: identify your crawler
#   Rate limit: ≤ 1 req/sec per domain (good citizen)

@dataclass(order=True)
class CrawlJob:
    priority:   float           # lower = higher priority (min-heap)
    url:        str = field(compare=False)
    depth:      int = field(compare=False, default=0)
    scheduled:  float = field(compare=False, default_factory=time.time)


class CrawlScheduler:
    """
    Priority-based crawl scheduler with:
    - Bloom filter for seen URLs
    - Per-domain politeness (rate limiting)
    - robots.txt respect (simulated)
    """

    def __init__(self, capacity: int = 10_000):
        self.frontier: list[CrawlJob] = []
        self.seen = BloomFilter(capacity=capacity, false_positive_rate=0.001)
        self.domain_last_fetch: dict[str, float] = {}
        self.crawl_delay = 1.0  # seconds between fetches per domain
        self.disallowed: dict[str, set[str]] = {}   # domain → set of disallowed prefixes

    def _domain(self, url: str) -> str:
        return urlparse(url).netloc.lower()

    def _is_allowed(self, url: str) -> bool:
        """Simplified robots.txt check."""
        domain = self._domain(url)
        path   = urlparse(url).path
        for prefix in self.disallowed.get(domain, set()):
            if path.startswith(prefix):
                return False
        return True

    def add_disallow(self, domain: str, path_prefix: str):
        self.disallowed.setdefault(domain, set()).add(path_prefix)

    def schedule(self, url: str, priority: float = 0.5, depth: int = 0) -> bool:
        """
        Add URL to frontier. Returns False if already seen or disallowed.
        Priority: 0.0 = highest, 1.0 = lowest.
        """
        canonical = normalize_url(url)

        if canonical in self.seen:
            return False  # already seen (possible FP — bloom filter)

        if not self._is_allowed(canonical):
            return False

        self.seen.add(canonical)
        import heapq
        heapq.heappush(self.frontier, CrawlJob(priority, canonical, depth))
        return True

    def next_job(self) -> Optional[CrawlJob]:
        """
        Pop the highest-priority job that respects crawl-delay for its domain.
        In production: a more sophisticated scheduler with per-domain queues.
        """
        import heapq
        now = time.time()

        # Scan frontier for a job whose domain delay has elapsed
        temp = []
        job = None
        while self.frontier:
            candidate = heapq.heappop(self.frontier)
            domain = self._domain(candidate.url)
            last = self.domain_last_fetch.get(domain, 0)
            if now - last >= self.crawl_delay:
                job = candidate
                break
            temp.append(candidate)

        # Restore skipped jobs
        for j in temp:
            heapq.heappush(self.frontier, j)

        if job:
            self.domain_last_fetch[self._domain(job.url)] = now

        return job

    @property
    def frontier_size(self) -> int:
        return len(self.frontier)


# =============================================================================
# TESTS
# =============================================================================

class TestBloomFilter(unittest.TestCase):
    def setUp(self):
        self.bf = BloomFilter(capacity=1000, false_positive_rate=0.01)

    def test_contains_added_item(self):
        self.bf.add("https://redis.io/docs")
        self.assertIn("https://redis.io/docs", self.bf)

    def test_no_false_negatives(self):
        items = [f"url_{i}" for i in range(500)]
        for item in items:
            self.bf.add(item)
        for item in items:
            self.assertIn(item, self.bf)  # must never return False for added items

    def test_low_fpr_on_capacity(self):
        """False positive rate should stay near target for items within capacity."""
        bf = BloomFilter(capacity=1000, false_positive_rate=0.05)
        for i in range(1000):
            bf.add(f"item_{i}")
        fp = 0
        n_test = 1000
        for i in range(10_000, 10_000 + n_test):
            if f"item_{i}" in bf:
                fp += 1
        actual_fpr = fp / n_test
        self.assertLess(actual_fpr, 0.2)  # generous bound for small test

    def test_memory_smaller_than_storing_strings(self):
        """Bloom filter should use less memory than storing all URLs."""
        bf = BloomFilter(capacity=10_000, false_positive_rate=0.01)
        # 10K URLs at ~50 bytes each = 500KB. Bloom filter should be << that.
        self.assertLess(bf.memory_bytes, 500_000)


class TestSimHash(unittest.TestCase):
    def setUp(self):
        self.sh = SimHash(bits=64, ngram_size=3)

    def test_identical_docs_same_hash(self):
        text = "Redis is an in-memory data structure store"
        self.assertEqual(self.sh.fingerprint(text), self.sh.fingerprint(text))

    def test_similar_docs_low_hamming(self):
        t1 = "Redis is an in-memory data structure store for caching"
        t2 = "Redis is an in-memory data structure store for caching and more"
        d  = self.sh.hamming_distance(self.sh.fingerprint(t1), self.sh.fingerprint(t2))
        self.assertLess(d, 20)  # similar content → low hamming distance

    def test_different_docs_high_hamming(self):
        t1 = "Redis is an in-memory data structure store"
        t2 = "The Great Wall of China is a historical monument"
        d  = self.sh.hamming_distance(self.sh.fingerprint(t1), self.sh.fingerprint(t2))
        self.assertGreater(d, 10)

    def test_near_duplicate_detection(self):
        t1 = "Redis is fast and supports many data structures"
        t2 = "Redis is fast and supports many data structures and more"
        self.assertTrue(self.sh.is_near_duplicate(t1, t2, threshold=10))

    def test_not_near_duplicate(self):
        t1 = "Redis is a fast in-memory data store"
        t2 = "Machine learning models require gradient descent optimization"
        self.assertFalse(self.sh.is_near_duplicate(t1, t2, threshold=3))


class TestMinHash(unittest.TestCase):
    def setUp(self):
        self.mh = MinHash(n_hashes=64, shingle_size=4)

    def test_identical_jaccard_estimate(self):
        text = "Redis is a fast in-memory store"
        sig = self.mh.signature(text)
        est = self.mh.jaccard_estimate(sig, sig)
        self.assertAlmostEqual(est, 1.0)

    def test_jaccard_estimate_close_to_true(self):
        t1 = "the quick brown fox jumps over the lazy dog"
        t2 = "the quick brown fox jumps over the lazy cat"
        true_j = self.mh.true_jaccard(t1, t2)
        est_j  = self.mh.jaccard_estimate(self.mh.signature(t1), self.mh.signature(t2))
        self.assertAlmostEqual(est_j, true_j, delta=0.2)

    def test_different_docs_low_jaccard(self):
        t1 = "Redis caching distributed lock"
        t2 = "machine learning gradient descent neural network"
        true_j = self.mh.true_jaccard(t1, t2)
        self.assertLess(true_j, 0.2)


class TestURLNormalization(unittest.TestCase):
    def test_lowercase_host(self):
        self.assertEqual(normalize_url("HTTP://Redis.IO/docs"), "http://redis.io/docs")

    def test_remove_default_port(self):
        self.assertEqual(normalize_url("http://redis.io:80/docs"), "http://redis.io/docs")
        self.assertEqual(normalize_url("https://redis.io:443/docs"), "https://redis.io/docs")

    def test_remove_fragment(self):
        self.assertEqual(normalize_url("http://redis.io/docs#section"), "http://redis.io/docs")

    def test_remove_tracking_params(self):
        url = "http://redis.io/docs?utm_source=google&page=1"
        normalized = normalize_url(url)
        self.assertNotIn("utm_source", normalized)
        self.assertIn("page=1", normalized)

    def test_sort_query_params(self):
        url1 = normalize_url("http://example.com?b=2&a=1")
        url2 = normalize_url("http://example.com?a=1&b=2")
        self.assertEqual(url1, url2)

    def test_remove_trailing_slash(self):
        self.assertEqual(normalize_url("http://redis.io/docs/"), "http://redis.io/docs")

    def test_preserve_root_slash(self):
        result = normalize_url("http://redis.io/")
        # Root path should not have trailing slash removed (or normalized consistently)
        self.assertTrue(result.startswith("http://redis.io"))


class TestCrawlScheduler(unittest.TestCase):
    def setUp(self):
        self.scheduler = CrawlScheduler(capacity=1000)
        self.scheduler.crawl_delay = 0.0  # disable delays for testing

    def test_schedule_new_url(self):
        result = self.scheduler.schedule("http://redis.io/docs", priority=0.5)
        self.assertTrue(result)
        self.assertEqual(self.scheduler.frontier_size, 1)

    def test_no_duplicate_urls(self):
        self.scheduler.schedule("http://redis.io/docs")
        result = self.scheduler.schedule("http://redis.io/docs")
        self.assertFalse(result)
        self.assertEqual(self.scheduler.frontier_size, 1)

    def test_robots_txt_disallow(self):
        self.scheduler.add_disallow("private.com", "/admin")
        result = self.scheduler.schedule("http://private.com/admin/users")
        self.assertFalse(result)

    def test_priority_ordering(self):
        self.scheduler.schedule("http://low.com", priority=0.9)
        self.scheduler.schedule("http://high.com", priority=0.1)
        job = self.scheduler.next_job()
        self.assertIsNotNone(job)
        self.assertEqual(job.url, "http://high.com")

    def test_next_job_returns_none_when_empty(self):
        job = self.scheduler.next_job()
        self.assertIsNone(job)


def demo():
    print("=" * 60)
    print("CRAWLING & DEDUPLICATION DEMO")
    print("=" * 60)

    # Bloom filter memory comparison
    print("\n[Bloom Filter — memory vs accuracy tradeoff]")
    for fpr in [0.1, 0.01, 0.001]:
        bf = BloomFilter(capacity=1_000_000, false_positive_rate=fpr)
        print(f"  FPR={fpr:.1%}: {bf.m:>12,} bits  = {bf.memory_bytes/1024/1024:.1f} MB  "
              f"k={bf.k} hash functions")
    print(f"  Storing 1M URLs as strings: ~50 MB  (Bloom filter is 20-100x smaller)")

    print("\n[SimHash — near-duplicate detection]")
    sh = SimHash(bits=64)
    pairs = [
        ("Redis is a fast in-memory cache", "Redis is a fast in-memory cache store", "near-dup"),
        ("Redis is a fast in-memory cache", "Postgres is a relational database", "different"),
        ("Redis docs v7.0: installation guide", "Redis docs v7.1: installation guide", "near-dup"),
    ]
    for t1, t2, label in pairs:
        fp1, fp2 = sh.fingerprint(t1), sh.fingerprint(t2)
        dist = sh.hamming_distance(fp1, fp2)
        detected = "near-dup" if dist <= 10 else "different"
        correct = "✓" if detected == label else "✗"
        print(f"  {correct} Hamming={dist:>2d} [{label}]  '{t1[:35]}...'")

    print("\n[MinHash + LSH — fuzzy dedup at scale]")
    mh = MinHash(n_hashes=128)
    lsh = LSHIndex(mh, bands=16)
    articles = [
        "Redis is an open source in-memory data structure store used as cache and message broker",
        "Redis is an open source in-memory data store commonly used for caching and pub/sub",
        "PostgreSQL is a powerful open source relational database system with SQL support",
        "Redis supports various data structures: strings, hashes, lists, sets, sorted sets",
        "Redis, an open-source in-memory data structure store, is used as cache and broker",
    ]
    for i, text in enumerate(articles):
        lsh.add(i, text)

    print("  Near-duplicate candidates (Jaccard ≥ 0.3):")
    for doc_id in range(len(articles)):
        dupes = lsh.find_near_duplicates(doc_id, threshold=0.3)
        if dupes:
            for cand_id, sim in dupes:
                if cand_id > doc_id:  # avoid printing both directions
                    print(f"  Doc {doc_id} ↔ Doc {cand_id}: Jaccard≈{sim:.2f}")
                    print(f"    [{articles[doc_id][:55]}...]")
                    print(f"    [{articles[cand_id][:55]}...]")

    print("\n[URL normalization]")
    urls = [
        "HTTP://Redis.IO:80/Docs/",
        "http://redis.io/docs?utm_source=google&version=7",
        "https://redis.io:443/docs#commands",
        "http://redis.io/docs?b=2&a=1",
    ]
    for url in urls:
        print(f"  {url}")
        print(f"  → {normalize_url(url)}\n")

    print("[Crawl Scheduler — priority frontier]")
    sched = CrawlScheduler(capacity=10_000)
    sched.crawl_delay = 0.0
    sched.add_disallow("private.com", "/admin")
    urls_to_schedule = [
        ("https://redis.io/docs", 0.1),       # high priority
        ("https://redis.io/blog", 0.5),
        ("https://postgres.org/docs", 0.3),
        ("https://private.com/admin/panel", 0.0),  # blocked by robots
        ("https://redis.io/docs", 0.1),       # duplicate
    ]
    for url, pri in urls_to_schedule:
        added = sched.schedule(url, priority=pri)
        print(f"  {'SCHEDULED' if added else 'SKIPPED  '}: {url}")
    print(f"\n  Frontier size: {sched.frontier_size}")
    print("  Processing in priority order:")
    while sched.frontier_size > 0:
        job = sched.next_job()
        if job:
            print(f"    → {job.url}")


if __name__ == "__main__":
    demo()
    print("\n\nRUNNING TESTS\n" + "=" * 60)
    unittest.main(verbosity=2, exit=False)