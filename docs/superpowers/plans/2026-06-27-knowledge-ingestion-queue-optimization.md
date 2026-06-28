# Knowledge Ingestion Queue Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Redis-backed producer-consumer ingestion system that supports large batch vectorization, fast retrieval before governance, visible PKU/CKP progress, text quality blocking, and faster embedding/vector writes.

**Architecture:** Backend API endpoints create durable MySQL `knowledge_job` rows and enqueue Redis `{job_id}` messages. Engine startup runs bounded worker pools that consume ingest and governance queues, update job/resource progress, and recover stale jobs. Ingest produces searchable vectors first; governance runs as a separate stage and can fail into a visible partial-complete state.

**Tech Stack:** FastAPI, SQLAlchemy ORM, MySQL, Redis `redis==5.0.0`, PyMilvus, Elasticsearch, React/TypeScript, pytest, Node source-scan frontend tests.

---

## Spec Reference

Read and follow:

- `docs/superpowers/specs/2026-06-27-knowledge-ingestion-queue-optimization-design.md`

## File Structure

Create:

- `backend/app/models/knowledge_job.py`: durable MySQL job model.
- `backend/app/services/knowledge_job_queue.py`: producer-side job creation, Redis enqueue, active job reuse, batch enqueue.
- `backend/app/services/document_text_quality.py`: text quality gate shared by upload/API and workers.
- `backend/tests/test_knowledge_job_queue.py`: producer/job service tests.
- `backend/tests/test_document_text_quality.py`: text quality gate tests.
- `engine/app/jobs/__init__.py`: worker package marker.
- `engine/app/jobs/redis_queue.py`: Redis pop/push helpers and small fakeable interface.
- `engine/app/jobs/worker.py`: ingest/governance worker loops, retry, recovery.
- `engine/tests/test_ingest_workers.py`: worker/retry/recovery tests.
- `frontend/tests/knowledge-ingestion-queue.test.mjs`: frontend source assertions for batch action and statuses.

Modify:

- `backend/app/models/__init__.py`: export `KnowledgeJob`.
- `backend/app/models/knowledge_item.py`: add governance fields to `KnowledgeFile`.
- `backend/app/schemas/knowledge.py`: expose governance fields, job summary, batch ingest response.
- `backend/app/config.py`: add queue and quality settings.
- `engine/app/config.py`: add queue, chunk, embedding, worker settings.
- `backend/app/api/knowledge.py`: use job producer for single and topic batch ingest; remove direct background ingest path.
- `engine/app/api/ingest.py`: keep HTTP ingest compatible but make it fast-vectorization only.
- `engine/app/ingestion/chunker.py`: read chunk sizes from settings.
- `engine/app/ingestion/pipeline.py`: split vectorization from governance, add progress callback, use batch Milvus insert.
- `engine/app/ingestion/vectorizer.py`: verify batch size comes from settings.
- `engine/app/milvus_client.py`: add `insert_vectors_batch`.
- `backend/app/services/knowledge_governance.py`: add optional progress callback to document governance settlement.
- `engine/run.py`: start and stop worker manager on engine startup/shutdown.
- `frontend/src/app/api.ts`: add batch ingest API, governance fields, job summary types.
- `frontend/src/pages/KnowledgePage.tsx`: add topic-level batch action, status composition, progress display, retry governance.
- `.env.prod.example`: document new settings.

---

## Task 1: Add Job Model and Resource Governance Fields

**Files:**

- Create: `backend/app/models/knowledge_job.py`
- Modify: `backend/app/models/knowledge_item.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/schemas/knowledge.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_models.py`

- [ ] **Step 1: Write failing model test**

Append to `backend/tests/test_models.py`:

```python
def test_knowledge_job_and_resource_governance_fields(db_session):
    from backend.app.models import KnowledgeFile, KnowledgeJob, KnowledgeTopic

    topic = KnowledgeTopic(user_id="default-user", name="Queue")
    db_session.add(topic)
    db_session.flush()

    resource = KnowledgeFile(
        user_id="default-user",
        topic_id=topic.id,
        title="Paper",
        original_filename="paper.pdf",
        media_type="document",
        file_ext=".pdf",
        file_size=123,
        md5="abc123",
        storage_path="/tmp/paper.pdf",
        processing_status="queued",
        governance_status="queued",
        governance_progress_current=1,
        governance_progress_total=10,
    )
    db_session.add(resource)
    db_session.flush()

    job = KnowledgeJob(
        job_type="ingest",
        resource_id=resource.id,
        item_id="item-1",
        topic_id=topic.id,
        status="queued",
        progress_current=0,
        progress_total=10,
        max_attempts=3,
    )
    db_session.add(job)
    db_session.commit()

    loaded = db_session.query(KnowledgeJob).filter_by(resource_id=resource.id).one()
    assert loaded.status == "queued"
    assert loaded.max_attempts == 3
    assert loaded.resource_id == resource.id

    loaded_resource = db_session.query(KnowledgeFile).filter_by(id=resource.id).one()
    assert loaded_resource.governance_status == "queued"
    assert loaded_resource.governance_progress_current == 1
    assert loaded_resource.governance_progress_total == 10
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
python -m pytest backend/tests/test_models.py::test_knowledge_job_and_resource_governance_fields -q
```

Expected: FAIL because `KnowledgeJob` and governance fields do not exist.

- [ ] **Step 3: Create `KnowledgeJob` model**

Create `backend/app/models/knowledge_job.py`:

```python
import uuid

from sqlalchemy import Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.mysql import CHAR

from ..database import Base
from ..utils.time import local_now


def _uuid():
    return str(uuid.uuid4())


class KnowledgeJob(Base):
    __tablename__ = "knowledge_job"
    __table_args__ = (
        Index("ix_knowledge_job_status_available_priority_created", "status", "available_at", "priority", "created_at"),
        Index("ix_knowledge_job_resource_type_status", "resource_id", "job_type", "status"),
        Index("ix_knowledge_job_item_id", "item_id"),
        Index("ix_knowledge_job_topic_id", "topic_id"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    job_type = Column(String(32), nullable=False, comment="ingest / governance")
    resource_id = Column(CHAR(36), nullable=False, index=True)
    item_id = Column(CHAR(36), nullable=True)
    topic_id = Column(CHAR(36), nullable=True)
    status = Column(String(24), nullable=False, default="queued", comment="queued/processing/done/failed/canceled")
    priority = Column(Integer, nullable=False, default=100)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    progress_current = Column(Integer, nullable=False, default=0)
    progress_total = Column(Integer, nullable=False, default=0)
    stage = Column(String(64), nullable=False, default="")
    error_code = Column(String(64), nullable=False, default="")
    error_message = Column(Text, nullable=True)
    locked_by = Column(String(128), nullable=False, default="")
    locked_at = Column(DateTime, nullable=True)
    available_at = Column(DateTime, default=local_now, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)
```

- [ ] **Step 4: Add governance fields to `KnowledgeFile`**

In `backend/app/models/knowledge_item.py`, add imports and fields:

```python
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, UniqueConstraint
```

Add to `KnowledgeFile` near `error_message`:

```python
    governance_status = Column(String(20), nullable=False, default="not_started")
    governance_progress_current = Column(Integer, nullable=False, default=0)
    governance_progress_total = Column(Integer, nullable=False, default=0)
    governance_error_message = Column(Text, comment="Governance error")
    governance_started_at = Column(DateTime, nullable=True)
    governance_finished_at = Column(DateTime, nullable=True)
```

No new import is needed if `Integer` and `DateTime` are already imported.

- [ ] **Step 5: Export `KnowledgeJob`**

In `backend/app/models/__init__.py`:

```python
from .knowledge_job import KnowledgeJob
```

Add `"KnowledgeJob"` to `__all__`.

- [ ] **Step 6: Expose governance fields in schemas**

In `backend/app/schemas/knowledge.py`, add:

```python
class KnowledgeJobSummary(BaseModel):
    id: str
    job_type: str
    status: str
    stage: str
    attempts: int
    max_attempts: int
    progress_current: int
    progress_total: int
    error_code: str
    error_message: Optional[str]

    class Config:
        from_attributes = True


class TopicIngestOut(BaseModel):
    queued: int
    skipped: int
    failed: int
    job_ids: list[str] = []
    messages: list[str] = []
```

Add fields to `KnowledgeResourceOut`:

```python
    governance_status: str = "not_started"
    governance_progress_current: int = 0
    governance_progress_total: int = 0
    governance_error_message: Optional[str] = None
    governance_started_at: Optional[datetime] = None
    governance_finished_at: Optional[datetime] = None
    latest_job: Optional[KnowledgeJobSummary] = None
```

If Pydantic complains about ORM-only `latest_job`, leave it populated explicitly in later API helpers.

- [ ] **Step 7: Add settings**

In `backend/app/config.py`, add:

```python
    KNOWLEDGE_INGEST_QUEUE: str = os.getenv("KNOWLEDGE_INGEST_QUEUE", "prism:queue:ingest")
    KNOWLEDGE_GOVERNANCE_QUEUE: str = os.getenv("KNOWLEDGE_GOVERNANCE_QUEUE", "prism:queue:governance")
    KNOWLEDGE_TEXT_MAX_CHARS: int = int(os.getenv("KNOWLEDGE_TEXT_MAX_CHARS", "300000"))
    KNOWLEDGE_TEXT_MAX_CHARS_PER_PAGE: int = int(os.getenv("KNOWLEDGE_TEXT_MAX_CHARS_PER_PAGE", "12000"))
```

- [ ] **Step 8: Run model tests**

Run:

```bash
python -m pytest backend/tests/test_models.py::test_knowledge_job_and_resource_governance_fields -q
```

Expected: PASS.

---

## Task 2: Add Document Text Quality Gate

**Files:**

- Create: `backend/app/services/document_text_quality.py`
- Create: `backend/tests/test_document_text_quality.py`
- Modify: `backend/app/api/knowledge.py`

- [ ] **Step 1: Write failing text quality tests**

Create `backend/tests/test_document_text_quality.py`:

```python
from backend.app.services.document_text_quality import assess_document_text


def test_normal_paper_text_passes_quality_gate():
    text = "Representation learning improves retrieval. " * 1000
    result = assess_document_text(text, page_count=12, max_chars=300000, max_chars_per_page=12000)
    assert result.ok is True
    assert result.error_code == ""


def test_multi_million_character_document_is_blocked():
    text = "x" * 2_180_754
    result = assess_document_text(text, page_count=858, max_chars=300000, max_chars_per_page=12000)
    assert result.ok is False
    assert result.error_code == "text_too_large"
    assert "2180754" in result.message
    assert "858" in result.message


def test_missing_page_count_uses_total_character_limit():
    text = "x" * 300_001
    result = assess_document_text(text, page_count=None, max_chars=300000, max_chars_per_page=12000)
    assert result.ok is False
    assert result.error_code == "text_too_large"


def test_too_many_characters_per_page_is_blocked():
    text = "x" * 130_000
    result = assess_document_text(text, page_count=10, max_chars=300000, max_chars_per_page=12000)
    assert result.ok is False
    assert result.error_code == "text_density_too_high"
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
python -m pytest backend/tests/test_document_text_quality.py -q
```

Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement quality gate**

Create `backend/app/services/document_text_quality.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentTextQuality:
    ok: bool
    error_code: str = ""
    message: str = ""
    chars: int = 0
    page_count: int | None = None
    chars_per_page: float | None = None


def assess_document_text(
    text: str | None,
    *,
    page_count: int | None,
    max_chars: int,
    max_chars_per_page: int,
) -> DocumentTextQuality:
    chars = len(text or "")
    if chars > max_chars:
        return DocumentTextQuality(
            ok=False,
            error_code="text_too_large",
            message=(
                f"Parsed text is too large for vectorization: chars={chars}, "
                f"page_count={page_count or 'unknown'}, max_chars={max_chars}. "
                "Please re-upload the PDF or use a cleaner parsed version."
            ),
            chars=chars,
            page_count=page_count,
        )

    if page_count and page_count > 0:
        chars_per_page = chars / page_count
        if chars_per_page > max_chars_per_page:
            return DocumentTextQuality(
                ok=False,
                error_code="text_density_too_high",
                message=(
                    f"Parsed text density is abnormal: chars={chars}, page_count={page_count}, "
                    f"chars_per_page={chars_per_page:.1f}, max_chars_per_page={max_chars_per_page}. "
                    "Please re-upload the PDF or use a cleaner parsed version."
                ),
                chars=chars,
                page_count=page_count,
                chars_per_page=chars_per_page,
            )

    return DocumentTextQuality(ok=True, chars=chars, page_count=page_count)
```

- [ ] **Step 4: Run quality tests**

Run:

```bash
python -m pytest backend/tests/test_document_text_quality.py -q
```

Expected: PASS.

- [ ] **Step 5: Apply gate during document upload parse**

In `backend/app/api/knowledge.py`, import:

```python
from ..services.document_text_quality import assess_document_text
```

Inside `upload_topic_resource`, after `resource.content_text = text` and `resource.page_count = count_pages(...)`, add:

```python
            quality = assess_document_text(
                text,
                page_count=resource.page_count,
                max_chars=settings.KNOWLEDGE_TEXT_MAX_CHARS,
                max_chars_per_page=settings.KNOWLEDGE_TEXT_MAX_CHARS_PER_PAGE,
            )
            if not quality.ok:
                resource.processing_status = "text_invalid"
                resource.error_message = quality.message
                db.commit()
                db.refresh(resource)
                return resource
```

Keep `KnowledgeItem` creation only after quality passes.

- [ ] **Step 6: Add API test for text invalid upload**

Append to `backend/tests/test_knowledge_api.py`:

```python
def test_upload_document_marks_abnormal_text_invalid(client, monkeypatch):
    topic = _create_topic(client)
    monkeypatch.setattr("backend.app.api.knowledge.extract_text", lambda path: "x" * 300001)
    monkeypatch.setattr("backend.app.api.knowledge.count_pages", lambda path: 10)

    response = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("huge.txt", b"placeholder", "text/plain")},
    )

    assert response.status_code == 200
    resource = response.json()
    assert resource["processing_status"] == "text_invalid"
    assert "too large" in resource["error_message"]
    assert resource["item_id"] is None
```

- [ ] **Step 7: Run API text invalid test**

Run:

```bash
python -m pytest backend/tests/test_knowledge_api.py::test_upload_document_marks_abnormal_text_invalid -q
```

Expected: PASS.

---

## Task 3: Configurable Chunking and Embedding Batch Defaults

**Files:**

- Modify: `engine/app/config.py`
- Modify: `engine/app/ingestion/chunker.py`
- Modify: `.env.prod.example`
- Test: `engine/tests/test_chunker.py`
- Test: `engine/tests/test_vectorizer.py`

- [ ] **Step 1: Write failing chunk config test**

Append to `engine/tests/test_chunker.py`:

```python
def test_chunk_parent_child_uses_configured_balanced_sizes(monkeypatch):
    import engine.app.ingestion.chunker as chunker

    monkeypatch.setattr(chunker.settings, "CHILD_CHUNK_TOKENS", 384)
    monkeypatch.setattr(chunker.settings, "PARENT_CHUNK_TOKENS", 1536)
    monkeypatch.setattr(chunker.settings, "CHILD_OVERLAP_RATIO", 0.1)

    text = "This sentence has enough tokens for a small regression test. " * 300
    parents = chunker.chunk_parent_child(text)

    assert parents
    assert all(chunker.count_tokens(parent.content) <= 1536 * 1.15 for parent in parents)
    assert all(
        chunker.count_tokens(child.content) <= 384 * 1.25
        for parent in parents
        for child in parent.children
    )
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
python -m pytest engine/tests/test_chunker.py::test_chunk_parent_child_uses_configured_balanced_sizes -q
```

Expected: FAIL because `chunker.settings` does not exist.

- [ ] **Step 3: Add engine settings**

In `engine/app/config.py`, add:

```python
    KNOWLEDGE_INGEST_QUEUE: str = os.getenv("KNOWLEDGE_INGEST_QUEUE", "prism:queue:ingest")
    KNOWLEDGE_GOVERNANCE_QUEUE: str = os.getenv("KNOWLEDGE_GOVERNANCE_QUEUE", "prism:queue:governance")
    KNOWLEDGE_INGEST_WORKERS: int = int(os.getenv("KNOWLEDGE_INGEST_WORKERS", "2"))
    KNOWLEDGE_GOVERNANCE_WORKERS: int = int(os.getenv("KNOWLEDGE_GOVERNANCE_WORKERS", "1"))
    KNOWLEDGE_JOB_STALE_SECONDS: int = int(os.getenv("KNOWLEDGE_JOB_STALE_SECONDS", "1800"))
    KNOWLEDGE_TEXT_MAX_CHARS: int = int(os.getenv("KNOWLEDGE_TEXT_MAX_CHARS", "300000"))
    KNOWLEDGE_TEXT_MAX_CHARS_PER_PAGE: int = int(os.getenv("KNOWLEDGE_TEXT_MAX_CHARS_PER_PAGE", "12000"))
    CHILD_CHUNK_TOKENS: int = int(os.getenv("CHILD_CHUNK_TOKENS", "384"))
    PARENT_CHUNK_TOKENS: int = int(os.getenv("PARENT_CHUNK_TOKENS", "1536"))
    CHILD_OVERLAP_RATIO: float = float(os.getenv("CHILD_OVERLAP_RATIO", "0.1"))
```

Change existing embedding default:

```python
    EMBEDDING_BATCH_SIZE: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "64"))
```

- [ ] **Step 4: Use settings in chunker**

In `engine/app/ingestion/chunker.py`, add:

```python
from engine.app.config import settings
```

Change `chunk_parent_child` to use settings:

```python
    parent_contents = _merge_to_chunks(sentences, settings.PARENT_CHUNK_TOKENS)
```

And:

```python
        parent.children = _merge_to_chunks(
            child_sents,
            settings.CHILD_CHUNK_TOKENS,
            settings.CHILD_OVERLAP_RATIO,
        )
```

Leave constants as documented defaults for compatibility if other tests import them, but do not use them in `chunk_parent_child`.

- [ ] **Step 5: Update environment example**

Append to `.env.prod.example`:

```env
KNOWLEDGE_INGEST_WORKERS=2
KNOWLEDGE_GOVERNANCE_WORKERS=1
KNOWLEDGE_JOB_STALE_SECONDS=1800
KNOWLEDGE_TEXT_MAX_CHARS=300000
KNOWLEDGE_TEXT_MAX_CHARS_PER_PAGE=12000
EMBEDDING_BATCH_SIZE=64
CHILD_CHUNK_TOKENS=384
PARENT_CHUNK_TOKENS=1536
CHILD_OVERLAP_RATIO=0.1
```

- [ ] **Step 6: Run chunker/vectorizer tests**

Run:

```bash
python -m pytest engine/tests/test_chunker.py engine/tests/test_vectorizer.py -q
```

Expected: PASS.

---

## Task 4: Add Milvus Batch Insert

**Files:**

- Modify: `engine/app/milvus_client.py`
- Create or modify: `engine/tests/test_milvus_client.py`

- [ ] **Step 1: Write failing batch insert test**

Append to `engine/tests/test_milvus_client.py`:

```python
def test_insert_vectors_batch_inserts_all_vectors(monkeypatch):
    from engine.app import milvus_client

    calls = []

    class FakeCollection:
        def insert(self, payload):
            calls.append(payload)

    monkeypatch.setattr(milvus_client, "ensure_collection", lambda: FakeCollection())

    milvus_client.insert_vectors_batch(
        [
            {"chunk_id": "chunk-1", "item_id": "item-1", "embedding": [0.1, 0.2]},
            {"chunk_id": "chunk-2", "item_id": "item-1", "embedding": [0.3, 0.4]},
        ]
    )

    assert calls == [
        [
            ["chunk-1", "chunk-2"],
            [[0.1, 0.2], [0.3, 0.4]],
            ["chunk-1", "chunk-2"],
            ["item-1", "item-1"],
        ]
    ]
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
python -m pytest engine/tests/test_milvus_client.py::test_insert_vectors_batch_inserts_all_vectors -q
```

Expected: FAIL because `insert_vectors_batch` does not exist.

- [ ] **Step 3: Implement batch insert**

In `engine/app/milvus_client.py`, add:

```python
def insert_vectors_batch(rows: list[dict]):
    """Insert many knowledge chunk vectors in one Milvus call."""
    if not rows:
        return
    coll = ensure_collection()
    chunk_ids = [row["chunk_id"] for row in rows]
    embeddings = [row["embedding"] for row in rows]
    item_ids = [row["item_id"] for row in rows]
    coll.insert([
        chunk_ids,
        embeddings,
        chunk_ids,
        item_ids,
    ])
```

Optionally change `insert_vectors` to delegate:

```python
def insert_vectors(chunk_id: str, item_id: str, embedding: list[float]):
    insert_vectors_batch([{"chunk_id": chunk_id, "item_id": item_id, "embedding": embedding}])
```

- [ ] **Step 4: Run Milvus tests**

Run:

```bash
python -m pytest engine/tests/test_milvus_client.py -q
```

Expected: PASS.

---

## Task 5: Refactor Ingestion Pipeline to Fast Vectorization Only

**Files:**

- Modify: `engine/app/ingestion/pipeline.py`
- Modify: `engine/tests/test_ingestion_governance.py`
- Test: `engine/tests/test_ingestion_governance.py`

- [ ] **Step 1: Write failing test that ingest does not call governance**

Append to `engine/tests/test_ingestion_governance.py`:

```python
def test_ingest_item_skips_document_governance_and_uses_batch_vectors(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    session = Session()
    item = KnowledgeItem(
        title="Fast vectorization",
        content="Vectorization should finish before governance. " * 100,
        source_type="manual",
        user_id="default-user",
    )
    session.add(item)
    session.commit()
    item_id = item.id
    session.close()

    parent = ParentChunk("parent text")
    parent.children = ["child one", "child two"]
    batch_calls = []

    monkeypatch.setattr(pipeline, "_Session", Session)
    monkeypatch.setattr(pipeline, "chunk_parent_child", lambda content: [parent])
    monkeypatch.setattr(pipeline, "embed_texts", lambda texts: [[0.1], [0.2]])
    monkeypatch.setattr(pipeline, "insert_vectors_batch", lambda rows: batch_calls.append(rows))
    monkeypatch.setattr(pipeline, "_bulk_index_chunks_es", lambda **kwargs: 2)
    monkeypatch.setattr(pipeline, "_delete_es_chunks_by_item", lambda item_id: None)

    def fail_governance(*args, **kwargs):
        raise AssertionError("governance must not run in ingest_item")

    monkeypatch.setattr(pipeline, "settle_document_item_to_governance", fail_governance, raising=False)

    assert pipeline.ingest_item(item_id) == 2
    assert len(batch_calls) == 1
    assert [row["chunk_id"] for row in batch_calls[0]]
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
python -m pytest engine/tests/test_ingestion_governance.py::test_ingest_item_skips_document_governance_and_uses_batch_vectors -q
```

Expected: FAIL because pipeline imports/calls governance and uses per-vector insert.

- [ ] **Step 3: Refactor pipeline imports**

In `engine/app/ingestion/pipeline.py`, change:

```python
from ..milvus_client import insert_vectors
```

to:

```python
from ..milvus_client import insert_vectors_batch
```

Inside `ingest_item`, remove `settle_document_item_to_governance` import and call. Keep `clear_document_item_governance` import and call.

- [ ] **Step 4: Add progress callback support**

Change signature:

```python
def ingest_item(item_id: str, progress=None) -> int:
```

Add helper near `_log_stage`:

```python
def _report(progress, stage: str, current: int = 0, total: int = 0) -> None:
    if progress:
        progress(stage=stage, current=current, total=total)
```

Call `_report` after major stages:

```python
_report(progress, "chunking", 0, 0)
_report(progress, "embedding", 0, len(child_texts))
_report(progress, "store_mysql_chunks", 0, len(child_texts))
_report(progress, "store_milvus", 0, len(embeddings))
_report(progress, "index_es", 0, len(child_texts))
```

- [ ] **Step 5: Use batch Milvus insert**

Replace the per-child `insert_vectors(...)` loop with:

```python
        vector_rows = []
        child_embedding_index = 0
        for parent_index, pc in enumerate(parents):
            for child_index, _child_text in enumerate(pc.children):
                cid = child_id_map_by_position[(parent_index, child_index)]
                emb = embeddings[child_embedding_index]
                vector_rows.append({"chunk_id": cid, "item_id": item_id, "embedding": emb})
                child_embedding_index += 1
        insert_vectors_batch(vector_rows)
```

- [ ] **Step 6: Commit database chunk state before external indexes**

After MySQL chunk rows are flushed and ID maps are complete, add:

```python
        db.flush()
        db.commit()
```

Then continue Milvus and ES work. If a later external stage fails, worker retry will clear/rebuild chunks on the next attempt. This shortens MySQL lock lifetime.

- [ ] **Step 7: Run pipeline tests**

Run:

```bash
python -m pytest engine/tests/test_ingestion_governance.py -q
```

Expected: PASS after updating old tests that expected governance during ingest. Old governance expectations should move to Task 9 worker tests, not be removed without replacement.

---

## Task 6: Add Producer-Side Job Queue Service

**Files:**

- Create: `backend/app/services/knowledge_job_queue.py`
- Create: `backend/tests/test_knowledge_job_queue.py`

- [ ] **Step 1: Write failing job queue tests**

Create `backend/tests/test_knowledge_job_queue.py`:

```python
from backend.app.models import KnowledgeFile, KnowledgeItem, KnowledgeTopic
from backend.app.services.knowledge_job_queue import enqueue_ingest_job, enqueue_topic_ingest_jobs


class FakeRedis:
    def __init__(self):
        self.messages = []

    def lpush(self, queue_name, payload):
        self.messages.append((queue_name, payload))


def _resource(db_session, topic, title="Paper", status="completed"):
    item = KnowledgeItem(title=title, content="content", source_type="file", user_id="default-user")
    db_session.add(item)
    db_session.flush()
    resource = KnowledgeFile(
        user_id="default-user",
        topic_id=topic.id,
        item_id=item.id,
        title=title,
        original_filename=f"{title}.pdf",
        media_type="document",
        file_ext=".pdf",
        file_size=10,
        md5=f"md5-{title}",
        storage_path=f"/tmp/{title}.pdf",
        processing_status=status,
    )
    db_session.add(resource)
    db_session.commit()
    return resource


def test_enqueue_ingest_job_reuses_active_job(db_session):
    topic = KnowledgeTopic(user_id="default-user", name="Queue")
    db_session.add(topic)
    db_session.commit()
    resource = _resource(db_session, topic)
    redis_client = FakeRedis()

    first = enqueue_ingest_job(db_session, redis_client, resource.id, queue_name="ingest-q")
    second = enqueue_ingest_job(db_session, redis_client, resource.id, queue_name="ingest-q")

    assert first.id == second.id
    assert len(redis_client.messages) == 1
    db_session.refresh(resource)
    assert resource.processing_status == "queued"


def test_enqueue_topic_ingest_jobs_skips_ineligible_resources(db_session):
    topic = KnowledgeTopic(user_id="default-user", name="Batch")
    db_session.add(topic)
    db_session.commit()
    _resource(db_session, topic, title="Ready", status="completed")
    _resource(db_session, topic, title="AlreadyDone", status="done")
    _resource(db_session, topic, title="Invalid", status="text_invalid")
    redis_client = FakeRedis()

    result = enqueue_topic_ingest_jobs(db_session, redis_client, topic.id, queue_name="ingest-q")

    assert result.queued == 1
    assert result.skipped == 2
    assert result.failed == 0
    assert len(redis_client.messages) == 1
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python -m pytest backend/tests/test_knowledge_job_queue.py -q
```

Expected: FAIL because service does not exist.

- [ ] **Step 3: Implement queue service**

Create `backend/app/services/knowledge_job_queue.py`:

```python
import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.app.models import KnowledgeFile, KnowledgeJob
from backend.app.utils.time import local_now


ACTIVE_STATUSES = {"queued", "processing"}
ELIGIBLE_INGEST_STATUSES = {"completed", "failed"}


@dataclass
class BatchEnqueueResult:
    queued: int = 0
    skipped: int = 0
    failed: int = 0
    job_ids: list[str] | None = None
    messages: list[str] | None = None

    def __post_init__(self):
        self.job_ids = self.job_ids or []
        self.messages = self.messages or []


def _push(redis_client, queue_name: str, job_id: str) -> None:
    redis_client.lpush(queue_name, json.dumps({"job_id": job_id}))


def _active_job(db: Session, resource_id: str, job_type: str) -> KnowledgeJob | None:
    return (
        db.query(KnowledgeJob)
        .filter(
            KnowledgeJob.resource_id == resource_id,
            KnowledgeJob.job_type == job_type,
            KnowledgeJob.status.in_(ACTIVE_STATUSES),
        )
        .order_by(KnowledgeJob.created_at.desc())
        .first()
    )


def enqueue_ingest_job(db: Session, redis_client, resource_id: str, *, queue_name: str) -> KnowledgeJob:
    resource = db.query(KnowledgeFile).filter(KnowledgeFile.id == resource_id).first()
    if not resource:
        raise ValueError("resource_not_found")
    if resource.media_type != "document" or not resource.item_id:
        raise ValueError("resource_not_ingestable")
    if resource.processing_status == "text_invalid":
        raise ValueError("text_invalid")

    existing = _active_job(db, resource_id, "ingest")
    if existing:
        return existing

    job = KnowledgeJob(
        job_type="ingest",
        resource_id=resource.id,
        item_id=resource.item_id,
        topic_id=resource.topic_id,
        status="queued",
        max_attempts=3,
        available_at=local_now(),
    )
    db.add(job)
    resource.processing_status = "queued"
    resource.error_message = None
    db.commit()
    db.refresh(job)
    _push(redis_client, queue_name, job.id)
    return job


def enqueue_governance_job(db: Session, redis_client, resource_id: str, *, queue_name: str) -> KnowledgeJob:
    resource = db.query(KnowledgeFile).filter(KnowledgeFile.id == resource_id).first()
    if not resource or not resource.item_id:
        raise ValueError("resource_not_found")

    existing = _active_job(db, resource_id, "governance")
    if existing:
        return existing

    job = KnowledgeJob(
        job_type="governance",
        resource_id=resource.id,
        item_id=resource.item_id,
        topic_id=resource.topic_id,
        status="queued",
        max_attempts=3,
        available_at=local_now(),
    )
    db.add(job)
    resource.governance_status = "queued"
    resource.governance_error_message = None
    db.commit()
    db.refresh(job)
    _push(redis_client, queue_name, job.id)
    return job


def enqueue_topic_ingest_jobs(db: Session, redis_client, topic_id: str, *, queue_name: str) -> BatchEnqueueResult:
    result = BatchEnqueueResult()
    resources = (
        db.query(KnowledgeFile)
        .filter(KnowledgeFile.topic_id == topic_id, KnowledgeFile.media_type == "document")
        .order_by(KnowledgeFile.uploaded_at.asc())
        .all()
    )
    for resource in resources:
        if resource.processing_status not in ELIGIBLE_INGEST_STATUSES:
            result.skipped += 1
            continue
        try:
            job = enqueue_ingest_job(db, redis_client, resource.id, queue_name=queue_name)
        except ValueError as exc:
            result.failed += 1
            result.messages.append(f"{resource.title}: {exc}")
            continue
        result.queued += 1
        result.job_ids.append(job.id)
    return result
```

- [ ] **Step 4: Run service tests**

Run:

```bash
python -m pytest backend/tests/test_knowledge_job_queue.py -q
```

Expected: PASS.

---

## Task 7: Update Knowledge API Producers

**Files:**

- Modify: `backend/app/api/knowledge.py`
- Modify: `backend/app/schemas/knowledge.py`
- Test: `backend/tests/test_knowledge_api.py`

- [ ] **Step 1: Write failing API tests**

Append to `backend/tests/test_knowledge_api.py`:

```python
def test_ingest_resource_enqueues_job_instead_of_calling_engine(client, monkeypatch):
    topic = _create_topic(client)
    upload = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("notes.txt", b"hello document", "text/plain")},
    )
    resource = upload.json()
    calls = []

    class FakeRedis:
        def lpush(self, queue_name, payload):
            calls.append((queue_name, payload))

    monkeypatch.setattr("backend.app.api.knowledge._redis_client", lambda: FakeRedis())

    response = client.post(f"/api/v1/knowledge/resources/{resource['id']}/ingest")

    assert response.status_code == 200
    body = response.json()
    assert body["processing_status"] == "queued"
    assert calls


def test_topic_ingest_enqueues_all_eligible_documents(client, monkeypatch):
    topic = _create_topic(client)
    client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("one.txt", b"one", "text/plain")},
    )
    client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("two.txt", b"two", "text/plain")},
    )
    calls = []

    class FakeRedis:
        def lpush(self, queue_name, payload):
            calls.append((queue_name, payload))

    monkeypatch.setattr("backend.app.api.knowledge._redis_client", lambda: FakeRedis())

    response = client.post(f"/api/v1/knowledge/topics/{topic['id']}/ingest")

    assert response.status_code == 200
    assert response.json()["queued"] == 2
    assert len(calls) == 2
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python -m pytest backend/tests/test_knowledge_api.py::test_ingest_resource_enqueues_job_instead_of_calling_engine backend/tests/test_knowledge_api.py::test_topic_ingest_enqueues_all_eligible_documents -q
```

Expected: FAIL because APIs do not use queue service.

- [ ] **Step 3: Import queue services and Redis**

In `backend/app/api/knowledge.py`, add:

```python
import redis
from ..services.knowledge_job_queue import enqueue_ingest_job, enqueue_topic_ingest_jobs
```

Add helper:

```python
def _redis_client():
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
```

- [ ] **Step 4: Replace single resource ingest endpoint**

Change `ingest_resource` to:

```python
@router.post("/resources/{resource_id}/ingest", response_model=KnowledgeResourceOut)
def ingest_resource(resource_id: str, db: Session = Depends(get_db)):
    resource = db.query(KnowledgeFile).filter(
        KnowledgeFile.id == resource_id,
        KnowledgeFile.user_id == DEFAULT_USER_ID,
    ).first()
    if not resource:
        raise HTTPException(status_code=404, detail={"code": "resource_not_found", "message": "Resource not found"})
    if not resource.item_id:
        raise HTTPException(status_code=400, detail={"code": "no_item", "message": "Resource has no associated knowledge item"})
    if resource.processing_status == "text_invalid":
        raise HTTPException(status_code=409, detail={"code": "text_invalid", "message": resource.error_message or "Document text is invalid"})

    try:
        enqueue_ingest_job(db, _redis_client(), resource.id, queue_name=settings.KNOWLEDGE_INGEST_QUEUE)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc), "message": str(exc)}) from exc

    db.refresh(resource)
    return resource
```

Leave old `_trigger_resource_ingestion` helpers in place until tests are updated, then remove them in a cleanup task if unused.

- [ ] **Step 5: Add topic batch endpoint**

Add:

```python
@router.post("/topics/{topic_id}/ingest", response_model=TopicIngestOut)
def ingest_topic_resources(topic_id: str, db: Session = Depends(get_db)):
    _get_topic_or_404(topic_id, db)
    result = enqueue_topic_ingest_jobs(db, _redis_client(), topic_id, queue_name=settings.KNOWLEDGE_INGEST_QUEUE)
    return TopicIngestOut(
        queued=result.queued,
        skipped=result.skipped,
        failed=result.failed,
        job_ids=result.job_ids or [],
        messages=result.messages or [],
    )
```

Add `TopicIngestOut` import from schemas.

- [ ] **Step 6: Update old tests expecting background thread**

Tests like `test_ingest_resource_returns_processing_and_triggers_background` should be rewritten to expect queued status and a Redis enqueue call. Keep test intent: API should not do heavy work inline.

- [ ] **Step 7: Run knowledge API tests**

Run:

```bash
python -m pytest backend/tests/test_knowledge_api.py -q
```

Expected: PASS.

---

## Task 8: Build Engine Worker Infrastructure

**Files:**

- Create: `engine/app/jobs/__init__.py`
- Create: `engine/app/jobs/redis_queue.py`
- Create: `engine/app/jobs/worker.py`
- Modify: `engine/run.py`
- Create: `engine/tests/test_ingest_workers.py`

- [ ] **Step 1: Write failing worker claim/retry tests**

Create `engine/tests/test_ingest_workers.py`:

```python
from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import KnowledgeFile, KnowledgeItem, KnowledgeJob, KnowledgeTopic
from backend.app.utils.time import local_now


def _setup():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return engine, Session


def _resource_and_job(Session, status="queued"):
    db = Session()
    topic = KnowledgeTopic(user_id="default-user", name="Jobs")
    item = KnowledgeItem(title="Paper", content="hello", source_type="file", user_id="default-user")
    db.add_all([topic, item])
    db.flush()
    resource = KnowledgeFile(
        user_id="default-user",
        topic_id=topic.id,
        item_id=item.id,
        title="Paper",
        original_filename="paper.pdf",
        media_type="document",
        file_ext=".pdf",
        file_size=10,
        md5="job-md5",
        storage_path="/tmp/paper.pdf",
        processing_status="queued",
    )
    db.add(resource)
    db.flush()
    job = KnowledgeJob(
        job_type="ingest",
        resource_id=resource.id,
        item_id=item.id,
        topic_id=topic.id,
        status=status,
        max_attempts=3,
    )
    db.add(job)
    db.commit()
    job_id = job.id
    resource_id = resource.id
    db.close()
    return job_id, resource_id


def test_worker_claims_queued_job(monkeypatch):
    from engine.app.jobs import worker

    _, Session = _setup()
    job_id, _ = _resource_and_job(Session)
    monkeypatch.setattr(worker, "_Session", Session)

    db = Session()
    try:
        job = worker.claim_job(db, job_id, worker_id="test-worker")
        assert job is not None
        assert job.status == "processing"
        assert job.locked_by == "test-worker"
        assert job.attempts == 1
    finally:
        db.close()


def test_retryable_failure_requeues_until_max_attempts(monkeypatch):
    from engine.app.jobs import worker

    _, Session = _setup()
    job_id, resource_id = _resource_and_job(Session)
    monkeypatch.setattr(worker, "_Session", Session)

    db = Session()
    try:
        job = worker.claim_job(db, job_id, worker_id="test-worker")
        worker.mark_retry_or_failed(db, job, RuntimeError("temporary"), retryable=True)
        db.refresh(job)
        assert job.status == "queued"
        assert job.error_message == "temporary"

        job.status = "processing"
        job.attempts = 3
        db.commit()
        worker.mark_retry_or_failed(db, job, RuntimeError("temporary"), retryable=True)
        db.refresh(job)
        resource = db.query(KnowledgeFile).filter_by(id=resource_id).one()
        assert job.status == "failed"
        assert resource.processing_status == "failed"
    finally:
        db.close()


def test_recover_stale_processing_jobs(monkeypatch):
    from engine.app.jobs import worker

    _, Session = _setup()
    job_id, _ = _resource_and_job(Session, status="processing")
    monkeypatch.setattr(worker, "_Session", Session)

    db = Session()
    job = db.query(KnowledgeJob).filter_by(id=job_id).one()
    job.locked_at = local_now() - timedelta(seconds=3600)
    db.commit()
    db.close()

    recovered = worker.recover_stale_jobs(stale_seconds=60)
    assert recovered == 1
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python -m pytest engine/tests/test_ingest_workers.py -q
```

Expected: FAIL because worker module does not exist.

- [ ] **Step 3: Create Redis queue helper**

Create `engine/app/jobs/redis_queue.py`:

```python
import json

import redis

from engine.app.config import settings


def redis_client():
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def push_job(client, queue_name: str, job_id: str) -> None:
    client.lpush(queue_name, json.dumps({"job_id": job_id}))


def pop_job(client, queue_name: str, timeout_seconds: int = 2) -> str | None:
    item = client.brpop(queue_name, timeout=timeout_seconds)
    if not item:
        return None
    _queue, payload = item
    data = json.loads(payload)
    return data.get("job_id")
```

- [ ] **Step 4: Implement worker core**

Create `engine/app/jobs/worker.py` with these public functions:

```python
import logging
import socket
import threading
import time
from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models import KnowledgeFile, KnowledgeJob
from backend.app.services.document_text_quality import assess_document_text
from backend.app.utils.time import local_now
from engine.app.config import settings
from engine.app.ingestion.pipeline import ingest_item

from .redis_queue import pop_job, push_job, redis_client

_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)
logger = logging.getLogger("uvicorn.error")


class HardJobFailure(RuntimeError):
    pass


def _worker_id(prefix: str) -> str:
    return f"{prefix}:{socket.gethostname()}:{threading.get_ident()}"


def claim_job(db, job_id: str, worker_id: str) -> KnowledgeJob | None:
    job = db.query(KnowledgeJob).filter(KnowledgeJob.id == job_id).first()
    if not job or job.status != "queued":
        return None
    now = local_now()
    job.status = "processing"
    job.locked_by = worker_id
    job.locked_at = now
    job.started_at = job.started_at or now
    job.attempts += 1
    db.commit()
    db.refresh(job)
    return job


def update_job_progress(db, job: KnowledgeJob, *, stage: str, current: int = 0, total: int = 0) -> None:
    job.stage = stage
    job.progress_current = current
    job.progress_total = total
    db.commit()


def mark_done(db, job: KnowledgeJob) -> None:
    job.status = "done"
    job.stage = "done"
    job.finished_at = local_now()
    job.locked_by = ""
    job.locked_at = None
    db.commit()


def mark_retry_or_failed(db, job: KnowledgeJob, exc: Exception, *, retryable: bool) -> None:
    message = str(exc)[:2000]
    job.error_message = message
    job.error_code = exc.__class__.__name__
    job.locked_by = ""
    job.locked_at = None
    resource = db.query(KnowledgeFile).filter(KnowledgeFile.id == job.resource_id).first()
    if retryable and job.attempts < job.max_attempts:
        job.status = "queued"
        job.available_at = local_now() + timedelta(seconds=30 if job.attempts <= 1 else 120)
        if resource and job.job_type == "ingest":
            resource.processing_status = "queued"
        if resource and job.job_type == "governance":
            resource.governance_status = "queued"
            resource.governance_error_message = message
    else:
        job.status = "failed"
        job.finished_at = local_now()
        if resource and job.job_type == "ingest":
            resource.processing_status = "failed"
            resource.error_message = message
        if resource and job.job_type == "governance":
            resource.governance_status = "failed"
            resource.governance_error_message = message
    db.commit()


def recover_stale_jobs(stale_seconds: int | None = None) -> int:
    stale_seconds = stale_seconds or settings.KNOWLEDGE_JOB_STALE_SECONDS
    cutoff = local_now() - timedelta(seconds=stale_seconds)
    db = _Session()
    try:
        jobs = db.query(KnowledgeJob).filter(KnowledgeJob.status == "processing", KnowledgeJob.locked_at < cutoff).all()
        for job in jobs:
            job.status = "queued"
            job.locked_by = ""
            job.locked_at = None
            job.available_at = local_now()
        db.commit()
        return len(jobs)
    finally:
        db.close()
```

- [ ] **Step 5: Implement ingest execution**

Add to `worker.py`:

```python
def _validate_ingest_resource(db, job: KnowledgeJob) -> KnowledgeFile:
    resource = db.query(KnowledgeFile).filter(KnowledgeFile.id == job.resource_id).first()
    if not resource or not resource.item_id:
        raise HardJobFailure("resource_not_ingestable")
    quality = assess_document_text(
        resource.content_text,
        page_count=resource.page_count,
        max_chars=settings.KNOWLEDGE_TEXT_MAX_CHARS,
        max_chars_per_page=settings.KNOWLEDGE_TEXT_MAX_CHARS_PER_PAGE,
    )
    if not quality.ok:
        resource.processing_status = "text_invalid"
        resource.error_message = quality.message
        db.commit()
        raise HardJobFailure(quality.message)
    return resource


def run_ingest_job(job_id: str, *, worker_id: str) -> None:
    db = _Session()
    try:
        job = claim_job(db, job_id, worker_id)
        if not job:
            return
        resource = _validate_ingest_resource(db, job)
        resource.processing_status = "processing"
        db.commit()

        def progress(stage: str, current: int = 0, total: int = 0):
            update_job_progress(db, job, stage=stage, current=current, total=total)

        count = ingest_item(job.item_id, progress=progress)
        resource.processing_status = "done"
        resource.error_message = None
        resource.governance_status = "queued"
        resource.governance_error_message = None
        mark_done(db, job)
        enqueue_governance_job_from_worker(db, resource)
    except HardJobFailure as exc:
        if "job" in locals() and job:
            mark_retry_or_failed(db, job, exc, retryable=False)
    except Exception as exc:
        logger.exception("[knowledge_worker] ingest failed job_id=%s", job_id)
        if "job" in locals() and job:
            mark_retry_or_failed(db, job, exc, retryable=True)
    finally:
        db.close()
```

Also add `enqueue_governance_job_from_worker`:

```python
def enqueue_governance_job_from_worker(db, resource: KnowledgeFile) -> KnowledgeJob:
    existing = (
        db.query(KnowledgeJob)
        .filter(
            KnowledgeJob.resource_id == resource.id,
            KnowledgeJob.job_type == "governance",
            KnowledgeJob.status.in_(["queued", "processing"]),
        )
        .first()
    )
    if existing:
        return existing
    job = KnowledgeJob(
        job_type="governance",
        resource_id=resource.id,
        item_id=resource.item_id,
        topic_id=resource.topic_id,
        status="queued",
        max_attempts=3,
        available_at=local_now(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    push_job(redis_client(), settings.KNOWLEDGE_GOVERNANCE_QUEUE, job.id)
    return job
```

- [ ] **Step 6: Add worker manager skeleton**

Add to `worker.py`:

```python
class KnowledgeWorkerManager:
    def __init__(self):
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        client = redis_client()
        recover_stale_jobs()
        for index in range(max(1, settings.KNOWLEDGE_INGEST_WORKERS)):
            thread = threading.Thread(target=self._loop_ingest, args=(client, index), daemon=True)
            thread.start()
            self._threads.append(thread)
        for index in range(max(1, settings.KNOWLEDGE_GOVERNANCE_WORKERS)):
            thread = threading.Thread(target=self._loop_governance, args=(client, index), daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=3)

    def _loop_ingest(self, client, index: int) -> None:
        worker_id = f"ingest-{index}"
        while not self._stop.is_set():
            job_id = pop_job(client, settings.KNOWLEDGE_INGEST_QUEUE, timeout_seconds=2)
            if job_id:
                run_ingest_job(job_id, worker_id=worker_id)

    def _loop_governance(self, client, index: int) -> None:
        worker_id = f"governance-{index}"
        while not self._stop.is_set():
            job_id = pop_job(client, settings.KNOWLEDGE_GOVERNANCE_QUEUE, timeout_seconds=2)
            if job_id:
                run_governance_job(job_id, worker_id=worker_id)
```

`run_governance_job` is implemented in Task 9. For now define a stub that raises no error:

```python
def run_governance_job(job_id: str, *, worker_id: str) -> None:
    return None
```

- [ ] **Step 7: Start manager in engine startup**

In `engine/run.py`, import:

```python
from engine.app.jobs.worker import KnowledgeWorkerManager
```

At module level:

```python
_worker_manager = None
```

In startup:

```python
        global _worker_manager
        _worker_manager = KnowledgeWorkerManager()
        _worker_manager.start()
```

Add shutdown event:

```python
    @app.on_event("shutdown")
    def shutdown():
        global _worker_manager
        if _worker_manager:
            _worker_manager.stop()
            _worker_manager = None
```

- [ ] **Step 8: Run worker tests**

Run:

```bash
python -m pytest engine/tests/test_ingest_workers.py -q
```

Expected: PASS.

---

## Task 9: Move Governance Into Governance Worker With Progress

**Files:**

- Modify: `backend/app/services/knowledge_governance.py`
- Modify: `engine/app/jobs/worker.py`
- Modify: `engine/tests/test_ingest_workers.py`
- Test: `engine/tests/test_ingestion_governance.py`

- [ ] **Step 1: Write failing governance worker test**

Append to `engine/tests/test_ingest_workers.py`:

```python
def test_governance_worker_updates_progress_and_partial_failure(monkeypatch):
    from engine.app.jobs import worker

    _, Session = _setup()
    job_id, resource_id = _resource_and_job(Session)
    db = Session()
    job = db.query(KnowledgeJob).filter_by(id=job_id).one()
    job.job_type = "governance"
    job.status = "queued"
    resource = db.query(KnowledgeFile).filter_by(id=resource_id).one()
    resource.processing_status = "done"
    resource.governance_status = "queued"
    db.commit()
    db.close()

    monkeypatch.setattr(worker, "_Session", Session)

    def fake_settle(db, item_id, progress=None):
        progress(current=1, total=2, stage="governance")
        progress(current=2, total=2, stage="governance")

    monkeypatch.setattr(worker, "settle_document_item_to_governance", fake_settle)

    worker.run_governance_job(job_id, worker_id="governance-test")

    db = Session()
    try:
        resource = db.query(KnowledgeFile).filter_by(id=resource_id).one()
        job = db.query(KnowledgeJob).filter_by(id=job_id).one()
        assert resource.processing_status == "done"
        assert resource.governance_status == "done"
        assert resource.governance_progress_current == 2
        assert resource.governance_progress_total == 2
        assert job.status == "done"
    finally:
        db.close()
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
python -m pytest engine/tests/test_ingest_workers.py::test_governance_worker_updates_progress_and_partial_failure -q
```

Expected: FAIL because governance worker is stubbed.

- [ ] **Step 3: Add progress callback to governance service**

In `backend/app/services/knowledge_governance.py`, change signature:

```python
def settle_document_item_to_governance(db: Session, item_id: str, progress=None) -> GovernanceResult:
```

Inside the chunk loop:

```python
    total_chunks = len(chunks)
    for index, chunk in enumerate(chunks):
        if progress:
            progress(current=index, total=total_chunks, stage="governance")
```

After the loop:

```python
    if progress:
        progress(current=total_chunks, total=total_chunks, stage="governance")
```

Keep existing callers working because `progress` defaults to `None`.

- [ ] **Step 4: Implement governance worker**

In `engine/app/jobs/worker.py`, import:

```python
from backend.app.services.knowledge_governance import settle_document_item_to_governance
```

Replace `run_governance_job` stub:

```python
def run_governance_job(job_id: str, *, worker_id: str) -> None:
    db = _Session()
    try:
        job = claim_job(db, job_id, worker_id)
        if not job:
            return
        resource = db.query(KnowledgeFile).filter(KnowledgeFile.id == job.resource_id).first()
        if not resource or not resource.item_id:
            raise HardJobFailure("resource_not_governable")
        resource.governance_status = "processing"
        resource.governance_started_at = local_now()
        resource.governance_error_message = None
        db.commit()

        def progress(current: int, total: int, stage: str = "governance"):
            job.stage = stage
            job.progress_current = current
            job.progress_total = total
            resource.governance_progress_current = current
            resource.governance_progress_total = total
            db.commit()

        settle_document_item_to_governance(db, job.item_id, progress=progress)
        resource.governance_status = "done"
        resource.governance_finished_at = local_now()
        resource.governance_error_message = None
        mark_done(db, job)
    except HardJobFailure as exc:
        if "job" in locals() and job:
            mark_retry_or_failed(db, job, exc, retryable=False)
    except Exception as exc:
        logger.exception("[knowledge_worker] governance failed job_id=%s", job_id)
        if "job" in locals() and job:
            mark_retry_or_failed(db, job, exc, retryable=True)
    finally:
        db.close()
```

- [ ] **Step 5: Add exhausted failure partial-complete assertion**

Add another test:

```python
def test_governance_failure_leaves_resource_searchable_and_partial(monkeypatch):
    from engine.app.jobs import worker

    _, Session = _setup()
    job_id, resource_id = _resource_and_job(Session)
    db = Session()
    job = db.query(KnowledgeJob).filter_by(id=job_id).one()
    job.job_type = "governance"
    job.status = "queued"
    job.attempts = 2
    resource = db.query(KnowledgeFile).filter_by(id=resource_id).one()
    resource.processing_status = "done"
    resource.governance_status = "queued"
    db.commit()
    db.close()

    monkeypatch.setattr(worker, "_Session", Session)
    monkeypatch.setattr(worker, "settle_document_item_to_governance", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("llm timeout")))

    worker.run_governance_job(job_id, worker_id="governance-test")

    db = Session()
    try:
        resource = db.query(KnowledgeFile).filter_by(id=resource_id).one()
        assert resource.processing_status == "done"
        assert resource.governance_status == "failed"
        assert "llm timeout" in resource.governance_error_message
    finally:
        db.close()
```

- [ ] **Step 6: Run governance tests**

Run:

```bash
python -m pytest engine/tests/test_ingest_workers.py engine/tests/test_ingestion_governance.py -q
```

Expected: PASS.

---

## Task 10: Frontend API and Knowledge Page UI

**Files:**

- Modify: `frontend/src/app/api.ts`
- Modify: `frontend/src/pages/KnowledgePage.tsx`
- Create: `frontend/tests/knowledge-ingestion-queue.test.mjs`

- [ ] **Step 1: Write failing frontend source test**

Create `frontend/tests/knowledge-ingestion-queue.test.mjs`:

```javascript
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const api = readFileSync(resolve(root, 'src/app/api.ts'), 'utf8')
const page = readFileSync(resolve(root, 'src/pages/KnowledgePage.tsx'), 'utf8')

assert.match(api, /ingestTopicResources:/, 'API client exposes topic-level batch ingest.')
assert.match(api, /governance_status/, 'API resource type exposes governance status.')
assert.match(page, /handleIngestTopic/, 'Knowledge page handles topic batch ingest.')
assert.match(page, /partial-complete/, 'Knowledge page has partial-complete status handling.')
assert.match(page, /text-invalid/, 'Knowledge page has text-invalid status handling.')
assert.match(page, /governance_progress_current/, 'Knowledge page displays governance progress.')
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
node frontend/tests/knowledge-ingestion-queue.test.mjs
```

Expected: FAIL because API/UI are not updated.

- [ ] **Step 3: Update API types**

In `frontend/src/app/api.ts`, extend `KnowledgeResource`:

```typescript
  governance_status: string
  governance_progress_current: number
  governance_progress_total: number
  governance_error_message?: string | null
  governance_started_at?: string | null
  governance_finished_at?: string | null
```

Add:

```typescript
export interface TopicIngestResult {
  queued: number
  skipped: number
  failed: number
  job_ids: string[]
  messages: string[]
}
```

Add API method:

```typescript
  ingestTopicResources: (topicId: string) =>
    request<TopicIngestResult>(`/knowledge/topics/${topicId}/ingest`, { method: 'POST' }),
```

- [ ] **Step 4: Add composed status helper in KnowledgePage**

In `frontend/src/pages/KnowledgePage.tsx`, add helper:

```typescript
const resourcePrimaryStatus = (resource: KnowledgeResource) => {
  if (resource.processing_status === 'text_invalid') return 'text-invalid'
  if (resource.processing_status === 'queued') return 'queued'
  if (resource.processing_status === 'processing') return 'vectorizing'
  if (resource.processing_status === 'failed') return 'vectorization-failed'
  if (resource.processing_status === 'completed') return 'ready'
  if (resource.processing_status === 'done') {
    if (resource.governance_status === 'done') return 'complete'
    if (resource.governance_status === 'queued' || resource.governance_status === 'processing') return 'governance-running'
    if (resource.governance_status === 'failed') return 'partial-complete'
    return 'vectorized'
  }
  return resource.processing_status
}
```

Add label map:

```typescript
const PRIMARY_STATUS_LABEL: Record<string, string> = {
  ready: '待向量化',
  queued: '排队中',
  vectorizing: '向量化中',
  vectorized: '已向量化',
  'governance-running': '知识整理中',
  complete: '已完成',
  'partial-complete': '部分完成',
  'vectorization-failed': '向量化失败',
  'text-invalid': '文本异常',
}
```

Use Unicode only if the file already contains Chinese text. It does.

- [ ] **Step 5: Add topic batch handler**

Add:

```typescript
const handleIngestTopic = async () => {
  if (busy || !activeTopicId) return
  setBusy(true)
  setError(null)
  try {
    const result = await knowledgeApi.ingestTopicResources(activeTopicId)
    await loadResources(activeTopicId)
    if (result.failed > 0) {
      setError(`已入队 ${result.queued} 个，跳过 ${result.skipped} 个，失败 ${result.failed} 个`)
    }
  } catch (err) {
    setError(readApiError(err, '批量向量化失败'))
  } finally {
    setBusy(false)
  }
}
```

Add a button near topic resource controls:

```tsx
<button
  type="button"
  onClick={handleIngestTopic}
  disabled={busy || !activeTopicId}
  className="inline-flex h-8 items-center gap-2 rounded-md px-3 text-xs font-medium text-violet-600 transition hover:bg-violet-50 disabled:opacity-50"
>
  <Zap size={14} />
  一键向量化
</button>
```

- [ ] **Step 6: Show progress**

In resource card metadata, add:

```tsx
{resource.governance_status === 'processing' && resource.governance_progress_total > 0 && (
  <span>{`治理 ${resource.governance_progress_current}/${resource.governance_progress_total}`}</span>
)}
```

Also show job stage if backend later exposes it; do not block this task on job summary UI.

- [ ] **Step 7: Update retry buttons**

For `partial-complete`, wire the existing `onIngest` only to vectorization failures. Add a new `onRetryGovernance` prop only if backend exposes a separate governance retry endpoint in Task 11. If not yet present, display disabled title `知识整理失败，稍后可重试`.

- [ ] **Step 8: Run frontend checks**

Run:

```bash
node frontend/tests/knowledge-ingestion-queue.test.mjs
npm --prefix frontend run build
```

Expected: test passes and build succeeds.

---

## Task 11: Governance Retry Endpoint

**Files:**

- Modify: `backend/app/api/knowledge.py`
- Modify: `backend/app/services/knowledge_job_queue.py`
- Modify: `frontend/src/app/api.ts`
- Modify: `frontend/src/pages/KnowledgePage.tsx`
- Test: `backend/tests/test_knowledge_api.py`

- [ ] **Step 1: Write failing backend retry governance test**

Append to `backend/tests/test_knowledge_api.py`:

```python
def test_retry_governance_enqueues_governance_job(client, db_session, monkeypatch):
    topic = _create_topic(client)
    upload = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("notes.txt", b"hello document", "text/plain")},
    )
    resource = upload.json()
    saved = db_session.query(KnowledgeFile).filter_by(id=resource["id"]).one()
    saved.processing_status = "done"
    saved.governance_status = "failed"
    db_session.commit()
    calls = []

    class FakeRedis:
        def lpush(self, queue_name, payload):
            calls.append((queue_name, payload))

    monkeypatch.setattr("backend.app.api.knowledge._redis_client", lambda: FakeRedis())

    response = client.post(f"/api/v1/knowledge/resources/{resource['id']}/governance/retry")

    assert response.status_code == 200
    assert response.json()["governance_status"] == "queued"
    assert calls
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
python -m pytest backend/tests/test_knowledge_api.py::test_retry_governance_enqueues_governance_job -q
```

Expected: FAIL because endpoint does not exist.

- [ ] **Step 3: Add endpoint**

In `backend/app/api/knowledge.py`, import `enqueue_governance_job`.

Add:

```python
@router.post("/resources/{resource_id}/governance/retry", response_model=KnowledgeResourceOut)
def retry_resource_governance(resource_id: str, db: Session = Depends(get_db)):
    resource = db.query(KnowledgeFile).filter(
        KnowledgeFile.id == resource_id,
        KnowledgeFile.user_id == DEFAULT_USER_ID,
    ).first()
    if not resource:
        raise HTTPException(status_code=404, detail={"code": "resource_not_found", "message": "Resource not found"})
    if resource.processing_status != "done":
        raise HTTPException(status_code=409, detail={"code": "not_vectorized", "message": "Resource must be vectorized before governance"})
    enqueue_governance_job(db, _redis_client(), resource.id, queue_name=settings.KNOWLEDGE_GOVERNANCE_QUEUE)
    db.refresh(resource)
    return resource
```

- [ ] **Step 4: Add frontend API and button**

In `frontend/src/app/api.ts`:

```typescript
  retryGovernance: (id: string) =>
    request<KnowledgeResource>(`/knowledge/resources/${id}/governance/retry`, { method: 'POST' }),
```

In `KnowledgePage.tsx`, add handler similar to `handleIngest`:

```typescript
const handleRetryGovernance = async (resourceId: string) => {
  if (busy || !activeTopicId) return
  setError(null)
  try {
    const updated = await knowledgeApi.retryGovernance(resourceId)
    setResources((current) => current.map((r) => (r.id === resourceId ? updated : r)))
  } catch (err) {
    setError(readApiError(err, '知识整理重试失败'))
  }
}
```

Pass it to resource cards and show a retry action when primary status is `partial-complete`.

- [ ] **Step 5: Run backend/frontend checks**

Run:

```bash
python -m pytest backend/tests/test_knowledge_api.py::test_retry_governance_enqueues_governance_job -q
node frontend/tests/knowledge-ingestion-queue.test.mjs
```

Expected: PASS.

---

## Task 12: End-to-End Verification and Cleanup

**Files:**

- Modify only files touched by prior tasks if tests reveal issues.

- [ ] **Step 1: Run targeted backend tests**

Run:

```bash
python -m pytest backend/tests/test_models.py backend/tests/test_document_text_quality.py backend/tests/test_knowledge_job_queue.py backend/tests/test_knowledge_api.py -q
```

Expected: PASS.

- [ ] **Step 2: Run targeted engine tests**

Run:

```bash
python -m pytest engine/tests/test_chunker.py engine/tests/test_vectorizer.py engine/tests/test_milvus_client.py engine/tests/test_ingest_api.py engine/tests/test_ingestion_governance.py engine/tests/test_ingest_workers.py -q
```

Expected: PASS.

- [ ] **Step 3: Run frontend tests/build**

Run:

```bash
node frontend/tests/knowledge-topic-resource.test.mjs
node frontend/tests/knowledge-ingestion-queue.test.mjs
npm --prefix frontend run build
```

Expected: PASS and build succeeds.

- [ ] **Step 4: Compile changed Python modules**

Run:

```bash
python -m py_compile backend/app/models/knowledge_job.py backend/app/services/document_text_quality.py backend/app/services/knowledge_job_queue.py backend/app/api/knowledge.py engine/app/jobs/redis_queue.py engine/app/jobs/worker.py engine/app/ingestion/pipeline.py engine/app/ingestion/chunker.py engine/app/milvus_client.py engine/run.py
```

Expected: exit code 0.

- [ ] **Step 5: Manual smoke test with live services**

With MySQL, Redis, Milvus, ES, backend, and engine running:

1. Upload a normal paper.
2. Click single resource vectorize.
3. Confirm resource becomes queued, then vectorizing, then vectorized/governance running.
4. Confirm chunks exist in MySQL.
5. Confirm governance progress increments.
6. Upload or simulate abnormal text and confirm `text_invalid`.
7. Click topic-level batch vectorize on several resources and confirm jobs are queued, not run inline.

Expected: no MySQL lock waits and Redis queues drain according to worker concurrency.

- [ ] **Step 6: Inspect git diff**

Run:

```bash
git diff --stat
git diff -- backend/app/models/knowledge_job.py backend/app/models/knowledge_item.py backend/app/api/knowledge.py engine/app/jobs/worker.py engine/app/ingestion/pipeline.py frontend/src/pages/KnowledgePage.tsx
```

Expected: changes match this plan; no unrelated files reverted.

---

## Self-Review Checklist

- Spec coverage:
  - Redis queue plus MySQL job table: Tasks 1, 6, 8.
  - Producer-consumer batch ingestion: Tasks 6, 7, 8.
  - Ingest workers default concurrency 2: Task 3 and Task 8.
  - Governance separated and visible: Tasks 1, 5, 9, 10, 11.
  - Partial complete on governance failure: Tasks 1, 9, 10.
  - PDF text abnormal blocking: Task 2 and Task 8.
  - Chunk 384/1536 and embedding batch 64: Task 3.
  - Milvus batch insert: Task 4 and Task 5.
  - Topic-level one-click vectorization: Task 7 and Task 10.
  - Automatic retry 2 times plus manual retry: Tasks 8 and 11.

- Placeholder scan:
  - No `TBD`, `TODO`, or "implement later" steps are intended.
  - Each task has concrete test and implementation guidance.

- Type consistency:
  - `KnowledgeJob`, `KnowledgeJobSummary`, and `TopicIngestOut` are named consistently.
  - Queue names are `KNOWLEDGE_INGEST_QUEUE` and `KNOWLEDGE_GOVERNANCE_QUEUE`.
  - Resource governance fields use `governance_*`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-27-knowledge-ingestion-queue-optimization.md`. Two execution options:

1. **Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
