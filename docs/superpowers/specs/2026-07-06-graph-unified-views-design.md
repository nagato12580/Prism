# Unified `/graph` Dual-View Migration Design

## 1. Goal

Migrate `http://localhost:5173/graph` from the legacy CKP/PKU governance graph to the new unified graph that matches Prism's current retrieval backbone:

- graph + traditional vector retrieval remain the retrieval foundation
- graph nodes can represent both document chunks and personal asset units through shared entities
- `/graph` should become the user-facing visualization of this unified graph
- the page should support two views:
  - entity-centric
  - source-centric

This is a gradual replacement, not a full rewrite.

## 2. User Outcome

After this migration:

- `/graph` no longer presents CKP and PKU as the primary mental model
- users can inspect how the same entity connects uploaded document chunks and `PersonalAssetUnit` sources
- users can switch between:
  - `实体中心`
  - `来源中心`
- the graph page reflects the same unified knowledge space used by retrieval

## 3. Non-Goals

This phase does not:

- remove the underlying CKP/PKU governance data model from storage
- rebuild the graph page from scratch
- introduce graph editing for entities or relations
- display the entire global graph without focus or limits
- merge old CKP/PKU API payloads with the new unified graph payload
- change the current hybrid retrieval backbone

## 4. Current Baseline

### 4.1 Frontend

The current `/graph` page is driven by:

- `frontend/src/pages/KnowledgeGraphPage.tsx`
- `frontend/src/pages/KnowledgeGraphWorkbench.tsx`

Current UI structure:

- a `CKP Workbench` tab
- a `全局网络` tab
- node and edge types centered on:
  - `canonical`
  - `pku`
  - `canonical_pku`
  - `pku_source`
  - `canonical_relation`

### 4.2 Backend

The current graph payload comes from:

- `backend/app/api/knowledge_graph.py`

This API is governance-centric and assumes CKP/PKU as the primary graph layer.

### 4.3 Architectural Mismatch

This no longer matches the current product direction.

Retrieval is now centered on:

- entities
- document chunks
- personal asset units

So the graph page must move to the same unified graph semantics.

## 5. Target Product Model

### 5.1 Main Principle

`/graph` should visualize the same unified entity graph that powers cross-source retrieval.

The graph's primary semantic objects become:

- `entity`
- `document_chunk`
- `personal_asset_unit`

CKP and PKU stop being the default display language of the page.

### 5.2 View Modes

The page keeps one route, `/graph`, but changes its top-level modes to:

- `实体中心`
- `来源中心`

Default mode:

- `实体中心`

Reason:

- retrieval and knowledge linking are already entity-centric
- entity-first is the clearest default mental model
- source-first is still valuable as a secondary inspection view

## 6. View Design

### 6.1 Entity-Centric View

Primary node type:

- `entity`

First-ring connected nodes:

- `document_chunk`
- `personal_asset_unit`
- related `entity`

Primary questions this view answers:

- which documents and asset units mention the same entity
- which entities connect otherwise separate sources
- what related entities surround a concept

Right-side inspector should show:

- entity label
- entity type
- aliases if available
- related document source count
- related asset-unit source count
- grouped source lists:
  - documents
  - personal assets
- related entity list

### 6.2 Source-Centric View

Primary node types:

- `document_chunk`
- `personal_asset_unit`

First-ring connected nodes:

- extracted `entity` nodes
- optionally other sources linked through shared entities

Primary questions this view answers:

- which entities were extracted from this source
- why two sources are connected
- whether a document and a personal asset unit overlap semantically

Right-side inspector should show:

- source title
- source type
- snippet or summary
- extracted entities
- related sources connected by shared entities

## 7. Unified Graph Data Model

### 7.1 Node Types

Frontend node types for the new page should be limited to:

- `entity`
- `document_chunk`
- `personal_asset_unit`

### 7.2 Edge Types

Frontend edge types should be limited to:

- `mentioned_in`
- `mentions_entity`
- `related_to`
- `co_occurs_with`
- `shares_entity_with`

Not every edge type must appear in both views, but both views should consume the same unified schema.

### 7.3 Suggested Payload

```ts
type UnifiedGraphNodeType = 'entity' | 'document_chunk' | 'personal_asset_unit'

type UnifiedGraphEdgeType =
  | 'mentioned_in'
  | 'mentions_entity'
  | 'related_to'
  | 'co_occurs_with'
  | 'shares_entity_with'

interface UnifiedGraphNode {
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

interface UnifiedGraphEdge {
  id: string
  source: string
  target: string
  type: UnifiedGraphEdgeType
  label: string
  weight?: number
  metadata?: Record<string, unknown>
}

interface UnifiedGraphPayload {
  view: 'entity' | 'source'
  nodes: UnifiedGraphNode[]
  edges: UnifiedGraphEdge[]
  stats: Record<string, number>
  focus?: {
    node_id?: string
    query?: string
  }
}
```

## 8. API Strategy

### 8.1 Do Not Mutate the Old Governance API

Do not overload `backend/app/api/knowledge_graph.py` with new unified semantics.

Reason:

- it is explicitly CKP/PKU-shaped
- mutating it in place would create mixed semantics
- frontend migration would become harder to reason about

### 8.2 Introduce a New Unified Graph API

Add a new API module, for example:

- `backend/app/api/unified_graph.py`

Suggested endpoints:

- `GET /api/v1/unified-graph?view=entity`
- `GET /api/v1/unified-graph?view=source`

Suggested query parameters:

- `q`
- `entity_id`
- `source_id`
- `source_type`
- `limit`

### 8.3 Backend Data Sources

The unified graph API should be built from the current entity graph layer, not from the CKP/PKU governance layer.

Primary data sources:

- `KnowledgeEntity`
- `EntityMention`
- `EntityRelation`
- `KnowledgeChunk`
- `PersonalAssetUnit`

This aligns the graph page with the current retrieval chain.

## 9. Frontend Migration Strategy

### 9.1 Preserve the Page Shell

Keep:

- the `/graph` route
- the graph canvas
- pan, zoom, drag, and search interactions
- the right-side inspector pattern

Replace:

- top-level tabs
- node type mapping
- edge type mapping
- search placeholder and copy
- inspector fields
- data API

### 9.2 Retire the Workbench Gradually

Do not expand `KnowledgeGraphWorkbench.tsx` into the new model.

Instead:

- remove it from the primary `/graph` entry flow
- keep it only as compatibility code during migration if needed
- eventually delete it after unified graph rollout is stable

### 9.3 New Frontend API Layer

In `frontend/src/app/api.ts`:

- add `UnifiedGraphNode`
- add `UnifiedGraphEdge`
- add `UnifiedGraphPayload`
- add `unifiedGraphApi`

Do not delete `knowledgeGraphApi` in phase 1.

## 10. Phased Delivery

### Phase 1: Unified Entity View Backend

- add the new unified graph API
- support the `entity` view first
- return only unified node and edge types

Acceptance:

- backend can return an entity-centric graph linking entities to document chunks and personal asset units

### Phase 2: `/graph` Entity View Frontend

- switch `KnowledgeGraphPage.tsx` to use `unifiedGraphApi`
- replace `CKP Workbench / 全局网络` with:
  - `实体中心`
  - placeholder or disabled `来源中心` if necessary
- render the entity-centric graph

Acceptance:

- `/graph` no longer presents CKP/PKU as the default graph semantics

### Phase 3: Unified Source View Backend

- add the `source` view mode to the unified graph API
- return source-centric graph payloads

Acceptance:

- backend can return source-first graph data linking sources to extracted entities

### Phase 4: `/graph` Source View Frontend

- add the source-centric tab
- render source nodes and shared-entity links

Acceptance:

- users can switch cleanly between entity view and source view

### Phase 5: Cleanup

- remove CKP/PKU terminology from `/graph`
- hide or retire workbench entry
- reduce dependency on old governance graph UI types

Acceptance:

- `/graph` is fully positioned as the unified graph page

## 11. File-Level Scope

### Frontend

Primary files to modify:

- `frontend/src/pages/KnowledgeGraphPage.tsx`
- `frontend/src/app/api.ts`

Compatibility file to de-emphasize later:

- `frontend/src/pages/KnowledgeGraphWorkbench.tsx`

### Backend

Primary new file:

- `backend/app/api/unified_graph.py`

Likely supporting query helpers may also be added under backend services if needed, but the first phase should avoid large refactors.

## 12. Explicit First-Phase Exclusions

Do not do these in the first implementation pass:

- graph editing for entities or edges
- mixed CKP/PKU and unified graph rendering on the same page
- full graph exploration without limits
- advanced graph clustering UI
- replacing hybrid retrieval logic
- rewriting the entire graph UI from scratch

## 13. Risks and Mitigations

### Risk 1: Semantic Drift Between Old and New Graph Pages

Mitigation:

- keep old governance API separate
- keep unified graph API separate
- migrate the page by switching API consumers, not by mixing payload types

### Risk 2: Frontend Type Entanglement

Mitigation:

- introduce new unified graph types instead of mutating existing governance graph types in place

### Risk 3: Large Blast Radius in One Pass

Mitigation:

- phase the work
- ship entity view first
- ship source view second

### Risk 4: User Confusion During Transition

Mitigation:

- remove CKP/PKU language from `/graph` as soon as the entity view is live
- keep terminology consistent with retrieval and unified knowledge space

## 14. Final Recommendation

Use a gradual replacement strategy:

- keep `/graph`
- keep the current page shell
- replace the semantics underneath
- introduce a new unified graph API
- default to `实体中心`
- add `来源中心` as the secondary view

This is the smallest migration that makes the graph page consistent with the current unified retrieval architecture and unified knowledge-space direction.
