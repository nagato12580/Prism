# Knowledge Graph Outbox and Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make scoped MySQL graph facts authoritative, project them idempotently to Neo4j and Milvus through a transactional Outbox, publish graph generations atomically, and preserve Prism's current GraphRAG and governance behavior.

**Architecture:** Entity, Mention, Relation, extraction-revision, and graph-generation state live in MySQL under `tenant_id + kb_uid`; fact changes and immutable Outbox events commit in the same transaction. Engine projectors independently claim each event, use deterministic external IDs, record per-target receipts/retries, and allow `active_graph_generation` to switch only after required Neo4j and Milvus projections reach a validated barrier.

**Tech Stack:** Python 3.11, SQLAlchemy 2, Alembic, MySQL 8, Redis 7, Neo4j 5.28, Milvus 2.4, OpenAI-compatible embeddings/LLM, FastAPI, Pydantic 2, pytest

---

## Prerequisite and Fixed Names

Complete these plans first, in order:

1. `docs/superpowers/plans/2026-07-22-knowledge-foundation.md`
2. `docs/superpowers/plans/2026-07-22-knowledge-ingestion-generation.md`
3. `docs/superpowers/plans/2026-07-22-knowledge-retrieval-evaluation.md`
4. `docs/superpowers/plans/2026-07-22-knowledge-agent-tools-citations.md`

The following names and boundaries must remain unchanged: `ActorContext`, `KnowledgeAccessPolicy`, `KnowledgeJobService`, `JobCommand`, `EmbeddingProfile`, `SearchScope`, `ChannelResult`, `Candidate`, `Evidence`, `kb_uid`, `file_uid`, `chunk_uid`, `active_index_generation`, and `active_graph_generation`.

This plan adds these names exactly once:

- `KnowledgeGraphGeneration`: one graph build/publication record per configuration generation.
- `GraphExtractionRevision`: idempotent extraction identity for one Chunk content/config combination.
- `GraphOutboxEvent`: immutable MySQL event committed with graph fact changes.
- `GraphProjectionReceipt`: per-event, per-projector durable retry/cursor state.
- `GraphProjectionCursor`: contiguous applied sequence per projector and graph scope.
- projector names `neo4j` and `milvus_graph`.

Do not create a second graph fact store. Neo4j and Milvus are disposable projections. Do not replace `unified_search`, `graph_search`, `AgenticRagRunner`, or the six knowledge tools with parallel entry points.

## File Structure

- Create: `backend/alembic/versions/20260722_03_graph_outbox_governance.py` — scoped graph fact/outbox migration and legacy backfill.
- Modify: `backend/app/models/entity.py` — tenant/KB/generation/revision scope on Entity, Alias, Mention, and Relation facts.
- Create: `backend/app/models/graph_outbox.py` — generation, extraction revision, event, and projection receipt models.
- Modify: `backend/app/models/__init__.py` — register graph models.
- Create: `backend/app/services/graph_facts.py` — transaction-owned graph fact writer and file deactivation rules.
- Create: `backend/app/services/graph_outbox.py` — append, claim, retry, receipt, and barrier queries.
- Modify: `backend/app/services/entity_extraction.py` — delegate scoped writes without committing.
- Modify: `backend/app/services/graph_client.py` — fully scoped, generation-aware Neo4j operations.
- Modify: `backend/app/services/graph_projection.py` — deterministic payload builders retained for compatibility and replay.
- Modify: `backend/app/services/knowledge_cleanup.py` — deactivate only the deleted file's graph evidence.
- Create: `engine/app/graph/outbox_projector.py` — common projector loop and retry classification.
- Create: `engine/app/graph/neo4j_projector.py` — idempotent Neo4j projection.
- Create: `engine/app/indexing/graph_vector_index.py` — scoped graph-vector schema and deterministic upsert/delete.
- Create: `engine/app/graph/milvus_projector.py` — idempotent Entity/Relation graph-vector projection.
- Create: `engine/app/graph/generation.py` — build validation, barrier wait, and atomic activation.
- Modify: `engine/app/graph/pipeline.py` — extract facts/outbox first; remove direct projection from ingestion.
- Modify: `engine/app/graph/analyzer.py` — analyze one tenant/KB/generation and persist governed facts/outbox.
- Modify: `engine/app/graph/ckp_governance.py` — scope CKP governance and emit fact changes transactionally.
- Modify: `engine/app/jobs/knowledge_handlers.py` — graph build, projection replay, and re-extraction handlers.
- Modify: `engine/app/jobs/worker.py` — dispatch graph/projector jobs with lease heartbeat.
- Modify: `engine/app/retrieval/graph_expand.py` — require `SearchScope` for seeds and traversal.
- Modify: `engine/app/retrieval/unified.py` — preserve the existing Graph channel contract and degradation semantics.
- Create: `backend/app/api/knowledge_graph.py` — scoped graph status/build/replay/re-extract commands.
- Modify: `backend/app/api/__init__.py` — register graph routes.
- Modify: `backend/app/schemas/knowledge.py` — graph generation/status/command DTOs.
- Create: `backend/tests/test_graph_outbox_models.py`
- Create: `backend/tests/test_graph_fact_transaction.py`
- Create: `backend/tests/test_graph_fact_deletion.py`
- Create: `backend/tests/test_knowledge_graph_api.py`
- Create: `backend/tests/integration/test_graph_outbox_mysql.py`
- Create: `engine/tests/test_neo4j_outbox_projector.py`
- Create: `engine/tests/test_milvus_graph_projector.py`
- Create: `engine/tests/test_graph_generation_activation.py`
- Modify: `engine/tests/test_graph_analyzer.py`
- Modify: `engine/tests/test_ckp_governance.py`
- Modify: `engine/tests/test_graph_expand.py`
- Modify: `engine/tests/test_unified_retrieval.py`
- Create: `engine/tests/integration/test_graph_projection_recovery.py`
- Create: `engine/tests/integration/test_scoped_graph_rag.py`

## Task 1: Add Scoped Graph Facts, Generations, and Outbox Schema

**Files:**
- Create: `backend/alembic/versions/20260722_03_graph_outbox_governance.py`
- Modify: `backend/app/models/entity.py`
- Create: `backend/app/models/graph_outbox.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/tests/test_graph_outbox_models.py`
- Create: `backend/tests/integration/test_graph_outbox_mysql.py`

- [ ] **Step 1: Write failing model tests**

```python
# backend/tests/test_graph_outbox_models.py
from sqlalchemy.exc import IntegrityError

from backend.app.models import GraphOutboxEvent, GraphProjectionReceipt, KnowledgeEntity


def test_entity_identity_is_scoped_by_tenant_kb_and_generation(db_session):
    common = dict(entity_type="concept", normalized_key="prism", canonical_name="Prism")
    db_session.add_all([
        KnowledgeEntity(tenant_id="t1", kb_uid="k1", graph_generation="g1", **common),
        KnowledgeEntity(tenant_id="t1", kb_uid="k2", graph_generation="g1", **common),
    ])
    db_session.commit()
    assert db_session.query(KnowledgeEntity).count() == 2


def test_projection_receipt_is_unique_per_event_and_projector(db_session):
    event = GraphOutboxEvent(
        event_id="evt-1", tenant_id="t1", kb_uid="k1", graph_generation="g1",
        aggregate_type="mention", aggregate_id="mention-1", event_type="mention.upserted",
        payload={"mention_id": "mention-1"},
    )
    db_session.add(event)
    db_session.flush()
    db_session.add_all([
        GraphProjectionReceipt(event_id="evt-1", projector="neo4j"),
        GraphProjectionReceipt(event_id="evt-1", projector="neo4j"),
    ])
    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
    else:
        raise AssertionError("duplicate projection receipt was accepted")
```

- [ ] **Step 2: Run tests and confirm missing models/scope**

Run: `$env:DATABASE_URL='sqlite:///./_test.db'; python -m pytest backend/tests/test_graph_outbox_models.py -v`

Expected: FAIL because `GraphOutboxEvent`, `GraphProjectionReceipt`, and scoped Entity columns do not exist.

- [ ] **Step 3: Add the graph models**

```python
# backend/app/models/graph_outbox.py
import uuid

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import CHAR, JSON

from ..database import Base
from ..utils.time import local_now


def new_uuid() -> str:
    return str(uuid.uuid4())


class KnowledgeGraphGeneration(Base):
    __tablename__ = "knowledge_graph_generation"
    __table_args__ = (UniqueConstraint("tenant_id", "kb_uid", "generation", name="uq_graph_generation_scope"),)
    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    kb_uid = Column(CHAR(36), nullable=False, index=True)
    generation = Column(CHAR(36), nullable=False)
    extractor_config_hash = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False, default="building")
    barrier_sequence = Column(BigInteger, nullable=True)
    failure_code = Column(String(64), nullable=False, default="")
    failure_message = Column(Text)
    created_at = Column(DateTime, nullable=False, default=local_now)
    activated_at = Column(DateTime)


class GraphExtractionRevision(Base):
    __tablename__ = "graph_extraction_revision"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "kb_uid", "chunk_uid", "content_hash", "extractor_config_hash",
            name="uq_graph_extraction_key",
        ),
    )
    revision_id = Column(CHAR(36), primary_key=True, default=new_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    kb_uid = Column(CHAR(36), nullable=False, index=True)
    file_uid = Column(CHAR(36), nullable=False, index=True)
    item_id = Column(CHAR(36), nullable=False, index=True)
    chunk_uid = Column(CHAR(36), nullable=False, index=True)
    graph_generation = Column(CHAR(36), nullable=False, index=True)
    content_hash = Column(String(64), nullable=False)
    extractor_config_hash = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False, default="running")
    model_version = Column(String(255), nullable=False)
    prompt_version = Column(String(128), nullable=False)
    created_at = Column(DateTime, nullable=False, default=local_now)


MYSQL_SEQUENCE = BigInteger().with_variant(Integer, "sqlite")


class GraphOutboxEvent(Base):
    __tablename__ = "graph_outbox_event"
    sequence = Column(MYSQL_SEQUENCE, primary_key=True, autoincrement=True)
    event_id = Column(CHAR(36), nullable=False, unique=True, default=new_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    kb_uid = Column(CHAR(36), nullable=False, index=True)
    graph_generation = Column(CHAR(36), nullable=False, index=True)
    aggregate_type = Column(String(32), nullable=False)
    aggregate_id = Column(CHAR(36), nullable=False)
    event_type = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=local_now)
    __table_args__ = (Index("ix_graph_outbox_scope_sequence", "tenant_id", "kb_uid", "graph_generation", "sequence"),)


class GraphProjectionReceipt(Base):
    __tablename__ = "graph_projection_receipt"
    __table_args__ = (
        UniqueConstraint("event_id", "projector", name="uq_graph_projection_event_target"),
        Index("ix_graph_projection_due", "projector", "status", "next_attempt_at"),
    )
    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    event_id = Column(CHAR(36), ForeignKey("graph_outbox_event.event_id", ondelete="CASCADE"), nullable=False)
    projector = Column(String(32), nullable=False)
    status = Column(String(24), nullable=False, default="pending")
    attempt = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=8)
    next_attempt_at = Column(DateTime, nullable=False, default=local_now)
    lease_owner = Column(String(128), nullable=False, default="")
    lease_expires_at = Column(DateTime)
    last_error_code = Column(String(64), nullable=False, default="")
    last_error_message = Column(Text)
    applied_at = Column(DateTime)
    applied_sequence = Column(BigInteger)


class GraphProjectionCursor(Base):
    __tablename__ = "graph_projection_cursor"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "kb_uid", "graph_generation", "projector",
            name="uq_graph_projection_cursor_scope",
        ),
    )
    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    tenant_id = Column(String(64), nullable=False)
    kb_uid = Column(CHAR(36), nullable=False)
    graph_generation = Column(CHAR(36), nullable=False)
    projector = Column(String(32), nullable=False)
    applied_through_sequence = Column(BigInteger, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False, default=local_now, onupdate=local_now)
```

- [ ] **Step 4: Scope existing fact models**

Add non-null `tenant_id`, `kb_uid`, and `graph_generation` to `KnowledgeEntity`, `EntityAlias`, `EntityMention`, and `EntityRelation`. Add `file_uid`, `chunk_uid`, `revision_id`, `active`, `char_start`, and `char_end` to Mention; add `file_uid`, `revision_id`, and `active` to Relation. Replace the old user-only Entity unique key with:

```python
UniqueConstraint(
    "tenant_id", "kb_uid", "graph_generation", "entity_type", "normalized_key",
    name="uq_entity_scope_type_key",
)
```

Keep `user_id` only as a compatibility/audit column. New graph queries must not use it as scope.

- [ ] **Step 5: Write the additive/backfill migration**

Set `revision="20260722_03"` and `down_revision="20260722_02"`, then implement:

1. create the four new tables above;
2. add scoped columns nullable first;
3. backfill `tenant_id/kb_uid/file_uid/chunk_uid` by joining Topic/File/Item/Chunk stable IDs created in Plans 1–2;
4. create one legacy graph generation per KB and set Topic `active_graph_generation` to it;
5. backfill Mention/Relation `revision_id`, `active=1`, and fact generation;
6. move the identifiers and reason for rows that cannot be assigned to a KB into `graph_scope_migration_audit(id, table_name, row_id, reason, created_at)` before making scope columns non-null; abort the migration when this table is non-empty so no fact is silently discarded;
7. replace old unique indexes with scoped unique indexes;
8. implement downgrade by dropping only these new constraints/tables/columns.

- [ ] **Step 6: Verify migration on real MySQL**

Run:

```powershell
docker compose up -d mysql
if (-not $env:PRISM_TEST_DATABASE_URL) { throw 'PRISM_TEST_DATABASE_URL must target the dedicated prism_test MySQL database' }
$env:DATABASE_URL=$env:PRISM_TEST_DATABASE_URL
alembic upgrade 20260722_01
alembic upgrade head
python -m pytest backend/tests/integration/test_graph_outbox_mysql.py -v
```

Expected: migration reaches head; scoped unique constraints reject only same-scope duplicates; Outbox sequence is monotonic.

- [ ] **Step 7: Commit scoped graph schema**

```powershell
git add backend/alembic/versions/20260722_03_graph_outbox_governance.py backend/app/models/entity.py backend/app/models/graph_outbox.py backend/app/models/__init__.py backend/tests/test_graph_outbox_models.py backend/tests/integration/test_graph_outbox_mysql.py
git commit -m "feat(graph): 增加图事实作用域与 outbox 模型"
```

## Task 2: Commit Graph Facts and Outbox Events Atomically

**Files:**
- Create: `backend/app/services/graph_facts.py`
- Create: `backend/app/services/graph_outbox.py`
- Modify: `backend/app/services/entity_extraction.py`
- Create: `backend/tests/test_graph_fact_transaction.py`
- Modify: `backend/tests/test_entity_settle.py`
- Create: `backend/tests/integration/test_graph_outbox_mysql.py`

- [ ] **Step 1: Write rollback and extraction-key tests**

```python
# backend/tests/test_graph_fact_transaction.py
import pytest

from backend.app.models import EntityMention, GraphOutboxEvent
from backend.app.services.graph_facts import GraphFactScope, GraphFactWriter


def test_fact_and_outbox_roll_back_together(db_session, monkeypatch):
    writer = GraphFactWriter(db_session)
    scope = GraphFactScope("t1", "k1", "f1", "i1", "c1", "g1")
    monkeypatch.setattr(writer.outbox, "append", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        with db_session.begin():
            writer.settle(scope, candidates=[entity_candidate("Prism")], content_hash="a" * 64, extractor_config_hash="b" * 64)
    assert db_session.query(EntityMention).count() == 0
    assert db_session.query(GraphOutboxEvent).count() == 0


def test_same_extraction_key_returns_existing_revision(db_session):
    writer = GraphFactWriter(db_session)
    scope = GraphFactScope("t1", "k1", "f1", "i1", "c1", "g1")
    first = writer.settle(scope, [entity_candidate("Prism")], "a" * 64, "b" * 64)
    second = writer.settle(scope, [entity_candidate("Prism")], "a" * 64, "b" * 64)
    assert second.revision_id == first.revision_id
    assert db_session.query(GraphOutboxEvent).count() == first.event_count
```

- [ ] **Step 2: Run and verify the writer is absent**

Run: `$env:DATABASE_URL='sqlite:///./_test.db'; python -m pytest backend/tests/test_graph_fact_transaction.py -v`

Expected: FAIL with import error for `GraphFactWriter`.

- [ ] **Step 3: Implement transaction-owned fact writes**

```python
# backend/app/services/graph_facts.py
from dataclasses import dataclass
from hashlib import sha256

from backend.app.models import GraphExtractionRevision
from backend.app.services.graph_outbox import GraphOutboxService


@dataclass(frozen=True)
class GraphFactScope:
    tenant_id: str
    kb_uid: str
    file_uid: str
    item_id: str
    chunk_uid: str
    graph_generation: str


class GraphFactWriter:
    def __init__(self, db):
        self.db = db
        self.outbox = GraphOutboxService(db)

    def extraction_key(self, scope: GraphFactScope, content_hash: str, extractor_config_hash: str) -> str:
        raw = "|".join((scope.kb_uid, scope.chunk_uid, content_hash, extractor_config_hash))
        return sha256(raw.encode("utf-8")).hexdigest()

    def settle(self, scope, candidates, content_hash, extractor_config_hash):
        revision = self._get_or_create_revision(scope, content_hash, extractor_config_hash)
        if revision.status == "succeeded":
            return revision
        changed = self._upsert_scoped_facts(scope, revision.revision_id, candidates)
        for fact in changed:
            self.outbox.append_fact_change(scope, fact)
        revision.status = "succeeded"
        self.db.flush()
        return revision
```

`_upsert_scoped_facts` must use the exact scope on every Entity/Alias/Mention/Relation lookup. It deactivates the prior active revision for the same Chunk only after all replacement facts and their Outbox events are staged. This service calls `flush()` but never `commit()` or `rollback()`.

- [ ] **Step 4: Implement append and receipt creation**

```python
# backend/app/services/graph_outbox.py
REQUIRED_PROJECTORS = ("neo4j", "milvus_graph")


class GraphOutboxService:
    def __init__(self, db):
        self.db = db

    def append(self, *, scope, aggregate_type, aggregate_id, event_type, payload):
        event = GraphOutboxEvent(
            tenant_id=scope.tenant_id, kb_uid=scope.kb_uid,
            graph_generation=scope.graph_generation, aggregate_type=aggregate_type,
            aggregate_id=aggregate_id, event_type=event_type, payload=payload,
        )
        self.db.add(event)
        self.db.flush()
        for projector in REQUIRED_PROJECTORS:
            self.db.add(GraphProjectionReceipt(event_id=event.event_id, projector=projector))
        return event
```

Payloads contain public IDs, normalized names, evidence positions, confidence, and version fields. They must not contain document text beyond the bounded evidence span, API keys, provider responses, or `storage_uri`.

- [ ] **Step 5: Route current extraction through the writer**

Change `settle_entity_candidates` to require `GraphFactScope` on the new knowledge path and delegate to `GraphFactWriter`. Keep one explicitly named `settle_legacy_entity_candidates` adapter for non-KB personal assets until cutover; it cannot be called by `engine/app/graph/pipeline.py`.

- [ ] **Step 6: Run unit and MySQL atomicity tests**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_test.db'
python -m pytest backend/tests/test_graph_fact_transaction.py backend/tests/test_entity_settle.py -v
if (-not $env:PRISM_TEST_DATABASE_URL) { throw 'PRISM_TEST_DATABASE_URL must target the dedicated prism_test MySQL database' }
$env:DATABASE_URL=$env:PRISM_TEST_DATABASE_URL
python -m pytest backend/tests/integration/test_graph_outbox_mysql.py -v
```

Expected: all tests PASS; forced failure leaves neither facts nor events; duplicate extraction creates no additional events.

- [ ] **Step 7: Commit atomic fact writing**

```powershell
git add backend/app/services/graph_facts.py backend/app/services/graph_outbox.py backend/app/services/entity_extraction.py backend/tests/test_graph_fact_transaction.py backend/tests/test_entity_settle.py backend/tests/integration/test_graph_outbox_mysql.py
git commit -m "feat(graph): 原子提交图事实与 outbox 事件"
```

## Task 3: Project Outbox Events to Neo4j Idempotently

**Files:**
- Modify: `backend/app/services/graph_client.py`
- Modify: `backend/app/services/graph_projection.py`
- Create: `engine/app/graph/outbox_projector.py`
- Create: `engine/app/graph/neo4j_projector.py`
- Modify: `engine/app/jobs/worker.py`
- Create: `engine/tests/test_neo4j_outbox_projector.py`
- Create: `engine/tests/integration/test_graph_projection_recovery.py`

- [ ] **Step 1: Write duplicate-delivery and retry tests**

```python
# engine/tests/test_neo4j_outbox_projector.py
def test_duplicate_event_converges_to_one_mention(fake_graph, outbox_event, receipt_store):
    projector = Neo4jOutboxProjector(fake_graph, receipt_store)
    projector.apply(outbox_event)
    projector.apply(outbox_event)
    assert fake_graph.count_relationships("MENTIONED_IN", mention_id="mention-1") == 1
    assert receipt_store.status(outbox_event.event_id, "neo4j") == "applied"


def test_transient_neo4j_failure_is_scheduled_for_retry(fake_graph, outbox_event, receipt_store):
    fake_graph.fail_once(ConnectionError("neo4j unavailable"))
    Neo4jOutboxProjector(fake_graph, receipt_store).apply(outbox_event)
    receipt = receipt_store.get(outbox_event.event_id, "neo4j")
    assert receipt.status == "retry"
    assert receipt.attempt == 1
    assert receipt.next_attempt_at is not None
    assert receipt.last_error_code == "NEO4J_UNAVAILABLE"
```

- [ ] **Step 2: Run and verify projector import failure**

Run: `$env:DATABASE_URL='sqlite:///./_test.db'; python -m pytest engine/tests/test_neo4j_outbox_projector.py -v`

Expected: FAIL because `Neo4jOutboxProjector` is absent.

- [ ] **Step 3: Implement common claim/retry behavior**

```python
# engine/app/graph/outbox_projector.py
from dataclasses import dataclass
from datetime import timedelta
import random


@dataclass(frozen=True)
class ProjectionFailure:
    code: str
    retryable: bool


def retry_delay(attempt: int, jitter: float | None = None) -> timedelta:
    seconds = min(2 ** max(attempt - 1, 0), 300)
    return timedelta(seconds=seconds + (random.random() if jitter is None else jitter))


class OutboxProjectorLoop:
    def __init__(self, projector, receipts, worker_id: str):
        self.projector = projector
        self.receipts = receipts
        self.worker_id = worker_id

    def run_batch(self, limit: int = 100) -> int:
        claimed = self.receipts.claim_due(
            projector=self.projector.name, worker_id=self.worker_id, limit=limit,
        )
        for event, receipt in claimed:
            self.projector.apply(event, receipt)
        return len(claimed)
```

`claim_due` uses MySQL `SELECT ... FOR UPDATE SKIP LOCKED`, a 60-second lease, and conditional receipt updates. `mark_applied` stores `applied_sequence` and advances `GraphProjectionCursor.applied_through_sequence` only across a contiguous run of applied receipts; an out-of-order success cannot jump over a failed event. Retryable failures are connection reset, timeout, 429, and dependency unavailability. Invalid payload, unknown event type, missing scope, and dimension mismatch become terminal `failed` receipts.

- [ ] **Step 4: Make Neo4j writes deterministic and scoped**

```python
# engine/app/graph/neo4j_projector.py
class Neo4jOutboxProjector:
    name = "neo4j"

    def __init__(self, graph, receipts):
        self.graph = graph
        self.receipts = receipts

    def apply(self, event, receipt=None):
        handler = {
            "entity.upserted": self._upsert_entity,
            "mention.upserted": self._upsert_mention,
            "mention.removed": self._remove_mention,
            "relation.upserted": self._upsert_relation,
            "relation.removed": self._remove_relation,
            "entity.removed": self._remove_entity,
            "analysis.updated": self._update_analysis,
        }.get(event.event_type)
        if handler is None:
            return self.receipts.fail(event.event_id, self.name, "GRAPH_EVENT_UNSUPPORTED", retryable=False)
        try:
            handler(event)
            self.receipts.mark_applied(event.event_id, self.name, event.sequence)
        except Exception as exc:
            self.receipts.record_failure(event.event_id, self.name, classify_neo4j_error(exc))
```

Every Neo4j node key is `(tenant_id, kb_uid, graph_generation, id)`. Every relationship uses fact ID as `mention_id` or `relation_id`; repeated `MERGE` updates properties instead of creating another edge. Every read/traversal Cypher clause repeats the same scope. Remove methods delete one fact edge and delete Entity nodes only on explicit `entity.removed` events.

- [ ] **Step 5: Remove direct projection from ingestion**

`engine/app/graph/pipeline.py` must stop calling `project_item_entities` after extraction. It commits MySQL facts/events, enqueues projector work by event/receipt availability, and returns. Retain payload builders in `graph_projection.py` for replay tests, but no production ingestion path may write Neo4j before the MySQL transaction commits.

- [ ] **Step 6: Verify crash recovery with real Neo4j**

Run:

```powershell
docker compose up -d mysql neo4j
if (-not $env:PRISM_TEST_DATABASE_URL) { throw 'PRISM_TEST_DATABASE_URL must target the dedicated prism_test MySQL database' }
$env:DATABASE_URL=$env:PRISM_TEST_DATABASE_URL
python -m pytest engine/tests/test_neo4j_outbox_projector.py engine/tests/integration/test_graph_projection_recovery.py -v -k neo4j
```

Expected: PASS; stopping Neo4j produces retry receipts, restarting and replaying reaches one node/edge per fact.

- [ ] **Step 7: Commit Neo4j projector**

```powershell
git add backend/app/services/graph_client.py backend/app/services/graph_projection.py engine/app/graph/outbox_projector.py engine/app/graph/neo4j_projector.py engine/app/graph/pipeline.py engine/app/jobs/worker.py engine/tests/test_neo4j_outbox_projector.py engine/tests/integration/test_graph_projection_recovery.py
git commit -m "feat(graph): 增加幂等 Neo4j outbox 投影"
```

## Task 4: Project Graph Vectors to Milvus Idempotently

**Files:**
- Create: `engine/app/indexing/graph_vector_index.py`
- Create: `engine/app/graph/milvus_projector.py`
- Modify: `engine/app/graph/outbox_projector.py`
- Create: `engine/tests/test_milvus_graph_projector.py`
- Modify: `engine/tests/integration/test_graph_projection_recovery.py`

- [ ] **Step 1: Write stable-ID and outage tests**

```python
# engine/tests/test_milvus_graph_projector.py
def test_entity_upsert_uses_stable_vector_id(fake_graph_index, event, receipts):
    event.event_type = "entity.upserted"
    event.aggregate_id = "entity-1"
    projector = MilvusGraphProjector(fake_graph_index, fake_embedder, receipts)
    projector.apply(event)
    projector.apply(event)
    assert fake_graph_index.ids == ["g1:entity:entity-1"]


def test_dimension_mismatch_is_terminal(fake_graph_index, event, receipts):
    fake_graph_index.expected_dimension = 1024
    fake_embedder.dimension = 768
    MilvusGraphProjector(fake_graph_index, fake_embedder, receipts).apply(event)
    receipt = receipts.get(event.event_id, "milvus_graph")
    assert receipt.status == "failed"
    assert receipt.last_error_code == "GRAPH_VECTOR_DIMENSION_MISMATCH"
```

- [ ] **Step 2: Run and verify missing graph index**

Run: `$env:DATABASE_URL='sqlite:///./_test.db'; python -m pytest engine/tests/test_milvus_graph_projector.py -v`

Expected: FAIL because graph-vector modules are absent.

- [ ] **Step 3: Implement the scoped graph-vector index**

```python
# engine/app/indexing/graph_vector_index.py
from dataclasses import dataclass


@dataclass(frozen=True)
class GraphVectorRow:
    vector_id: str
    tenant_id: str
    kb_uid: str
    generation: str
    fact_type: str
    fact_id: str
    text_hash: str
    embedding_model_version: str
    embedding: list[float]


def graph_vector_id(generation: str, fact_type: str, fact_id: str) -> str:
    return f"{generation}:{fact_type}:{fact_id}"


class GraphVectorIndex:
    def __init__(self, milvus, profile):
        self.milvus = milvus
        self.profile = profile
        self.collection = profile.graph_collection

    def upsert(self, row: GraphVectorRow) -> None:
        if len(row.embedding) != self.profile.dimension:
            raise GraphVectorDimensionMismatch(self.profile.dimension, len(row.embedding))
        self.milvus.upsert(self.collection, [row.__dict__])

    def delete(self, vector_id: str, tenant_id: str, kb_uid: str, generation: str) -> None:
        expr = (
            f'vector_id == "{escape(vector_id)}" and tenant_id == "{escape(tenant_id)}" '
            f'and kb_uid == "{escape(kb_uid)}" and generation == "{escape(generation)}"'
        )
        self.milvus.delete(self.collection, expr)
```

The collection is `EmbeddingProfile.graph_collection` from Plan 2 and includes native scalar indexes for `tenant_id`, `kb_uid`, `generation`, `fact_type`, and `fact_id`. Entity text is canonical name + aliases + description; Relation text is subject + predicate + object. Evidence text is not embedded into Entity identity.

- [ ] **Step 4: Implement the Milvus projector**

Handle `entity.upserted`, `relation.upserted`, `entity.removed`, and `relation.removed`. Mention-only events are acknowledged without a vector write. Compute embedding only when payload `text_hash` differs from the currently indexed row. Upsert by deterministic `graph_vector_id`; retry transient HTTP/Milvus errors and fail dimension/config errors terminally.

- [ ] **Step 5: Verify recovery with real Milvus**

Run:

```powershell
docker compose up -d etcd minio milvus mysql
if (-not $env:PRISM_TEST_DATABASE_URL) { throw 'PRISM_TEST_DATABASE_URL must target the dedicated prism_test MySQL database' }
$env:DATABASE_URL=$env:PRISM_TEST_DATABASE_URL
python -m pytest engine/tests/test_milvus_graph_projector.py engine/tests/integration/test_graph_projection_recovery.py -v -k milvus
```

Expected: PASS; duplicate delivery leaves one vector; temporary Milvus outage retries and converges after restart.

- [ ] **Step 6: Commit Milvus graph projector**

```powershell
git add engine/app/indexing/graph_vector_index.py engine/app/graph/milvus_projector.py engine/app/graph/outbox_projector.py engine/tests/test_milvus_graph_projector.py engine/tests/integration/test_graph_projection_recovery.py
git commit -m "feat(graph): 增加幂等 Milvus 图向量投影"
```

## Task 5: Build and Activate Graph Generations Atomically

**Files:**
- Create: `engine/app/graph/generation.py`
- Modify: `engine/app/graph/pipeline.py`
- Modify: `engine/app/graph/analyzer.py`
- Modify: `engine/app/jobs/knowledge_handlers.py`
- Create: `engine/tests/test_graph_generation_activation.py`
- Modify: `engine/tests/test_graph_analyzer.py`

- [ ] **Step 1: Write failed-build and successful-barrier tests**

```python
# engine/tests/test_graph_generation_activation.py
def test_failed_build_keeps_old_active_generation(db_session, generation_service):
    topic = make_topic(db_session, active_graph_generation="old")
    generation_service.projectors.fail("milvus_graph", "new")
    result = generation_service.build_and_activate(topic.kb_uid, expected_active="old", generation="new")
    db_session.refresh(topic)
    assert result.status == "failed"
    assert topic.active_graph_generation == "old"


def test_activation_waits_for_both_projectors(db_session, generation_service):
    generation_service.receipts.mark_scope_applied("t1", "k1", "new", "neo4j", through=42)
    assert generation_service.try_activate("t1", "k1", "old", "new", barrier=42) is False
    generation_service.receipts.mark_scope_applied("t1", "k1", "new", "milvus_graph", through=42)
    assert generation_service.try_activate("t1", "k1", "old", "new", barrier=42) is True
```

- [ ] **Step 2: Run and verify missing generation service**

Run: `$env:DATABASE_URL='sqlite:///./_test.db'; python -m pytest engine/tests/test_graph_generation_activation.py -v`

Expected: FAIL because `GraphGenerationService` is absent.

- [ ] **Step 3: Implement generation build and barrier validation**

```python
# engine/app/graph/generation.py
class GraphGenerationService:
    required_projectors = ("neo4j", "milvus_graph")

    def try_activate(self, tenant_id, kb_uid, expected_active, generation, barrier):
        if not all(
            self.receipts.is_applied_through(tenant_id, kb_uid, generation, name, barrier)
            for name in self.required_projectors
        ):
            return False
        self.validator.validate(tenant_id, kb_uid, generation)
        updated = (
            self.db.query(KnowledgeTopic)
            .filter_by(tenant_id=tenant_id, kb_uid=kb_uid, active_graph_generation=expected_active)
            .update({
                "active_graph_generation": generation,
                "graph_status": "ready",
            })
        )
        if updated != 1:
            self.db.rollback()
            return False
        self.db.query(KnowledgeGraphGeneration).filter_by(
            tenant_id=tenant_id, kb_uid=kb_uid, generation=generation,
        ).update({"status": "active", "activated_at": local_now()})
        self.db.commit()
        return True
```

The validator checks MySQL fact counts, active Mention back-links, Neo4j node/edge counts, Milvus graph-vector counts/dimension, scope sampling, and absence of terminal required-projector receipts through the barrier.

- [ ] **Step 4: Preserve incremental semantics**

- Extractor model, prompt, schema, or normalization changes create a new `KnowledgeGraphGeneration`, re-extract all active Chunks, project beside the old generation, validate, and CAS-switch.
- File add/update under unchanged extractor config uses the current graph generation and creates only new `GraphExtractionRevision` rows/events.
- A file reaches `graph_status=ready` only when both required projector receipts for that file's revision are applied.
- A terminal receipt sets graph generation/file status to `degraded`; it never marks Dense/BM25 indexing failed.
- Old generation cleanup runs only after activation and retention, and it never deletes the active generation.

- [ ] **Step 5: Scope graphify analysis**

Change `export_graph_for_graphify` and `run_analysis` to require `tenant_id`, `kb_uid`, and `graph_generation`. Persist community/god/surprising/diagnostic results as MySQL governed state plus `analysis.updated` Outbox events; do not write Neo4j directly from `run_analysis`.

- [ ] **Step 6: Run generation/analyzer tests**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_test.db'
python -m pytest engine/tests/test_graph_generation_activation.py engine/tests/test_graph_analyzer.py -v
```

Expected: PASS; failed generation preserves old active; analysis never reads another KB/generation.

- [ ] **Step 7: Commit graph generation publication**

```powershell
git add engine/app/graph/generation.py engine/app/graph/pipeline.py engine/app/graph/analyzer.py engine/app/jobs/knowledge_handlers.py engine/tests/test_graph_generation_activation.py engine/tests/test_graph_analyzer.py
git commit -m "feat(graph): 原子发布 active graph generation"
```

## Task 6: Delete File Mentions Without Deleting Shared Entities

**Files:**
- Modify: `backend/app/services/graph_facts.py`
- Modify: `backend/app/services/knowledge_cleanup.py`
- Modify: `engine/app/jobs/knowledge_handlers.py`
- Create: `backend/tests/test_graph_fact_deletion.py`
- Modify: `engine/tests/integration/test_graph_projection_recovery.py`

- [ ] **Step 1: Write shared-entity deletion tests**

```python
# backend/tests/test_graph_fact_deletion.py
def test_delete_file_deactivates_only_its_mentions(db_session, graph_facts):
    shared = graph_facts.entity("Prism", files=("file-a", "file-b"))
    events = graph_facts.deactivate_file("t1", "k1", "g1", "file-a")
    assert active_mentions(db_session, shared.id) == ["file-b"]
    assert "entity.removed" not in [event.event_type for event in events]
    assert "mention.removed" in [event.event_type for event in events]


def test_last_active_mention_emits_entity_removal(db_session, graph_facts):
    entity = graph_facts.entity("Solo", files=("file-a",))
    events = graph_facts.deactivate_file("t1", "k1", "g1", "file-a")
    assert active_mentions(db_session, entity.id) == []
    assert [event.event_type for event in events].count("entity.removed") == 1
```

- [ ] **Step 2: Run and verify current delete semantics fail**

Run: `$env:DATABASE_URL='sqlite:///./_test.db'; python -m pytest backend/tests/test_graph_fact_deletion.py -v`

Expected: FAIL because file-scoped Mention deactivation and orphan rules are absent.

- [ ] **Step 3: Implement file-scoped deactivation**

```python
# backend/app/services/graph_facts.py
def deactivate_file(self, tenant_id: str, kb_uid: str, generation: str, file_uid: str):
    scope_filter = dict(
        tenant_id=tenant_id, kb_uid=kb_uid,
        graph_generation=generation, file_uid=file_uid, active=True,
    )
    mentions = self.db.query(EntityMention).filter_by(**scope_filter).with_for_update().all()
    relations = self.db.query(EntityRelation).filter_by(**scope_filter).with_for_update().all()
    events = []
    for fact in [*mentions, *relations]:
        fact.active = False
        events.append(self.outbox.append_removal(fact))
    self.db.flush()
    for entity_id in {mention.entity_id for mention in mentions}:
        remaining = self.db.query(EntityMention.id).filter_by(
            tenant_id=tenant_id, kb_uid=kb_uid, graph_generation=generation,
            entity_id=entity_id, active=True,
        ).first()
        if remaining is None:
            events.append(self.outbox.append_entity_removal(tenant_id, kb_uid, generation, entity_id))
    return events
```

Relation projection is removed only when the deleted file supplied that relation evidence. If another active Relation fact supports the same subject/predicate/object triple, its deterministic edge remains. MySQL Entity rows remain as audit facts; `status=orphaned` excludes them from active retrieval until a new Mention reactivates them.

- [ ] **Step 4: Wire cleanup checkpoint ordering**

In `KnowledgeCleanup`, the graph checkpoint becomes: begin transaction -> deactivate file Mentions/Relations + append events -> commit -> wait/retry projectors asynchronously. Storage and Item/Chunk physical cleanup can continue after the fact transaction commits. Repeating the cleanup finds inactive facts and emits no duplicate events.

- [ ] **Step 5: Run unit and projection recovery tests**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_test.db'
python -m pytest backend/tests/test_graph_fact_deletion.py backend/tests/test_knowledge_cleanup.py -v
if (-not $env:PRISM_TEST_DATABASE_URL) { throw 'PRISM_TEST_DATABASE_URL must target the dedicated prism_test MySQL database' }
$env:DATABASE_URL=$env:PRISM_TEST_DATABASE_URL
python -m pytest engine/tests/integration/test_graph_projection_recovery.py -v -k delete
```

Expected: deleting file A removes only A's edges/vectors; shared Entity and file B evidence remain queryable; retry is a no-op.

- [ ] **Step 6: Commit safe graph deletion**

```powershell
git add backend/app/services/graph_facts.py backend/app/services/knowledge_cleanup.py engine/app/jobs/knowledge_handlers.py backend/tests/test_graph_fact_deletion.py engine/tests/integration/test_graph_projection_recovery.py
git commit -m "fix(graph): 删除文件时保留共享实体"
```

## Task 7: Scope GraphRAG and Governance Without Replacing the Main Chain

**Files:**
- Modify: `backend/app/services/graph_client.py`
- Modify: `engine/app/retrieval/graph_expand.py`
- Modify: `engine/app/retrieval/unified.py`
- Modify: `engine/app/graph/ckp_governance.py`
- Modify: `engine/app/graph/insights.py`
- Modify: `engine/tests/test_graph_expand.py`
- Modify: `engine/tests/test_unified_retrieval.py`
- Modify: `engine/tests/test_ckp_governance.py`
- Create: `engine/tests/integration/test_scoped_graph_rag.py`

- [ ] **Step 1: Write cross-KB and degradation tests**

```python
# engine/tests/integration/test_scoped_graph_rag.py
def test_graph_search_never_crosses_kb_scope(scoped_graph_fixture):
scope = SearchScope(tenant_id="t1", kb_uid="kb-a", index_generation="index-a", graph_generation="graph-a")
    result = graph_search("shared term", scope, scoped_graph_fixture.client, top_k=30, hops=2)
    assert result.status == "ok"
    assert result.candidates
    assert {candidate.kb_uid for candidate in result.candidates} == {"kb-a"}


def test_graph_outage_degrades_existing_text_results(monkeypatch, scope):
    monkeypatch.setattr("engine.app.retrieval.unified.graph_search", failed_graph_channel)
    result = unified_search("query", scope=scope, top_k=8)
    assert result.status == "degraded"
    assert result.evidence
    assert result.channel_health["graph"].status == "failed"
```

- [ ] **Step 2: Run and verify scope signatures fail**

Run: `$env:DATABASE_URL='sqlite:///./_test.db'; python -m pytest engine/tests/test_graph_expand.py engine/tests/test_unified_retrieval.py -v`

Expected: FAIL because current graph seed/traversal methods do not require `SearchScope`.

- [ ] **Step 3: Require SearchScope at every graph read**

```python
# engine/app/retrieval/graph_expand.py
def match_seed_entities(db, query: str, scope: SearchScope, limit: int = 10) -> list[str]:
    return [
        row.id
        for row in (
            db.query(KnowledgeEntity.id)
            .filter_by(
                tenant_id=scope.tenant_id,
                kb_uid=scope.kb_uid,
                graph_generation=scope.graph_generation,
                status="active",
            )
            .filter(KnowledgeEntity.normalized_key.in_(query_keys(query)))
            .limit(limit)
            .all()
        )
    ]


def graph_search(query: str, scope: SearchScope, graph_client, top_k: int, hops: int) -> ChannelResult:
    seeds = match_seed_entities(graph_client.db, query, scope)
    candidates = graph_client.expand(scope=scope, seed_ids=seeds, hops=hops, limit=top_k)
    return ChannelResult(channel="graph", health="ok", candidates=candidates)
```

Update `neighbors`, `community_members`, `god_neighbors`, `surprising_endpoints`, `entity_path`, and source-link explanation to take scope and include `tenant_id + kb_uid + graph_generation` in every Neo4j node match. Graph-vector seed queries use the same scope as native Milvus pre-filter.

- [ ] **Step 4: Preserve unified retrieval behavior**

`unified_search` continues to call Dense, BM25, and Graph once, applies the single Weighted RRF from Plan 3, reranks text, and returns canonical `Evidence`. Graph uses `scope.graph_generation` resolved from Topic `active_graph_generation`; document channels use `scope.index_generation` resolved from Topic `active_index_generation`. A missing graph generation, projector lag, or graph dependency failure returns a failed/degraded `ChannelResult`, never `[]` disguised as `no_hits`.

- [ ] **Step 5: Scope governance and insights**

`run_analysis`, `govern_ckp_status_by_graph`, community persistence, and graph insights all require `tenant_id/kb_uid/generation`. Only active/approved PKU/CKP facts participate in answer evidence. `INFERRED` paths retain their full path and never become extracted fact evidence. Governance fact updates append `analysis.updated` events in the same MySQL transaction.

- [ ] **Step 6: Run focused and real-scope tests**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_test.db'
python -m pytest engine/tests/test_graph_expand.py engine/tests/test_unified_retrieval.py engine/tests/test_ckp_governance.py engine/tests/test_graph_insights.py -v
if (-not $env:PRISM_TEST_DATABASE_URL) { throw 'PRISM_TEST_DATABASE_URL must target the dedicated prism_test MySQL database' }
$env:DATABASE_URL=$env:PRISM_TEST_DATABASE_URL
python -m pytest engine/tests/integration/test_scoped_graph_rag.py -v
```

Expected: PASS; identical entities in two KBs never cross; graph outage returns `degraded` with Dense/BM25 Evidence.

- [ ] **Step 7: Commit scoped GraphRAG and governance**

```powershell
git add backend/app/services/graph_client.py engine/app/retrieval/graph_expand.py engine/app/retrieval/unified.py engine/app/graph/ckp_governance.py engine/app/graph/insights.py engine/tests/test_graph_expand.py engine/tests/test_unified_retrieval.py engine/tests/test_ckp_governance.py engine/tests/integration/test_scoped_graph_rag.py
git commit -m "fix(graph): 收紧 GraphRAG 与治理作用域"
```

## Task 8: Expose Separate Build, Replay, and Re-Extraction Commands

**Files:**
- Create: `backend/app/api/knowledge_graph.py`
- Modify: `backend/app/api/__init__.py`
- Modify: `backend/app/schemas/knowledge.py`
- Modify: `engine/app/jobs/knowledge_handlers.py`
- Modify: `engine/app/jobs/worker.py`
- Create: `backend/tests/test_knowledge_graph_api.py`
- Modify: `engine/tests/integration/test_graph_projection_recovery.py`

- [ ] **Step 1: Write command-boundary tests**

```python
# backend/tests/test_knowledge_graph_api.py
def test_rebuild_projection_enqueues_replay_without_llm(client, fake_jobs):
    response = client.post("/api/v1/knowledge-bases/kb-a/graph/rebuild-projection")
    assert response.status_code == 202
    assert fake_jobs.last.job_type == "graph_projection_replay"
    assert fake_jobs.last.payload == {"generation": "g1"}


def test_reextract_creates_new_generation_and_cost_warning(client, fake_jobs):
    response = client.post(
        "/api/v1/knowledge-bases/kb-a/graph/re-extract",
        json={"extractor_config": {"model": "extract-v2", "prompt_version": "p2"}},
    )
    assert response.status_code == 202
    assert fake_jobs.last.job_type == "graph_reextract"
    assert response.json()["cost_incurred"] is True


def test_forbidden_actor_cannot_read_graph_status(client, actor_headers):
    response = client.get("/api/v1/knowledge-bases/kb-private/graph/status", headers=actor_headers("bob"))
    assert response.status_code == 403
```

- [ ] **Step 2: Run and verify routes are absent**

Run: `$env:DATABASE_URL='sqlite:///./_test.db'; python -m pytest backend/tests/test_knowledge_graph_api.py -v`

Expected: FAIL with 404 for the graph v1 routes.

- [ ] **Step 3: Implement authorized command routes**

Add these routes under `/api/v1/knowledge-bases/{kb_uid}/graph`:

- `GET /status`: active/building generations, projector lag, terminal failures, and `ready/degraded/building` status.
- `POST /build`: incremental current-generation build for stale files.
- `POST /rebuild-projection`: replay MySQL facts/Outbox to Neo4j and Milvus without LLM calls.
- `POST /re-extract`: create a new generation and run extraction, projection, validation, and activation; response includes `cost_incurred=true`.
- `POST /retry-failed-projections`: reset retryable failed receipts only; terminal payload/config failures remain failed.

Every route resolves `ActorContext`, calls `KnowledgeAccessPolicy.require_manage`, creates `JobCommand`, and returns Job ID plus structured graph status. Model/provider secrets and internal URLs are absent from responses.

- [ ] **Step 4: Implement replay from MySQL facts**

`graph_projection_replay` scans scoped active facts in stable primary-key order, emits missing Outbox events with deterministic replay idempotency keys, and lets normal projectors apply them. It does not call Stage A extraction, graphify, rerank, or any LLM. `graph_reextract` creates a new generation and invokes the extraction pipeline.

- [ ] **Step 5: Add lag and failure observability**

Record structured fields `trace_id/job_id/tenant_id/kb_uid/generation/projector/event_id/attempt/error_code`. Export gauges for oldest pending age and pending/failed receipt counts by projector, plus graph generation status. Logs must not contain Chunk text, evidence spans longer than the bounded preview, ActorContext dumps, credentials, or provider response bodies.

- [ ] **Step 6: Run API and recovery tests**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_test.db'
python -m pytest backend/tests/test_knowledge_graph_api.py -v
if (-not $env:PRISM_TEST_DATABASE_URL) { throw 'PRISM_TEST_DATABASE_URL must target the dedicated prism_test MySQL database' }
$env:DATABASE_URL=$env:PRISM_TEST_DATABASE_URL
python -m pytest engine/tests/integration/test_graph_projection_recovery.py -v
```

Expected: PASS; replay performs zero LLM calls; failed Neo4j/Milvus receipts converge after dependencies recover; authorization rejects cross-owner access.

- [ ] **Step 7: Commit graph commands and observability**

```powershell
git add backend/app/api/knowledge_graph.py backend/app/api/__init__.py backend/app/schemas/knowledge.py engine/app/jobs/knowledge_handlers.py engine/app/jobs/worker.py backend/tests/test_knowledge_graph_api.py engine/tests/integration/test_graph_projection_recovery.py
git commit -m "feat(graph): 增加投影重放与重新抽取命令"
```

## Plan Verification

- [ ] Run schema/model tests: `$env:DATABASE_URL='sqlite:///./_test.db'; python -m pytest backend/tests/test_graph_outbox_models.py backend/tests/test_graph_fact_transaction.py backend/tests/test_graph_fact_deletion.py -v`.
- [ ] Run projector/generation tests: `$env:DATABASE_URL='sqlite:///./_test.db'; python -m pytest engine/tests/test_neo4j_outbox_projector.py engine/tests/test_milvus_graph_projector.py engine/tests/test_graph_generation_activation.py -v`.
- [ ] Run existing graph regressions: `$env:DATABASE_URL='sqlite:///./_test.db'; python -m pytest backend/tests/test_entity_settle.py backend/tests/test_graph_client.py backend/tests/test_graph_projection.py engine/tests/test_graph_analyzer.py engine/tests/test_graph_expand.py engine/tests/test_unified_retrieval.py engine/tests/test_ckp_governance.py engine/tests/test_graph_insights.py -v`.
- [ ] Run real integration tests with MySQL, Neo4j, and Milvus after setting `$env:DATABASE_URL=$env:PRISM_TEST_DATABASE_URL`: `python -m pytest backend/tests/integration/test_graph_outbox_mysql.py engine/tests/integration/test_graph_projection_recovery.py engine/tests/integration/test_scoped_graph_rag.py -v`.
- [ ] Stop Neo4j during projection, confirm `retry` receipts and unchanged active generation, restart it, and confirm receipt lag reaches zero.
- [ ] Stop Milvus during projection, confirm Dense/BM25 remain available and Graph is `degraded`, restart it, and confirm graph vectors converge without duplicates.
- [ ] Build a failing new graph generation and verify queries continue using the previous `active_graph_generation`.
- [ ] Delete one of two files mentioning the same Entity and verify only that file's Mention/Relation evidence disappears from MySQL, Neo4j, and Evidence.
- [ ] Replay the active generation and verify no LLM/embedding call occurs for unchanged graph-vector `text_hash` rows.
- [ ] Run `rg -n "default-user|user_id=.*scope|delete_item_sources\(" backend/app/services/graph_client.py backend/app/services/graph_facts.py engine/app/graph engine/app/retrieval/graph_expand.py`.
- [ ] Expected: no production graph scope fallback and no destructive per-item Neo4j delete/reproject path.
- [ ] Run `git diff --check` and verify no secrets, internal URLs, absolute storage paths, or provider payloads were added.
- [ ] Record all eight task commit hashes and verification results in `docs/superpowers/plans/2026-07-22-knowledge-system-roadmap.md` in a follow-up docs-only commit.
