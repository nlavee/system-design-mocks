### Priority order 

| # | Script | Why exa.ai cares | The one thing to nail |
|---|---|---|---|
| 1 | **ANN Vector Search** | This IS their product primitive | ef_construction/ef_search tradeoff. HNSW vs IVF vs PQ memory math |
| 2 | **Hybrid Retrieval + RRF** | Sparse + dense fusion is their retrieval stack | Why you can't add BM25 + cosine scores directly. RRF works on ranks, not scores |
| 3 | **Re-ranking / Two-Tower** | Their quality moat over commodity search | Bi-encoder for recall, cross-encoder for precision. Why O(N) cross-encoder only works on small candidate sets |
| 4 | **Distributed Index** | They index the whole web, not one machine | Scatter-gather, consistent hashing with vnodes, NRT refresh cycle |
| 7 | **Crawling & Dedup** | They built their own crawler (major differentiator) | SimHash Hamming threshold, Bloom filter FP math, why `normalize_url` matters |
| 5 | **Text Processing** | Feeds every embedding they generate | **Symmetry**: index-time and query-time analysis MUST be identical |
| 6 | **Query Understanding** | "Search the way you think" is their tagline | HyDE (hypothetical document embeddings) is the most exa.ai-specific concept |

---

### The three answers that signal Staff-level vs Senior-level

**"How do you scale to 1B documents?"**
→ Shard by doc hash using consistent hashing → HNSW per shard (or IVF+PQ for memory) → scatter-gather with fetch_k=50 per shard → merge top-K at coordinator → cross-encoder re-rank final 20

**"Why does exa.ai outperform Google for research queries?"**
→ Google optimizes for BM25/PageRank which rewards keyword frequency and authority. Exa embeds semantic intent — "papers arguing against X" matches documents by *meaning*, not by whether those exact words appear. HyDE further improves this by generating a hypothetical answer and searching in "answer space"

**"How do you keep the index fresh?"**
→ Crawl priority queue weighted by domain authority + link freshness signals → NRT index buffer with 1s refresh cycle → SimHash dedup before indexing → separate "freshness score" feature in the ranker