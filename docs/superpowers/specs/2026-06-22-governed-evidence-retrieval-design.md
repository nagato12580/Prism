# Governed Evidence Retrieval Design

## Background

The current Prism governed knowledge chain has a clear architectural idea:
Canonical Knowledge Points (CKPs) represent stable, normalized knowledge, while
Personal Knowledge Units (PKUs) and document chunks provide evidence. This is a
good governance model, but the current query path is still too shallow for
retrieval evaluation and fine-grained question answering.

The existing `governed_ckp_pku` retrieval path works roughly as follows:

1. Parse the user query into simple lexical terms.
2. Load the most recently updated CKPs, capped at `max(limit * 8, 80)`.
3. Concatenate linked PKU statements for those CKPs.
4. Score CKPs by substring matches across CKP fields and linked PKU text.
5. For each selected CKP, return up to 12 linked PKUs ordered by link confidence
   and creation time.

This means the chain does not currently perform query-time vector retrieval over
CKPs, does not search all CKPs, and does not rerank linked PKUs according to the
query. It also returns parent chunk evidence when PKUs are attached to parent
chunks, while the current golden retrieval dataset marks relevant child chunks.

The goal is to preserve the value of the CKP/PKU governance layer while adding a
dedicated evidence retrieval mode that can support offline retrieval metrics and
fine-grained RAG answers.

## Product Direction

Use a dual-mode design:

- `governed_ckp_pku`: the existing semantic governance mode. It remains focused
  on stable knowledge points, synthesis, memory-like recall, and cross-source
  understanding.
- `governed_evidence`: a new evidence retrieval mode. It is optimized for
  evidence recall, benchmark evaluation, and question answering over uploaded
  documents.

The first implementation phase will use the conservative strategy:

1. Add query-time CKP vector retrieval.
2. Fuse CKP vector candidates with lexical CKP candidates.
3. Rerank linked PKUs with query-aware scoring.
4. Expand parent chunk evidence into child chunks for evaluation and answer
   grounding.

The first phase will not directly mix traditional hybrid chunk search into the
new chain. This keeps the evaluation clean: any improvement in
`governed_evidence` should come from the CKP/PKU chain itself, not from copying
the traditional RAG baseline.

## Design Principles

### CKP Is Not A Chunk

CKPs should not be treated as another chunk index. A CKP is a normalized
knowledge point: it is useful because it groups semantically equivalent or
related PKUs and provides a stable concept-level handle. The evidence layer
should use CKP to route toward relevant PKUs and chunks, but answers should still
be grounded in PKU evidence and original document chunks.

### Candidate Recall Must Be Broad

The current "latest 80 CKPs" candidate strategy is brittle. A correct CKP may be
old, and a fine-grained query may not share lexical terms with the CKP title.
The improved pipeline must retrieve CKPs by query semantics across the whole CKP
vector collection, then combine those candidates with lexical candidates.

### Evidence Ranking Must Be Query-Aware

A CKP can have many linked PKUs. Returning PKUs by link confidence is useful for
governance quality, but it is not enough for retrieval. The evidence selected
for a question should be ranked by how well the PKU statement and evidence span
match the query, while still respecting CKP score and link confidence.

### Evaluation Must Match Evidence Granularity

The current golden dataset is child-chunk based. CKP/PKU extraction for uploaded
documents currently attaches PKUs to parent chunks. Therefore, evidence retrieval
must expose parent-to-child expansion explicitly. This avoids incorrectly
penalizing a chain for returning the right parent evidence while the metric is
checking child chunk IDs.

## Phase 1 Architecture

### Query Flow

```text
query
  -> query term extraction
  -> CKP vector recall
  -> CKP lexical recall
  -> CKP candidate fusion
  -> linked PKU query-aware rerank
  -> source evidence backtracking
  -> parent-child evidence expansion
  -> governed_evidence results
```

### CKP Vector Recall

The project already has a dedicated CKP vector collection named `prism_ckp` and
a `search_ckp_vectors()` service. Phase 1 will use that service during query
time:

- Input: raw user query.
- Filter: `user_id == "default-user"`.
- Candidate size: larger than final top-k, for example `max(limit * 8, 50)`.
- Output: CKP IDs with vector similarity scores.

Failures in CKP vector retrieval should degrade gracefully to lexical CKP
retrieval. The chain should still work if Milvus or the embedding provider is
temporarily unavailable.

### CKP Lexical Recall

The existing lexical scoring should be kept as a fallback and a complementary
signal. However, it should not be limited to the latest 80 rows as the only
candidate path.

Phase 1 can use a practical lexical candidate strategy:

- Search CKP fields such as title, canonical statement, summary, aliases,
  concepts, and keywords with the existing query terms.
- Include linked PKU text for scoring when available.
- Return a bounded lexical candidate set, for example the top 50 to 100 CKPs by
  lexical score.

This keeps implementation cost low while removing the most important weakness:
candidate recall no longer depends only on recency.

### CKP Fusion

Vector candidates and lexical candidates should be fused into a single CKP
ranking. The recommended first version is weighted Reciprocal Rank Fusion:

```text
score =
  vector_weight / (rrf_k + vector_rank + 1)
  + lexical_weight / (rrf_k + lexical_rank + 1)
  + small confidence boost
```

Suggested defaults:

- `rrf_k = 60`
- `vector_weight = 0.6`
- `lexical_weight = 0.4`

The output should preserve explainability metadata:

- vector rank and score
- lexical rank and score
- matched terms
- match reasons
- final fused score

### PKU Query-Aware Reranking

After CKP candidates are selected, linked PKUs should be reranked for the current
query. A PKU evidence score should combine:

- PKU text match score across `statement`, `normalized_statement`,
  `evidence_span`, `keywords`, `concepts`, and entities.
- Parent CKP fused score.
- `PKUCanonicalLink.confidence`.
- `PersonalKnowledgeUnit.confidence`.

Suggested first formula:

```text
pku_evidence_score =
  0.50 * normalized_pku_text_score
  + 0.25 * normalized_ckp_fused_score
  + 0.15 * link_confidence
  + 0.10 * pku_confidence
```

The final bundle should include the top linked PKUs after reranking. The
hard-coded limit of 12 can remain as a default, but the implementation should
make it easy to tune for evaluation.

### Evidence Backtracking

For each reranked PKU:

- If the PKU source is `document_chunk`, return the source chunk as evidence.
- If the source chunk is a parent chunk, also fetch its child chunks ordered by
  chunk index.
- If the PKU source is a personal asset item or asset unit, preserve the
  existing source behavior.

The evidence object should distinguish:

- `raw_sources`: sources directly linked from PKUs.
- `expanded_sources`: child chunk evidence expanded from parent chunks.

The existing agent citation behavior can continue using `raw_sources`. The
evaluation path can use `expanded_sources` to match child-level golden labels.

## Evaluation Plan

The retrieval comparison script should evaluate three chains:

```text
traditional_hybrid
governed_ckp_pku
governed_evidence
```

The primary dataset for Phase 1 is:

```text
evaluation/datasets/formal_docs_v1.json
```

The Phase 1 target is:

- `governed_evidence` Expanded Hit@10 >= 60%.
- `governed_evidence` Expanded Recall@10 >= 45%.

The evaluation output should be written under the existing independent
evaluation workspace:

```text
evaluation/runs/retrieval/<timestamp>_compare/
```

The run should preserve:

- `summary.json`
- `detailed_exact.csv`
- `detailed_expanded.csv`

The summary should show all three chains side by side.

## Phase 2 Roadmap

Phase 2 should improve semantic coverage rather than only tune ranking weights.

### PKU Reverse Recall

Add a PKU-first candidate path:

```text
query -> PKU lexical/vector search -> linked CKP -> CKP fusion
```

This is important for fine-grained questions where the user wording appears in
the original evidence but not in the CKP title or summary.

### CKP Embedding Text Upgrade

The current CKP vector text uses title, canonical statement, summary, keywords,
and concepts. A better CKP embedding text should include:

- aliases
- domains
- representative PKU statements
- representative evidence spans
- possible question-like expressions

This makes CKP vector retrieval match how users ask, not only how the system
summarizes knowledge.

### Graph Neighbor Expansion

Use CKP relations and PKU relations to expand near-neighbor knowledge points
after the initial recall step. This should be a controlled boost rather than an
unbounded graph walk.

### Query Rewrite Or HyDE

For abstract or underspecified user questions, generate one or more retrieval
queries before CKP/PKU recall. This should be benchmarked carefully because it
can improve recall but may also introduce query drift.

### Reranker

If lexical and vector fusion plateau, add a cross-encoder reranker or LLM judge
reranker for CKP/PKU evidence pairs. This should be optional and separately
measured because it adds latency and cost.

## Non-Goals

Phase 1 will not:

- Change CKP or PKU extraction prompts.
- Rebuild the golden dataset.
- Directly merge traditional hybrid chunk hits into `governed_evidence`.
- Replace the existing `governed_ckp_pku` behavior used by the agent.
- Add online evaluation or LLM-as-a-judge benchmark infrastructure.

Those are valid future tasks, but they should not be mixed with the first
retrieval-chain optimization.

## Testing Strategy

Unit tests should cover:

- CKP vector hits are included in query-time CKP candidates.
- Lexical CKP candidates still work when vector search fails.
- CKP fusion combines vector and lexical candidates deterministically.
- PKUs are reranked by query relevance instead of only link confidence.
- Parent chunk evidence expands to ordered child chunks.
- The comparison evaluator can run the new `governed_evidence` chain.

Integration verification should run:

```powershell
python -m pytest engine\tests\test_compare_retrieval_chains.py engine\tests\test_governed_knowledge_search.py
python -m engine.eval.compare_retrieval_chains --dataset evaluation/datasets/formal_docs_v1.json --chains traditional governed governed_evidence --verbose
```

The final report should include:

- before/after metrics for `governed_ckp_pku` and `governed_evidence`
- top failure categories
- notes on whether the Phase 1 targets were met

## Open Decisions

The current approved direction is:

- Architecture: dual-mode `governed_ckp_pku` plus `governed_evidence`.
- Phase 1 implementation strategy: conservative CKP/PKU-native optimization.
- Phase 1 success target: Expanded Hit@10 >= 60% and Expanded Recall@10 >= 45%.

The exact weighting constants may be tuned during implementation, but any tuning
should be documented in the evaluation output.
