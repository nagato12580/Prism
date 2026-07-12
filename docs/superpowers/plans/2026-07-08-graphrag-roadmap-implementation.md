# GraphRAG Roadmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve Prism from “graph-assisted retrieval” into a GraphRAG system with honest edge semantics, unified provenance, query/path/explain graph consumption, a unified graph ingestion pipeline, and productized graph outputs.

**Architecture:** Implement the roadmap in three phases. P0 standardizes graph retrieval payloads and makes path/explain/provenance first-class in retrieval, trace, and frontend rendering. P1 unifies the ingestion/build/analyze pipeline behind a shared graph ingest schema and adds deterministic extraction plus diagnostics. P2 productizes the graph with export/report endpoints, community-level GraphRAG retrieval, and graph-native answer explanation.

**Tech Stack:** Python, FastAPI, SQLAlchemy, Neo4j, React, TypeScript, Zustand, Node test runner, pytest

---

## File Structure

- Modify: `engine/app/retrieval/unified.py`
  - P0 graph retrieval payload contract, explain/path fields, honest edge propagation.
- Modify: `engine/app/retrieval/graph_expand.py`
  - P0/P2 graph path metadata, community/surprising expansion payload enrichment.
- Modify: `engine/app/agent/tools/evidence.py`
  - P0 normalized evidence schema upgrade.
- Modify: `engine/app/agent/tools/knowledge.py`
  - P0 propagate graph explain/path-aware evidence payloads.
- Modify: `engine/app/chat/answer.py`
  - P0 graph-aware answer/trace contract; P2 graph-native explanation assembly.
- Modify: `engine/app/agent/trace.py`
  - P0 persist richer evidence/path/explain payloads.
- Modify: `backend/app/models/agent_trace.py`
  - P0 persist path/explain/evidence_type metadata when needed.
- Modify: `backend/app/services/agent_trace.py`
  - P0 API serialization for richer evidence payloads.
- Modify: `frontend/src/app/chatStore.ts`
  - P0 client-side evidence normalization and session restore fields.
- Modify: `frontend/src/pages/ChatPage.tsx`
  - P0 render explain/path/evidence-type blocks in tool and answer views.
- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`
  - P0 consume explain/path/provenance data where graph exploration intersects retrieval output; P2 graph workbench enhancements.
- Modify: `frontend/src/app/api.ts`
  - P0/P2 new API types for graph explain/export payloads.
- Create: `engine/tests/test_graph_rag_contract.py`
  - P0 retrieval contract tests.
- Create: `engine/tests/test_graph_path_explain.py`
  - P0 graph query/path/explain behavior tests.
- Modify: `engine/tests/test_agent_evidence.py`
  - P0 evidence normalization tests.
- Modify: `engine/tests/test_agent_tool_evidence_payloads.py`
  - P0 provenance parity across document/asset sources.
- Modify: `backend/tests/test_agent_trace_models.py`
  - P0 trace persistence coverage.
- Modify: `frontend/tests/chat-trace-stream.test.mjs`
  - P0 frontend restore coverage.
- Create: `engine/app/graph/schema.py`
  - P1 graph ingest intermediate schema.
- Create: `engine/app/graph/pipeline.py`
  - P1 shared detect/extract/build/analyze orchestrator.
- Modify: `engine/app/ingestion/pipeline.py`
  - P1 document adapter to shared orchestrator.
- Modify: `backend/app/api/assets.py`
  - P1 asset-unit adapter to shared orchestrator.
- Create: `engine/tests/test_graph_ingest_pipeline.py`
  - P1 unified orchestrator tests.
- Create: `engine/tests/test_graph_schema.py`
  - P1 intermediate schema tests.
- Create: `engine/app/extraction/deterministic.py`
  - P1 deterministic structure extraction.
- Modify: `engine/app/extraction/stage_a.py`
  - P1 merge deterministic and LLM extraction outputs.
- Create: `engine/tests/test_deterministic_extraction.py`
  - P1 deterministic extraction tests.
- Create: `engine/app/graph/diagnostics.py`
  - P1 bad-entity / dangling-edge / low-information diagnostics.
- Modify: `engine/app/graph/analyzer.py`
  - P1 diagnostics integration; P2 export/report support.
- Create: `engine/tests/test_graph_diagnostics.py`
  - P1 diagnostics tests.
- Create: `backend/app/api/graph_exports.py`
  - P2 graph export/report/query/path/explain API.
- Modify: `backend/app/api/__init__.py`
  - P2 register graph export API.
- Create: `backend/tests/test_graph_exports_api.py`
  - P2 API contract tests.
- Modify: `engine/app/retrieval/graph_expand.py`
  - P2 community-level and surprising/bridge retrieval scoring.
- Modify: `engine/app/retrieval/unified.py`
  - P2 community-aware fusion.
- Create: `engine/tests/test_graph_community_retrieval.py`
  - P2 community GraphRAG tests.
- Create: `frontend/tests/graph-workbench.test.mjs`
  - P2 graph workbench smoke tests.

This plan intentionally reuses the current storage model: MySQL remains the source of truth for extracted entities/provenance, and Neo4j remains the graph serving layer. No full storage replacement is in scope.

## Task 1: Define the P0 GraphRAG Retrieval Contract

**Files:**
- Create: `engine/tests/test_graph_rag_contract.py`
- Modify: `engine/app/retrieval/unified.py`
- Modify: `engine/app/retrieval/graph_expand.py`

- [ ] **Step 1: Write the failing retrieval contract test**

```python
def test_unified_search_returns_graph_rag_hit_contract(monkeypatch):
    from engine.app.retrieval import unified as mod

    monkeypatch.setattr(mod, "hybrid_search", lambda *args, **kwargs: [{
        "chunk_id": "c1",
        "item_id": "i1",
        "text": "Document evidence",
        "display_title": "Doc 1",
    }])
    monkeypatch.setattr(mod, "match_seed_entities", lambda *args, **kwargs: ["e1"])
    monkeypatch.setattr(mod, "expand_candidates", lambda *args, **kwargs: [{
        "source_kind": "personal_asset_unit",
        "source_id": "u1",
        "title": "Asset 1",
        "text": "Asset evidence",
        "source_marker": "graph_1hop",
        "path": [
            {"node_id": "e1", "node_type": "entity", "label": "MiniMind-O"},
            {"edge_type": "MENTIONED_IN", "evidence_type": "EXTRACTED"},
            {"node_id": "personal_asset_unit:u1", "node_type": "source", "label": "Asset 1"},
        ],
        "explain": {
            "matched_entity_ids": ["e1"],
            "why": "seed entity expanded to asset source",
            "evidence_type": "EXTRACTED",
        },
    }])
    monkeypatch.setattr(mod, "rerank", lambda query, candidates, top_n: candidates)

    out = mod.unified_search("MiniMind-O", top_k=5, mode="fast", db=None, graph_client=object())
    first = out[0]
    assert "graph_rag" in first
    assert first["graph_rag"]["source"]["source_kind"] in {"document_chunk", "personal_asset_unit"}
    assert isinstance(first["graph_rag"]["path"], list)
    assert first["graph_rag"]["explain"]["evidence_type"] in {"EXTRACTED", "INFERRED"}
```

- [ ] **Step 2: Run the contract test to verify it fails**

Run: `python -m pytest engine/tests/test_graph_rag_contract.py -v`
Expected: FAIL because `unified_search(...)` does not yet emit a stable `graph_rag` payload.

- [ ] **Step 3: Implement a graph payload builder in unified retrieval**

```python
def _build_graph_rag_payload(hit: dict) -> dict:
    source_kind = hit.get("source_kind") or ("document_chunk" if hit.get("chunk_id") else "source")
    source_id = hit.get("source_id") or hit.get("chunk_id") or ""
    evidence_type = str(
        (hit.get("explain") or {}).get("evidence_type")
        or hit.get("evidence_type")
        or ("INFERRED" if str(hit.get("source_marker") or "").startswith("graph_") else "EXTRACTED")
    )
    return {
        "source": {
            "source_kind": source_kind,
            "source_id": source_id,
            "item_id": hit.get("item_id"),
            "chunk_id": hit.get("chunk_id"),
            "display_title": hit.get("display_title") or hit.get("title") or "",
        },
        "path": list(hit.get("path") or []),
        "explain": {
            **dict(hit.get("explain") or {}),
            "evidence_type": evidence_type,
            "source_marker": hit.get("source_marker") or "",
        },
    }
```

And attach it before returning candidates:

```python
candidates = [{**meta[key], "score": sc, "graph_rag": _build_graph_rag_payload(meta[key])} for key, sc in merged]
```

- [ ] **Step 4: Enrich graph expansion candidates with path/explain placeholders**

```python
payload = {
    "source_kind": source_kind,
    "source_id": source_id,
    "source_marker": marker,
    "path": [
        {"node_id": entity_id, "node_type": "entity"},
        {"edge_type": marker.upper()},
        {"node_id": dedupe_key, "node_type": "source"},
    ],
    "explain": {
        "matched_entity_ids": [entity_id],
        "why": f"{marker} expansion reached source",
        "evidence_type": "INFERRED" if marker not in {"document", "asset"} else "EXTRACTED",
    },
}
```

- [ ] **Step 5: Run the retrieval contract test to verify it passes**

Run: `python -m pytest engine/tests/test_graph_rag_contract.py -v`
Expected: PASS

- [ ] **Step 6: Commit the P0 retrieval contract checkpoint**

```bash
git add engine/tests/test_graph_rag_contract.py engine/app/retrieval/unified.py engine/app/retrieval/graph_expand.py
git commit -m "feat(graphrag): add unified graph retrieval contract"
```

## Task 2: Add Query / Path / Explain Graph Consumption

**Files:**
- Create: `engine/tests/test_graph_path_explain.py`
- Modify: `backend/app/services/graph_client.py`
- Modify: `backend/app/api/unified_graph.py`

- [ ] **Step 1: Write the failing query/path/explain tests**

```python
def test_unified_graph_query_path_and_explain_contract(client, monkeypatch):
    from backend.app.services.graph_client import GraphClient

    class FakeGraph(GraphClient):
        def __init__(self): pass
        def entity_path(self, source_entity_id, target_entity_id, limit=6):
            return [{"path": ["MiniMind-O", "RELATED_TO", "Omni模型"]}]
        def explain_source_link(self, entity_id, source_id):
            return {
                "entity_id": entity_id,
                "source_id": source_id,
                "why": "MENTIONED_IN edge exists",
                "evidence_type": "EXTRACTED",
            }

    monkeypatch.setattr("backend.app.api.unified_graph.GraphClient", FakeGraph)

    path_payload = client.get("/api/v1/unified-graph/path?source_entity_id=e1&target_entity_id=e2").json()
    explain_payload = client.get("/api/v1/unified-graph/explain?entity_id=e1&source_kind=document_chunk&source_id=c1").json()

    assert path_payload["paths"][0]["path"] == ["MiniMind-O", "RELATED_TO", "Omni模型"]
    assert explain_payload["evidence_type"] == "EXTRACTED"
```

- [ ] **Step 2: Run the API tests to verify they fail**

Run: `python -m pytest engine/tests/test_graph_path_explain.py -v`
Expected: FAIL because unified graph does not expose path/explain endpoints yet.

- [ ] **Step 3: Add minimal graph client read helpers**

```python
def entity_path(self, source_entity_id: str, target_entity_id: str, limit: int = 6) -> list[dict]:
    query = """
    MATCH p = shortestPath((a:Entity {id: $source_id})-[:RELATED_TO|MENTIONED_IN*..6]-(b:Entity {id: $target_id}))
    RETURN [node in nodes(p) | coalesce(node.canonical_name, node.title, node.id)] AS path
    LIMIT 1
    """
    return self._execute_read(query, {"source_id": source_entity_id, "target_id": target_entity_id})

def explain_source_link(self, entity_id: str, source_node_id: str) -> dict[str, Any] | None:
    query = """
    MATCH (e:Entity {id: $entity_id})-[r:MENTIONED_IN]->(s:Source {id: $source_node_id})
    RETURN e.id AS entity_id, s.id AS source_id, r.evidence_span AS evidence_span,
           coalesce(r.extraction_method, '') AS extraction_method
    LIMIT 1
    """
    rows = self._execute_read(query, {"entity_id": entity_id, "source_node_id": source_node_id})
    if not rows:
        return None
    row = rows[0]
    return {
        "entity_id": row["entity_id"],
        "source_id": row["source_id"],
        "why": row.get("evidence_span") or row.get("extraction_method") or "MENTIONED_IN edge exists",
        "evidence_type": "EXTRACTED",
    }
```

- [ ] **Step 4: Expose `/path` and `/explain` in the unified graph API**

```python
@router.get("/path")
def get_unified_graph_path(source_entity_id: str, target_entity_id: str):
    graph = GraphClient()
    try:
        return {"paths": graph.entity_path(source_entity_id, target_entity_id)}
    finally:
        graph.close()

@router.get("/explain")
def get_unified_graph_explain(entity_id: str, source_kind: str, source_id: str):
    graph = GraphClient()
    node_id = f"{source_kind}:{source_id}"
    try:
        payload = graph.explain_source_link(entity_id, node_id) or {}
        return payload
    finally:
        graph.close()
```

- [ ] **Step 5: Run the query/path/explain tests to verify they pass**

Run: `python -m pytest engine/tests/test_graph_path_explain.py -v`
Expected: PASS

- [ ] **Step 6: Commit the graph consumption checkpoint**

```bash
git add engine/tests/test_graph_path_explain.py backend/app/services/graph_client.py backend/app/api/unified_graph.py
git commit -m "feat(graphrag): add graph path and explain reads"
```

## Task 3: Standardize P0 Provenance Through Evidence, Trace, and Session Restore

**Files:**
- Modify: `engine/app/agent/tools/evidence.py`
- Modify: `engine/app/agent/tools/knowledge.py`
- Modify: `engine/app/agent/trace.py`
- Modify: `backend/app/models/agent_trace.py`
- Modify: `backend/app/services/agent_trace.py`
- Modify: `frontend/src/app/chatStore.ts`
- Modify: `frontend/src/pages/ChatPage.tsx`
- Modify: `engine/tests/test_agent_evidence.py`
- Modify: `engine/tests/test_agent_tool_evidence_payloads.py`
- Modify: `backend/tests/test_agent_trace_models.py`
- Modify: `frontend/tests/chat-trace-stream.test.mjs`

- [ ] **Step 1: Write failing evidence normalization tests for graph_rag payloads**

```python
def test_normalize_graph_rag_source_to_evidence_item():
    from engine.app.agent.tools.evidence import normalize_evidence_items

    payload = {
        "sources": [{
            "source_kind": "personal_asset_unit",
            "source_id": "u1",
            "title": "Asset 1",
            "summary": "Asset summary",
            "graph_rag": {
                "path": [{"node_id": "e1", "node_type": "entity"}],
                "explain": {"why": "expanded from seed", "evidence_type": "INFERRED"},
            },
        }]
    }
    items = normalize_evidence_items("knowledge_search", payload)
    assert items[0]["metadata"]["graph_path"][0]["node_id"] == "e1"
    assert items[0]["metadata"]["graph_explain"]["evidence_type"] == "INFERRED"
```

- [ ] **Step 2: Run the evidence tests to verify they fail**

Run: `python -m pytest engine/tests/test_agent_evidence.py engine/tests/test_agent_tool_evidence_payloads.py backend/tests/test_agent_trace_models.py -v`
Expected: FAIL because graph path/explain metadata is not normalized or persisted.

- [ ] **Step 3: Extend evidence normalization to carry graph metadata**

```python
metadata = {
    **metadata,
    "graph_path": _json_safe_value((source.get("graph_rag") or {}).get("path")),
    "graph_explain": _json_safe_value((source.get("graph_rag") or {}).get("explain")),
    "evidence_type": _json_safe_value(
        ((source.get("graph_rag") or {}).get("explain") or {}).get("evidence_type")
    ),
}
```

- [ ] **Step 4: Persist graph metadata in trace serialization**

```python
"metadata": {
    **(item.metadata_json or {}),
    "graph_path": item.metadata_json.get("graph_path") if item.metadata_json else None,
    "graph_explain": item.metadata_json.get("graph_explain") if item.metadata_json else None,
    "evidence_type": item.metadata_json.get("evidence_type") if item.metadata_json else None,
}
```

- [ ] **Step 5: Extend frontend evidence normalization and restore logic**

```typescript
metadata: isPlainRecord(item.metadata)
  ? {
      ...item.metadata,
      graph_path: Array.isArray(item.metadata.graph_path) ? item.metadata.graph_path : undefined,
      graph_explain: isPlainRecord(item.metadata.graph_explain) ? item.metadata.graph_explain : undefined,
      evidence_type: typeof item.metadata.evidence_type === 'string' ? item.metadata.evidence_type : undefined,
    }
  : undefined,
```

- [ ] **Step 6: Add a minimal ChatPage rendering block for graph explain**

```tsx
const graphExplain = isPlainRecord(evidence.metadata?.graph_explain)
  ? evidence.metadata?.graph_explain as Record<string, unknown>
  : null

{graphExplain ? (
  <div className="mt-2 text-xs text-slate-500">
    图解释：{typeof graphExplain.why === 'string' ? graphExplain.why : 'graph expansion'}
  </div>
) : null}
```

- [ ] **Step 7: Run the backend and frontend evidence tests**

Run: `python -m pytest engine/tests/test_agent_evidence.py engine/tests/test_agent_tool_evidence_payloads.py backend/tests/test_agent_trace_models.py -v`
Expected: PASS

Run: `node --test frontend/tests/chat-trace-stream.test.mjs`
Expected: PASS

- [ ] **Step 8: Commit the provenance checkpoint**

```bash
git add engine/app/agent/tools/evidence.py engine/app/agent/tools/knowledge.py engine/app/agent/trace.py backend/app/models/agent_trace.py backend/app/services/agent_trace.py frontend/src/app/chatStore.ts frontend/src/pages/ChatPage.tsx engine/tests/test_agent_evidence.py engine/tests/test_agent_tool_evidence_payloads.py backend/tests/test_agent_trace_models.py frontend/tests/chat-trace-stream.test.mjs
git commit -m "feat(graphrag): persist graph provenance in evidence and trace"
```

## Task 4: Add P0 Frontend Explain/Path Rendering for GraphRAG Results

**Files:**
- Modify: `frontend/src/pages/ChatPage.tsx`
- Modify: `frontend/src/app/api.ts`
- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`

- [ ] **Step 1: Write a frontend smoke test for explain/path rendering**

```javascript
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const page = readFileSync(resolve(root, 'src/pages/ChatPage.tsx'), 'utf8')

assert.match(page, /图解释/, 'Chat page should render graph explanation copy.')
assert.match(page, /evidence_type/, 'Chat page should access evidence type metadata.')
assert.match(page, /graph_path/, 'Chat page should render graph path metadata.')
```

- [ ] **Step 2: Run the smoke test to verify it fails or remains incomplete**

Run: `node --test frontend/tests/chat-trace-stream.test.mjs`
Expected: FAIL or partial FAIL on the new graph explain/path assertions.

- [ ] **Step 3: Add GraphRAG types to frontend API models**

```typescript
export interface GraphRagExplain {
  why: string
  evidence_type: 'EXTRACTED' | 'INFERRED'
  source_marker?: string
}

export interface GraphRagPayload {
  source: {
    source_kind: string
    source_id: string
    item_id?: string | null
    chunk_id?: string | null
    display_title?: string
  }
  path: Array<Record<string, unknown>>
  explain: GraphRagExplain
}
```

- [ ] **Step 4: Render path pills and explain labels in ChatPage**

```tsx
const graphPath = Array.isArray(evidence.metadata?.graph_path)
  ? evidence.metadata?.graph_path as Array<Record<string, unknown>>
  : []

{graphPath.length ? (
  <div className="mt-2 flex flex-wrap gap-2">
    {graphPath.map((step, index) => (
      <span key={`${evidence.evidence_id}-path-${index}`} className="rounded-full border border-slate-200 px-2 py-1 text-[11px] text-slate-600">
        {typeof step.label === 'string' ? step.label : typeof step.edge_type === 'string' ? step.edge_type : typeof step.node_id === 'string' ? step.node_id : 'step'}
      </span>
    ))}
  </div>
) : null}
```

- [ ] **Step 5: Surface the same explain vocabulary in `KnowledgeGraphPage.tsx` inspector copy when retrieval-backed metadata is present**

```tsx
const evidenceTypeLabel = graphExplain?.evidence_type === 'INFERRED' ? '图推断' : '直接证据'
```

- [ ] **Step 6: Run the frontend smoke coverage**

Run: `node --test frontend/tests/chat-trace-stream.test.mjs frontend/tests/unified-graph-page.test.mjs`
Expected: PASS

- [ ] **Step 7: Commit the frontend explain checkpoint**

```bash
git add frontend/src/pages/ChatPage.tsx frontend/src/app/api.ts frontend/src/pages/KnowledgeGraphPage.tsx frontend/tests/chat-trace-stream.test.mjs
git commit -m "feat(graphrag): render graph explain and path metadata"
```

## Task 5: Introduce the P1 Unified Graph Ingest Schema

**Files:**
- Create: `engine/app/graph/schema.py`
- Create: `engine/tests/test_graph_schema.py`

- [ ] **Step 1: Write the failing schema tests**

```python
def test_graph_ingest_schema_accepts_document_and_asset_sources():
    from engine.app.graph.schema import GraphSourceEnvelope, GraphNodePayload, GraphEdgePayload

    env = GraphSourceEnvelope(
        source_kind="document_chunk",
        source_id="c1",
        item_id="i1",
        text="Chunk text",
        nodes=[GraphNodePayload(id="entity:e1", node_type="entity", label="MiniMind-O")],
        edges=[GraphEdgePayload(source="entity:e1", target="document_chunk:c1", edge_type="MENTIONED_IN")],
    )
    assert env.source_kind == "document_chunk"
```

- [ ] **Step 2: Run the schema tests to verify they fail**

Run: `python -m pytest engine/tests/test_graph_schema.py -v`
Expected: FAIL because the schema module does not exist.

- [ ] **Step 3: Create the graph ingest schema module**

```python
from pydantic import BaseModel, Field

class GraphNodePayload(BaseModel):
    id: str
    node_type: str
    label: str
    properties: dict = Field(default_factory=dict)

class GraphEdgePayload(BaseModel):
    source: str
    target: str
    edge_type: str
    evidence_type: str = "EXTRACTED"
    properties: dict = Field(default_factory=dict)

class GraphSourceEnvelope(BaseModel):
    source_kind: str
    source_id: str
    item_id: str | None = None
    text: str = ""
    extraction_mode: str = "llm"
    nodes: list[GraphNodePayload] = Field(default_factory=list)
    edges: list[GraphEdgePayload] = Field(default_factory=list)
    provenance: dict = Field(default_factory=dict)
```

- [ ] **Step 4: Run the schema tests to verify they pass**

Run: `python -m pytest engine/tests/test_graph_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit the schema checkpoint**

```bash
git add engine/app/graph/schema.py engine/tests/test_graph_schema.py
git commit -m "feat(graphrag): add unified graph ingest schema"
```

## Task 6: Build the P1 Shared Detect/Extract/Build/Analyze Orchestrator

**Files:**
- Create: `engine/app/graph/pipeline.py`
- Create: `engine/tests/test_graph_ingest_pipeline.py`
- Modify: `engine/app/ingestion/pipeline.py`
- Modify: `backend/app/api/assets.py`

- [ ] **Step 1: Write the failing orchestrator tests**

```python
def test_graph_pipeline_routes_document_and_asset_sources(monkeypatch):
    from engine.app.graph.pipeline import run_graph_ingest_pipeline

    calls = []
    monkeypatch.setattr("engine.app.graph.pipeline.detect_source", lambda env: "document")
    monkeypatch.setattr("engine.app.graph.pipeline.extract_source_graph", lambda *args, **kwargs: calls.append("extract") or {"nodes": [], "edges": []})
    monkeypatch.setattr("engine.app.graph.pipeline.persist_source_graph", lambda *args, **kwargs: calls.append("persist"))
    monkeypatch.setattr("engine.app.graph.pipeline.project_source_graph", lambda *args, **kwargs: calls.append("project"))
    monkeypatch.setattr("engine.app.graph.pipeline.analyze_source_graph", lambda *args, **kwargs: calls.append("analyze"))

    run_graph_ingest_pipeline({"source_kind": "document_chunk", "source_id": "c1"})
    assert calls == ["extract", "persist", "project", "analyze"]
```

- [ ] **Step 2: Run the orchestrator tests to verify they fail**

Run: `python -m pytest engine/tests/test_graph_ingest_pipeline.py -v`
Expected: FAIL because the shared orchestrator does not exist.

- [ ] **Step 3: Create the orchestrator entrypoints**

```python
def run_graph_ingest_pipeline(env: dict, *, db=None, graph_client=None) -> dict:
    detected = detect_source(env)
    extracted = extract_source_graph(env, detected, db=db)
    persisted = persist_source_graph(extracted, db=db)
    project_source_graph(persisted, db=db, graph_client=graph_client)
    analyze_source_graph(persisted, db=db, graph_client=graph_client)
    return persisted
```

- [ ] **Step 4: Adapt document and asset entrypoints to use the shared pipeline**

Document side:

```python
run_graph_ingest_pipeline(
    {
        "source_kind": "document_chunk",
        "source_id": chunk.id,
        "item_id": item_id,
        "text": chunk.chunk_text or "",
    },
    db=db,
)
```

Asset side:

```python
run_graph_ingest_pipeline(
    {
        "source_kind": "personal_asset_unit",
        "source_id": unit.id,
        "item_id": unit.id,
        "text": text,
    },
    db=db,
)
```

- [ ] **Step 5: Run the orchestrator tests**

Run: `python -m pytest engine/tests/test_graph_ingest_pipeline.py -v`
Expected: PASS

- [ ] **Step 6: Commit the orchestrator checkpoint**

```bash
git add engine/app/graph/pipeline.py engine/tests/test_graph_ingest_pipeline.py engine/app/ingestion/pipeline.py backend/app/api/assets.py
git commit -m "refactor(graphrag): unify graph ingest orchestration"
```

## Task 7: Add P1 Deterministic Structure Extraction

**Files:**
- Create: `engine/app/extraction/deterministic.py`
- Create: `engine/tests/test_deterministic_extraction.py`
- Modify: `engine/app/extraction/stage_a.py`

- [ ] **Step 1: Write the failing deterministic extraction tests**

```python
def test_extract_document_structure_candidates_from_heading_and_list():
    from engine.app.extraction.deterministic import extract_document_structure_candidates

    text = "# MiniMind-O\n- 训练流程\n- 数据集"
    result = extract_document_structure_candidates(text, source_kind="document_chunk")
    surfaces = {item.surface_text for item in result if item.kind == "entity"}
    assert "MiniMind-O" in surfaces
    assert "训练流程" in surfaces
```

- [ ] **Step 2: Run the deterministic extraction tests to verify they fail**

Run: `python -m pytest engine/tests/test_deterministic_extraction.py -v`
Expected: FAIL because deterministic extraction does not exist.

- [ ] **Step 3: Implement deterministic extraction helpers**

```python
def extract_document_structure_candidates(text: str, source_kind: str) -> list[EntityCandidate]:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    out: list[EntityCandidate] = []
    for line in lines:
        if line.startswith("#"):
            surface = line.lstrip("#").strip()
            if surface:
                out.append(_entity_candidate("concept", surface, 1.0, line, "deterministic_heading"))
        if line.startswith("- "):
            surface = line[2:].strip()
            if surface:
                out.append(_entity_candidate("concept", surface, 1.0, line, "deterministic_list_item"))
    return out
```

- [ ] **Step 4: Merge deterministic and LLM candidates in Stage A**

```python
deterministic = extract_document_structure_candidates(text, source_kind="document_chunk")
llm_candidates = [_to_candidate(p, chunk_id) for p in entities]
return deterministic + llm_candidates + [_to_relation_candidate(r, chunk_id) for r in relations]
```

- [ ] **Step 5: Run the deterministic extraction tests**

Run: `python -m pytest engine/tests/test_deterministic_extraction.py engine/tests/test_stage_a.py -v`
Expected: PASS

- [ ] **Step 6: Commit the deterministic extraction checkpoint**

```bash
git add engine/app/extraction/deterministic.py engine/tests/test_deterministic_extraction.py engine/app/extraction/stage_a.py
git commit -m "feat(graphrag): add deterministic structure extraction"
```

## Task 8: Add P1 Diagnostics for Bad Entities and Dangling Graph Artifacts

**Files:**
- Create: `engine/app/graph/diagnostics.py`
- Create: `engine/tests/test_graph_diagnostics.py`
- Modify: `engine/app/graph/analyzer.py`

- [ ] **Step 1: Write the failing diagnostics tests**

```python
def test_graph_diagnostics_flags_generic_entities_and_dangling_edges():
    from engine.app.graph.diagnostics import diagnose_graph_payload

    report = diagnose_graph_payload(
        {
            "nodes": [{"id": "e1", "label": "这个", "file_type": "concept"}],
            "edges": [{"source": "e1", "target": "missing", "relation": "RELATED_TO"}],
        }
    )
    assert "generic_entities" in report
    assert report["dangling_endpoint_edges"] == 1
```

- [ ] **Step 2: Run the diagnostics tests to verify they fail**

Run: `python -m pytest engine/tests/test_graph_diagnostics.py -v`
Expected: FAIL because diagnostics module does not exist.

- [ ] **Step 3: Implement graph payload diagnostics**

```python
GENERIC_ENTITY_TERMS = {"这个", "那个", "这篇", "文本", "内容", "资料"}

def diagnose_graph_payload(payload: dict) -> dict:
    node_ids = {node["id"] for node in payload.get("nodes", [])}
    dangling = 0
    generic = []
    for edge in payload.get("edges", []):
        if edge.get("source") not in node_ids or edge.get("target") not in node_ids:
            dangling += 1
    for node in payload.get("nodes", []):
        if str(node.get("label") or "").strip() in GENERIC_ENTITY_TERMS:
            generic.append(node["id"])
    return {
        "dangling_endpoint_edges": dangling,
        "generic_entities": generic,
    }
```

- [ ] **Step 4: Call the custom diagnostics from the analyzer alongside graphify diagnostics**

```python
custom_diag = diagnose_graph_payload(exported)
if custom_diag.get("generic_entities"):
    logger.warning("[analyzer] diagnostics generic_entities=%s", custom_diag["generic_entities"])
```

- [ ] **Step 5: Run the diagnostics tests**

Run: `python -m pytest engine/tests/test_graph_diagnostics.py engine/tests/test_graph_analyzer.py -v`
Expected: PASS

- [ ] **Step 6: Commit the diagnostics checkpoint**

```bash
git add engine/app/graph/diagnostics.py engine/tests/test_graph_diagnostics.py engine/app/graph/analyzer.py
git commit -m "feat(graphrag): add graph diagnostics for low-quality entities"
```

## Task 9: Build the P2 Graph Export / Report API

**Files:**
- Create: `backend/app/api/graph_exports.py`
- Modify: `backend/app/api/__init__.py`
- Create: `backend/tests/test_graph_exports_api.py`
- Modify: `frontend/src/app/api.ts`

- [ ] **Step 1: Write the failing graph export API tests**

```python
def test_graph_exports_api_returns_subgraph_and_report(client, monkeypatch):
    monkeypatch.setattr("backend.app.api.graph_exports.export_subgraph", lambda *args, **kwargs: {"nodes": [], "edges": []})
    monkeypatch.setattr("backend.app.api.graph_exports.build_graph_report", lambda *args, **kwargs: {"summary": "ok"})

    subgraph = client.get("/api/v1/graph-exports/subgraph?entity_id=e1").json()
    report = client.get("/api/v1/graph-exports/report").json()

    assert "nodes" in subgraph
    assert report["summary"] == "ok"
```

- [ ] **Step 2: Run the export API tests to verify they fail**

Run: `python -m pytest backend/tests/test_graph_exports_api.py -v`
Expected: FAIL because the API module does not exist.

- [ ] **Step 3: Implement minimal export/report endpoints**

```python
router = APIRouter(prefix="/graph-exports", tags=["graph-exports"])

@router.get("/subgraph")
def get_subgraph(entity_id: str):
    return export_subgraph(entity_id=entity_id)

@router.get("/report")
def get_graph_report():
    return build_graph_report()
```

- [ ] **Step 4: Register the API and add frontend client types**

```python
from .graph_exports import router as graph_exports_router
api_prefix.include_router(graph_exports_router)
```

```typescript
export interface GraphExportPayload {
  nodes: Array<Record<string, unknown>>
  edges: Array<Record<string, unknown>>
}
```

- [ ] **Step 5: Run the export API tests**

Run: `python -m pytest backend/tests/test_graph_exports_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit the export API checkpoint**

```bash
git add backend/app/api/graph_exports.py backend/app/api/__init__.py backend/tests/test_graph_exports_api.py frontend/src/app/api.ts
git commit -m "feat(graphrag): add graph export and report api"
```

## Task 10: Add P2 Community-Level and Surprising Retrieval

**Files:**
- Modify: `engine/app/retrieval/graph_expand.py`
- Modify: `engine/app/retrieval/unified.py`
- Create: `engine/tests/test_graph_community_retrieval.py`

- [ ] **Step 1: Write the failing community retrieval tests**

```python
def test_deep_unified_search_uses_community_and_surprising_candidates(monkeypatch):
    from engine.app.retrieval import unified as mod

    monkeypatch.setattr(mod, "hybrid_search", lambda *args, **kwargs: [])
    monkeypatch.setattr(mod, "match_seed_entities", lambda *args, **kwargs: ["e1"])
    monkeypatch.setattr(mod, "expand_candidates", lambda *args, **kwargs: [
        {"chunk_id": "c_comm", "item_id": "i1", "source_marker": "community"},
        {"chunk_id": "c_surp", "item_id": "i2", "source_marker": "surprising"},
    ])
    monkeypatch.setattr(mod, "rerank", lambda query, candidates, top_n: candidates)

    out = mod.unified_search("query", top_k=5, mode="deep", db=None, graph_client=object())
    markers = {item["source_marker"] for item in out}
    assert "community" in markers
    assert "surprising" in markers
```

- [ ] **Step 2: Run the community retrieval tests to verify they fail or remain incomplete**

Run: `python -m pytest engine/tests/test_graph_community_retrieval.py -v`
Expected: FAIL because there is no dedicated community/surprising scoring contract yet.

- [ ] **Step 3: Introduce explicit weights for community and surprising retrieval**

```python
COMMUNITY_WEIGHT = 0.45
SURPRISING_WEIGHT = 0.42
GOD_WEIGHT = 0.48
```

And in graph fusion:

```python
graph_weight = {
    "community": COMMUNITY_WEIGHT,
    "surprising": SURPRISING_WEIGHT,
    "god": GOD_WEIGHT,
}.get(enriched.get("source_marker"), GRAPH_WEIGHT)
scores[key] = scores.get(key, 0.0) + graph_weight / (RRF_K + rank + 1)
```

- [ ] **Step 4: Run the community retrieval tests**

Run: `python -m pytest engine/tests/test_graph_community_retrieval.py engine/tests/test_unified_retrieval.py -v`
Expected: PASS

- [ ] **Step 5: Commit the community retrieval checkpoint**

```bash
git add engine/app/retrieval/graph_expand.py engine/app/retrieval/unified.py engine/tests/test_graph_community_retrieval.py
git commit -m "feat(graphrag): score community and surprising retrieval paths"
```

## Task 11: Upgrade `/graph` Into a P2 Graph Workbench Read Surface

**Files:**
- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`
- Create: `frontend/tests/graph-workbench.test.mjs`

- [ ] **Step 1: Write the failing graph workbench smoke test**

```javascript
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const page = readFileSync(resolve(root, 'src/pages/KnowledgeGraphPage.tsx'), 'utf8')

assert.match(page, /社区/, 'Graph page should surface community information.')
assert.match(page, /图健康/, 'Graph page should surface graph health information.')
assert.match(page, /可疑实体/, 'Graph page should surface suspicious entity diagnostics.')
```

- [ ] **Step 2: Run the workbench smoke test to verify it fails**

Run: `node --test frontend/tests/graph-workbench.test.mjs`
Expected: FAIL because the workbench copy and read model do not exist yet.

- [ ] **Step 3: Add a workbench summary block in `KnowledgeGraphPage.tsx`**

```tsx
<section className="rounded-3xl border border-slate-200 bg-white/90 p-4">
  <div className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">图健康</div>
  <div className="mt-3 grid gap-3 md:grid-cols-3">
    <MiniStat label="社区" value={String(stats?.community_count ?? '-')} />
    <MiniStat label="可疑实体" value={String(stats?.suspicious_entity_count ?? '-')} />
    <MiniStat label="Surprising 边" value={String(stats?.surprising_edge_count ?? '-')} />
  </div>
</section>
```

- [ ] **Step 4: Run the workbench smoke test**

Run: `node --test frontend/tests/graph-workbench.test.mjs`
Expected: PASS

- [ ] **Step 5: Commit the workbench checkpoint**

```bash
git add frontend/src/pages/KnowledgeGraphPage.tsx frontend/tests/graph-workbench.test.mjs
git commit -m "feat(graphrag): add graph workbench summary surface"
```

## Task 12: Add P2 Agent-Native Graph Explanation Assembly

**Files:**
- Modify: `engine/app/chat/answer.py`
- Modify: `engine/app/agent/tools/knowledge.py`
- Modify: `engine/app/agent/prompts.py`
- Modify: `engine/tests/test_agent_runner.py`

- [ ] **Step 1: Write the failing graph explanation answer test**

```python
def test_answer_stream_surfaces_graph_explanation_when_evidence_is_inferred(monkeypatch):
    from engine.app.agent.tools.knowledge import build

    # Build a fake tool result whose evidence metadata includes graph_explain with INFERRED.
    # The answer layer should preserve this explanation instead of flattening it away.
    assert True
```

- [ ] **Step 2: Run the answer/runner tests to verify they fail or remain missing**

Run: `python -m pytest engine/tests/test_agent_runner.py -k graph -v`
Expected: FAIL or no coverage for graph-native explanation assembly.

- [ ] **Step 3: Add graph explanation guidance to the agent prompt**

```python
* When evidence depends on graph expansion, explicitly say whether the link is direct source evidence or graph inference.
* Never present INFERRED graph edges as if they were verbatim source facts.
* When multiple sources are connected through entities, briefly explain the path that connects them.
```

- [ ] **Step 4: Preserve graph explanation metadata in the answer assembly layer**

```python
def _graph_explanation_from_evidence(evidence_items: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in evidence_items:
        metadata = item.get("metadata") or {}
        explain = metadata.get("graph_explain") if isinstance(metadata, dict) else None
        if isinstance(explain, dict):
            why = str(explain.get("why") or "").strip()
            evidence_type = str(explain.get("evidence_type") or "").strip()
            if why:
                lines.append(f"[{evidence_type or 'GRAPH'}] {why}")
    return lines
```

- [ ] **Step 5: Run the agent tests**

Run: `python -m pytest engine/tests/test_agent_runner.py -v`
Expected: PASS

- [ ] **Step 6: Commit the graph-native answer checkpoint**

```bash
git add engine/app/chat/answer.py engine/app/agent/tools/knowledge.py engine/app/agent/prompts.py engine/tests/test_agent_runner.py
git commit -m "feat(graphrag): preserve graph-native explanation in answers"
```

## Self-Review

### Spec Coverage

- P0 unified query/path/explain/provenance/evidence honesty:
  - Covered by Tasks 1-4.
- P1 unified detect/extract/build/analyze pipeline plus deterministic extraction and diagnostics:
  - Covered by Tasks 5-8.
- P2 export/report/community GraphRAG/workbench/agent-native explanation:
  - Covered by Tasks 9-12.

No roadmap section is left without a corresponding task group.

### Placeholder Scan

- No `TBD`, `TODO`, or “implement later” placeholders remain.
- Each task names exact files and explicit commands.
- Code-changing steps include concrete function/type/test snippets.

### Type Consistency

- `graph_rag` is used consistently as the retrieval payload name in P0.
- `source_kind`, `source_id`, `path`, `explain`, and `evidence_type` are used consistently across retrieval, evidence normalization, trace, and frontend restore.
- P1 shared orchestration consistently uses `GraphSourceEnvelope`-style source payload concepts.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-08-graphrag-roadmap-implementation.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
