# Unified `/graph` Dual-View Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `/graph`'s CKP/PKU-first experience with a gradual dual-view unified graph page backed by entity/document-chunk/personal-asset-unit graph data.

**Architecture:** Add a new backend unified-graph API instead of mutating the legacy governance graph API, then migrate `KnowledgeGraphPage` to consume the new payload while preserving the existing route, canvas, zoom, drag, and inspector shell. Deliver entity view first, then source view, then retire the old workbench entry from the main flow.

**Tech Stack:** FastAPI, SQLAlchemy, React, TypeScript, existing Prism frontend route shell, pytest, existing entity graph tables (`KnowledgeEntity`, `EntityMention`, `EntityRelation`, `KnowledgeChunk`, `PersonalAssetUnit`).

---

## File Structure

- Create: `backend/app/api/unified_graph.py`
  - New unified graph API with `view=entity|source`
- Modify: `backend/app/api/__init__.py`
  - Register the new API router
- Create: `backend/tests/test_unified_graph_api.py`
  - Backend contract tests for entity and source view payloads
- Modify: `frontend/src/app/api.ts`
  - Add unified graph types and `unifiedGraphApi`
- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`
  - Replace CKP/PKU page semantics with entity/source dual view while preserving page shell
- Create: `frontend/tests/unified-graph-page.test.mjs`
  - Frontend smoke tests for new tab copy and API wiring

## Task 1: Add Backend Unified Graph API Contract

**Files:**
- Create: `backend/tests/test_unified_graph_api.py`
- Modify: `backend/app/models/__init__.py` only if test imports require an existing export

- [ ] **Step 1: Write the failing backend entity-view test**

```python
from backend.app.models import (
    EntityMention,
    EntityRelation,
    KnowledgeChunk,
    KnowledgeEntity,
    KnowledgeItem,
    PersonalAssetUnit,
)


def test_unified_graph_entity_view_returns_entities_and_cross_source_neighbors(client, db_session):
    entity = KnowledgeEntity(
        id="entity-1",
        user_id="default-user",
        entity_type="concept",
        canonical_name="MiniMind-O",
        normalized_key="minimind_o",
        status="active",
    )
    item = KnowledgeItem(id="item-1", title="Doc", user_id="default-user")
    chunk = KnowledgeChunk(id="chunk-1", item_id="item-1", chunk_text="MiniMind-O is an omni model.", chunk_type="child")
    unit = PersonalAssetUnit(
        id="unit-1",
        user_id="default-user",
        title="MiniMind note",
        content="MiniMind-O appears in my personal note.",
        summary="Asset summary",
        status="confirmed",
    )
    db_session.add_all([entity, item, chunk, unit])
    db_session.flush()
    db_session.add_all([
        EntityMention(
            entity_id="entity-1",
            source_kind="document_chunk",
            source_id="chunk-1",
            item_id="item-1",
            chunk_id="chunk-1",
            surface_text="MiniMind-O",
            normalized_key="minimind_o",
        ),
        EntityMention(
            entity_id="entity-1",
            source_kind="personal_asset_unit",
            source_id="unit-1",
            item_id="",
            chunk_id="",
            surface_text="MiniMind-O",
            normalized_key="minimind_o",
        ),
    ])
    db_session.commit()

    response = client.get("/api/v1/unified-graph", params={"view": "entity"})

    assert response.status_code == 200
    body = response.json()
    node_types = {node["type"] for node in body["nodes"]}
    assert "entity" in node_types
    assert "document_chunk" in node_types
    assert "personal_asset_unit" in node_types
    assert body["view"] == "entity"
```

- [ ] **Step 2: Write the failing backend source-view test**

```python
def test_unified_graph_source_view_returns_sources_with_entities(client, db_session):
    entity = KnowledgeEntity(
        id="entity-2",
        user_id="default-user",
        entity_type="technology",
        canonical_name="LoRA",
        normalized_key="lora",
        status="active",
    )
    unit = PersonalAssetUnit(
        id="unit-2",
        user_id="default-user",
        title="LoRA note",
        content="LoRA reduces trainable parameters.",
        summary="LoRA asset",
        status="confirmed",
    )
    db_session.add_all([entity, unit])
    db_session.flush()
    db_session.add(
        EntityMention(
            entity_id="entity-2",
            source_kind="personal_asset_unit",
            source_id="unit-2",
            item_id="",
            chunk_id="",
            surface_text="LoRA",
            normalized_key="lora",
        )
    )
    db_session.commit()

    response = client.get("/api/v1/unified-graph", params={"view": "source"})

    assert response.status_code == 200
    body = response.json()
    assert body["view"] == "source"
    assert any(node["type"] == "personal_asset_unit" for node in body["nodes"])
    assert any(edge["type"] == "mentions_entity" for edge in body["edges"])
```

- [ ] **Step 3: Run backend tests to verify they fail**

Run: `python -m pytest backend/tests/test_unified_graph_api.py -v`
Expected: FAIL with `404` for `/api/v1/unified-graph` or import errors because the API file does not exist yet.

- [ ] **Step 4: Commit the failing-test checkpoint**

```bash
git add backend/tests/test_unified_graph_api.py
git commit -m "test(graph): add unified graph API contract tests"
```

## Task 2: Implement Backend Unified Graph API

**Files:**
- Create: `backend/app/api/unified_graph.py`
- Modify: `backend/app/api/__init__.py`
- Test: `backend/tests/test_unified_graph_api.py`

- [ ] **Step 1: Add the new API router and serializers**

```python
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import EntityMention, EntityRelation, KnowledgeChunk, KnowledgeEntity, KnowledgeItem, PersonalAssetUnit

router = APIRouter(prefix="/unified-graph", tags=["unified-graph"])


def _entity_node(entity: KnowledgeEntity) -> dict[str, Any]:
    return {
        "id": f"entity:{entity.id}",
        "type": "entity",
        "label": entity.canonical_name,
        "entity_type": entity.entity_type,
        "summary": entity.description,
    }


def _chunk_node(db: Session, chunk_id: str) -> dict[str, Any] | None:
    chunk = db.query(KnowledgeChunk).filter(KnowledgeChunk.id == chunk_id).first()
    if not chunk:
        return None
    item = db.query(KnowledgeItem).filter(KnowledgeItem.id == chunk.item_id).first()
    return {
        "id": f"document_chunk:{chunk.id}",
        "type": "document_chunk",
        "label": (item.title if item else None) or chunk.id,
        "text": chunk.chunk_text,
        "item_id": chunk.item_id,
        "chunk_id": chunk.id,
        "source_kind": "document_chunk",
    }


def _asset_unit_node(db: Session, unit_id: str) -> dict[str, Any] | None:
    unit = db.query(PersonalAssetUnit).filter(PersonalAssetUnit.id == unit_id).first()
    if not unit:
        return None
    return {
        "id": f"personal_asset_unit:{unit.id}",
        "type": "personal_asset_unit",
        "label": unit.title,
        "text": unit.content,
        "summary": unit.summary,
        "source_id": unit.id,
        "source_kind": "personal_asset_unit",
    }
```

- [ ] **Step 2: Implement `view=entity` and `view=source` response builders**

```python
@router.get("")
def get_unified_graph(
    view: str = Query("entity", pattern="^(entity|source)$"),
    q: str | None = Query(None),
    limit: int = Query(48, ge=1, le=200),
    db: Session = Depends(get_db),
):
    mentions = db.query(EntityMention).all()
    entities_by_id = {
        entity.id: entity
        for entity in db.query(KnowledgeEntity).filter(KnowledgeEntity.status == "active").all()
    }
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}

    def add_source_for_mention(mention: EntityMention):
        if mention.source_kind == "document_chunk":
            source = _chunk_node(db, mention.source_id)
            edge_type = "mentioned_in"
        elif mention.source_kind == "personal_asset_unit":
            source = _asset_unit_node(db, mention.source_id)
            edge_type = "mentioned_in"
        else:
            source = None
            edge_type = "mentioned_in"
        if not source:
            return
        entity = entities_by_id.get(mention.entity_id)
        if not entity:
            return
        entity_node = _entity_node(entity)
        nodes[entity_node["id"]] = entity_node
        nodes[source["id"]] = source
        edge_id = f"{entity_node['id']}->{source['id']}"
        edges[edge_id] = {
            "id": edge_id,
            "source": entity_node["id"],
            "target": source["id"],
            "type": edge_type if view == "entity" else "mentions_entity",
            "label": edge_type if view == "entity" else "mentions_entity",
        }

    for mention in mentions:
        add_source_for_mention(mention)

    for relation in db.query(EntityRelation).all():
        source_id = f"entity:{relation.subject_entity_id}"
        target_id = f"entity:{relation.object_entity_id}" if relation.object_entity_id else None
        if not target_id or source_id not in nodes or target_id not in nodes:
            continue
        edge_id = f"relation:{relation.id}"
        edges[edge_id] = {
            "id": edge_id,
            "source": source_id,
            "target": target_id,
            "type": "related_to",
            "label": relation.predicate or "related_to",
        }

    filtered_nodes = list(nodes.values())
    filtered_edges = list(edges.values())
    if q:
        q_lower = q.lower()
        keep_ids = {node["id"] for node in filtered_nodes if q_lower in (node.get("label") or "").lower() or q_lower in (node.get("text") or "").lower()}
        keep_ids |= {edge["source"] for edge in filtered_edges if edge["source"] in keep_ids or edge["target"] in keep_ids}
        keep_ids |= {edge["target"] for edge in filtered_edges if edge["source"] in keep_ids or edge["target"] in keep_ids}
        filtered_nodes = [node for node in filtered_nodes if node["id"] in keep_ids]
        filtered_edges = [edge for edge in filtered_edges if edge["source"] in keep_ids and edge["target"] in keep_ids]

    if view == "source":
        filtered_nodes = [node for node in filtered_nodes if node["type"] != "entity" or any(edge["target"] == node["id"] for edge in filtered_edges)]
        filtered_edges = [
            {
                **edge,
                "source": edge["target"] if edge["type"] == "mentions_entity" else edge["source"],
                "target": edge["source"] if edge["type"] == "mentions_entity" else edge["target"],
            }
            if edge["type"] == "mentions_entity"
            else edge
            for edge in filtered_edges
        ]

    return {
        "view": view,
        "nodes": filtered_nodes[:limit],
        "edges": [edge for edge in filtered_edges if edge["source"] in {n["id"] for n in filtered_nodes[:limit]} and edge["target"] in {n["id"] for n in filtered_nodes[:limit]}],
        "stats": {
            "node_count": len(filtered_nodes[:limit]),
            "edge_count": len(filtered_edges),
        },
        "focus": {"query": q or ""},
    }
```

- [ ] **Step 3: Register the new router**

```python
from .unified_graph import router as unified_graph_router

def register_routers(app: FastAPI):
    api_prefix = APIRouter(prefix="/api/v1")
    ...
    api_prefix.include_router(unified_graph_router)
    app.include_router(api_prefix)
```

- [ ] **Step 4: Run backend tests to verify they pass**

Run: `python -m pytest backend/tests/test_unified_graph_api.py -v`
Expected: PASS with `2 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/unified_graph.py backend/app/api/__init__.py backend/tests/test_unified_graph_api.py
git commit -m "feat(graph): add unified graph API for entity and source views"
```

## Task 3: Add Frontend Unified Graph API Types

**Files:**
- Modify: `frontend/src/app/api.ts`
- Test: `frontend/tests/unified-graph-page.test.mjs`

- [ ] **Step 1: Write the failing frontend API test**

```javascript
import test from 'node:test'
import assert from 'node:assert/strict'

test('unifiedGraphApi targets /api/v1/unified-graph', async () => {
  const calls = []
  global.fetch = async (url) => {
    calls.push(String(url))
    return {
      ok: true,
      json: async () => ({ view: 'entity', nodes: [], edges: [], stats: {}, focus: {} }),
      text: async () => '',
    }
  }

  const { unifiedGraphApi } = await import('../src/app/api.ts')
  await unifiedGraphApi.get({ view: 'entity', q: 'MiniMind' })

  assert.equal(calls.length, 1)
  assert.match(calls[0], /\/api\/v1\/unified-graph\?/)
  assert.match(calls[0], /view=entity/)
})
```

- [ ] **Step 2: Run frontend API test to verify it fails**

Run: `node --test frontend/tests/unified-graph-page.test.mjs`
Expected: FAIL because `unifiedGraphApi` does not exist yet.

- [ ] **Step 3: Add unified graph types and API client**

```ts
export type UnifiedGraphNodeType = 'entity' | 'document_chunk' | 'personal_asset_unit'
export type UnifiedGraphEdgeType = 'mentioned_in' | 'mentions_entity' | 'related_to' | 'co_occurs_with' | 'shares_entity_with'

export interface UnifiedGraphNode {
  id: string
  type: UnifiedGraphNodeType
  label: string
  summary?: string
  text?: string
  entity_type?: string
  source_id?: string
  item_id?: string
  chunk_id?: string
  source_kind?: 'document_chunk' | 'personal_asset_unit'
  metadata?: Record<string, unknown>
}

export interface UnifiedGraphEdge {
  id: string
  source: string
  target: string
  type: UnifiedGraphEdgeType
  label: string
  weight?: number
  metadata?: Record<string, unknown>
}

export interface UnifiedGraphPayload {
  view: 'entity' | 'source'
  nodes: UnifiedGraphNode[]
  edges: UnifiedGraphEdge[]
  stats: Record<string, number>
  focus?: { node_id?: string; query?: string }
}

export const unifiedGraphApi = {
  get: (params?: { view?: 'entity' | 'source'; q?: string; limit?: number }) => {
    const search = new URLSearchParams()
    if (params?.view) search.set('view', params.view)
    if (params?.q) search.set('q', params.q)
    if (params?.limit) search.set('limit', String(params.limit))
    const qs = search.toString() ? `?${search.toString()}` : ''
    return request<UnifiedGraphPayload>(`/unified-graph${qs}`)
  },
}
```

- [ ] **Step 4: Run frontend API test to verify it passes**

Run: `node --test frontend/tests/unified-graph-page.test.mjs`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/api.ts frontend/tests/unified-graph-page.test.mjs
git commit -m "feat(graph): add frontend unified graph API client"
```

## Task 4: Migrate `/graph` to Entity-Centric Unified View

**Files:**
- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`
- Test: `frontend/tests/unified-graph-page.test.mjs`

- [ ] **Step 1: Add the failing page-copy smoke test**

```javascript
import fs from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'
import assert from 'node:assert/strict'

test('KnowledgeGraphPage uses unified graph copy instead of CKP workbench copy', async () => {
  const file = await fs.readFile(path.resolve('frontend/src/pages/KnowledgeGraphPage.tsx'), 'utf8')
  assert.match(file, /实体中心/)
  assert.match(file, /来源中心/)
  assert.doesNotMatch(file, /CKP Workbench/)
})
```

- [ ] **Step 2: Run the page-copy smoke test to verify it fails**

Run: `node --test frontend/tests/unified-graph-page.test.mjs`
Expected: FAIL because the page still contains `CKP Workbench`

- [ ] **Step 3: Replace legacy graph semantics in `KnowledgeGraphPage.tsx`**

```tsx
import {
  unifiedGraphApi,
  type UnifiedGraphEdge,
  type UnifiedGraphNode,
  type UnifiedGraphNodeType,
  type UnifiedGraphPayload,
} from '@/app/api'

type GraphViewMode = 'entity' | 'source'

const nodeMeta: Record<
  UnifiedGraphNodeType,
  { label: string; color: string; fill: string; icon: typeof Network; lane: string }
> = {
  entity: { label: '实体', color: '#155eef', fill: '#eff6ff', icon: Sparkles, lane: '实体层' },
  document_chunk: { label: '文档片段', color: '#0f766e', fill: '#ecfdf5', icon: FileText, lane: '文档来源' },
  personal_asset_unit: { label: '资产单元', color: '#be185d', fill: '#fdf2f8', icon: Boxes, lane: '个人资产来源' },
}

const [viewMode, setViewMode] = useState<GraphViewMode>('entity')

const loadGraph = async (nextQuery = query, nextView = viewMode) => {
  setLoading(true)
  setError(null)
  try {
    const data = await unifiedGraphApi.get({ view: nextView, q: nextQuery.trim() || undefined, limit: 60 })
    setPayload(data)
    setSelectedId(data.nodes[0]?.id ?? null)
  } catch (err) {
    setError(`加载统一图谱失败：${getErrorMessage(err)}`)
  } finally {
    setLoading(false)
  }
}
```

Replace the page header and tabs with:

```tsx
<div className="inline-flex w-fit rounded-lg border border-[var(--prism-line)] bg-white p-1">
  <button
    type="button"
    onClick={() => {
      setViewMode('entity')
      void loadGraph(query, 'entity')
    }}
    className={cn('rounded-md px-3 py-1.5 text-sm font-medium', viewMode === 'entity' ? 'bg-slate-950 text-white' : 'text-slate-600')}
  >
    实体中心
  </button>
  <button
    type="button"
    onClick={() => {
      setViewMode('source')
      void loadGraph(query, 'source')
    }}
    className={cn('rounded-md px-3 py-1.5 text-sm font-medium', viewMode === 'source' ? 'bg-slate-950 text-white' : 'text-slate-600')}
  >
    来源中心
  </button>
</div>
```

Update copy:

```tsx
<span>统一知识图谱</span>
<h1 className="mt-1 text-xl font-semibold text-slate-950">实体与来源图谱</h1>
<input ... placeholder="搜索实体、文档片段或资产单元" />
```

- [ ] **Step 4: Run the page-copy smoke test to verify it passes**

Run: `node --test frontend/tests/unified-graph-page.test.mjs`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/KnowledgeGraphPage.tsx frontend/tests/unified-graph-page.test.mjs
git commit -m "feat(graph): migrate /graph to unified entity and source views"
```

## Task 5: Inspector and View-Specific Rendering Cleanup

**Files:**
- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`
- Test: `frontend/tests/unified-graph-page.test.mjs`

- [ ] **Step 1: Add a failing smoke check for unified inspector copy**

```javascript
test('KnowledgeGraphPage inspector avoids CKP and PKU primary labels', async () => {
  const file = await fs.readFile(path.resolve('frontend/src/pages/KnowledgeGraphPage.tsx'), 'utf8')
  assert.doesNotMatch(file, /全局 CKP 主题网络/)
  assert.doesNotMatch(file, /查看 PKU 网络/)
})
```

- [ ] **Step 2: Run the smoke check to verify it fails**

Run: `node --test frontend/tests/unified-graph-page.test.mjs`
Expected: FAIL because inspector copy still contains CKP/PKU text.

- [ ] **Step 3: Update inspector and graph labels to unified graph semantics**

```tsx
const selectedSources = useMemo(
  () =>
    selected?.type === 'entity'
      ? (payload?.edges ?? [])
          .filter((edge) => edge.source === selected.id || edge.target === selected.id)
          .map((edge) => {
            const otherId = edge.source === selected.id ? edge.target : edge.source
            return { edge, node: allNodeById.get(otherId) }
          })
          .filter((entry): entry is { edge: UnifiedGraphEdge; node: UnifiedGraphNode } => Boolean(entry.node))
      : [],
  [allNodeById, payload?.edges, selected],
)
```

Update labels such as:

```tsx
{viewMode === 'entity' ? '实体中心网络' : '来源中心网络'}
{selected?.type === 'entity' ? '相关来源' : '相关实体'}
```

Right-side inspector should branch on node type:

```tsx
{node.type === 'entity' ? <DetailBlock label="实体类型" value={node.entity_type || '-'} /> : null}
{node.type !== 'entity' ? <DetailBlock label="摘要" value={node.summary || node.text || ''} /> : null}
```

- [ ] **Step 4: Run the smoke check to verify it passes**

Run: `node --test frontend/tests/unified-graph-page.test.mjs`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/KnowledgeGraphPage.tsx frontend/tests/unified-graph-page.test.mjs
git commit -m "refactor(graph): align inspector and graph labels with unified graph semantics"
```

## Task 6: Focused Regression Verification

**Files:**
- Test: `backend/tests/test_unified_graph_api.py`
- Test: `frontend/tests/unified-graph-page.test.mjs`
- Verify existing graph page route remains `frontend/src/app/routes.tsx`

- [ ] **Step 1: Run backend unified-graph tests**

Run: `python -m pytest backend/tests/test_unified_graph_api.py -v`
Expected: PASS

- [ ] **Step 2: Run existing backend graph-adjacent regressions**

Run: `python -m pytest backend/tests/test_knowledge_graph_api.py backend/tests/test_assets_api.py -v`
Expected: PASS, confirming old governance API remains untouched.

- [ ] **Step 3: Run frontend unified-graph smoke tests**

Run: `node --test frontend/tests/unified-graph-page.test.mjs`
Expected: PASS

- [ ] **Step 4: Manually verify route continuity**

Run: `rg -n "path: 'graph'" frontend/src/app/routes.tsx`
Expected: one match pointing to `KnowledgeGraphPage`

- [ ] **Step 5: Commit final verification checkpoint**

```bash
git add docs/superpowers/plans/2026-07-06-graph-unified-views.md
git commit -m "docs(plan): add unified graph dual-view migration plan"
```

## Self-Review

**1. Spec coverage**

- Dual-view `/graph` replacement: covered by Tasks 4 and 5.
- New unified backend API instead of mutating old governance API: covered by Task 2.
- Entity-first default and source view follow-up: covered by Tasks 2, 4, and 5.
- Gradual migration and workbench de-emphasis: covered by Tasks 4 and 6.
- Explicit first-phase exclusions: preserved by not planning edits to `KnowledgeGraphWorkbench.tsx` behavior beyond de-emphasis.

**2. Placeholder scan**

- No `TBD`, `TODO`, or “implement later” placeholders remain.
- Every code-changing task includes concrete code blocks.
- Every test step has an exact command and expected result.

**3. Type consistency**

- New frontend types consistently use `UnifiedGraphNode`, `UnifiedGraphEdge`, and `UnifiedGraphPayload`.
- Backend endpoint naming is consistently `/api/v1/unified-graph`.
- View names consistently use `entity` and `source`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-06-graph-unified-views.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
