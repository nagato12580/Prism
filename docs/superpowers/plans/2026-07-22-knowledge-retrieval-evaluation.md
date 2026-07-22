# Knowledge Retrieval, Evidence, and Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Prism's double-fusion/hidden-failure retrieval with one scoped Dense/BM25/Graph fusion, text-based Rerank, stable Evidence, working deep-search controls, and reproducible RAG evaluation/mindmap/question generation.

**Architecture:** Each retrieval channel returns a typed health/result object. One orchestrator applies Weighted RRF, loads child text, reranks, expands parent context, and returns Evidence; evaluations snapshot all models/config/generations.

**Tech Stack:** Python, Pydantic 2, MySQL, Milvus, Elasticsearch, Neo4j, OpenAI-compatible embedding/rerank/LLM APIs, pytest

---

## Prerequisite

Complete Foundation and Ingestion plans. Queries require `SearchScope(tenant_id, kb_uid, index_generation, graph_generation, file_uids, source_types)` and active generation state.

## File Structure

- Create: `engine/app/retrieval/contracts.py` — channel health, scope, candidate, final status.
- Modify: `engine/app/retrieval/vector_search.py` — native scoped Dense channel.
- Modify: `engine/app/retrieval/es_search.py` — scoped BM25 and honest failures.
- Modify: `engine/app/retrieval/graph_expand.py` — scoped Graph channel.
- Replace internals: `engine/app/retrieval/unified.py` — one Weighted RRF.
- Deprecate production fallback: `engine/app/retrieval/bm25_search.py` — test/dev only.
- Modify: `engine/app/retrieval/rerank.py` — text input, score/length validation.
- Modify: `engine/app/chat/answer.py` — child load before rerank, parent expansion after.
- Modify: `engine/app/agent/rag/agentic.py` — distinct rewrites and cumulative Evidence.
- Modify: `engine/app/agent/tools/deep_knowledge_search.py` — pass depth/limit/iterations.
- Create: `engine/app/retrieval/evidence.py` — canonical Evidence DTO.
- Create: `engine/app/api/retrieval.py` — private retrieval endpoint.
- Create: `backend/app/api/knowledge_retrieval.py` — authorized public query/test/config.
- Create: `backend/app/models/knowledge_evaluation.py`
- Create: `backend/alembic/versions/20260722_02_knowledge_evaluation.py` — evaluation dataset/run tables and indexes.
- Create: `backend/app/api/knowledge_evaluation.py`
- Create: `engine/app/evaluation/metrics.py`
- Create: `engine/app/evaluation/runner.py`
- Create: `engine/app/knowledge/enrichment.py` — mindmap/sample questions/export payloads.
- Create/modify tests listed below.

## Task 1: Define Typed Channel Health and Scope

**Files:**
- Create: `engine/app/retrieval/contracts.py`
- Create: `engine/tests/test_retrieval_contracts.py`

- [ ] **Step 1: Write failing contract tests**

```python
def test_search_scope_requires_tenant_kb_and_generation():
    from pydantic import ValidationError
    from engine.app.retrieval.contracts import SearchScope

    try:
        SearchScope(tenant_id="t", kb_uid="k", index_generation="")
    except ValidationError:
        pass
    else:
        raise AssertionError("empty generation accepted")


def test_failed_channel_is_not_no_hits():
    from engine.app.retrieval.contracts import ChannelResult

    failed = ChannelResult.failed("dense", "VECTOR_INDEX_UNAVAILABLE", retryable=True)
    empty = ChannelResult.ok("dense", [])
    assert failed.health == "failed"
    assert empty.health == "ok" and empty.candidates == []
```

- [ ] **Step 2: Run and confirm missing contract**

Run: `python -m pytest engine/tests/test_retrieval_contracts.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement the contract**

```python
# engine/app/retrieval/contracts.py
from typing import Literal
from pydantic import BaseModel, Field


class SearchScope(BaseModel):
    tenant_id: str = Field(min_length=1)
    kb_uid: str = Field(min_length=1)
    index_generation: str = Field(min_length=1)
    graph_generation: str | None = None
    file_uids: tuple[str, ...] = ()
    source_types: tuple[str, ...] = ()


class Candidate(BaseModel):
    chunk_uid: str
    item_id: str
    file_uid: str
    channel: Literal["dense", "bm25", "graph"]
    raw_score: float
    raw_rank: int
    metadata: dict = Field(default_factory=dict)


class ChannelProblem(BaseModel):
    code: str
    message: str = ""
    retryable: bool = False


class ChannelResult(BaseModel):
    channel: str
    health: Literal["ok", "degraded", "failed"]
    candidates: list[Candidate] = Field(default_factory=list)
    elapsed_ms: int = 0
    problem: ChannelProblem | None = None

    @classmethod
    def ok(cls, channel: str, candidates: list[Candidate]):
        return cls(channel=channel, health="ok", candidates=candidates)

    @classmethod
    def failed(cls, channel: str, code: str, retryable: bool):
        return cls(channel=channel, health="failed", problem=ChannelProblem(code=code, retryable=retryable))
```

- [ ] **Step 4: Run and commit**

```bash
python -m pytest engine/tests/test_retrieval_contracts.py -v
git add engine/app/retrieval/contracts.py engine/tests/test_retrieval_contracts.py
git commit -m "feat(retrieval): 定义检索通道健康契约"
```

## Task 2: Make Dense, BM25, and Graph Channels Natively Scoped

**Files:**
- Modify: `engine/app/retrieval/vector_search.py`
- Modify: `engine/app/retrieval/es_search.py`
- Modify: `engine/app/retrieval/graph_expand.py`
- Modify: `engine/app/indexing/milvus_index.py`
- Create: `engine/tests/test_scoped_retrieval.py`
- Create: `engine/tests/integration/test_retrieval_scope_isolation.py`

- [ ] **Step 1: Write failing scope tests**

```python
def test_dense_passes_native_scope_to_milvus(monkeypatch):
    from engine.app.retrieval.contracts import SearchScope
    from engine.app.retrieval.vector_search import vector_search

    seen = {}
    monkeypatch.setattr("engine.app.retrieval.vector_search.search_index", lambda **kw: seen.update(kw) or [])
    scope = SearchScope(tenant_id="t1", kb_uid="k1", index_generation="g1", graph_generation="gg1")
    vector_search([0.1, 0.2], scope, top_k=50)
    assert seen["scope"] == scope


def test_graph_seed_query_contains_kb_scope(fake_graph):
    from engine.app.retrieval.contracts import SearchScope
    from engine.app.retrieval.graph_expand import graph_search

    scope = SearchScope(tenant_id="t1", kb_uid="k1", index_generation="g1", graph_generation="gg1")
    graph_search("query", scope, fake_graph, top_k=30, hops=1)
    assert fake_graph.last_params["tenant_id"] == "t1"
    assert fake_graph.last_params["kb_uid"] == "k1"
```

- [ ] **Step 2: Run and verify tests fail**

Run: `python -m pytest engine/tests/test_scoped_retrieval.py -v`

Expected: FAIL because existing functions do not accept scope.

- [ ] **Step 3: Change all channel signatures**

Use these exact public signatures:

```python
def vector_search(query_embedding: list[float], scope: SearchScope, top_k: int) -> ChannelResult: ...
def es_fulltext_search(query: str, scope: SearchScope, top_k: int) -> ChannelResult: ...
def graph_search(query: str, scope: SearchScope, graph_client, top_k: int, hops: int) -> ChannelResult: ...
```

Vector/ES exceptions return failed `ChannelResult` with typed codes after client-level retries. Graph seeds, communities, and paths include scope parameters in every Cypher match. Remove MySQL allowed-ID post-filtering from the production path.

- [ ] **Step 4: Add cross-KB real-service fixture**

Index identical text under `k1/g1` and `k2/g1` in all services. Query `k1`; assert every candidate has `kb_uid == k1`. Repeat for file filter and source type.

- [ ] **Step 5: Run and commit**

```bash
python -m pytest engine/tests/test_scoped_retrieval.py -v
python -m pytest engine/tests/integration/test_retrieval_scope_isolation.py -v
git add engine/app/retrieval engine/app/indexing/milvus_index.py engine/tests/test_scoped_retrieval.py engine/tests/integration/test_retrieval_scope_isolation.py
git commit -m "fix(retrieval): 强制三路知识库作用域"
```

## Task 3: Fuse Three Raw Lists Exactly Once

**Files:**
- Modify: `engine/app/retrieval/unified.py`
- Modify: `engine/app/retrieval/hybrid.py`
- Create: `engine/tests/test_weighted_rrf_once.py`

- [ ] **Step 1: Write failing fusion test**

```python
def test_unified_search_calls_each_channel_once_and_rrf_once(monkeypatch, scope):
    from engine.app.retrieval import unified

    calls = {"dense": 0, "bm25": 0, "graph": 0, "rrf": 0}
    monkeypatch.setattr(unified, "vector_search", lambda *a, **k: channel("dense", "c1", calls))
    monkeypatch.setattr(unified, "es_fulltext_search", lambda *a, **k: channel("bm25", "c1", calls))
    monkeypatch.setattr(unified, "graph_search", lambda *a, **k: channel("graph", "c2", calls))
    monkeypatch.setattr(unified, "weighted_rrf", lambda *a, **k: count_rrf(calls, a[0]))

    unified.recall("query", [0.1], scope)
    assert calls == {"dense": 1, "bm25": 1, "graph": 1, "rrf": 1}
```

- [ ] **Step 2: Run and see double-fusion failure**

Run: `python -m pytest engine/tests/test_weighted_rrf_once.py -v`

Expected: FAIL on current hybrid + unified behavior.

- [ ] **Step 3: Implement pure Weighted RRF**

```python
def weighted_rrf(results: list[ChannelResult], weights: dict[str, float], k: int = 60) -> list[dict]:
    healthy = [result for result in results if result.health != "failed"]
    active = {result.channel: weights[result.channel] for result in healthy}
    total = sum(active.values()) or 1.0
    active = {name: value / total for name, value in active.items()}
    merged: dict[str, dict] = {}
    for result in healthy:
        for candidate in result.candidates:
            row = merged.setdefault(candidate.chunk_uid, {"chunk_uid": candidate.chunk_uid, "rrf_score": 0.0, "channels": {}})
            row["rrf_score"] += active[result.channel] / (k + candidate.raw_rank)
            row["channels"][result.channel] = {"raw_rank": candidate.raw_rank, "raw_score": candidate.raw_score}
    return sorted(merged.values(), key=lambda row: row["rrf_score"], reverse=True)
```

`hybrid.py` may keep the pure helper but must not call retrieval from production. `unified.recall` owns all three channel calls and the single fusion.

- [ ] **Step 4: Add health-to-final-status tests**

Assert:

- all healthy/empty -> `no_hits`;
- one failed and one result -> `degraded`;
- Dense and BM25 failed with Graph disabled -> `unavailable`;
- Graph failed but text results exist -> `degraded`.

- [ ] **Step 5: Run and commit**

```bash
python -m pytest engine/tests/test_weighted_rrf_once.py engine/tests/test_unified_retrieval.py engine/tests/test_hybrid_search.py -v
git add engine/app/retrieval/unified.py engine/app/retrieval/hybrid.py engine/tests/test_weighted_rrf_once.py
git commit -m "refactor(retrieval): 统一单次三路 RRF 融合"
```

## Task 4: Rerank Text Before Small-to-Big Expansion

**Files:**
- Modify: `engine/app/retrieval/rerank.py`
- Modify: `engine/app/chat/answer.py`
- Create: `engine/tests/test_rerank_text_contract.py`

- [ ] **Step 1: Write failing provider-payload test**

```python
def test_reranker_receives_chunk_text_not_uuid(monkeypatch):
    from engine.app.retrieval.rerank import rerank

    payload = {}
    monkeypatch.setattr("engine.app.retrieval.rerank.post_rerank", lambda body: payload.update(body) or {"results": [{"index": 0, "relevance_score": 0.9}]})
    out = rerank("query", [{"chunk_uid": "uuid-c1", "text": "real chunk text", "rrf_score": 0.01}], top_n=20)
    assert payload["documents"] == ["real chunk text"]
    assert out[0]["rerank_score"] == 0.9
```

- [ ] **Step 2: Run and confirm UUID behavior failure**

Run: `python -m pytest engine/tests/test_rerank_text_contract.py -v`

Expected: FAIL.

- [ ] **Step 3: Reorder pipeline**

Use this sequence in `answer.py`/unified service:

```python
fused = recall(...)
children = load_child_texts(db, [row["chunk_uid"] for row in fused[:candidate_limit]])
reranked = rerank(query, children, top_n=rerank_top_n)
evidence_rows = expand_parent_context(db, reranked[:final_top_k])
```

Validate response count, indexes, and numeric scores. Provider error returns original RRF order plus warning `RERANK_UNAVAILABLE`; it does not fabricate scores.

- [ ] **Step 4: Run and commit**

```bash
python -m pytest engine/tests/test_rerank_text_contract.py engine/tests/test_rerank.py engine/tests/test_page_index.py -v
git add engine/app/retrieval/rerank.py engine/app/chat/answer.py engine/tests/test_rerank_text_contract.py
git commit -m "fix(retrieval): 使用正文执行重排"
```

## Task 5: Make Deep Search Controls and Rewrite Iterations Real

**Files:**
- Modify: `engine/app/agent/rag/agentic.py`
- Modify: `engine/app/agent/tools/deep_knowledge_search.py`
- Modify: `engine/app/api/chat.py`
- Modify: `engine/tests/test_agentic_rag.py`
- Modify: `engine/tests/test_deep_knowledge_search_tool.py`

- [ ] **Step 1: Add failing distinct-rewrite tests**

```python
def test_runner_stops_when_judge_repeats_query(runner):
    runner.judge = lambda *a, **k: judge_insufficient(rewrite_query="same query")
    result = runner.run("same query", max_iterations=3)
    assert result.iterations == 1


def test_runner_accumulates_evidence_across_distinct_rewrites(runner):
    runner.search = sequential_search([[evidence("K-a")], [evidence("K-b")]])
    runner.judge = sequential_judge([judge_insufficient("refined"), judge_sufficient()])
    result = runner.run("original", max_iterations=3)
    assert {row["chunk_uid"] for row in result.evidence} == {"K-a", "K-b"}
```

- [ ] **Step 2: Run and verify current overwrite/repeat behavior**

Run: `python -m pytest engine/tests/test_agentic_rag.py engine/tests/test_deep_knowledge_search_tool.py -v`

Expected: FAIL.

- [ ] **Step 3: Pass real controls**

Define `RagRunConfig(mode, top_k, graph_hops, max_iterations)` and pass it from ChatRequest/tool input to Runner. Normalize queries before comparing rewrites. Maintain an ordered Evidence map keyed by `chunk_uid` across iterations.

- [ ] **Step 4: Run and commit**

```bash
python -m pytest engine/tests/test_agentic_rag.py engine/tests/test_deep_knowledge_search_tool.py -v
git add engine/app/agent/rag/agentic.py engine/app/agent/tools/deep_knowledge_search.py engine/app/api/chat.py engine/tests/test_agentic_rag.py engine/tests/test_deep_knowledge_search_tool.py
git commit -m "fix(retrieval): 让深度检索参数与改写真正生效"
```

## Task 6: Normalize Evidence and Add Retrieval APIs

**Files:**
- Create: `engine/app/retrieval/evidence.py`
- Create: `engine/app/api/retrieval.py`
- Create: `backend/app/api/knowledge_retrieval.py`
- Modify: `backend/app/schemas/knowledge.py`
- Create: `engine/tests/test_evidence_contract.py`
- Create: `backend/tests/test_knowledge_retrieval_api.py`

- [ ] **Step 1: Write failing Evidence/API tests**

```python
def test_evidence_contains_provenance_and_channel_scores():
    from engine.app.retrieval.evidence import Evidence

    row = Evidence.model_validate(make_full_evidence())
    assert row.kb_uid == "kb-a"
    assert row.channel_scores["dense"].raw_rank == 1
    assert row.index_generation == "g1"


def test_public_query_distinguishes_no_hits_and_unavailable(client, fake_engine):
    fake_engine.response = {"status": "unavailable", "evidence": [], "warnings": []}
    response = client.post("/api/v1/knowledge-bases/kb-a/retrieval/query", json={"query": "x"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RETRIEVAL_UNAVAILABLE"
```

- [ ] **Step 2: Run and verify failures**

Run: `python -m pytest engine/tests/test_evidence_contract.py backend/tests/test_knowledge_retrieval_api.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement immutable Evidence DTO**

```python
# engine/app/retrieval/evidence.py
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ChannelScore(BaseModel):
    model_config = ConfigDict(frozen=True)
    raw_score: float
    raw_rank: int


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)
    evidence_id: str | None = None
    tenant_id: str
    kb_uid: str
    file_uid: str
    item_id: str | None = None
    chunk_uid: str
    parent_chunk_uid: str | None = None
    display_title: str
    original_filename: str | None = None
    excerpt: str
    page_start: int | None = None
    page_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    channel_scores: dict[str, ChannelScore]
    rrf_score: float
    rerank_score: float | None = None
    rerank_model: str | None = None
    retrieval_channels: tuple[Literal["dense", "bm25", "graph"], ...]
    graph_path: tuple[str, ...] = ()
    graph_explanation: str | None = None
    evidence_type: Literal["chunk", "graph_path", "entity"] = "chunk"
    index_generation: str
    degradation_flags: tuple[str, ...] = ()
```

`evidence_id` remains `None` during retrieval and is assigned once per AgentRun in Plan 4. Do not add storage paths or provider payloads to this model.

- [ ] **Step 4: Implement private and public routes**

```python
# shared response shape used by engine/app/api/retrieval.py
class RetrievalResponse(BaseModel):
    status: Literal["ok", "no_hits", "degraded", "unavailable", "invalid_request"]
    evidence: list[Evidence]
    warnings: list[ChannelProblem] = []


# backend/app/api/knowledge_retrieval.py
@router.post("/{kb_uid}/retrieval/query")
async def query_knowledge_base(
    kb_uid: str,
    request: RetrievalQuery,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    topic = KnowledgeAccessPolicy(db).require_read(actor, kb_uid)
    result = await engine_client.query(
        scope=scope_signer.for_actor(actor, allowed_kb_uids=(kb_uid,)),
        kb_uid=kb_uid,
        index_generation=topic.active_index_generation,
        graph_generation=topic.active_graph_generation,
        request=request,
    )
    if result.status == "unavailable":
        raise ApiProblem(503, "RETRIEVAL_UNAVAILABLE", "Knowledge retrieval is unavailable")
    if result.status == "invalid_request":
        raise ApiProblem(422, "INVALID_RETRIEVAL_REQUEST", "Invalid retrieval request")
    return public_retrieval_response(result)
```

The private Engine route accepts only a verified `AuthorizedKnowledgeScope`, query/mode, public filters, and bounded config overrides. `public_retrieval_response` strips `tenant_id` and any internal provider data; `degraded` returns HTTP 206, while `ok` and `no_hits` return HTTP 200.

- [ ] **Step 5: Run and commit**

```bash
python -m pytest engine/tests/test_evidence_contract.py backend/tests/test_knowledge_retrieval_api.py -v
git add engine/app/retrieval/evidence.py engine/app/api/retrieval.py backend/app/api/knowledge_retrieval.py backend/app/schemas/knowledge.py engine/tests/test_evidence_contract.py backend/tests/test_knowledge_retrieval_api.py
git commit -m "feat(retrieval): 增加证据契约与检索 API"
```

## Task 7: Add Reproducible Evaluation Runs

**Files:**
- Create: `backend/app/models/knowledge_evaluation.py`
- Create: `backend/alembic/versions/20260722_02_knowledge_evaluation.py`
- Create: `backend/app/api/knowledge_evaluation.py`
- Create: `engine/app/evaluation/__init__.py`
- Create: `engine/app/evaluation/metrics.py`
- Create: `engine/app/evaluation/runner.py`
- Create: `backend/tests/test_knowledge_evaluation_api.py`
- Create: `backend/tests/integration/test_knowledge_evaluation_mysql.py`
- Create: `engine/tests/test_evaluation_metrics.py`
- Create: `engine/tests/test_evaluation_runner.py`

- [ ] **Step 1: Write failing metric/snapshot tests**

```python
def test_retrieval_metrics_known_example():
    from engine.app.evaluation.metrics import retrieval_metrics

    out = retrieval_metrics(["c2", "c1", "c3"], {"c1"}, ks=(1, 3))
    assert out["recall@1"] == 0.0
    assert out["recall@3"] == 1.0
    assert out["mrr"] == 0.5


def test_run_freezes_config_and_generation(db_session):
    run = create_run(db_session, retrieval_config={"weights": [0.45, 0.35, 0.2]}, generation="g1")
    mutate_topic_to_generation(db_session, "g2")
    assert run.index_generation == "g1"
```

Add this real-MySQL migration assertion in `backend/tests/integration/test_knowledge_evaluation_mysql.py`:

```python
def test_evaluation_tables_exist_after_alembic(mysql_engine):
    from sqlalchemy import inspect

    tables = set(inspect(mysql_engine).get_table_names())
    assert {
        "evaluation_dataset", "evaluation_dataset_item",
        "evaluation_run", "evaluation_run_item",
    } <= tables
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest engine/tests/test_evaluation_metrics.py engine/tests/test_evaluation_runner.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement models and pure metrics**

Models: `EvaluationDataset`, `EvaluationDatasetItem`, `EvaluationRun`, `EvaluationRunItem`, mapped respectively to `evaluation_dataset`, `evaluation_dataset_item`, `evaluation_run`, and `evaluation_run_item`. Store gold chunks/answer, retrieved Evidence, per-item metrics, overall metrics, status/progress, model/config/generation snapshots.

Create `backend/alembic/versions/20260722_02_knowledge_evaluation.py` with `down_revision="20260722_01"`. Its `upgrade()` creates all four tables, foreign keys to the scoped knowledge base, and indexes for `(tenant_id, kb_uid, created_at)`, dataset items, and run-item status. Its `downgrade()` drops only those four tables in reverse dependency order. Run this migration against the dedicated MySQL test database; do not rely on SQLite `create_all` as deployment behavior.

Implement Recall@K, MRR, NDCG using pure functions. Answer/Judge metrics are optional only when corresponding models are configured; missing optional models do not invalidate retrieval metrics.

- [ ] **Step 4: Implement Job-driven runner and APIs**

APIs support JSONL import/export, generated dataset creation, run create/list/detail/cancel/delete. Runner processes each item independently; item failures are recorded and the Run status is `succeeded_with_errors` when at least one item succeeds.

- [ ] **Step 5: Run and commit**

```powershell
if (-not $env:PRISM_TEST_DATABASE_URL) { throw 'PRISM_TEST_DATABASE_URL must target the dedicated prism_test MySQL database' }
$env:DATABASE_URL=$env:PRISM_TEST_DATABASE_URL
alembic upgrade head
python -m pytest engine/tests/test_evaluation_metrics.py engine/tests/test_evaluation_runner.py backend/tests/test_knowledge_evaluation_api.py -v
python -m pytest backend/tests/integration/test_knowledge_evaluation_mysql.py -v
git add backend/app/models/knowledge_evaluation.py backend/alembic/versions/20260722_02_knowledge_evaluation.py backend/app/api/knowledge_evaluation.py engine/app/evaluation backend/tests/test_knowledge_evaluation_api.py backend/tests/integration/test_knowledge_evaluation_mysql.py engine/tests/test_evaluation_metrics.py engine/tests/test_evaluation_runner.py
git commit -m "feat(knowledge): 增加可复现的 RAG 评估"
```

## Task 8: Add Versioned Mindmap, Sample Questions, and Export

**Files:**
- Create: `engine/app/knowledge/__init__.py`
- Create: `engine/app/knowledge/enrichment.py`
- Create: `backend/app/api/knowledge_enrichment.py`
- Create: `engine/tests/test_knowledge_enrichment.py`
- Create: `backend/tests/test_knowledge_enrichment_api.py`

- [ ] **Step 1: Write failing deterministic-delete and stale tests**

```python
def test_mindmap_delete_only_update_does_not_call_llm(monkeypatch):
    from engine.app.knowledge.enrichment import apply_mindmap_diff

    monkeypatch.setattr("engine.app.knowledge.enrichment.call_llm", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    updated = apply_mindmap_diff(existing_map(), added=[], deleted=["file-a"], renamed=[])
    assert "file-a" not in flatten_ids(updated)


def test_file_change_marks_questions_stale(db_session):
    topic = topic_with_questions(db_session, version=3)
    mark_enrichment_stale(db_session, topic.kb_uid, reason="file_changed")
    assert topic.sample_questions_status == "stale"
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest engine/tests/test_knowledge_enrichment.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement Job-based enrichment**

Mindmap input uses file tree/title paths and bounded representative summaries, stores version/generation/model/prompt metadata, and supports deterministic deletion. Sample questions use stratified representative chunks and never regenerate from a polling loop.

- [ ] **Step 4: Implement export**

Export a ZIP containing manifest, configs without secrets, file list, parsed Markdown, evaluation JSONL, and MySQL graph facts. Do not export vectors or local absolute paths.

- [ ] **Step 5: Run and commit**

```bash
python -m pytest engine/tests/test_knowledge_enrichment.py backend/tests/test_knowledge_enrichment_api.py -v
git add engine/app/knowledge backend/app/api/knowledge_enrichment.py engine/tests/test_knowledge_enrichment.py backend/tests/test_knowledge_enrichment_api.py
git commit -m "feat(knowledge): 增加导图示例问题与安全导出"
```

## Plan Verification

- [ ] Run all focused tests from Tasks 1–8.
- [ ] Run existing retrieval/agent tests: `python -m pytest engine/tests/test_hybrid_search.py engine/tests/test_unified_retrieval.py engine/tests/test_rerank.py engine/tests/test_graph_expand.py engine/tests/test_agentic_rag.py -v`.
- [ ] Run cross-KB real-service isolation test.
- [ ] Capture one trace proving Dense/BM25/Graph each execute once and Rerank receives text.
- [ ] Verify `no_hits`, `degraded`, and `unavailable` response snapshots.
- [ ] Record commits in the roadmap.
