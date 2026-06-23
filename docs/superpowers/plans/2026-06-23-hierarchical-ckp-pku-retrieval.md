# Hierarchical CKP/PKU Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a first-phase hierarchical governed retrieval chain where parent CKPs route by keyword/entity fields, child CKPs match by multiple retrieval vectors, and PKUs are recalled mainly from matched child CKPs with low-weight global PKU fallback.

**Architecture:** Add a focused child CKP retrieval-vector service, then layer a new `hierarchical_ckp_pku` query path beside the existing `governed_evidence` path. The new chain uses parent keyword routing, `CanonicalRelation.subtopic_of` child expansion, child multi-vector aggregation, local linked-PKU reranking, and conditional global PKU vector fallback. Query-time LLM rerank is explicitly out of scope for this phase.

**Tech Stack:** Python, SQLAlchemy, PyMilvus, OpenAI-compatible embeddings, pytest, existing Prism backend/engine/evaluation modules.

---

## File Structure

- Create `backend/app/services/child_ckp_vectors.py`
  - Owns Milvus collection `prism_child_ckp_retrieval`.
  - Provides `upsert_child_ckp_retrieval_vectors()`, `delete_child_ckp_retrieval_vectors()`, and `search_child_ckp_retrieval_vectors()`.

- Create `backend/tests/test_child_ckp_vectors.py`
  - Tests collection schema, multiple vector rows per child CKP, parent filters, and graceful no-provider behavior.

- Modify `backend/app/services/knowledge_governance.py`
  - Adds helpers to build child CKP retrieval payloads from linked PKUs.
  - Marks child CKP summary fields dirty when PKU links are created.
  - Refreshes parent CKP aggregate terms from child CKPs.
  - Refreshes child CKP retrieval vectors after child topic creation/update using existing fields first.

- Modify `backend/tests/test_document_chunk_pku_extraction.py`
  - Verifies child CKP retrieval metadata and parent aggregate terms are written during document governance settlement.

- Modify `backend/tests/test_asset_unit_pku_extraction.py`
  - Verifies the same metadata path for personal asset unit governance settlement.

- Modify `engine/app/agent/tools/governed_knowledge.py`
  - Adds parent keyword router.
  - Adds child CKP vector/keyword aggregation.
  - Adds local PKU reranking from matched child CKPs.
  - Adds global PKU fallback with `retrieval_path`.
  - Exposes `_query_hierarchical_ckp_pku()`.

- Modify `engine/tests/test_governed_knowledge_search.py`
  - Tests parent routing does not call CKP vector service.
  - Tests child multi-vector hits route to local PKUs.
  - Tests local PKU-only primary path and low-weight global fallback.

- Modify `engine/eval/compare_retrieval_chains.py`
  - Adds `hierarchical` chain.
  - Adds hierarchical parameters to `summary.json`.
  - Adds retrieval path diagnostics to verbose results.

- Modify `engine/tests/test_compare_retrieval_chains.py`
  - Tests chain map and metadata support for hierarchical chain.

- Modify `evaluation/README.md`
  - Documents how to run the hierarchical evaluation chain.

---

### Task 1: Child CKP Multi-Vector Service

**Files:**
- Create: `backend/app/services/child_ckp_vectors.py`
- Create: `backend/tests/test_child_ckp_vectors.py`

- [ ] **Step 1: Write failing tests for child CKP vector collection**

Create `backend/tests/test_child_ckp_vectors.py` with:

```python
def test_child_ckp_vectors_use_dedicated_collection(monkeypatch):
    from backend.app.services import child_ckp_vectors

    captured = {}

    class FakeUtility:
        @staticmethod
        def has_collection(name):
            captured["has_collection_name"] = name
            return False

    class FakeCollection:
        def __init__(self, name, schema):
            captured["collection_name"] = name
            captured["schema"] = schema

        def create_index(self, field_name, index_params):
            captured["index_field"] = field_name
            captured["index_params"] = index_params

    monkeypatch.setattr(child_ckp_vectors.connections, "connect", lambda **kwargs: None)
    monkeypatch.setattr(child_ckp_vectors, "utility", FakeUtility)
    monkeypatch.setattr(child_ckp_vectors, "Collection", FakeCollection)

    child_ckp_vectors.ensure_child_ckp_retrieval_collection()

    assert captured["has_collection_name"] == "prism_child_ckp_retrieval"
    assert captured["collection_name"] == "prism_child_ckp_retrieval"
    assert captured["index_field"] == "embedding"
    assert captured["index_params"]["metric_type"] == "COSINE"
```

```python
def test_upsert_child_ckp_retrieval_vectors_writes_multiple_rows(monkeypatch):
    from backend.app.models import CanonicalKnowledgePoint
    from backend.app.services import child_ckp_vectors

    calls = []

    class FakeCollection:
        def delete(self, expr):
            calls.append(("delete", expr))

        def insert(self, rows):
            calls.append(("insert", rows))

        def flush(self):
            calls.append(("flush", None))

    monkeypatch.setattr(child_ckp_vectors.settings, "EMBEDDING_API_BASE", "http://embedding.local/v1")
    monkeypatch.setattr(child_ckp_vectors.settings, "EMBEDDING_API_KEY", "test-key")
    monkeypatch.setattr(child_ckp_vectors, "embed_text", lambda text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(child_ckp_vectors, "ensure_child_ckp_retrieval_collection", lambda: FakeCollection())

    ckp = CanonicalKnowledgePoint(
        id="child-1",
        user_id="default-user",
        canonical_type="topic",
        title="Python project layering",
        canonical_statement="Python projects use layered modules.",
        summary="Python projects separate services and repositories.",
        confidence=0.8,
        extra_meta={
            "topic_level": "child",
            "key_facts": ["services hold business logic"],
            "retrieval_queries": ["FastAPI service repository 怎么拆"],
        },
    )

    vector_ids = child_ckp_vectors.upsert_child_ckp_retrieval_vectors(ckp, parent_ckp_id="parent-1")

    assert len(vector_ids) == 3
    assert [call[0] for call in calls] == ["delete", "insert", "flush"]
    rows = calls[1][1]
    assert rows[2] == ["child-1", "child-1", "child-1"]
    assert rows[3] == ["parent-1", "parent-1", "parent-1"]
    assert rows[5] == ["summary", "key_fact", "retrieval_query"]
```

```python
def test_search_child_ckp_retrieval_vectors_filters_by_parent_ids(monkeypatch):
    from backend.app.services import child_ckp_vectors

    captured = {}

    class FakeEntity:
        def __init__(self):
            self.data = {
                "ckp_id": "child-1",
                "parent_ckp_id": "parent-1",
                "user_id": "default-user",
                "vector_kind": "retrieval_query",
                "source_text": "FastAPI service repository 怎么拆",
            }

        def get(self, key):
            return self.data[key]

    class FakeHit:
        score = 0.91
        entity = FakeEntity()

    class FakeCollection:
        def load(self):
            captured["loaded"] = True

        def search(self, **kwargs):
            captured["expr"] = kwargs["expr"]
            captured["limit"] = kwargs["limit"]
            return [[FakeHit()]]

    monkeypatch.setattr(child_ckp_vectors.settings, "EMBEDDING_API_BASE", "http://embedding.local/v1")
    monkeypatch.setattr(child_ckp_vectors.settings, "EMBEDDING_API_KEY", "test-key")
    monkeypatch.setattr(child_ckp_vectors, "embed_text", lambda text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(child_ckp_vectors, "ensure_child_ckp_retrieval_collection", lambda: FakeCollection())

    hits = child_ckp_vectors.search_child_ckp_retrieval_vectors(
        text="FastAPI repository",
        user_id="default-user",
        parent_ckp_ids=["parent-1", "parent-2"],
        top_k=5,
    )

    assert captured["limit"] == 5
    assert 'user_id == "default-user"' in captured["expr"]
    assert 'parent_ckp_id in ["parent-1", "parent-2"]' in captured["expr"]
    assert hits == [
        {
            "ckp_id": "child-1",
            "parent_ckp_id": "parent-1",
            "score": 0.91,
            "user_id": "default-user",
            "vector_kind": "retrieval_query",
            "source_text": "FastAPI service repository 怎么拆",
        }
    ]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
python -m pytest backend\tests\test_child_ckp_vectors.py -v
```

Expected: fails because `backend.app.services.child_ckp_vectors` does not exist.

- [ ] **Step 3: Implement child CKP vector service**

Create `backend/app/services/child_ckp_vectors.py` with:

```python
import hashlib
import uuid
from typing import Any

from openai import OpenAI
from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

from backend.app.config import settings
from backend.app.models.knowledge_governance import CanonicalKnowledgePoint


CHILD_CKP_RETRIEVAL_COLLECTION_NAME = "prism_child_ckp_retrieval"
_embedding_client: OpenAI | None = None


def _connect_milvus() -> None:
    connections.connect(alias="default", host=settings.MILVUS_HOST, port=settings.MILVUS_PORT)


def ensure_child_ckp_retrieval_collection() -> Collection:
    _connect_milvus()
    if utility.has_collection(CHILD_CKP_RETRIEVAL_COLLECTION_NAME):
        return Collection(CHILD_CKP_RETRIEVAL_COLLECTION_NAME)

    fields = [
        FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=settings.EMBEDDING_DIM),
        FieldSchema(name="ckp_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="parent_ckp_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="user_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="vector_kind", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="source_text", dtype=DataType.VARCHAR, max_length=2048),
        FieldSchema(name="source_hash", dtype=DataType.VARCHAR, max_length=64),
    ]
    schema = CollectionSchema(fields, description="Prism child CKP retrieval vectors")
    collection = Collection(CHILD_CKP_RETRIEVAL_COLLECTION_NAME, schema)
    collection.create_index(
        field_name="embedding",
        index_params={"index_type": "IVF_FLAT", "metric_type": "COSINE", "params": {"nlist": 128}},
    )
    return collection


def _get_embedding_client() -> OpenAI:
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = OpenAI(base_url=settings.EMBEDDING_API_BASE, api_key=settings.EMBEDDING_API_KEY)
    return _embedding_client


def embed_text(text: str) -> list[float]:
    client = _get_embedding_client()
    response = client.embeddings.create(model=settings.EMBEDDING_MODEL, input=[text])
    return response.data[0].embedding


def _list_text(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def _source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _child_retrieval_entries(ckp: CanonicalKnowledgePoint) -> list[tuple[str, str]]:
    meta = ckp.extra_meta if isinstance(ckp.extra_meta, dict) else {}
    entries: list[tuple[str, str]] = []
    if ckp.summary:
        entries.append(("summary", str(ckp.summary).strip()))
    for text in _list_text(meta.get("key_facts"))[:8]:
        entries.append(("key_fact", text))
    for text in _list_text(meta.get("retrieval_queries"))[:8]:
        entries.append(("retrieval_query", text))
    if not entries:
        fallback = " ".join(part for part in [ckp.title, ckp.canonical_statement] if part)
        if fallback:
            entries.append(("summary", fallback[:2048]))
    return [(kind, text[:2048]) for kind, text in entries if text]


def delete_child_ckp_retrieval_vectors(ckp_id: str) -> None:
    collection = ensure_child_ckp_retrieval_collection()
    collection.delete(expr=f'ckp_id == "{ckp_id}"')
    collection.flush()


def upsert_child_ckp_retrieval_vectors(ckp: CanonicalKnowledgePoint, *, parent_ckp_id: str) -> list[str]:
    if not settings.EMBEDDING_API_BASE or not settings.EMBEDDING_API_KEY:
        return []
    entries = _child_retrieval_entries(ckp)
    if not entries:
        return []
    collection = ensure_child_ckp_retrieval_collection()
    collection.delete(expr=f'ckp_id == "{ckp.id}"')
    vector_ids: list[str] = []
    embeddings: list[list[float]] = []
    ckp_ids: list[str] = []
    parent_ids: list[str] = []
    user_ids: list[str] = []
    kinds: list[str] = []
    texts: list[str] = []
    hashes: list[str] = []
    for kind, text in entries:
        vector_id = f"child-ckp-{uuid.uuid4()}"
        vector_ids.append(vector_id)
        embeddings.append(embed_text(text))
        ckp_ids.append(str(ckp.id))
        parent_ids.append(str(parent_ckp_id))
        user_ids.append(str(ckp.user_id))
        kinds.append(kind)
        texts.append(text)
        hashes.append(_source_hash(text))
    collection.insert([vector_ids, embeddings, ckp_ids, parent_ids, user_ids, kinds, texts, hashes])
    collection.flush()
    return vector_ids


def search_child_ckp_retrieval_vectors(
    *,
    text: str,
    user_id: str,
    parent_ckp_ids: list[str],
    top_k: int = 20,
) -> list[dict[str, Any]]:
    if not settings.EMBEDDING_API_BASE or not settings.EMBEDDING_API_KEY or not parent_ckp_ids:
        return []
    embedding = embed_text(text)
    collection = ensure_child_ckp_retrieval_collection()
    collection.load()
    parent_expr = ", ".join(f'"{parent_id}"' for parent_id in parent_ckp_ids)
    expr = f'user_id == "{user_id}" && parent_ckp_id in [{parent_expr}]'
    results = collection.search(
        data=[embedding],
        anns_field="embedding",
        param={"metric_type": "COSINE", "params": {"nprobe": 32}},
        limit=top_k,
        expr=expr,
        output_fields=["ckp_id", "parent_ckp_id", "user_id", "vector_kind", "source_text"],
    )
    return [
        {
            "ckp_id": hit.entity.get("ckp_id"),
            "parent_ckp_id": hit.entity.get("parent_ckp_id"),
            "score": float(hit.score),
            "user_id": hit.entity.get("user_id"),
            "vector_kind": hit.entity.get("vector_kind"),
            "source_text": hit.entity.get("source_text"),
        }
        for hit in results[0]
    ]
```

- [ ] **Step 4: Run child vector tests**

Run:

```powershell
python -m pytest backend\tests\test_child_ckp_vectors.py -v
```

Expected: 3 passed.

---

### Task 2: Parent Aggregate Terms and Child Retrieval Metadata

**Files:**
- Modify: `backend/app/services/knowledge_governance.py`
- Modify: `backend/tests/test_document_chunk_pku_extraction.py`
- Modify: `backend/tests/test_asset_unit_pku_extraction.py`

- [ ] **Step 1: Write failing tests for metadata refresh**

In `backend/tests/test_document_chunk_pku_extraction.py`, add a test shaped like:

```python
def test_document_governance_refreshes_child_retrieval_and_parent_terms(monkeypatch, db_session):
    import backend.app.services.knowledge_governance as kg

    refreshed = []
    monkeypatch.setattr(kg, "_refresh_pku_vector", lambda pku: None)
    monkeypatch.setattr(
        kg,
        "upsert_child_ckp_retrieval_vectors",
        lambda ckp, parent_ckp_id: refreshed.append((ckp.id, parent_ckp_id)) or ["vec-1"],
    )

    # Use the existing document settlement fixture/helpers in this test file.
    # Create one KnowledgeItem with parent/child chunks and settle it.
    result = kg.settle_document_item_to_governance(db_session, item_id)

    parent_ckp = (
        db_session.query(kg.CanonicalKnowledgePoint)
        .filter(kg.CanonicalKnowledgePoint.extra_meta["topic_level"].as_string() == "parent")
        .first()
    )
    child_ckp = (
        db_session.query(kg.CanonicalKnowledgePoint)
        .filter(kg.CanonicalKnowledgePoint.extra_meta["topic_level"].as_string() == "child")
        .first()
    )

    assert result.canonical_count > 0
    assert refreshed
    assert child_ckp.extra_meta["summary_dirty"] is False
    assert isinstance(child_ckp.extra_meta["retrieval_terms"], list)
    assert isinstance(child_ckp.extra_meta["retrieval_queries"], list)
    assert isinstance(child_ckp.extra_meta["key_facts"], list)
    assert parent_ckp.extra_meta["child_title_terms"]
    assert "child_keyword_terms" in parent_ckp.extra_meta
```

In `backend/tests/test_asset_unit_pku_extraction.py`, add the equivalent assertion using the existing asset unit governance settlement test setup:

```python
def test_asset_unit_governance_refreshes_child_retrieval_and_parent_terms(monkeypatch, db_session):
    import backend.app.services.knowledge_governance as kg

    refreshed = []
    monkeypatch.setattr(kg, "_refresh_pku_vector", lambda pku: None)
    monkeypatch.setattr(
        kg,
        "upsert_child_ckp_retrieval_vectors",
        lambda ckp, parent_ckp_id: refreshed.append((ckp.id, parent_ckp_id)) or ["vec-1"],
    )

    result = kg.settle_asset_unit_to_governance(db_session, unit_id)

    assert result.canonical_count > 0
    assert refreshed
```

Adapt only fixture names to the exact fixtures already present in those test files. Keep the assertions above.

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
python -m pytest backend\tests\test_document_chunk_pku_extraction.py backend\tests\test_asset_unit_pku_extraction.py -k "retrieval_and_parent_terms" -v
```

Expected: fails because the metadata/vector refresh helpers are not implemented.

- [ ] **Step 3: Implement metadata helpers**

Modify `backend/app/services/knowledge_governance.py`:

Add import near vector imports:

```python
from backend.app.services.child_ckp_vectors import upsert_child_ckp_retrieval_vectors
```

Add helpers near `_topic_level()`:

```python
def _merge_unique_strings(*values: Any, limit: int = 80) -> list[str]:
    merged: list[str] = []
    for value in values:
        if not value:
            continue
        items = value if isinstance(value, list) else [value]
        for item in items:
            text = _normalize_space(str(item))
            if not text or text in merged:
                continue
            merged.append(text[:120])
            if len(merged) >= limit:
                return merged
    return merged


def _child_retrieval_queries_for_ckp(ckp: CanonicalKnowledgePoint, pkus: list[PersonalKnowledgeUnit]) -> list[str]:
    seeds = [ckp.title, ckp.summary, ckp.canonical_statement]
    seeds.extend(pku.normalized_statement or pku.statement for pku in pkus[:5])
    terms = _merge_unique_strings(seeds, limit=8)
    return [f"{term} 是什么？" if len(term) < 40 else term for term in terms[:8]]


def _refresh_child_ckp_retrieval_meta(
    db: Session,
    *,
    child_ckp: CanonicalKnowledgePoint,
    parent_ckp_id: str,
) -> None:
    links = db.query(PKUCanonicalLink).filter(PKUCanonicalLink.canonical_id == child_ckp.id).all()
    pkus = [link.pku for link in links if link.pku and link.pku.status == "active"]
    meta = dict(child_ckp.extra_meta or {})
    meta["topic_level"] = "child"
    meta["retrieval_terms"] = _merge_unique_strings(
        child_ckp.title,
        child_ckp.keywords or [],
        child_ckp.concepts or [],
        child_ckp.entities or [],
        [keyword for pku in pkus for keyword in (pku.keywords or [])],
        [entity for pku in pkus for entity in (pku.entities or [])],
        limit=80,
    )
    meta["key_facts"] = _merge_unique_strings(
        [pku.normalized_statement or pku.statement for pku in pkus],
        limit=8,
    )
    meta["retrieval_queries"] = _child_retrieval_queries_for_ckp(child_ckp, pkus)
    meta["summary_dirty"] = False
    meta["summary_updated_at"] = local_now().isoformat()
    child_ckp.extra_meta = meta
    upsert_child_ckp_retrieval_vectors(child_ckp, parent_ckp_id=parent_ckp_id)


def _refresh_parent_ckp_aggregate_terms(
    db: Session,
    *,
    parent_ckp: CanonicalKnowledgePoint,
) -> None:
    relations = (
        db.query(CanonicalRelation)
        .filter(
            CanonicalRelation.target_canonical_id == parent_ckp.id,
            CanonicalRelation.relation_type == "subtopic_of",
        )
        .all()
    )
    child_ids = [relation.source_canonical_id for relation in relations]
    children = db.query(CanonicalKnowledgePoint).filter(CanonicalKnowledgePoint.id.in_(child_ids)).all() if child_ids else []
    meta = dict(parent_ckp.extra_meta or {})
    meta["topic_level"] = "parent"
    meta["child_title_terms"] = _merge_unique_strings([child.title for child in children], limit=80)
    meta["child_keyword_terms"] = _merge_unique_strings([keyword for child in children for keyword in (child.keywords or [])], limit=120)
    meta["child_entity_terms"] = _merge_unique_strings([entity for child in children for entity in (child.entities or [])], limit=120)
    meta["child_concept_terms"] = _merge_unique_strings([concept for child in children for concept in (child.concepts or [])], limit=120)
    parent_ckp.extra_meta = meta
```

In `_settle_local_pku_topics()`, after all parent relations are created, add:

```python
    for parent_topic in parent_topics:
        ...
        for ref in member_refs:
            ...
            if relation:
                relation_ids.add(relation.id)
            _refresh_child_ckp_retrieval_meta(
                db,
                child_ckp=child_ckps_by_ref[ref],
                parent_ckp_id=parent_ckp.id,
            )
        _refresh_parent_ckp_aggregate_terms(db, parent_ckp=parent_ckp)
```

- [ ] **Step 4: Run metadata tests**

Run:

```powershell
python -m pytest backend\tests\test_document_chunk_pku_extraction.py backend\tests\test_asset_unit_pku_extraction.py -k "retrieval_and_parent_terms" -v
```

Expected: tests pass.

---

### Task 3: Hierarchical Parent and Child Candidate Retrieval

**Files:**
- Modify: `engine/app/agent/tools/governed_knowledge.py`
- Modify: `engine/tests/test_governed_knowledge_search.py`

- [ ] **Step 1: Write failing tests for parent keyword routing and child vector aggregation**

Add to `engine/tests/test_governed_knowledge_search.py`:

```python
def test_hierarchical_parent_route_uses_keywords_without_ckp_vector(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    parent = CanonicalKnowledgePoint(
        title="Python 工程结构",
        canonical_type="topic",
        canonical_statement="Python project structure topic.",
        summary="Directory routing only.",
        keywords=["python", "工程", "结构"],
        entities=["FastAPI"],
        user_id="default-user",
        confidence=0.8,
        extra_meta={"topic_level": "parent", "child_title_terms": ["service repository 分层"]},
    )
    session.add(parent)
    session.commit()
    session.close()

    monkeypatch.setattr(governed_tool, "_Session", Session)

    def fail_ckp_vector(**kwargs):
        raise AssertionError("parent route must not call CKP vector search")

    monkeypatch.setattr(governed_tool, "search_ckp_vectors", fail_ckp_vector)

    terms = governed_tool._query_terms("FastAPI service repository 分层")
    parents = governed_tool._hierarchical_parent_candidates(Session(), terms, limit=8)

    assert parents[0][0].title == "Python 工程结构"
    assert "service" in parents[0][2] or "repository" in parents[0][2]
```

```python
def test_hierarchical_child_candidates_use_parent_filtered_vectors(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    parent = CanonicalKnowledgePoint(
        title="Python 工程结构",
        canonical_type="topic",
        canonical_statement="Parent.",
        user_id="default-user",
        confidence=0.8,
        extra_meta={"topic_level": "parent", "child_title_terms": ["service repository"]},
    )
    child = CanonicalKnowledgePoint(
        title="Service Repository 分层",
        canonical_type="topic",
        canonical_statement="Services hold business logic and repositories handle data access.",
        summary="Service and repository responsibilities.",
        keywords=["service", "repository"],
        user_id="default-user",
        confidence=0.9,
        extra_meta={"topic_level": "child", "retrieval_terms": ["FastAPI", "service", "repository"]},
    )
    session.add_all([parent, child])
    session.flush()
    session.add(governed_tool.CanonicalRelation(
        source_canonical_id=child.id,
        target_canonical_id=parent.id,
        relation_type="subtopic_of",
        confidence=0.9,
        user_id="default-user",
    ))
    session.commit()
    parent_id = parent.id
    child_id = child.id
    session.close()

    monkeypatch.setattr(governed_tool, "_Session", Session)
    monkeypatch.setattr(
        governed_tool,
        "search_child_ckp_retrieval_vectors",
        lambda **kwargs: [
            {
                "ckp_id": child_id,
                "parent_ckp_id": parent_id,
                "score": 0.92,
                "vector_kind": "retrieval_query",
                "source_text": "FastAPI service repository 怎么拆",
            }
        ],
    )

    db = Session()
    parents = [(db.query(CanonicalKnowledgePoint).filter(CanonicalKnowledgePoint.id == parent_id).first(), 0.8, ["service"], ["service matched child_title_terms"])]
    children = governed_tool._hierarchical_child_candidates(db, "FastAPI repository", ["fastapi", "repository"], parents, limit_per_parent=3, global_limit=12)

    assert children[0]["ckp"].id == child_id
    assert children[0]["parent_ckp_id"] == parent_id
    assert children[0]["score"] > 0
    assert "retrieval_query" in " ".join(children[0]["reasons"])
    db.close()
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
python -m pytest engine\tests\test_governed_knowledge_search.py -k "hierarchical_parent_route or hierarchical_child_candidates" -v
```

Expected: fails because hierarchical helpers and import do not exist.

- [ ] **Step 3: Implement parent and child helpers**

Modify imports in `engine/app/agent/tools/governed_knowledge.py`:

```python
from backend.app.models.knowledge_governance import (
    CanonicalKnowledgePoint,
    CanonicalRelation,
    PKUCanonicalLink,
    PersonalKnowledgeUnit,
)
from backend.app.services.child_ckp_vectors import search_child_ckp_retrieval_vectors
```

Add constants near existing governed constants:

```python
_HIER_PARENT_TOP_N = 8
_HIER_CHILD_TOP_PER_PARENT = 3
_HIER_CHILD_GLOBAL_TOP_N = 12
_HIER_LOCAL_PKU_TOP_N = 20
_HIER_FINAL_EVIDENCE_TOP_N = 10
_HIER_MIN_EVIDENCE = 5
_HIER_LOCAL_PKU_MIN_SCORE = 0.25
_HIER_GLOBAL_PKU_FALLBACK_WEIGHT = 0.25
```

Add parent field/scoring helpers:

```python
_PARENT_FIELD_WEIGHTS = {
    "title": 5.0,
    "aliases": 4.5,
    "entities": 4.0,
    "child_title_terms": 3.5,
    "child_entity_terms": 3.5,
    "keywords": 3.0,
    "child_keyword_terms": 3.0,
    "concepts": 2.5,
    "child_concept_terms": 2.5,
    "domains": 1.0,
}


def _meta_list(ckp: CanonicalKnowledgePoint, key: str) -> list[str]:
    meta = ckp.extra_meta if isinstance(ckp.extra_meta, dict) else {}
    value = meta.get(key)
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if value:
        return [str(value)]
    return []


def _is_parent_ckp(ckp: CanonicalKnowledgePoint) -> bool:
    meta = ckp.extra_meta if isinstance(ckp.extra_meta, dict) else {}
    return str(meta.get("topic_level") or "") == "parent"


def _is_child_ckp(ckp: CanonicalKnowledgePoint) -> bool:
    meta = ckp.extra_meta if isinstance(ckp.extra_meta, dict) else {}
    return str(meta.get("topic_level") or "child") == "child"


def _parent_fields(ckp: CanonicalKnowledgePoint) -> dict[str, str]:
    return {
        "title": _normalize_text(ckp.title),
        "aliases": _normalize_text(ckp.aliases or []),
        "entities": _normalize_text(ckp.entities or []),
        "child_title_terms": _normalize_text(_meta_list(ckp, "child_title_terms")),
        "child_entity_terms": _normalize_text(_meta_list(ckp, "child_entity_terms")),
        "keywords": _normalize_text(ckp.keywords or []),
        "child_keyword_terms": _normalize_text(_meta_list(ckp, "child_keyword_terms")),
        "concepts": _normalize_text(ckp.concepts or []),
        "child_concept_terms": _normalize_text(_meta_list(ckp, "child_concept_terms")),
        "domains": _normalize_text(ckp.domains or []),
    }


def _score_parent_ckp(ckp: CanonicalKnowledgePoint, terms: list[str]) -> tuple[float, list[str], list[str]]:
    score, matched_terms, reasons = _score_fields(_parent_fields(ckp), terms, _PARENT_FIELD_WEIGHTS)
    if matched_terms:
        score += min(float(ckp.confidence or 0.0), 1.0)
    return round(score, 4), matched_terms, reasons


def _hierarchical_parent_candidates(db, terms: list[str], limit: int = _HIER_PARENT_TOP_N):
    rows = (
        db.query(CanonicalKnowledgePoint)
        .filter(
            CanonicalKnowledgePoint.user_id == "default-user",
            CanonicalKnowledgePoint.status != "deprecated",
            CanonicalKnowledgePoint.canonical_type == "topic",
        )
        .all()
    )
    scored = []
    for ckp in rows:
        if not _is_parent_ckp(ckp):
            continue
        score, matched_terms, reasons = _score_parent_ckp(ckp, terms)
        if not terms or matched_terms:
            scored.append((ckp, score, matched_terms, reasons))
    scored.sort(key=lambda item: (item[1], item[0].confidence or 0.0, item[0].updated_at), reverse=True)
    return scored[:limit]
```

Add child vector safe search and aggregation:

```python
def _safe_search_child_ckp_vectors(query: str, parent_ckp_ids: list[str], limit: int) -> list[dict[str, Any]]:
    try:
        return search_child_ckp_retrieval_vectors(
            text=query,
            user_id="default-user",
            parent_ckp_ids=parent_ckp_ids,
            top_k=limit,
        )
    except Exception:
        return []


def _vector_kind_boost(kind: str) -> float:
    if kind == "retrieval_query":
        return 1.0
    if kind == "key_fact":
        return 0.75
    if kind == "summary":
        return 0.5
    return 0.0


def _child_keyword_score(ckp: CanonicalKnowledgePoint, terms: list[str]) -> tuple[float, list[str], list[str]]:
    meta = ckp.extra_meta if isinstance(ckp.extra_meta, dict) else {}
    fields = {
        "title": _normalize_text(ckp.title),
        "summary": _normalize_text(ckp.summary),
        "canonical_statement": _normalize_text(ckp.canonical_statement),
        "keywords": _normalize_text(ckp.keywords or []),
        "concepts": _normalize_text(ckp.concepts or []),
        "entities": _normalize_text(ckp.entities or []),
        "retrieval_terms": _normalize_text(meta.get("retrieval_terms") or []),
        "key_facts": _normalize_text(meta.get("key_facts") or []),
    }
    return _score_fields(fields, terms, {
        "title": 4.0,
        "summary": 2.0,
        "canonical_statement": 2.0,
        "keywords": 3.0,
        "concepts": 2.0,
        "entities": 3.0,
        "retrieval_terms": 4.0,
        "key_facts": 3.0,
    })


def _hierarchical_child_candidates(
    db,
    query: str,
    terms: list[str],
    parent_hits: list[tuple[CanonicalKnowledgePoint, float, list[str], list[str]]],
    *,
    limit_per_parent: int = _HIER_CHILD_TOP_PER_PARENT,
    global_limit: int = _HIER_CHILD_GLOBAL_TOP_N,
) -> list[dict[str, Any]]:
    parent_ids = [str(parent.id) for parent, _score, _terms, _reasons in parent_hits]
    if not parent_ids:
        return []
    relations = (
        db.query(CanonicalRelation)
        .filter(CanonicalRelation.target_canonical_id.in_(parent_ids), CanonicalRelation.relation_type == "subtopic_of")
        .all()
    )
    child_to_parent = {str(relation.source_canonical_id): str(relation.target_canonical_id) for relation in relations}
    if not child_to_parent:
        return []
    children = db.query(CanonicalKnowledgePoint).filter(CanonicalKnowledgePoint.id.in_(child_to_parent.keys())).all()
    child_by_id = {str(child.id): child for child in children if _is_child_ckp(child)}
    parent_score = {str(parent.id): score for parent, score, _terms, _reasons in parent_hits}
    vector_hits = _safe_search_child_ckp_vectors(query, parent_ids, max(global_limit * 4, 30))
    best_vector_by_child: dict[str, dict[str, Any]] = {}
    for hit in vector_hits:
        child_id = str(hit.get("ckp_id") or "")
        if child_id not in child_by_id:
            continue
        if float(hit.get("score") or 0.0) > float(best_vector_by_child.get(child_id, {}).get("score") or -1.0):
            best_vector_by_child[child_id] = hit

    candidates: list[dict[str, Any]] = []
    for child_id, child in child_by_id.items():
        parent_id = child_to_parent[child_id]
        keyword_score, matched_terms, reasons = _child_keyword_score(child, terms)
        vector_hit = best_vector_by_child.get(child_id, {})
        vector_score = min(max(float(vector_hit.get("score") or 0.0), 0.0), 1.0)
        kind = str(vector_hit.get("vector_kind") or "")
        normalized_keyword = min(float(keyword_score or 0.0) / 20.0, 1.0)
        normalized_parent = min(float(parent_score.get(parent_id, 0.0) or 0.0) / 20.0, 1.0)
        combined = (
            0.45 * vector_score
            + 0.25 * normalized_keyword
            + 0.15 * normalized_parent
            + 0.10 * _vector_kind_boost(kind)
            + 0.05 * min(float(child.confidence or 0.0), 1.0)
        )
        if not vector_hit and not matched_terms:
            continue
        candidate_reasons = list(reasons)
        if vector_hit:
            candidate_reasons.append(f"child_vector {kind} score={vector_score:.4f}")
        candidates.append({
            "ckp": child,
            "parent_ckp_id": parent_id,
            "score": round(combined, 4),
            "matched_terms": matched_terms,
            "reasons": candidate_reasons[:8],
        })

    by_parent: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        by_parent.setdefault(candidate["parent_ckp_id"], []).append(candidate)
    limited: list[dict[str, Any]] = []
    for items in by_parent.values():
        items.sort(key=lambda item: (item["score"], item["ckp"].confidence or 0.0, item["ckp"].updated_at), reverse=True)
        limited.extend(items[:limit_per_parent])
    limited.sort(key=lambda item: (item["score"], item["ckp"].confidence or 0.0, item["ckp"].updated_at), reverse=True)
    return limited[:global_limit]
```

- [ ] **Step 4: Run hierarchical candidate tests**

Run:

```powershell
python -m pytest engine\tests\test_governed_knowledge_search.py -k "hierarchical_parent_route or hierarchical_child_candidates" -v
```

Expected: tests pass.

---

### Task 4: Local PKU Ranking and Global Fallback

**Files:**
- Modify: `engine/app/agent/tools/governed_knowledge.py`
- Modify: `engine/tests/test_governed_knowledge_search.py`

- [ ] **Step 1: Write failing tests for local PKU primary path and fallback**

Add to `engine/tests/test_governed_knowledge_search.py`:

```python
def test_hierarchical_query_prefers_local_child_pkus(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    item = KnowledgeItem(title="FastAPI architecture", content="Services hold business logic.", source_type="manual", user_id="default-user")
    session.add(item)
    session.flush()
    parent_chunk = KnowledgeChunk(item_id=item.id, chunk_text="Services hold business logic.", chunk_type="parent")
    session.add(parent_chunk)
    session.flush()
    child_chunk = KnowledgeChunk(item_id=item.id, parent_id=parent_chunk.id, chunk_text="Services hold business logic.", chunk_type="child")
    parent_ckp = CanonicalKnowledgePoint(
        title="Python 工程结构",
        canonical_type="topic",
        canonical_statement="Parent.",
        keywords=["python", "工程"],
        user_id="default-user",
        confidence=0.8,
        extra_meta={"topic_level": "parent", "child_title_terms": ["service repository"]},
    )
    child_ckp = CanonicalKnowledgePoint(
        title="Service Repository 分层",
        canonical_type="topic",
        canonical_statement="Services hold business logic.",
        summary="Service and repository responsibilities.",
        keywords=["service", "repository"],
        user_id="default-user",
        confidence=0.9,
        extra_meta={"topic_level": "child", "retrieval_terms": ["service", "repository"]},
    )
    session.add_all([parent_ckp, child_ckp])
    session.flush()
    pku = PersonalKnowledgeUnit(
        source_kind="document_chunk",
        source_id=parent_chunk.id,
        unit_type="claim",
        statement="Services hold business logic.",
        normalized_statement="services hold business logic",
        normalized_statement_hash="services-business-logic",
        evidence_span="Services hold business logic.",
        keywords=["service", "business", "logic"],
        user_id="default-user",
        confidence=0.9,
    )
    session.add(pku)
    session.flush()
    session.add_all([
        governed_tool.CanonicalRelation(
            source_canonical_id=child_ckp.id,
            target_canonical_id=parent_ckp.id,
            relation_type="subtopic_of",
            confidence=0.9,
            user_id="default-user",
        ),
        PKUCanonicalLink(
            pku_id=pku.id,
            canonical_id=child_ckp.id,
            relation_type="about",
            role="topic_member",
            confidence=0.85,
            user_id="default-user",
        ),
    ])
    session.commit()
    pku_id = pku.id
    child_chunk_id = child_chunk.id
    child_ckp_id = child_ckp.id
    session.close()

    monkeypatch.setattr(governed_tool, "_Session", Session)
    monkeypatch.setattr(governed_tool, "search_child_ckp_retrieval_vectors", lambda **kwargs: [])
    monkeypatch.setattr(governed_tool, "search_pku_vectors", lambda **kwargs: [])

    _terms, bundles, _knowledge = governed_tool._query_hierarchical_ckp_pku("service business logic", limit=5)

    assert bundles[0]["canonical_id"] == child_ckp_id
    assert bundles[0]["retrieval_mode"] == "hierarchical_ckp_pku"
    assert bundles[0]["linked_pkus"][0]["pku_id"] == pku_id
    assert bundles[0]["linked_pkus"][0]["retrieval_path"] == "parent_child_local_pku"
    assert bundles[0]["expanded_sources"][0]["chunk_id"] == child_chunk_id
```

```python
def test_hierarchical_query_uses_low_weight_global_pku_fallback(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    item = KnowledgeItem(title="Fallback evidence", content="A rare answer exists only in PKU vector fallback.", source_type="manual", user_id="default-user")
    session.add(item)
    session.flush()
    chunk = KnowledgeChunk(item_id=item.id, chunk_text="A rare answer exists only in PKU vector fallback.", chunk_type="parent")
    ckp = CanonicalKnowledgePoint(
        title="Fallback CKP",
        canonical_type="topic",
        canonical_statement="Fallback evidence.",
        keywords=["fallback"],
        user_id="default-user",
        confidence=0.6,
        extra_meta={"topic_level": "child"},
    )
    session.add_all([chunk, ckp])
    session.flush()
    pku = PersonalKnowledgeUnit(
        source_kind="document_chunk",
        source_id=chunk.id,
        unit_type="claim",
        statement="A rare answer exists only in PKU vector fallback.",
        normalized_statement="rare answer exists only in pku vector fallback",
        normalized_statement_hash="rare-fallback",
        evidence_span="A rare answer exists only in PKU vector fallback.",
        keywords=["rare", "fallback"],
        user_id="default-user",
        confidence=0.8,
    )
    session.add(pku)
    session.flush()
    session.add(PKUCanonicalLink(pku_id=pku.id, canonical_id=ckp.id, relation_type="about", role="fallback", confidence=0.7, user_id="default-user"))
    session.commit()
    pku_id = pku.id
    session.close()

    monkeypatch.setattr(governed_tool, "_Session", Session)
    monkeypatch.setattr(governed_tool, "search_child_ckp_retrieval_vectors", lambda **kwargs: [])
    monkeypatch.setattr(governed_tool, "search_pku_vectors", lambda **kwargs: [{"pku_id": pku_id, "score": 0.95}])

    _terms, bundles, _knowledge = governed_tool._query_hierarchical_ckp_pku("rare fallback answer", limit=5)

    assert bundles[0]["linked_pkus"][0]["pku_id"] == pku_id
    assert bundles[0]["linked_pkus"][0]["retrieval_path"] == "global_pku_fallback"
    assert bundles[0]["linked_pkus"][0]["pku_vector_score"] == 0.95
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
python -m pytest engine\tests\test_governed_knowledge_search.py -k "hierarchical_query" -v
```

Expected: fails because `_query_hierarchical_ckp_pku()` does not exist.

- [ ] **Step 3: Implement local PKU and fallback helpers**

Add to `engine/app/agent/tools/governed_knowledge.py`:

```python
def _local_pkus_for_child_candidates(db, child_candidates: list[dict[str, Any]], terms: list[str]) -> list[tuple[PersonalKnowledgeUnit, dict[str, Any], float, list[str], list[str]]]:
    rows: list[tuple[PersonalKnowledgeUnit, dict[str, Any], float, list[str], list[str]]] = []
    child_score_by_id = {str(item["ckp"].id): float(item["score"]) for item in child_candidates}
    for item in child_candidates:
        ckp = item["ckp"]
        links = db.query(PKUCanonicalLink).filter(PKUCanonicalLink.canonical_id == ckp.id).all()
        for link in links:
            if not link.pku or link.pku.status != "active":
                continue
            text_score, matched_terms, reasons = _score_fields(
                _pku_fields(link.pku),
                terms,
                {
                    "statement": 4.0,
                    "normalized_statement": 4.0,
                    "evidence_span": 5.0,
                    "keywords": 3.0,
                    "concepts": 2.0,
                    "entities": 2.0,
                },
            )
            normalized_text = min(float(text_score or 0.0) / 20.0, 1.0)
            combined = (
                0.35 * normalized_text
                + 0.20 * min(float(child_score_by_id.get(str(ckp.id), 0.0)), 1.0)
                + 0.10 * min(float(link.confidence or 0.0), 1.0)
                + 0.10 * min(float(link.pku.confidence or 0.0), 1.0)
            )
            payload = {
                "child_ckp_id": str(ckp.id),
                "child_score": float(item["score"]),
                "link_confidence": float(link.confidence or 0.0),
                "retrieval_path": "parent_child_local_pku",
                "pku_vector_score": 0.0,
            }
            rows.append((link.pku, payload, round(combined, 4), matched_terms, reasons))
    rows.sort(key=lambda row: (row[2], row[0].confidence or 0.0, row[0].updated_at), reverse=True)
    return rows[:_HIER_LOCAL_PKU_TOP_N]


def _global_pku_fallback_rows(db, terms: list[str], query: str, existing_pku_ids: set[str], limit: int) -> list[tuple[PersonalKnowledgeUnit, dict[str, Any], float, list[str], list[str]]]:
    hits = _safe_search_pku_vectors(query, limit)
    pku_ids = [str(hit.get("pku_id") or "") for hit in hits if hit.get("pku_id")]
    if not pku_ids:
        return []
    pku_by_id = {
        str(pku.id): pku
        for pku in db.query(PersonalKnowledgeUnit).filter(PersonalKnowledgeUnit.id.in_(pku_ids), PersonalKnowledgeUnit.status == "active").all()
    }
    score_by_id = {str(hit.get("pku_id")): float(hit.get("score") or 0.0) for hit in hits}
    rows = []
    for pku_id in pku_ids:
        if pku_id in existing_pku_ids or pku_id not in pku_by_id:
            continue
        pku = pku_by_id[pku_id]
        text_score, matched_terms, reasons = _score_fields(_pku_fields(pku), terms, {
            "statement": 4.0,
            "normalized_statement": 4.0,
            "evidence_span": 5.0,
            "keywords": 3.0,
            "concepts": 2.0,
            "entities": 2.0,
        })
        vector_score = min(max(score_by_id.get(pku_id, 0.0), 0.0), 1.0)
        combined = _HIER_GLOBAL_PKU_FALLBACK_WEIGHT * vector_score + 0.10 * min(float(text_score or 0.0) / 20.0, 1.0)
        payload = {
            "child_ckp_id": "",
            "child_score": 0.0,
            "link_confidence": 0.0,
            "retrieval_path": "global_pku_fallback",
            "pku_vector_score": vector_score,
        }
        rows.append((pku, payload, round(combined, 4), matched_terms, [*reasons, f"global_pku_vector score={vector_score:.4f}"]))
    rows.sort(key=lambda row: (row[2], row[0].confidence or 0.0, row[0].updated_at), reverse=True)
    return rows
```

Add bundle builder for hierarchical rows:

```python
def _hierarchical_bundle_from_pku_rows(db, rows, limit: int) -> list[dict[str, Any]]:
    bundles: list[dict[str, Any]] = []
    for pku, payload, score, matched_terms, reasons in rows[:limit]:
        source = _source_for_pku(db, pku)
        raw_sources = []
        expanded_sources = []
        if source:
            source["score"] = score
            source["raw_score"] = score
            source["retrieval_path"] = payload["retrieval_path"]
            raw_sources.append(source)
            for expanded_source in _expanded_sources_for_source(db, source):
                expanded_source["retrieval_path"] = payload["retrieval_path"]
                expanded_sources.append(expanded_source)
        bundles.append({
            "canonical_id": payload.get("child_ckp_id") or "",
            "canonical_type": "pku_evidence",
            "title": pku.statement[:80],
            "canonical_statement": pku.normalized_statement,
            "summary": pku.evidence_span,
            "status": pku.status,
            "confidence": pku.confidence,
            "score": score,
            "matched_terms": matched_terms,
            "match_reasons": reasons[:8],
            "retrieval_mode": "hierarchical_ckp_pku",
            "linked_pkus": [{
                "pku_id": pku.id,
                "statement": pku.statement,
                "normalized_statement": pku.normalized_statement,
                "unit_type": pku.unit_type,
                "modality": pku.modality,
                "source_kind": pku.source_kind,
                "source_id": pku.source_id,
                "confidence": pku.confidence,
                "evidence_score": score,
                "pku_vector_score": payload.get("pku_vector_score", 0.0),
                "matched_terms": matched_terms,
                "match_reasons": reasons[:8],
                "evidence_span": pku.evidence_span,
                "retrieval_path": payload["retrieval_path"],
                "child_ckp_id": payload.get("child_ckp_id", ""),
            }],
            "raw_sources": raw_sources,
            "expanded_sources": expanded_sources,
        })
    return bundles
```

Add main query:

```python
def _query_hierarchical_ckp_pku(query: str, limit: int) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    terms = _query_terms(query)
    db = _Session()
    try:
        parents = _hierarchical_parent_candidates(db, terms, _HIER_PARENT_TOP_N)
        children = _hierarchical_child_candidates(
            db,
            query,
            terms,
            parents,
            limit_per_parent=_HIER_CHILD_TOP_PER_PARENT,
            global_limit=_HIER_CHILD_GLOBAL_TOP_N,
        )
        local_rows = _local_pkus_for_child_candidates(db, children, terms)
        existing_ids = {str(row[0].id) for row in local_rows}
        should_fallback = (
            not parents
            or not children
            or len(local_rows) < _HIER_MIN_EVIDENCE
            or (local_rows and local_rows[0][2] < _HIER_LOCAL_PKU_MIN_SCORE)
        )
        fallback_rows = _global_pku_fallback_rows(db, terms, query, existing_ids, _HIER_LOCAL_PKU_TOP_N) if should_fallback else []
        rows = [*local_rows, *fallback_rows]
        rows.sort(key=lambda row: (row[2], row[0].confidence or 0.0, row[0].updated_at), reverse=True)
        return terms, _hierarchical_bundle_from_pku_rows(db, rows, limit), []
    finally:
        db.close()
```

- [ ] **Step 4: Run hierarchical query tests**

Run:

```powershell
python -m pytest engine\tests\test_governed_knowledge_search.py -k "hierarchical_query" -v
```

Expected: tests pass.

---

### Task 5: Evaluation Chain and Diagnostics

**Files:**
- Modify: `engine/eval/compare_retrieval_chains.py`
- Modify: `engine/tests/test_compare_retrieval_chains.py`
- Modify: `evaluation/README.md`

- [ ] **Step 1: Write failing evaluator tests**

Add to `engine/tests/test_compare_retrieval_chains.py`:

```python
def test_chain_map_supports_hierarchical_ckp_pku():
    assert "hierarchical" in eval_compare._chain_map()
    assert eval_compare._chain_map()["hierarchical"][0] == "hierarchical_ckp_pku"
```

```python
def test_hierarchical_params_document_layered_retrieval():
    params = eval_compare._hierarchical_params()

    assert params["parent_recall"] == "keyword_entity_only"
    assert params["child_recall"] == "multi_vector_plus_keyword"
    assert params["global_pku_fallback"] == "low_weight"
    assert params["llm_rerank"] is False
```

```python
def test_hierarchical_retriever_preserves_retrieval_path(monkeypatch):
    monkeypatch.setattr(
        eval_compare,
        "_query_hierarchical_ckp_pku",
        lambda query, limit: (
            [],
            [
                {
                    "canonical_id": "child-1",
                    "title": "Test child",
                    "score": 0.7,
                    "raw_sources": [
                        {
                            "source_kind": "document_chunk",
                            "chunk_id": "parent-1",
                            "item_id": "item-1",
                            "score": 0.7,
                            "retrieval_path": "parent_child_local_pku",
                        }
                    ],
                    "expanded_sources": [
                        {
                            "source_kind": "document_chunk",
                            "chunk_id": "child-chunk-1",
                            "item_id": "item-1",
                            "score": 0.7,
                            "retrieval_path": "parent_child_local_pku",
                        }
                    ],
                }
            ],
            [],
        ),
    )

    hits = eval_compare._hierarchical_ckp_pku("question", 10)

    assert hits[0]["source"] == "hierarchical_ckp_pku"
    assert hits[0]["retrieval_path"] == "parent_child_local_pku"
    assert hits[0]["expanded_child_ids"] == ["child-chunk-1"]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
python -m pytest engine\tests\test_compare_retrieval_chains.py -k "hierarchical" -v
```

Expected: fails because hierarchical evaluator functions are missing.

- [ ] **Step 3: Implement evaluator support**

Modify imports in `engine/eval/compare_retrieval_chains.py`:

```python
from engine.app.agent.tools.governed_knowledge import (
    _GOVERNED_EVIDENCE_PKU_VECTOR_WEIGHT as GOVERNED_EVIDENCE_PKU_VECTOR_WEIGHT,
    _HIER_CHILD_GLOBAL_TOP_N,
    _HIER_CHILD_TOP_PER_PARENT,
    _HIER_FINAL_EVIDENCE_TOP_N,
    _HIER_GLOBAL_PKU_FALLBACK_WEIGHT,
    _HIER_PARENT_TOP_N,
    _query_governed_evidence,
    _query_governed_knowledge,
    _query_hierarchical_ckp_pku,
)
```

Add:

```python
def _hierarchical_params() -> dict[str, Any]:
    return {
        "parent_recall": "keyword_entity_only",
        "parent_top_n": _HIER_PARENT_TOP_N,
        "child_recall": "multi_vector_plus_keyword",
        "child_top_per_parent": _HIER_CHILD_TOP_PER_PARENT,
        "child_global_top_n": _HIER_CHILD_GLOBAL_TOP_N,
        "local_pku_recall": "linked_pkus_under_matched_child_ckps",
        "global_pku_fallback": "low_weight",
        "global_pku_fallback_weight": _HIER_GLOBAL_PKU_FALLBACK_WEIGHT,
        "final_evidence_top_n": _HIER_FINAL_EVIDENCE_TOP_N,
        "llm_rerank": False,
    }
```

Add retriever:

```python
def _hierarchical_ckp_pku(query: str, top_k: int) -> list[dict[str, Any]]:
    _terms, bundles, _knowledge_results = _query_hierarchical_ckp_pku(query, limit=top_k)
    hits: list[dict[str, Any]] = []
    for bundle in bundles:
        expanded_ids = [
            str(source.get("chunk_id"))
            for source in bundle.get("expanded_sources", [])
            if source.get("source_kind") == "document_chunk" and source.get("chunk_id")
        ]
        for source in bundle.get("raw_sources", []):
            if source.get("source_kind") != "document_chunk":
                continue
            hits.append(
                {
                    "chunk_id": str(source.get("chunk_id") or source.get("source_id")),
                    "score": float(source.get("score") or bundle.get("score") or 0.0),
                    "source": "hierarchical_ckp_pku",
                    "retrieval_path": source.get("retrieval_path", ""),
                    "expanded_child_ids": expanded_ids,
                    "text": source.get("text") or source.get("snippet") or "",
                    "title": source.get("title") or source.get("display_title") or "",
                }
            )
    return hits[:top_k]
```

Extend `_chain_map()`:

```python
"hierarchical": ("hierarchical_ckp_pku", _hierarchical_ckp_pku),
```

Extend CLI choices:

```python
choices=["traditional", "governed", "governed_evidence", "hierarchical"],
```

Add to summary metadata:

```python
"hierarchical_params": _hierarchical_params(),
```

When writing verbose retrieved hits, keep `retrieval_path` if present.

- [ ] **Step 4: Run evaluator tests**

Run:

```powershell
python -m pytest engine\tests\test_compare_retrieval_chains.py -k "hierarchical" -v
```

Expected: tests pass.

- [ ] **Step 5: Update evaluation README**

Add to `evaluation/README.md`:

```markdown
### 分层 CKP/PKU 召回链路

运行父 CKP 关键词路由、子 CKP 多向量召回、PKU 局部证据召回链路：

```powershell
python -m engine.eval.compare_retrieval_chains --dataset evaluation/datasets/formal_docs_v1.json --chains traditional governed governed_evidence hierarchical --verbose
```

第一阶段不启用 query-time LLM rerank。重点观察 `summary.json` 中的 `hierarchical_params`、`retrieval_path` 分布和 Expanded MRR/Hit@10。
```

---

### Task 6: Verification, Evaluation Run, and Chinese Report

**Files:**
- Create: `evaluation/runs/retrieval/<timestamp>_compare/hierarchical_ckp_pku_retrieval_report.md`
- Modify: `evaluation/README.md`

- [ ] **Step 1: Run focused tests**

Run:

```powershell
python -m pytest backend\tests\test_child_ckp_vectors.py backend\tests\test_document_chunk_pku_extraction.py backend\tests\test_asset_unit_pku_extraction.py engine\tests\test_governed_knowledge_search.py engine\tests\test_compare_retrieval_chains.py -v
```

Expected: all selected tests pass.

- [ ] **Step 2: Run compile check**

Run:

```powershell
python -m py_compile backend\app\services\child_ckp_vectors.py backend\app\services\knowledge_governance.py engine\app\agent\tools\governed_knowledge.py engine\eval\compare_retrieval_chains.py
```

Expected: exit code 0.

- [ ] **Step 3: Run retrieval evaluation**

Run:

```powershell
python -m engine.eval.compare_retrieval_chains --dataset evaluation/datasets/formal_docs_v1.json --chains traditional governed governed_evidence hierarchical --verbose
```

Expected:

```text
evaluation/runs/retrieval/<timestamp>_compare/summary.json
evaluation/runs/retrieval/<timestamp>_compare/detailed_exact.csv
evaluation/runs/retrieval/<timestamp>_compare/detailed_expanded.csv
evaluation/runs/retrieval/<timestamp>_compare/detailed_verbose.json
```

- [ ] **Step 4: Write Chinese evaluation report**

Create `evaluation/runs/retrieval/<timestamp>_compare/hierarchical_ckp_pku_retrieval_report.md` with this structure:

```markdown
# 分层 CKP/PKU 召回链路评测报告

## 本轮改造

- 父 CKP 只做关键词/实体目录路由。
- 子 CKP 使用 summary、key_fact、retrieval_query 多向量召回。
- PKU 主通道限制在命中子 CKP 下。
- 全局 PKU vector 仅作为低权重兜底。
- 第一阶段未启用 query-time LLM rerank。

## 评测数据集

- 数据集：`evaluation/datasets/formal_docs_v1.json`
- 对比链路：`traditional_hybrid`、`governed_ckp_pku`、`governed_evidence`、`hierarchical_ckp_pku`

## 指标结果

从本次 run 的 `summary.json` 读取以下字段，生成四行指标表：

- `traditional_hybrid`
- `governed_ckp_pku`
- `governed_evidence`
- `hierarchical_ckp_pku`

每一行展示：

- `expanded.recall@10.mean`
- `expanded.mrr.mean`
- `expanded.hit@10.mean`
- `exact.recall@10.mean`

## 诊断结果

- 父层漏召样本：
- 子层漏召样本：
- 局部 PKU 排序错误样本：
- 全局兜底贡献：

## 结论

说明 hierarchical 链路是否提升 MRR、是否保持 Hit@10、全局兜底是否过度参与。

## 下一步

根据指标决定是否进入 query-time LLM rerank 阶段。
```

Before finalizing the report, verify every metric in the table is a numeric value copied from the generated `summary.json`.

- [ ] **Step 5: Update README with latest run**

Append a short note to `evaluation/README.md`:

```markdown
### 最新分层 CKP/PKU 评测

- Run: `evaluation/runs/retrieval/<timestamp>_compare/`
- Report: `evaluation/runs/retrieval/<timestamp>_compare/hierarchical_ckp_pku_retrieval_report.md`
```

- [ ] **Step 6: Final status**

Report to the user:

```text
已完成：
- 新增/修改的文件
- 通过的测试命令
- py_compile 结果
- 离线评测 run 目录
- hierarchical 指标与 governed_evidence 对比
- 下一阶段是否建议加入 LLM rerank
```

---

## Self-Review

Spec coverage:

- 父 CKP 关键词/实体目录路由：Task 3。
- 子 CKP 多向量 collection：Task 1。
- 子 CKP retrieval fields and parent aggregate terms：Task 2。
- PKU 局部主召回：Task 4。
- 全局 PKU 低权重兜底：Task 4。
- 第一阶段不启用 LLM rerank：Task 5 params and Task 6 report.
- 离线评测与诊断：Task 5 and Task 6。

Placeholder scan:

- The report task describes how to generate numeric metric rows from `summary.json`; it does not include metric cell placeholders.
- No implementation task uses open-ended placeholder instructions.

Type consistency:

- `CanonicalRelation` is imported from `backend.app.models.knowledge_governance`.
- `search_child_ckp_retrieval_vectors()` returns `ckp_id`, `parent_ckp_id`, `score`, `user_id`, `vector_kind`, and `source_text`.
- `_query_hierarchical_ckp_pku()` matches the existing governed query signature: `(terms, bundles, knowledge_results)`.
