# PersonalAssetUnit Entity Graph Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate `PersonalAssetUnit` into the existing entity graph so confirmed asset units can share `Entity` nodes with document chunks and be returned by graph expansion as evidence.

**Architecture:** Reuse the current document entity extraction and Neo4j projection model. Add a parallel asset-unit path that settles `personal_asset_unit` mentions/relations into the existing MySQL audit tables, projects them into the same `Entity`/`Source` graph, and extends graph expansion plus downstream evidence loading to recognize `personal_asset_unit:<id>` sources.

**Tech Stack:** FastAPI, SQLAlchemy ORM, Neo4j driver, pytest, existing Prism entity extraction/projection/retrieval modules

---

## File Map

**Modify:**

- `backend/app/api/assets.py`
  - Trigger asset-unit entity extraction/projection after confirm.
- `backend/app/services/graph_projection.py`
  - Add `project_asset_unit_entities(...)`.
- `engine/app/retrieval/graph_expand.py`
  - Return `personal_asset_unit` graph sources in addition to `document_chunk`.
- `engine/app/agent/tools/knowledge.py`
  - Load and serialize asset-unit evidence when search hits point at asset-unit sources.
- `frontend/src/pages/ChatPage.tsx`
  - Distinguish asset-unit sources from document chunk sources in the rendered source list if needed by the current payload shape.

**Test:**

- `backend/tests/test_graph_projection.py`
  - Cover asset-unit projection behavior.
- `backend/tests/test_assets_api.py`
  - Cover confirm-time entity graph trigger and best-effort failure isolation.
- `engine/tests/test_graph_expand.py`
  - Cover asset-unit graph source expansion.
- `engine/tests/test_agent_tool_evidence_payloads.py`
  - Cover asset-unit evidence payload resolution.

---

### Task 1: Add Projection Support for `PersonalAssetUnit`

**Files:**
- Modify: `backend/app/services/graph_projection.py`
- Test: `backend/tests/test_graph_projection.py`

- [ ] **Step 1: Write the failing projection test**

Add a new test to `backend/tests/test_graph_projection.py` that creates:

- one confirmed `PersonalAssetUnit`
- two settled `KnowledgeEntity` rows
- `EntityMention` rows with `source_kind="personal_asset_unit"` and `source_id=<unit.id>`
- one `EntityRelation` row with `source_kind="personal_asset_unit"`

Expected assertions:

- one `Source` node is upserted with `id="personal_asset_unit:<unit_id>"`
- both entities are upserted
- two `MENTIONED_IN` edges are written
- one `RELATED_TO` edge is written

Test skeleton:

```python
def test_project_asset_unit_entities_projects_source_mentions_and_relations():
    unit = PersonalAssetUnit(
        user_id="default-user",
        title="GraphRAG retrospective",
        summary="Summary",
        content="Entity-driven notes",
        status="confirmed",
    )
    db.add(unit)
    db.flush()

    entity_a = KnowledgeEntity(
        user_id="default-user",
        canonical_name="GraphRAG",
        normalized_key="graphrag",
        entity_type="concept",
        status="active",
        confidence=0.9,
    )
    entity_b = KnowledgeEntity(
        user_id="default-user",
        canonical_name="Neo4j",
        normalized_key="neo4j",
        entity_type="tool",
        status="active",
        confidence=0.9,
    )
    db.add_all([entity_a, entity_b])
    db.flush()

    db.add_all(
        [
            EntityMention(
                entity_id=entity_a.id,
                source_kind="personal_asset_unit",
                source_id=unit.id,
                item_id=None,
                confidence=0.8,
                evidence_span="GraphRAG",
            ),
            EntityMention(
                entity_id=entity_b.id,
                source_kind="personal_asset_unit",
                source_id=unit.id,
                item_id=None,
                confidence=0.8,
                evidence_span="Neo4j",
            ),
        ]
    )
    db.flush()

    db.add(
        EntityRelation(
            subject_entity_id=entity_a.id,
            object_entity_id=entity_b.id,
            predicate="related_to",
            source_kind="personal_asset_unit",
            source_id=unit.id,
            confidence=0.7,
        )
    )
    db.commit()

    fake = FakeGraph()
    result = project_asset_unit_entities(db, fake, asset_unit_id=unit.id, user_id="default-user")

    assert result == 3
    assert {"personal_asset_unit:" + unit.id} == {row["id"] for row in fake.sources}
    assert {entity_a.id, entity_b.id} == {row["id"] for row in fake.entities}
    assert sum(1 for row in fake.relations if row["rel_type"] == "MENTIONED_IN") == 2
    assert sum(1 for row in fake.relations if row["rel_type"] == "RELATED_TO") == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_t.db'; python -m pytest backend/tests/test_graph_projection.py::test_project_asset_unit_entities_projects_source_mentions_and_relations -v
```

Expected: FAIL because `project_asset_unit_entities` does not exist yet.

- [ ] **Step 3: Implement `project_asset_unit_entities(...)`**

In `backend/app/services/graph_projection.py`:

- import `PersonalAssetUnit`
- add helper `_source_node_for_asset_unit(unit: PersonalAssetUnit) -> dict`
- add `project_asset_unit_entities(db, graph, asset_unit_id: str, user_id: str = "default-user") -> int`

Implementation shape:

```python
def _source_node_for_asset_unit(unit: PersonalAssetUnit) -> dict:
    return {
        "id": f"personal_asset_unit:{unit.id}",
        "source_kind": "personal_asset_unit",
        "source_id": unit.id,
        "item_id": unit.id,
        "title": unit.title or unit.summary or unit.id,
    }


def project_asset_unit_entities(db, graph, asset_unit_id: str, user_id: str = "default-user") -> int:
    unit = (
        db.query(PersonalAssetUnit)
        .filter(
            PersonalAssetUnit.id == asset_unit_id,
            PersonalAssetUnit.user_id == user_id,
        )
        .one_or_none()
    )
    if unit is None:
        return 0

    mentions = (
        db.query(EntityMention)
        .join(KnowledgeEntity, EntityMention.entity_id == KnowledgeEntity.id)
        .filter(
            EntityMention.source_kind == "personal_asset_unit",
            EntityMention.source_id == asset_unit_id,
            KnowledgeEntity.status != "deprecated",
        )
        .all()
    )
    if not mentions:
        return 0

    source_node = _source_node_for_asset_unit(unit)
    graph.upsert_source(source_node)

    entity_cache: dict[str, KnowledgeEntity] = {}
    edges = 0
    for mention in mentions:
        entity = entity_cache.get(mention.entity_id)
        if entity is None:
            entity = db.query(KnowledgeEntity).filter_by(id=mention.entity_id).one_or_none()
            if entity is None:
                continue
            entity_cache[mention.entity_id] = entity
            graph.upsert_entity(
                {
                    "id": entity.id,
                    "user_id": entity.user_id,
                    "entity_type": entity.entity_type,
                    "canonical_name": entity.canonical_name,
                    "normalized_key": entity.normalized_key,
                    "status": entity.status,
                    "confidence": entity.confidence,
                }
            )
        graph.relate(
            "Entity",
            mention.entity_id,
            "MENTIONED_IN",
            "Source",
            source_node["id"],
            _relation_props(
                mention,
                ["confidence", "evidence_span", "extraction_method", "source_kind", "source_id"],
            ),
        )
        edges += 1

    relations = (
        db.query(EntityRelation)
        .filter(
            EntityRelation.source_kind == "personal_asset_unit",
            EntityRelation.source_id == asset_unit_id,
        )
        .all()
    )
    for relation in relations:
        if not relation.object_entity_id:
            continue
        graph.relate(
            "Entity",
            relation.subject_entity_id,
            "RELATED_TO",
            "Entity",
            relation.object_entity_id,
            _relation_props(
                relation,
                ["predicate", "confidence", "evidence_span", "extraction_method"],
            ),
        )
        edges += 1

    return edges
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_t.db'; python -m pytest backend/tests/test_graph_projection.py::test_project_asset_unit_entities_projects_source_mentions_and_relations -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/graph_projection.py backend/tests/test_graph_projection.py
git commit -m "feat: project personal asset unit entities to graph"
```

### Task 2: Trigger Asset-Unit Entity Graph Ingestion on Confirm

**Files:**
- Modify: `backend/app/api/assets.py`
- Test: `backend/tests/test_assets_api.py`

- [ ] **Step 1: Write the failing confirm-flow tests**

Add two tests to `backend/tests/test_assets_api.py`.

Test A: successful trigger

```python
def test_confirm_personal_asset_unit_triggers_entity_graph_ingestion(client, db_session, monkeypatch):
    calls = {}

    def fake_extract_stage_a_parallel(chunk_inputs):
        calls["chunk_inputs"] = chunk_inputs
        return {
            "unit-1": [
                EntityCandidate(
                    entity_type="concept",
                    canonical_name="GraphRAG",
                    aliases=["GraphRAG"],
                    confidence=0.9,
                    evidence_span="GraphRAG",
                    relations=[],
                )
            ]
        }

    def fake_project_asset_unit_entities(db, graph, asset_unit_id, user_id="default-user"):
        calls["projected"] = asset_unit_id
        return 1

    monkeypatch.setattr("backend.app.api.assets.extract_stage_a_parallel", fake_extract_stage_a_parallel)
    monkeypatch.setattr("backend.app.api.assets.project_asset_unit_entities", fake_project_asset_unit_entities)
    monkeypatch.setattr("backend.app.api.assets.GraphClient", FakeGraphClient)

    response = client.post(f"/api/v1/assets/personal_asset_units/{unit.id}/confirm")

    assert response.status_code == 200
    assert calls["projected"] == unit.id
    assert calls["chunk_inputs"] == [("unit-1", expected_text)]
```

Test B: best-effort failure isolation

```python
def test_confirm_personal_asset_unit_survives_entity_graph_failure(client, db_session, monkeypatch):
    monkeypatch.setattr(
        "backend.app.api.assets.extract_stage_a_parallel",
        lambda chunk_inputs: (_ for _ in ()).throw(RuntimeError("llm timeout")),
    )

    response = client.post(f"/api/v1/assets/personal_asset_units/{unit.id}/confirm")

    assert response.status_code == 200
    body = response.json()
    assert body["unit"]["status"] == "confirmed"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_t.db'; python -m pytest backend/tests/test_assets_api.py::test_confirm_personal_asset_unit_triggers_entity_graph_ingestion backend/tests/test_assets_api.py::test_confirm_personal_asset_unit_survives_entity_graph_failure -v
```

Expected: FAIL because confirm flow does not trigger entity graph ingestion.

- [ ] **Step 3: Implement confirm-time entity graph ingestion**

In `backend/app/api/assets.py`:

- import `extract_stage_a_parallel` from `engine.app.extraction.stage_a`
- import `settle_entity_candidates`
- import `GraphClient`
- import `project_asset_unit_entities`
- add helper `_asset_unit_entity_graph_text(unit: PersonalAssetUnit) -> str`
- add helper `_ingest_asset_unit_entity_graph(db: Session, unit: PersonalAssetUnit) -> None`

Helper shape:

```python
def _asset_unit_entity_graph_text(unit: PersonalAssetUnit) -> str:
    parts = [unit.title or "", unit.summary or "", unit.content or ""]
    return "\n\n".join(part.strip() for part in parts if part and part.strip())[:4000]


def _ingest_asset_unit_entity_graph(db: Session, unit: PersonalAssetUnit) -> None:
    text = _asset_unit_entity_graph_text(unit)
    if not text:
        return

    per_source = extract_stage_a_parallel([(unit.id, text)])
    candidates = per_source.get(unit.id, [])
    if not candidates:
        return

    settle_entity_candidates(
        db,
        candidates,
        source_kind="personal_asset_unit",
        source_id=unit.id,
        item_id=None,
        chunk_id=None,
        user_id=unit.user_id or DEFAULT_USER_ID,
    )
    db.flush()

    graph = GraphClient()
    try:
        project_asset_unit_entities(db, graph, asset_unit_id=unit.id, user_id=unit.user_id or DEFAULT_USER_ID)
    finally:
        graph.close()
```

In `confirm_personal_asset_unit(...)`, after `settle_personal_asset_unit_to_governance(db, unit)` and before final `db.commit()`:

```python
    try:
        _ingest_asset_unit_entity_graph(db, unit)
    except Exception:
        pass
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_t.db'; python -m pytest backend/tests/test_assets_api.py::test_confirm_personal_asset_unit_triggers_entity_graph_ingestion backend/tests/test_assets_api.py::test_confirm_personal_asset_unit_survives_entity_graph_failure -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add backend/app/api/assets.py backend/tests/test_assets_api.py
git commit -m "feat: ingest confirmed asset units into entity graph"
```

### Task 3: Extend Graph Expansion to Return Asset Units

**Files:**
- Modify: `engine/app/retrieval/graph_expand.py`
- Test: `engine/tests/test_graph_expand.py`

- [ ] **Step 1: Write the failing graph expansion test**

Add a test to `engine/tests/test_graph_expand.py`:

```python
def test_expand_candidates_returns_personal_asset_unit_sources():
    class FakeGraph:
        def neighbors(self, entity_id, hops=1, limit=8):
            return [{"id": "personal_asset_unit:unit-1", "kind": "Source"}]

        def entity_community(self, entity_id):
            return None

    hits = expand_candidates(
        db=None,
        graph=FakeGraph(),
        seed_entity_ids=["entity-1"],
        mode="fast",
        hops=1,
        max_candidates=10,
    )

    assert hits == [
        {
            "source_kind": "personal_asset_unit",
            "source_id": "unit-1",
            "source_marker": "graph_1hop",
        }
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_t.db'; python -m pytest engine/tests/test_graph_expand.py::test_expand_candidates_returns_personal_asset_unit_sources -v
```

Expected: FAIL because `expand_candidates` ignores non-`document_chunk:` source ids.

- [ ] **Step 3: Implement dual-source expansion**

In `engine/app/retrieval/graph_expand.py`, replace the chunk-only `_add_source(...)` behavior with source-aware payloads:

```python
    def _add_source(node_id: str, marker: str):
        if not node_id:
            return

        if node_id.startswith("document_chunk:"):
            source_kind = "document_chunk"
            source_id = node_id.split("document_chunk:", 1)[1]
        elif node_id.startswith("personal_asset_unit:"):
            source_kind = "personal_asset_unit"
            source_id = node_id.split("personal_asset_unit:", 1)[1]
        else:
            return

        dedupe_key = f"{source_kind}:{source_id}"
        if dedupe_key in seen_chunks:
            idx = _chunk_index.get(dedupe_key)
            if idx is not None:
                existing = candidates[idx].get("source_marker")
                if existing and marker not in existing:
                    candidates[idx]["source_marker"] = f"{existing}+{marker}"
            return

        seen_chunks.add(dedupe_key)
        idx = len(candidates)
        _chunk_index[dedupe_key] = idx
        candidates.append(
            {
                "source_kind": source_kind,
                "source_id": source_id,
                "source_marker": marker,
            }
        )
```

Also rename local dedupe variables from chunk-specific names to source-specific names if needed for clarity.

- [ ] **Step 4: Run the test to verify it passes**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_t.db'; python -m pytest engine/tests/test_graph_expand.py::test_expand_candidates_returns_personal_asset_unit_sources -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add engine/app/retrieval/graph_expand.py engine/tests/test_graph_expand.py
git commit -m "feat: return asset units from graph expansion"
```

### Task 4: Load Asset-Unit Evidence in Knowledge Search Results

**Files:**
- Modify: `engine/app/agent/tools/knowledge.py`
- Test: `engine/tests/test_agent_tool_evidence_payloads.py`

- [ ] **Step 1: Write the failing evidence payload test**

Add a test to `engine/tests/test_agent_tool_evidence_payloads.py` covering a search hit with:

```python
{
    "source_kind": "personal_asset_unit",
    "source_id": "unit-1",
    "source_marker": "graph_1hop",
    "score": 0.42,
}
```

Expected payload assertions:

- source label uses asset-unit title
- source type is `personal_asset_unit`
- source text includes `content` or `summary`

Test skeleton:

```python
def test_asset_unit_graph_hit_builds_asset_source_payload(monkeypatch):
    payload = _load_asset_unit_payload("unit-1")
    assert payload["source_type"] == "personal_asset_unit"
    assert payload["title"] == "GraphRAG retrospective"
    assert "entity-driven" in payload["text"].lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_t.db'; python -m pytest engine/tests/test_agent_tool_evidence_payloads.py::test_asset_unit_graph_hit_builds_asset_source_payload -v
```

Expected: FAIL because the asset-unit loader does not exist yet.

- [ ] **Step 3: Implement asset-unit evidence loading**

In `engine/app/agent/tools/knowledge.py`:

- add loader helper for `PersonalAssetUnit`
- when processing search hits, branch on `source_kind == "personal_asset_unit"`
- emit source payloads with source type preserved

Implementation shape:

```python
def _load_asset_unit_payload(db, unit_id: str) -> dict | None:
    unit = db.query(PersonalAssetUnit).filter(PersonalAssetUnit.id == unit_id).first()
    if unit is None:
        return None
    return {
        "source_type": "personal_asset_unit",
        "source_id": unit.id,
        "title": unit.title,
        "text": unit.content or unit.summary or "",
        "summary": unit.summary or "",
    }
```

And in the hit-to-source conversion path:

```python
if hit.get("source_kind") == "personal_asset_unit":
    payload = _load_asset_unit_payload(db, hit["source_id"])
elif hit.get("chunk_id"):
    payload = _load_chunk_payload(db, hit["chunk_id"])
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_t.db'; python -m pytest engine/tests/test_agent_tool_evidence_payloads.py::test_asset_unit_graph_hit_builds_asset_source_payload -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add engine/app/agent/tools/knowledge.py engine/tests/test_agent_tool_evidence_payloads.py
git commit -m "feat: load asset unit evidence from graph hits"
```

### Task 5: Run Focused Regression Verification

**Files:**
- Modify: none
- Test: `backend/tests/test_graph_projection.py`
- Test: `backend/tests/test_assets_api.py`
- Test: `engine/tests/test_graph_expand.py`
- Test: `engine/tests/test_agent_tool_evidence_payloads.py`

- [ ] **Step 1: Run backend-focused tests**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_t.db'; python -m pytest backend/tests/test_graph_projection.py backend/tests/test_assets_api.py -v
```

Expected: PASS

- [ ] **Step 2: Run engine-focused tests**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_t.db'; python -m pytest engine/tests/test_graph_expand.py engine/tests/test_agent_tool_evidence_payloads.py -v
```

Expected: PASS

- [ ] **Step 3: Run the narrow end-to-end confidence pass**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_t.db'; python -m pytest backend/tests/test_assets_api.py::test_confirm_personal_asset_unit_triggers_entity_graph_ingestion engine/tests/test_graph_expand.py::test_expand_candidates_returns_personal_asset_unit_sources -v
```

Expected: PASS

- [ ] **Step 4: Commit final verification-only state if needed**

```powershell
git status --short
```

Expected: no unexpected tracked modifications beyond the intended implementation.
