# Governed Evidence Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `governed_evidence` retrieval mode that improves CKP/PKU evidence recall with query-time CKP vector retrieval, CKP lexical fusion, PKU query-aware reranking, and parent-child evidence expansion.

**Architecture:** Keep the existing `governed_ckp_pku` semantic governance path intact. Add reusable governed evidence helpers in `engine/app/agent/tools/governed_knowledge.py`, then expose them to `engine/eval/compare_retrieval_chains.py` as a third retrieval chain. Preserve graceful fallback when CKP vector search is unavailable.

**Tech Stack:** Python, SQLAlchemy ORM, existing Milvus CKP vector service (`backend.app.services.ckp_vectors.search_ckp_vectors`), pytest, existing retrieval evaluation workspace under `evaluation/runs/retrieval`.

---

### Task 1: Add Tests For CKP Vector Candidate Fusion

**Files:**
- Modify: `engine/tests/test_governed_knowledge_search.py`
- Modify: `engine/app/agent/tools/governed_knowledge.py`

- [ ] **Step 1: Write failing tests for vector recall and lexical fallback**

Append tests that prove `_query_governed_evidence()` can retrieve a CKP from vector hits even when lexical recency would miss it, and can still retrieve lexical CKPs when vector search fails.

```python
def test_governed_evidence_uses_ckp_vector_candidates(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    item = KnowledgeItem(title="Vector CKP evidence", content="Beam search keeps several candidate sequences.", source_type="manual", user_id="default-user")
    session.add(item)
    session.flush()
    parent = KnowledgeChunk(item_id=item.id, chunk_text="Beam search keeps several candidate sequences.", chunk_type="parent")
    child = KnowledgeChunk(item_id=item.id, parent_id=parent.id, chunk_text="Beam search keeps several candidate sequences.", chunk_type="child", chunk_index=0)
    ckp = CanonicalKnowledgePoint(
        title="Sequence decoding strategy",
        canonical_type="topic",
        canonical_statement="Decoding strategies maintain candidate sequences.",
        summary="Beam search evidence.",
        keywords=["decoding"],
        concepts=["sequence"],
        user_id="default-user",
        confidence=0.9,
    )
    session.add_all([parent, child, ckp])
    session.flush()
    pku = PersonalKnowledgeUnit(
        source_kind="document_chunk",
        source_id=parent.id,
        unit_type="claim",
        statement="Beam search keeps several candidate sequences.",
        normalized_statement="beam search keeps several candidate sequences",
        normalized_statement_hash="beam-search-hash",
        evidence_span="Beam search keeps several candidate sequences.",
        keywords=["beam", "search"],
        user_id="default-user",
        confidence=0.8,
    )
    session.add(pku)
    session.flush()
    session.add(PKUCanonicalLink(pku_id=pku.id, canonical_id=ckp.id, relation_type="about", role="evidence", confidence=0.7, user_id="default-user"))
    session.commit()
    session.close()

    monkeypatch.setattr(governed_tool, "_Session", Session)
    monkeypatch.setattr(governed_tool, "search_ckp_vectors", lambda **kwargs: [{"ckp_id": ckp.id, "score": 0.92}])

    _terms, bundles, _knowledge = governed_tool._query_governed_evidence("beam search candidates", limit=5)

    assert bundles[0]["canonical_id"] == ckp.id
    assert bundles[0]["retrieval_mode"] == "governed_evidence"
    assert bundles[0]["raw_sources"][0]["chunk_id"] == parent.id
    assert bundles[0]["expanded_sources"][0]["chunk_id"] == child.id
```

Add a second test:

```python
def test_governed_evidence_falls_back_to_lexical_when_vector_search_fails(monkeypatch):
    # Build one CKP whose title and PKU text match "metadata filter".
    # Monkeypatch search_ckp_vectors to raise RuntimeError("milvus down").
    # Assert _query_governed_evidence("metadata filter", limit=5) returns that CKP.
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```powershell
python -m pytest engine\tests\test_governed_knowledge_search.py::test_governed_evidence_uses_ckp_vector_candidates engine\tests\test_governed_knowledge_search.py::test_governed_evidence_falls_back_to_lexical_when_vector_search_fails -v
```

Expected: tests fail because `_query_governed_evidence` and `search_ckp_vectors` import usage are not implemented in `governed_knowledge.py`.

- [ ] **Step 3: Implement minimal CKP vector candidate fusion**

In `engine/app/agent/tools/governed_knowledge.py`:

1. Import `search_ckp_vectors`.
2. Add constants for governed evidence fusion weights.
3. Add `_safe_search_ckp_vectors(query, limit)`.
4. Add `_lexical_ckp_candidates(db, terms, limit)`.
5. Add `_fuse_ckp_candidates(vector_hits, lexical_hits, db, limit)`.
6. Add `_query_governed_evidence(query, limit)`.

The implementation must:

- Catch vector search exceptions and continue.
- Avoid the old "latest 80 only" path for evidence mode.
- Preserve matched terms and match reasons from lexical scoring.
- Return the same tuple shape as `_query_governed_knowledge`: `(terms, bundles, knowledge_results)`.

- [ ] **Step 4: Run tests and confirm pass**

Run:

```powershell
python -m pytest engine\tests\test_governed_knowledge_search.py::test_governed_evidence_uses_ckp_vector_candidates engine\tests\test_governed_knowledge_search.py::test_governed_evidence_falls_back_to_lexical_when_vector_search_fails -v
```

Expected: both tests pass.

### Task 2: Add PKU Query-Aware Reranking And Parent-Child Expansion

**Files:**
- Modify: `engine/tests/test_governed_knowledge_search.py`
- Modify: `engine/app/agent/tools/governed_knowledge.py`

- [ ] **Step 1: Write failing tests for PKU reranking and expanded sources**

Add a test where a CKP links to two PKUs: one high link confidence but irrelevant to the query, and one lower link confidence but query-relevant. Assert the query-relevant PKU is first in `linked_pkus` and its source is first in `raw_sources`.

```python
def test_governed_evidence_reranks_linked_pkus_by_query_relevance(monkeypatch):
    # Build one CKP linked to:
    # - PKU A: confidence 0.95, statement "General coding guideline."
    # - PKU B: confidence 0.60, statement "Database table storage engine must use InnoDB."
    # Query "database storage engine innodb".
    # Assert PKU B appears before PKU A.
```

Add a parent-child expansion assertion:

```python
assert bundle["expanded_sources"][0]["source_kind"] == "document_chunk"
assert bundle["expanded_sources"][0]["chunk_type"] == "child"
assert bundle["expanded_sources"][0]["parent_chunk_id"] == parent.id
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```powershell
python -m pytest engine\tests\test_governed_knowledge_search.py::test_governed_evidence_reranks_linked_pkus_by_query_relevance -v
```

Expected: fails because `_build_evidence_bundle` still orders links by confidence and does not return `expanded_sources`.

- [ ] **Step 3: Implement query-aware PKU reranking**

In `governed_knowledge.py`:

1. Add `_pku_fields(pku)`.
2. Add `_score_pku_evidence(pku, terms, ckp_score, link_confidence)`.
3. Add `_expanded_sources_for_source(db, source)`.
4. Update evidence mode to call a new `_build_evidence_bundle(..., query_terms=terms, evidence_mode=True)` path.

Keep the existing semantic mode behavior stable by default:

```python
def _build_evidence_bundle(db, ckp, score, matched_terms, reasons, *, query_terms=None, evidence_mode=False):
    if evidence_mode:
        # query-aware PKU reranking and expanded_sources
    else:
        # existing confidence ordering
```

- [ ] **Step 4: Run tests and confirm pass**

Run:

```powershell
python -m pytest engine\tests\test_governed_knowledge_search.py::test_governed_evidence_reranks_linked_pkus_by_query_relevance -v
```

Expected: test passes.

### Task 3: Add `governed_evidence` To Retrieval Evaluation

**Files:**
- Modify: `engine/tests/test_compare_retrieval_chains.py`
- Modify: `engine/eval/compare_retrieval_chains.py`

- [ ] **Step 1: Write failing evaluator tests**

Add tests:

```python
def test_chain_map_supports_governed_evidence():
    assert "governed_evidence" in eval_compare._chain_map()
```

```python
def test_governed_evidence_prefers_expanded_sources(monkeypatch):
    monkeypatch.setattr(
        eval_compare,
        "_query_governed_evidence",
        lambda query, limit: (
            [],
            [{
                "canonical_id": "ckp-1",
                "title": "Test CKP",
                "score": 1.0,
                "raw_sources": [{"source_kind": "document_chunk", "chunk_id": "parent-1", "item_id": "item-1", "score": 0.8}],
                "expanded_sources": [{"source_kind": "document_chunk", "chunk_id": "child-1", "item_id": "item-1", "score": 0.9}],
            }],
            [],
        ),
    )

    hits = eval_compare._governed_evidence("question", 10)

    assert hits[0]["chunk_id"] == "child-1"
    assert hits[0]["source"] == "governed_evidence"
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```powershell
python -m pytest engine\tests\test_compare_retrieval_chains.py::test_chain_map_supports_governed_evidence engine\tests\test_compare_retrieval_chains.py::test_governed_evidence_prefers_expanded_sources -v
```

Expected: fails because evaluator only accepts `traditional` and `governed`.

- [ ] **Step 3: Implement evaluator chain**

In `compare_retrieval_chains.py`:

1. Import `_query_governed_evidence`.
2. Add `_governed_evidence(query, top_k)`.
3. Prefer bundle `expanded_sources`, falling back to `raw_sources`.
4. Add `_chain_map()` returning all three chains.
5. Extend CLI choices to `["traditional", "governed", "governed_evidence"]`.
6. Add governed evidence parameter metadata to `summary.json`.

- [ ] **Step 4: Run evaluator tests and confirm pass**

Run:

```powershell
python -m pytest engine\tests\test_compare_retrieval_chains.py -v
```

Expected: all evaluator tests pass.

### Task 4: Run Full Verification And Offline Evaluation

**Files:**
- Read: `evaluation/datasets/formal_docs_v1.json`
- Create: `evaluation/runs/retrieval/<timestamp>_compare/`

- [ ] **Step 1: Run targeted unit tests**

Run:

```powershell
python -m pytest engine\tests\test_governed_knowledge_search.py engine\tests\test_compare_retrieval_chains.py engine\tests\test_generate_queries_cli.py -v
```

Expected: all tests pass.

- [ ] **Step 2: Compile modified modules**

Run:

```powershell
python -m py_compile engine\app\agent\tools\governed_knowledge.py engine\eval\compare_retrieval_chains.py
```

Expected: command exits with code 0.

- [ ] **Step 3: Run three-chain retrieval evaluation**

Run:

```powershell
python -m engine.eval.compare_retrieval_chains --dataset evaluation/datasets/formal_docs_v1.json --chains traditional governed governed_evidence --verbose
```

Expected: evaluation writes `summary.json`, `detailed_exact.csv`, `detailed_expanded.csv`, and `detailed_verbose.json` under a new timestamped folder.

- [ ] **Step 4: Inspect result summary**

Read the new `summary.json` and record:

- `traditional_hybrid` exact and expanded metrics.
- `governed_ckp_pku` exact and expanded metrics.
- `governed_evidence` exact and expanded metrics.
- Whether Phase 1 targets were met.

### Task 5: Write Learning Report

**Files:**
- Create: `evaluation/runs/retrieval/<timestamp>_compare/governed_evidence_report.md`
- Modify if useful: `evaluation/README.md`

- [ ] **Step 1: Write the run report**

Create a report in the run folder with:

- What changed in the retrieval chain.
- Why CKP vector recall helps.
- Why PKU reranking helps.
- Why parent-child expansion is necessary.
- Before/after metrics.
- Failure categories.
- Next phase recommendations.

- [ ] **Step 2: Link the latest run from evaluation README**

If `evaluation/README.md` already has a retrieval run section, add the latest run path and a short note. If it does not, add a compact "Latest retrieval run" section.

- [ ] **Step 3: Final status**

Report to the user:

- Files changed.
- Tests run.
- Evaluation run path.
- Metrics for all chains.
- Whether Phase 1 targets were met.
- What Phase 2 should tackle next.
