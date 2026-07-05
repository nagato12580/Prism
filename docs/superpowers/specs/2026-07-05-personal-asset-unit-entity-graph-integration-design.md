# PersonalAssetUnit Entity Graph Integration Design

## 1. Goal

Integrate `PersonalAssetUnit` into Prism's existing document entity-graph pipeline without changing the current document ingestion and retrieval backbone.

After this change:

- document chunks and personal asset units both become graph `Source`s
- both source types can attach to the same `Entity` nodes
- graph expansion can return either document chunks or personal asset units as evidence
- the current document hybrid retrieval path remains unchanged

This design intentionally does not use the PKU/CKP layer as the primary integration point.

## 2. Non-Goals

This phase does not:

- add Milvus/vector indexing for `PersonalAssetUnit`
- make `PersonalAssetUnit` participate in primary hybrid recall
- refactor document chunk ingestion
- replace the PKU/CKP governance layer
- introduce a new canonical knowledge node layer
- split `PersonalAssetUnit` into child chunks

## 3. Current Baseline

The current document-side graph flow is:

1. document upload creates `KnowledgeItem`
2. ingestion splits content into `KnowledgeChunk`
3. child chunks are embedded and indexed
4. Stage A extracts entities and relations from child chunks
5. extracted entities are written to MySQL audit tables
6. the item is projected into Neo4j as:
   - `Entity`
   - `Source`
   - `Entity-[:MENTIONED_IN]->Source`
   - `Entity-[:RELATED_TO]->Entity`
7. retrieval uses hybrid recall first, then graph expansion to bring back additional `document_chunk` sources

The integration proposed here reuses this exact graph model.

## 4. Target Architecture

### 4.1 Unified Graph Model

The graph remains entity-centric.

Core node types:

- `Entity`
- `Source`

Core edge types:

- `MENTIONED_IN`
- `RELATED_TO`

Source identity becomes:

- `document_chunk:<chunk_id>`
- `personal_asset_unit:<unit_id>`

Both source types connect to the same `Entity` nodes.

### 4.2 Retrieval Model

Primary recall remains document-first:

1. hybrid search over document chunks
2. seed entity matching from user query
3. graph expansion from matched entities
4. graph expansion may return:
   - document chunks
   - personal asset units

This means `PersonalAssetUnit` is a graph-returned evidence source, not a first-class hybrid-recall target in phase 1.

## 5. Source Semantics

### 5.1 Document Side

- graph source unit: `KnowledgeChunk`
- source id format: `document_chunk:<chunk_id>`
- extraction text: chunk text

### 5.2 Personal Side

- graph source unit: `PersonalAssetUnit`
- source id format: `personal_asset_unit:<unit_id>`
- extraction text:
  - `title`
  - `summary`
  - `content`

`PersonalAssetUnit` is treated as one whole source in phase 1. It is not chunked further.

## 6. Required Code Changes

### 6.1 Asset-Unit Entity Extraction Trigger

Add a new post-confirmation graph-ingestion step for `PersonalAssetUnit`.

Trigger point:

- after `POST /assets/personal_asset_units/{unit_id}/confirm`
- after the unit is marked `confirmed`

Behavior:

1. assemble extraction text from `title + summary + content`
2. run the same Stage A entity extraction logic used by document chunks
3. write entity mentions and relations using:
   - `source_kind = "personal_asset_unit"`
   - `source_id = <unit_id>`
4. project those records to Neo4j

Phase 1 can do this synchronously inside the confirm path if latency is acceptable. If confirm latency becomes too high, the work should move behind a background job with the same semantics.

### 6.2 MySQL Entity Audit Compatibility

Reuse the existing entity audit tables:

- `knowledge_entity`
- `entity_alias`
- `entity_mention`
- `entity_relation`

The settling layer must fully support non-document sources:

- `source_kind = personal_asset_unit`
- `source_id = <unit_id>`
- `item_id = null`
- `chunk_id = null`

No asset-specific entity tables should be introduced.

### 6.3 Neo4j Projection for PersonalAssetUnit

Add a projection path parallel to document item projection.

Required behavior:

1. upsert all mentioned `Entity` nodes
2. upsert one `Source` node for the asset unit
3. create `Entity-[:MENTIONED_IN]->Source`
4. create `Entity-[:RELATED_TO]->Entity` for extracted inter-entity relations

Recommended implementation:

- keep existing `project_item_entities(...)` unchanged
- add a parallel function for asset units
- avoid an early generic refactor in phase 1

This keeps document risk low and limits blast radius.

### 6.4 Graph Expansion Retrieval

Extend graph expansion so it can return `personal_asset_unit` sources in addition to `document_chunk`.

Current behavior assumes only:

- `document_chunk:<chunk_id>`

Phase 1 behavior should support:

- `document_chunk:<chunk_id>`
- `personal_asset_unit:<unit_id>`

Graph expansion must preserve source type in returned evidence so downstream response assembly can distinguish the two.

### 6.5 Evidence Payload and Response Rendering

Response payloads must preserve source identity.

Minimum source metadata:

- source type
- source id
- label/title
- evidence text

The assistant response layer and UI must distinguish:

- uploaded document evidence
- personal asset unit evidence

This is required to avoid source mixing.

## 7. Detailed Data Flow

### 7.1 PersonalAssetUnit Confirm Flow

1. user confirms `PersonalAssetUnit`
2. backend marks unit as `confirmed`
3. backend runs asset-unit entity extraction
4. extraction output is settled into MySQL entity tables
5. settled entities are projected into Neo4j as unified graph data
6. confirm response succeeds

### 7.2 Retrieval Flow After Integration

1. user asks a question
2. system runs existing hybrid document recall
3. system matches seed entities from the query
4. graph expansion walks the unified entity graph
5. graph expansion returns extra evidence sources:
   - related document chunks
   - related personal asset units
6. downstream answer construction renders both source types explicitly

## 8. Operational Constraints

### 8.1 Failure Isolation

Asset-unit graph ingestion must be best-effort.

If extraction or projection fails:

- the `PersonalAssetUnit` confirmation should still succeed
- the failure should be logged clearly
- the graph state may lag behind source confirmation

This mirrors the current document-side fault isolation style.

### 8.2 Idempotency

Re-confirmation or manual retry must not create duplicate graph edges.

The asset-unit projection flow should:

- upsert entities
- upsert source node
- merge graph relationships
- clean or overwrite stale source-scoped relationships when needed

### 8.3 Latency

If synchronous confirm introduces poor UX, move extraction/projection to a background task. The logical design stays the same either way.

## 9. Why This Design

This is the recommended phase 1 because it:

- directly reuses the strongest existing path in the system
- unifies document and asset evidence around shared entities
- keeps document ingestion stable
- avoids prematurely rebuilding retrieval or knowledge governance
- creates a clean bridge to a future unified knowledge space

It is the smallest change that achieves the desired outcome:

"the same entity node can connect both uploaded document chunks and personal asset units."

## 10. Trade-Offs

### Pros

- smallest implementation scope
- low risk to current document retrieval
- fast path to a unified graph
- preserves future optionality for vectorizing asset units later

### Cons

- `PersonalAssetUnit` will not be directly retrieved by semantic search in phase 1
- asset-unit recall quality depends on entity extraction quality
- query patterns with weak entity signals may not surface asset units

## 11. Future Extensions

Possible later phases:

1. add vector indexing for `PersonalAssetUnit`
2. let asset units participate in hybrid recall
3. refactor document and asset projection into a generic `project_source_entities(...)`
4. introduce source container hierarchy if needed
5. add unified entity workbench and source drill-down UI

None of these are required for phase 1.

## 12. Acceptance Criteria

Phase 1 is successful when:

1. confirming a `PersonalAssetUnit` produces entity mentions and relations in MySQL
2. those mentions project into Neo4j as `Source(personal_asset_unit:<id>)`
3. the same `Entity` node can connect both:
   - `document_chunk:*`
   - `personal_asset_unit:*`
4. graph expansion can return personal asset units as evidence
5. response payloads clearly mark whether evidence came from a document chunk or a personal asset unit
6. the current document hybrid retrieval behavior remains unchanged
