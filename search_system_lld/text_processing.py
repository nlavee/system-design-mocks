"""
=============================================================================
05 — TEXT PROCESSING PIPELINE
=============================================================================
PRIORITY: #5 for exa.ai — everything feeds through this before indexing.

WHAT TO MASTER:
  - Why character/word tokenization fails for NLP at scale
  - Byte-Pair Encoding (BPE): the tokenization algorithm behind GPT
  - WordPiece: BERT's tokenization variant
  - Text normalization: Unicode, case, accents, punctuation
  - Stop word removal and stemming tradeoffs
  - Query-time vs index-time analysis symmetry (critical gotcha)
  - Tokenization's effect on embedding quality

EXA.AI ANGLE:
  Exa feeds web text through a tokenizer before embedding. The tokenizer
  choice directly affects what semantic signals the model captures.
  Mismatched tokenization between index-time and query-time is a subtle
  bug that degrades recall — understanding this in depth signals seniority.

KEY INSIGHT:
  BPE/WordPiece solve the OOV (out-of-vocabulary) problem by splitting
  unknown words into known subword units. "unindexable" → ["un", "##index",
  "##able"]. This ensures every string gets a meaningful representation.
=============================================================================
"""

import re
import unicodedata
import unittest
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional


# =============================================================================
# TEXT NORMALIZATION
# =============================================================================
#
# ORDER MATTERS: normalize before tokenizing, not after.
# Typical pipeline: unicode_normalize → lowercase → accent_strip → tokenize
#
# UNICODE NORMALIZATION FORMS:
#   NFC : canonical decomposition, then canonical composition
#         "é" → "é" (single char). Preferred for storage.
#   NFD : canonical decomposition
#         "é" → "e" + combining accent. Useful before accent stripping.
#   NFKC: compatibility decomposition + composition
#         "ﬁ" (ligature) → "fi". Good for search normalization.
#
# INTERVIEW TIP: Inconsistent normalization between index and query time
# is a subtle but impactful bug. If you NFC-normalize at index time but
# not at query time, "café" might not match "café" due to Unicode encoding.

def unicode_normalize(text: str, form: str = "NFKC") -> str:
    """
    Normalize Unicode characters.
    NFKC handles ligatures, full-width chars, etc.
    """
    return unicodedata.normalize(form, text)

def strip_accents(text: str) -> str:
    """
    Remove combining diacritics (accents) after NFD decomposition.
    "café" → "cafe", "naïve" → "naive"
    Improves recall for queries without accents matching accented text.
    """
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")

def normalize_whitespace(text: str) -> str:
    """Collapse multiple spaces/newlines/tabs into single space."""
    return re.sub(r"\s+", " ", text).strip()

def remove_html(text: str) -> str:
    """Strip HTML tags. Critical for web-crawled content (exa.ai use case)."""
    clean = re.sub(r"<[^>]+>", " ", text)
    # Decode common HTML entities
    entities = {"&amp;": "&", "&lt;": "<", "&gt;": ">",
                "&quot;": '"', "&#39;": "'", "&nbsp;": " "}
    for entity, char in entities.items():
        clean = clean.replace(entity, char)
    return normalize_whitespace(clean)

def full_normalize(text: str) -> str:
    """Full normalization pipeline for web text."""
    text = remove_html(text)
    text = unicode_normalize(text)
    text = normalize_whitespace(text)
    return text.lower()


# =============================================================================
# STOP WORDS
# =============================================================================
#
# TRADEOFF: removing stop words reduces index size but hurts phrase queries.
# "to be or not to be" → all stop words removed → unsearchable.
# "the who" (band) → "who" is a stop word in naive lists → bad.
#
# MODERN PRACTICE: don't remove stop words for dense/embedding retrieval.
# For BM25, IDF naturally down-weights common words — stop word removal
# is less critical but still reduces index size.

STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "and", "or", "but", "if", "as", "it", "its", "this", "that", "these",
    "those", "i", "you", "he", "she", "we", "they", "what", "which", "who",
    "not", "no", "nor",
}

def remove_stop_words(tokens: list[str]) -> list[str]:
    return [t for t in tokens if t not in STOP_WORDS]


# =============================================================================
# PORTER STEMMER (simplified)
# =============================================================================
#
# Stemming: reduce inflected words to their stem.
# "running" → "run", "indexed" → "index", "faster" → "fast"
#
# TRADEOFF: improves recall (more matches) but hurts precision
# ("university" and "universe" both stem to "univers" → false matches).
#
# ALTERNATIVES:
#   Lemmatization: "better" → "good" (uses vocabulary, more accurate)
#   Stemming: "better" → "bet" (purely rule-based, faster)
#
# For modern neural search, neither is used — the embedding model handles
# morphological variation. Stemming is a BM25/sparse-index optimization.

class PorterStemmer:
    """
    Simplified Porter stemmer (handles common English suffixes).
    Full implementation: nltk.stem.PorterStemmer
    """

    def stem(self, word: str) -> str:
        if len(word) <= 3:
            return word
        word = self._step1(word)
        word = self._step2(word)
        return word

    def _step1(self, word: str) -> str:
        """Remove common suffixes."""
        rules = [
            ("ational", "ate"), ("tional", "tion"), ("enci", "ence"),
            ("anci", "ance"), ("izer", "ize"), ("ising", "ise"),
            ("izing", "ize"), ("ation", "ate"), ("ator", "ate"),
            ("alism", "al"), ("ness", ""), ("ment", ""),
            ("ing", ""), ("ies", "i"), ("ed", ""),
            ("er", ""), ("ly", ""), ("s", ""),
        ]
        for suffix, replacement in rules:
            if word.endswith(suffix) and len(word) - len(suffix) > 2:
                return word[:-len(suffix)] + replacement
        return word

    def _step2(self, word: str) -> str:
        """Normalize remaining endings."""
        for suffix in ("iate", "ional", "ous", "ive", "ful", "al"):
            if word.endswith(suffix) and len(word) - len(suffix) > 3:
                return word[:-len(suffix)]
        return word


# =============================================================================
# BYTE-PAIR ENCODING (BPE)
# =============================================================================
#
# ALGORITHM (Sennrich et al., 2016)
# ──────────────────────────────────
# 1. Start with character-level vocabulary (every char is a token)
# 2. Count all adjacent symbol pairs in the training corpus
# 3. Merge the most frequent pair into a new symbol
# 4. Repeat steps 2-3 for n_merges iterations
# 5. The resulting vocabulary is used to tokenize new text
#
# EXAMPLE:
#   Corpus: "low low low new new newest"
#   Characters: l,o,w, ,n,e,w, ...
#   Merge 1: "lo" (most frequent pair) → vocabulary gains "lo"
#   Merge 2: "low" → vocabulary gains "low"
#   etc.
#
# WHY BPE:
#   - No OOV: any string can be tokenized (fall back to chars)
#   - Common words get single tokens; rare words split into subwords
#   - Language-agnostic: works on any script
#   - "unindexable" → ["un", "index", "able"] or ["unindexa", "ble"] etc.
#     depending on training corpus
#
# TOKENIZER VARIANTS:
#   BPE (GPT, RoBERTa): merge frequency-based pairs
#   WordPiece (BERT): choose merges that maximize LM likelihood
#   SentencePiece (T5, LLaMA): treats input as raw bytes, no pre-tokenization
#   Unigram (XLNet): probabilistic model, can produce multiple tokenizations
#
# VOCABULARY SIZE TRADEOFFS:
#   Small vocab (8K):  more splits, longer sequences, more context needed
#   Large vocab (100K): fewer splits, shorter sequences, more embeddings
#   GPT-4: ~100K BPE tokens
#   BERT: 30K WordPiece tokens

@dataclass
class BPETokenizer:
    """
    Byte-Pair Encoding tokenizer trained from scratch.
    For production: use tokenizers library (HuggingFace) — Rust-backed, fast.
    """

    vocab_size: int = 500
    merges: list[tuple[str, str]] = None
    vocab: set[str] = None

    def __post_init__(self):
        self.merges = self.merges or []
        self.vocab  = self.vocab  or set()

    def _get_pairs(self, word: list[str]) -> dict[tuple[str, str], int]:
        """Count adjacent symbol pairs in a tokenized word."""
        pairs: dict[tuple[str, str], int] = defaultdict(int)
        for i in range(len(word) - 1):
            pairs[(word[i], word[i + 1])] += 1
        return pairs

    def fit(self, texts: list[str], n_merges: int = 100):
        """
        Train BPE on a corpus.
        1. Initialize with character-level words (split into chars)
        2. Iteratively merge the most frequent pair
        """
        # Pre-tokenize: split on whitespace, add end-of-word marker
        word_freqs: dict[str, int] = defaultdict(int)
        for text in texts:
            for word in text.lower().split():
                word_freqs[word + "</w>"] += 1

        # Initialize vocabulary with all characters
        vocab: dict[str, list[str]] = {}
        for word in word_freqs:
            vocab[word] = list(word)  # split into characters
            self.vocab.update(vocab[word])

        self.merges = []
        for _ in range(n_merges):
            # Count all pair frequencies across all words
            pair_freqs: dict[tuple[str, str], int] = defaultdict(int)
            for word, symbols in vocab.items():
                freq = word_freqs[word]
                for pair, count in self._get_pairs(symbols).items():
                    pair_freqs[pair] += count * freq

            if not pair_freqs:
                break

            # Find and apply the most frequent merge
            best_pair = max(pair_freqs, key=pair_freqs.get)
            self.merges.append(best_pair)

            # Merge this pair in all words
            merged = best_pair[0] + best_pair[1]
            self.vocab.add(merged)
            new_vocab = {}
            for word, symbols in vocab.items():
                new_symbols = self._apply_merge(symbols, best_pair)
                new_vocab[word] = new_symbols
            vocab = new_vocab

    def _apply_merge(self, symbols: list[str], pair: tuple[str, str]) -> list[str]:
        """Apply a single merge rule to a symbol list."""
        result = []
        i = 0
        while i < len(symbols):
            if i < len(symbols) - 1 and (symbols[i], symbols[i+1]) == pair:
                result.append(symbols[i] + symbols[i+1])
                i += 2
            else:
                result.append(symbols[i])
                i += 1
        return result

    def tokenize(self, text: str) -> list[str]:
        """Apply learned BPE merges to tokenize new text."""
        tokens = []
        for word in text.lower().split():
            symbols = list(word + "</w>")
            for merge in self.merges:
                symbols = self._apply_merge(symbols, merge)
            tokens.extend(symbols)
        return tokens

    def encode(self, text: str) -> list[int]:
        """Convert text to token IDs (build vocab map first)."""
        vocab_list = sorted(self.vocab)
        vocab_map  = {v: i for i, v in enumerate(vocab_list)}
        return [vocab_map.get(t, vocab_map.get("<unk>", 0)) for t in self.tokenize(text)]


# =============================================================================
# WORDPIECE TOKENIZER (BERT-style)
# =============================================================================
#
# DIFFERENCE FROM BPE:
#   BPE: merge pairs that are most frequent in corpus
#   WordPiece: merge pairs that maximize LM likelihood (log P(corpus))
#
# KEY DIFFERENCE IN OUTPUT:
#   WordPiece prefixes continuation tokens with "##":
#     "playing" → ["play", "##ing"]
#   This signals which tokens are subword continuations vs word starts.
#   Important for BERT's position-aware attention.

class WordPieceTokenizer:
    """
    WordPiece tokenizer (simplified). Real: transformers.BertTokenizer.
    """

    def __init__(self, vocab: Optional[set[str]] = None):
        # A minimal hardcoded vocab for demonstration
        self.vocab = vocab or {
            "[UNK]", "[CLS]", "[SEP]", "[PAD]", "[MASK]",
            "redis", "cache", "distributed", "lock", "search",
            "index", "vector", "embedding", "query", "document",
            "neural", "rank", "score", "fast", "memory",
            "##ing", "##ed", "##er", "##s", "##ly",
            "##tion", "##al", "##ize", "##able",
            "un", "re", "pre",
        }
        # Add single characters as fallback
        self.vocab.update(set("abcdefghijklmnopqrstuvwxyz0123456789"))

    def tokenize_word(self, word: str) -> list[str]:
        """
        Greedy longest-match tokenization for a single word.
        Algorithm: find the longest prefix in vocab, then continue on suffix.
        """
        tokens = []
        start = 0
        is_first_subword = True

        while start < len(word):
            end = len(word)
            found = False

            while start < end:
                substr = word[start:end]
                if not is_first_subword:
                    substr = "##" + substr

                if substr in self.vocab:
                    tokens.append(substr)
                    start = end
                    is_first_subword = False
                    found = True
                    break
                end -= 1

            if not found:
                tokens.append("[UNK]")
                break

        return tokens if tokens else ["[UNK]"]

    def tokenize(self, text: str, add_special: bool = True) -> list[str]:
        """Full tokenization pipeline: normalize → split → wordpiece."""
        text = unicode_normalize(text).lower()
        words = re.findall(r"[a-z0-9]+", text)
        tokens = []
        if add_special:
            tokens.append("[CLS]")
        for word in words:
            tokens.extend(self.tokenize_word(word))
        if add_special:
            tokens.append("[SEP]")
        return tokens


# =============================================================================
# FULL TEXT ANALYSIS PIPELINE
# =============================================================================
#
# SYMMETRY REQUIREMENT (critical interview point)
# ────────────────────────────────────────────────
# Query-time and index-time analysis MUST be identical.
# If you stem at index time, you MUST stem at query time.
# If you do case-folding at index time, do it at query time.
# Mismatch → terms don't match → recall drops silently.
#
# This is one of the most common bugs in search systems.

class TextAnalysisPipeline:
    """
    Configurable analysis pipeline.
    Used at both index time AND query time — must be identical for both.
    """

    def __init__(
        self,
        lowercase:        bool = True,
        strip_accents:    bool = True,
        remove_stops:     bool = False,   # off by default — see tradeoff comment
        stem:             bool = False,   # off for neural; on for BM25 indexes
        unicode_form:     str  = "NFKC",
    ):
        self.lowercase     = lowercase
        self.strip_accents_ = strip_accents
        self.remove_stops  = remove_stops
        self.stem          = stem
        self.unicode_form  = unicode_form
        self._stemmer      = PorterStemmer() if stem else None

    def analyze(self, text: str) -> list[str]:
        """Full pipeline: normalize → tokenize → filter → transform."""
        # 1. HTML removal
        text = remove_html(text)
        # 2. Unicode normalization
        text = unicode_normalize(text, self.unicode_form)
        # 3. Accent stripping
        if self.strip_accents_:
            text = strip_accents(text)
        # 4. Lowercase
        if self.lowercase:
            text = text.lower()
        # 5. Tokenize
        tokens = re.findall(r"[a-z0-9]+", text)
        # 6. Stop word removal
        if self.remove_stops:
            tokens = remove_stop_words(tokens)
        # 7. Stemming
        if self.stem and self._stemmer:
            tokens = [self._stemmer.stem(t) for t in tokens]
        return tokens

    def analyze_for_embedding(self, text: str) -> str:
        """
        For embedding models: return clean text string, not token list.
        Don't stem or remove stop words — the model handles semantics.
        """
        text = remove_html(text)
        text = unicode_normalize(text, self.unicode_form)
        if self.strip_accents_:
            text = strip_accents(text)
        return normalize_whitespace(text.lower() if self.lowercase else text)


# =============================================================================
# TESTS
# =============================================================================

class TestNormalization(unittest.TestCase):
    def test_unicode_normalize(self):
        # NFKC normalizes ligature ﬁ → fi
        self.assertEqual(unicode_normalize("ﬁle", "NFKC"), "file")

    def test_strip_accents(self):
        self.assertEqual(strip_accents("café"), "cafe")
        self.assertEqual(strip_accents("naïve"), "naive")
        self.assertEqual(strip_accents("résumé"), "resume")

    def test_remove_html(self):
        self.assertEqual(remove_html("<b>hello</b> world"), "hello world")
        self.assertEqual(remove_html("a &amp; b"), "a & b")
        self.assertEqual(remove_html("<p>text<br/>more</p>"), "text more")

    def test_normalize_whitespace(self):
        self.assertEqual(normalize_whitespace("a  b\t\nc"), "a b c")


class TestBPETokenizer(unittest.TestCase):
    def setUp(self):
        corpus = [
            "redis is a cache system",
            "cache cache cache redis redis",
            "distributed lock redis system",
            "cache invalidation is hard",
        ] * 20
        self.bpe = BPETokenizer()
        self.bpe.fit(corpus, n_merges=30)

    def test_fit_creates_merges(self):
        self.assertGreater(len(self.bpe.merges), 0)

    def test_fit_creates_vocab(self):
        self.assertGreater(len(self.bpe.vocab), 5)

    def test_tokenize_returns_list(self):
        tokens = self.bpe.tokenize("redis cache")
        self.assertIsInstance(tokens, list)
        self.assertGreater(len(tokens), 0)

    def test_frequent_word_single_token(self):
        """Words frequent in training corpus should merge into single tokens."""
        tokens = self.bpe.tokenize("redis")
        # "redis" is frequent — should be a single token or at least a small number
        self.assertLessEqual(len(tokens), 6)  # at most 6 chars (r,e,d,i,s,</w>)

    def test_end_of_word_marker(self):
        """Tokenization should include end-of-word markers."""
        tokens = self.bpe.tokenize("cache")
        merged = "".join(tokens)
        self.assertIn("</w>", merged)


class TestWordPieceTokenizer(unittest.TestCase):
    def setUp(self):
        self.wp = WordPieceTokenizer()

    def test_special_tokens(self):
        tokens = self.wp.tokenize("redis cache", add_special=True)
        self.assertEqual(tokens[0], "[CLS]")
        self.assertEqual(tokens[-1], "[SEP]")

    def test_known_word_no_split(self):
        tokens = self.wp.tokenize("redis", add_special=False)
        self.assertIn("redis", tokens)

    def test_unknown_word_splits_to_chars(self):
        # "xyz" not in vocab → splits to characters or [UNK]
        tokens = self.wp.tokenize("xyz", add_special=False)
        self.assertGreater(len(tokens), 0)

    def test_suffix_marking(self):
        # Add a word that needs suffix splitting
        tokens = self.wp.tokenize("indexing", add_special=False)
        # Should contain "index" and "##ing"
        self.assertIn("index", tokens)
        self.assertIn("##ing", tokens)


class TestPorterStemmer(unittest.TestCase):
    def setUp(self):
        self.s = PorterStemmer()

    def test_removes_ing(self):
        self.assertEqual(self.s.stem("indexing"), "index")

    def test_removes_ed(self):
        self.assertIn(self.s.stem("indexed"), ["index", "indexed"])

    def test_short_words_unchanged(self):
        self.assertEqual(self.s.stem("run"), "run")


class TestAnalysisPipeline(unittest.TestCase):
    def test_basic_analysis(self):
        p = TextAnalysisPipeline()
        tokens = p.analyze("Redis is FAST!")
        self.assertIn("redis", tokens)
        self.assertIn("fast", tokens)

    def test_html_stripped(self):
        p = TextAnalysisPipeline()
        tokens = p.analyze("<b>Redis</b> cache")
        self.assertIn("redis", tokens)
        self.assertNotIn("<b>redis</b>", tokens)

    def test_accent_stripped(self):
        p = TextAnalysisPipeline(strip_accents=True)
        tokens = p.analyze("café résumé")
        self.assertIn("cafe", tokens)
        self.assertIn("resume", tokens)

    def test_stop_word_removal(self):
        p = TextAnalysisPipeline(remove_stops=True)
        tokens = p.analyze("this is a test")
        self.assertNotIn("this", tokens)
        self.assertNotIn("is", tokens)
        self.assertIn("test", tokens)

    def test_pipeline_symmetry(self):
        """Index and query analysis must produce matching terms."""
        p = TextAnalysisPipeline(lowercase=True, strip_accents=True)
        index_tokens = set(p.analyze("Redis Café Naïve"))
        query_tokens = set(p.analyze("redis cafe naive"))
        # After normalization, they should match
        self.assertEqual(index_tokens, query_tokens)

    def test_embedding_analysis_preserves_text(self):
        p = TextAnalysisPipeline()
        result = p.analyze_for_embedding("<p>Redis is fast</p>")
        self.assertNotIn("<p>", result)
        self.assertIn("redis", result)
        self.assertIn("fast", result)


def demo():
    print("=" * 60)
    print("TEXT PROCESSING PIPELINE DEMO")
    print("=" * 60)

    print("\n[Unicode normalization]")
    examples = ["ﬁle", "café", "naïve", "résumé", "HELLO WORLD", "Hello\t\nWorld"]
    for text in examples:
        print(f"  '{text}' → '{full_normalize(text)}'")

    print("\n[HTML extraction (exa.ai crawled content)]")
    html = """<html><head><title>Redis Guide</title></head>
    <body><h1>Redis &amp; Caching</h1><p>Redis is <b>fast</b> &amp; reliable.</p>
    <script>alert('x')</script></body></html>"""
    print(f"  Input : {html[:80]}...")
    print(f"  Output: {remove_html(html)}")

    print("\n[BPE Training]")
    corpus = [
        "redis cache distributed lock pub sub streams",
        "index search query document embedding vector",
        "database table row column transaction",
    ] * 50
    bpe = BPETokenizer()
    bpe.fit(corpus, n_merges=50)
    print(f"  Vocabulary size: {len(bpe.vocab)}")
    print(f"  Merges learned:  {len(bpe.merges)}")
    for word in ["redis", "caching", "unindexable", "embeddings"]:
        tokens = bpe.tokenize(word)
        print(f"  '{word}' → {tokens}")

    print("\n[WordPiece (BERT-style)]")
    wp = WordPieceTokenizer()
    for text in ["redis indexing", "distributed caching", "unrecognizedword"]:
        tokens = wp.tokenize(text, add_special=True)
        print(f"  '{text}' → {tokens}")

    print("\n[Analysis Pipeline — symmetry demo]")
    pipeline = TextAnalysisPipeline(lowercase=True, strip_accents=True, remove_stops=False)
    doc   = "<b>Café Redis</b> is FAST and naïve users love it"
    query = "cafe redis fast"
    d_tokens = pipeline.analyze(doc)
    q_tokens = pipeline.analyze(query)
    overlap = set(d_tokens) & set(q_tokens)
    print(f"  Doc tokens   : {d_tokens}")
    print(f"  Query tokens : {q_tokens}")
    print(f"  Overlap      : {sorted(overlap)}")
    print(f"  Match works  : {len(overlap) > 0}")


if __name__ == "__main__":
    demo()
    print("\n\nRUNNING TESTS\n" + "=" * 60)
    unittest.main(verbosity=2, exit=False)