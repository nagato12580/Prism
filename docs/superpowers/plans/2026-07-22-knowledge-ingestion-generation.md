# Knowledge Ingestion and Generation Indexing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Prism documents through durable upload, parse, chunk, index, reindex, and delete stages while publishing Milvus/Elasticsearch generations atomically.

**Architecture:** Backend owns upload/storage/metadata and enqueues typed Jobs; Engine workers consume Job IDs and execute parse/chunk/index stages. New generations are written beside active data, validated, then activated in one MySQL transaction; cleanup is asynchronous and idempotent.

**Tech Stack:** FastAPI, SQLAlchemy, MySQL, Redis, local FileStorage, PyMuPDF/python-docx/openpyxl/python-pptx, Milvus, Elasticsearch, pytest

---

## Prerequisite

Complete `2026-07-22-knowledge-foundation.md`. The following names must exist unchanged: `ActorContext`, `KnowledgeAccessPolicy`, `LocalFileStorage`, `KnowledgeJobService`, `kb_uid`, `file_uid`, `chunk_uid`, `active_index_generation`.

## File Structure

- Create: `engine/app/ingestion/parsers.py` — Parser protocol/registry and built-in adapters.
- Create: `engine/app/ingestion/presets.py` — six explicit Chunk presets.
- Modify: `engine/app/ingestion/chunker.py` — preset dispatch while preserving parent-child output.
- Create: `backend/app/api/knowledge_files.py` — upload/register/list/detail/preview/download/commands.
- Create: `backend/app/services/knowledge_uploads.py` — upload Saga and staging Reaper.
- Create: `backend/app/services/knowledge_cleanup.py` — checkpointed delete orchestration.
- Modify: `backend/app/schemas/knowledge.py` — file, command, Job response schemas.
- Modify: `backend/app/main.py` and `backend/app/api/__init__.py` — register routes/Reaper.
- Create: `engine/app/jobs/knowledge_handlers.py` — parse/chunk/index/delete handlers.
- Modify: `engine/app/jobs/worker.py` — dispatch typed Jobs and heartbeat/cancel.
- Create: `engine/app/indexing/__init__.py`
- Create: `engine/app/indexing/profiles.py` — `EmbeddingProfile` and collection naming.
- Create: `engine/app/indexing/milvus_index.py` — generation-aware schema/write/search/delete.
- Create: `engine/app/indexing/es_index.py` — generation-aware index/write/delete.
- Create: `engine/app/indexing/publisher.py` — validate and activate generation.
- Modify: `engine/app/ingestion/pipeline.py` — call stage services; remove destructive pre-delete.
- Deprecate after parity: `engine/app/api/ingest.py` process lock path.
- Create/modify tests listed under tasks.

## Task 1: Build a Capability-Driven Parser Registry

**Files:**
- Create: `engine/app/ingestion/parsers.py`
- Modify: `backend/app/utils/file_parser.py`
- Create: `engine/tests/test_parser_registry.py`

- [ ] **Step 1: Write failing registry tests**

```python
from pathlib import Path
import pytest


def test_registry_selects_markdown_parser(tmp_path: Path):
    from engine.app.ingestion.parsers import build_default_registry

    path = tmp_path / "a.md"
    path.write_text("# Title\nBody", encoding="utf-8")
    result = build_default_registry().parse(path, media_type="document", config={})
    assert result.markdown.startswith("# Title")
    assert result.parser_id == "markdown"


def test_registry_rejects_unsupported_extension(tmp_path: Path):
    from engine.app.ingestion.parsers import UnsupportedDocument, build_default_registry

    path = tmp_path / "a.bin"
    path.write_bytes(b"binary")
    with pytest.raises(UnsupportedDocument):
        build_default_registry().parse(path, media_type="document", config={})
```

- [ ] **Step 2: Run and verify missing registry failure**

Run: `python -m pytest engine/tests/test_parser_registry.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement protocol, result, and built-in adapters**

```python
# engine/app/ingestion/parsers.py
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class UnsupportedDocument(ValueError):
    pass


@dataclass(frozen=True)
class ParsedDocument:
    markdown: str
    parser_id: str
    page_count: int | None = None
    assets: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)


class DocumentParser(Protocol):
    parser_id: str
    extensions: frozenset[str]
    def parse(self, path: Path, config: dict) -> ParsedDocument: ...


class ParserRegistry:
    def __init__(self, parsers: list[DocumentParser]):
        self.parsers = parsers

    def parse(self, path: Path, media_type: str, config: dict) -> ParsedDocument:
        suffix = path.suffix.lower()
        parser = next((candidate for candidate in self.parsers if suffix in candidate.extensions), None)
        if parser is None:
            raise UnsupportedDocument(suffix)
        return parser.parse(path, config)

    def capabilities(self) -> list[dict]:
        return [{"parser_id": p.parser_id, "extensions": sorted(p.extensions)} for p in self.parsers]
```

Wrap the existing text/PDF/Office functions from `backend/app/utils/file_parser.py` in adapters rather than duplicating parsers. Parser failures must raise typed exceptions; do not return empty text as success.

- [ ] **Step 4: Add parser capability endpoint contract test**

Add a Backend test asserting `/api/v1/knowledge-bases/capabilities/parsers` returns the Engine/registry capability snapshot and that the upload UI never hardcodes more extensions than this response.

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest engine/tests/test_parser_registry.py backend/tests/test_file_parser.py -v
git add engine/app/ingestion/parsers.py engine/tests/test_parser_registry.py backend/app/utils/file_parser.py
git commit -m "feat(knowledge): 增加文档解析器注册表"
```

## Task 2: Add Six Chunk Presets with Immutable Snapshots

**Files:**
- Create: `engine/app/ingestion/presets.py`
- Modify: `engine/app/ingestion/chunker.py`
- Create: `engine/tests/test_chunk_presets.py`

- [ ] **Step 1: Write failing preset tests**

```python
import pytest


@pytest.mark.parametrize("preset_id", ["general", "qa", "book", "laws", "semantic", "separator"])
def test_each_preset_returns_parent_child_chunks(preset_id):
    from engine.app.ingestion.presets import chunk_with_preset

    chunks = chunk_with_preset("# Chapter\nQuestion? Answer.\nArticle 1 text.", preset_id, {})
    assert chunks
    assert all(parent.children for parent in chunks)


def test_unknown_preset_fails_explicitly():
    from engine.app.ingestion.presets import UnknownChunkPreset, chunk_with_preset

    with pytest.raises(UnknownChunkPreset):
        chunk_with_preset("text", "missing", {})
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest engine/tests/test_chunk_presets.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement immutable preset configs**

```python
# engine/app/ingestion/presets.py
from dataclasses import dataclass
from .chunker import ParentChunk, chunk_parent_child


class UnknownChunkPreset(ValueError):
    pass


@dataclass(frozen=True)
class ChunkPreset:
    preset_id: str
    parent_tokens: int
    child_tokens: int
    overlap_tokens: int
    separator: str | None = None


PRESETS = {
    "general": ChunkPreset("general", 1200, 384, 64),
    "qa": ChunkPreset("qa", 900, 320, 32, "\nQ:"),
    "book": ChunkPreset("book", 1600, 420, 80),
    "laws": ChunkPreset("laws", 1200, 360, 40, "\n第"),
    "semantic": ChunkPreset("semantic", 1200, 320, 48),
    "separator": ChunkPreset("separator", 1200, 384, 0, "\n---\n"),
}


def chunk_with_preset(text: str, preset_id: str, overrides: dict) -> list[ParentChunk]:
    if preset_id not in PRESETS:
        raise UnknownChunkPreset(preset_id)
    preset = PRESETS[preset_id]
    config = {**preset.__dict__, **overrides}
    return chunk_parent_child(
        text,
        parent_tokens=int(config["parent_tokens"]),
        child_tokens=int(config["child_tokens"]),
        overlap_tokens=int(config["overlap_tokens"]),
        separator=config.get("separator"),
    )
```

Update `chunk_parent_child` signature to accept these explicit values. Semantic preset must call the configured semantic splitter; if its embedding dependency is unavailable, mark the parse/chunk Job failed with `SEMANTIC_CHUNKER_UNAVAILABLE` rather than silently using general.

- [ ] **Step 4: Persist exact config snapshot in file/item records**

Add a test proving a later KB config change does not mutate an existing file's `chunk_config_snapshot`.

- [ ] **Step 5: Run and commit**

```bash
python -m pytest engine/tests/test_chunk_presets.py engine/tests/test_chunker.py -v
git add engine/app/ingestion/presets.py engine/app/ingestion/chunker.py engine/tests/test_chunk_presets.py engine/tests/test_chunker.py
git commit -m "feat(knowledge): 增加版本化分块预设"
```

## Task 3: Implement Upload Saga and File APIs

**Files:**
- Create: `backend/app/services/knowledge_uploads.py`
- Create: `backend/app/api/knowledge_files.py`
- Modify: `backend/app/schemas/knowledge.py`
- Modify: `backend/app/api/__init__.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_knowledge_upload_saga.py`
- Create: `backend/tests/test_knowledge_files_v1_api.py`

- [ ] **Step 1: Write failing Saga/API tests**

```python
def test_upload_commits_file_and_enqueues_parse(client, fake_storage, fake_redis):
    response = client.post(
        "/api/v1/knowledge-bases/kb-a/files",
        headers={"X-Prism-Actor": "alice", "X-Prism-Tenant": "tenant-a"},
        files={"file": ("a.md", b"# A", "text/markdown")},
        data={"relative_path": "docs/a.md", "auto_index": "true"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["file"]["storage_uri"].startswith("local://") is False
    assert body["file"]["parse_status"] == "pending"
    assert body["job"]["job_type"] == "parse"


def test_failed_storage_commit_leaves_no_registered_file(client, fake_storage):
    fake_storage.fail_commit = True
    response = client.post("/api/v1/knowledge-bases/kb-a/files", files={"file": ("a.md", b"x")})
    assert response.status_code == 503
    assert fake_storage.staged_files == []
```

- [ ] **Step 2: Run and verify missing routes**

Run: `python -m pytest backend/tests/test_knowledge_upload_saga.py backend/tests/test_knowledge_files_v1_api.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement `KnowledgeUploadService`**

```python
@dataclass(frozen=True)
class UploadRequest:
    kb_uid: str
    filename: str
    relative_path: str
    media_type: str
    content: bytes
    parser_config: dict
    chunk_config: dict
    auto_index: bool


class KnowledgeUploadService:
    def register(self, actor: ActorContext, request: UploadRequest) -> tuple[KnowledgeFile, KnowledgeJob]:
        topic = self.policy.require_manage(actor, request.kb_uid)
        file_uid = uuid4_str()
        staged = self.storage.stage(actor.tenant_id, topic.kb_uid, file_uid, request.filename, request.content)
        try:
            duplicate = self.db.query(KnowledgeFile).filter_by(
                tenant_id=actor.tenant_id, kb_uid=topic.kb_uid, content_sha256=staged.sha256, deleted_at=None,
            ).one_or_none()
            if duplicate:
                raise DuplicateKnowledgeFile(duplicate.file_uid)
            storage_uri = self.storage.commit(staged)
            file = KnowledgeFile(
                file_uid=file_uid, tenant_id=actor.tenant_id, kb_uid=topic.kb_uid,
                original_filename=request.filename, relative_path=request.relative_path,
                storage_uri=storage_uri, content_sha256=staged.sha256, size_bytes=staged.size_bytes,
                parser_config_snapshot=request.parser_config, chunk_config_snapshot=request.chunk_config,
            )
            self.db.add(file)
            self.db.commit()
            command = JobCommand("parse", actor.tenant_id, topic.kb_uid, file_uid, {"auto_index": request.auto_index})
            job = self.jobs.create(command, f"{topic.kb_uid}:{file_uid}:parse:{file.parsed_content_version}")
            self.queue.publish(job.id)
            return file, job
        except Exception:
            if staged.path.exists():
                staged.path.unlink()
            raise
```

Response serializers must expose a preview/download URL, never `storage_uri`.

- [ ] **Step 4: Add list/detail/preview/download/parse/index/delete routes**

All routes use `KnowledgeAccessPolicy`. List supports `cursor`, `limit <= 500`, `relative_path`, `media_type`, and stage status filters. Parse/index/delete commands return HTTP 202 with Job snapshot.

- [ ] **Step 5: Add staging Reaper**

Implement a scheduled service that removes `.part` files older than 24 hours only when no STAGED record references them. Test referenced files are preserved.

- [ ] **Step 6: Run and commit**

```bash
python -m pytest backend/tests/test_knowledge_upload_saga.py backend/tests/test_knowledge_files_v1_api.py backend/tests/test_file_storage.py -v
git add backend/app/api/knowledge_files.py backend/app/services/knowledge_uploads.py backend/app/schemas/knowledge.py backend/app/main.py backend/tests/test_knowledge_upload_saga.py backend/tests/test_knowledge_files_v1_api.py
git commit -m "feat(knowledge): 增加文件上传 Saga 与 v1 接口"
```

## Task 4: Execute Parse and Chunk as Durable Engine Jobs

**Files:**
- Create: `engine/app/jobs/knowledge_handlers.py`
- Modify: `engine/app/jobs/worker.py`
- Modify: `engine/app/ingestion/pipeline.py`
- Create: `engine/tests/test_knowledge_job_handlers.py`
- Modify: `engine/tests/test_ingest_workers.py`

- [ ] **Step 1: Write failing parse-handler tests**

```python
def test_parse_handler_is_idempotent(db_session, local_storage, monkeypatch):
    from engine.app.jobs.knowledge_handlers import handle_parse

    file = make_registered_file(db_session, storage=local_storage, content=b"# A")
    job = make_claimed_job(db_session, "parse", file)
    first = handle_parse(job.id, worker_id="w1")
    second = handle_parse(job.id, worker_id="w1")
    assert first.content_version == second.content_version == 1
    assert count_items(db_session, file.file_uid) == 1


def test_parse_failure_sets_error_without_losing_source(db_session, local_storage, monkeypatch):
    file = make_registered_file(db_session, storage=local_storage, content=b"bad")
    monkeypatch.setattr("engine.app.jobs.knowledge_handlers.build_default_registry", failing_registry)
    result = run_job("parse", file)
    assert result.status == "failed"
    assert file.parse_status == "failed"
    assert local_storage.exists(file.storage_uri)
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest engine/tests/test_knowledge_job_handlers.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement typed handlers**

`handle_parse` must:

1. claim/heartbeat Job;
2. conditionally move file parse status pending/failed -> running;
3. read source through local FileStorage;
4. parse and save versioned Markdown/metadata;
5. persist one logical Item;
6. call `chunk_with_preset` and replace only the new content version's MySQL Chunk draft rows;
7. mark parse/chunk succeeded;
8. enqueue index when `auto_index` is true;
9. check cancellation between parser, chunk, and enqueue stages.

Use one MySQL transaction for Item/Chunk draft rows. External parsing output files are committed before the transaction and cleaned if persistence fails.

- [ ] **Step 4: Remove process-global ingest lock from the primary path**

Keep `/api/v1/ingest` only as a compatibility adapter that creates/returns a Job; it must not call `ingest_item` under `_ingest_lock`.

- [ ] **Step 5: Run handler/worker tests and commit**

```bash
python -m pytest engine/tests/test_knowledge_job_handlers.py engine/tests/test_ingest_workers.py engine/tests/test_ingest_api.py -v
git add engine/app/jobs/knowledge_handlers.py engine/app/jobs/worker.py engine/app/ingestion/pipeline.py engine/app/api/ingest.py engine/tests
git commit -m "feat(knowledge): 将解析分块改为持久任务"
```

## Task 5: Build Generation-Aware Milvus and Elasticsearch Indexes

**Files:**
- Create: `engine/app/indexing/profiles.py`
- Create: `engine/app/indexing/milvus_index.py`
- Create: `engine/app/indexing/es_index.py`
- Create: `engine/app/indexing/publisher.py`
- Modify: `engine/app/milvus_client.py`
- Modify: `engine/app/es_client.py`
- Modify: `engine/app/ingestion/pipeline.py`
- Create: `engine/tests/test_index_profiles.py`
- Create: `engine/tests/test_generation_publisher.py`
- Create: `engine/tests/integration/test_generation_indexes.py`

- [ ] **Step 1: Write failing profile/publisher tests**

```python
def test_embedding_profile_collection_name_is_stable():
    from engine.app.indexing.profiles import EmbeddingProfile

    profile = EmbeddingProfile("jina", "jina-embeddings-v3", 1024, "COSINE", True)
    assert profile.profile_id == profile.profile_id
    assert profile.document_collection.startswith("prism_kb_")


def test_failed_generation_does_not_switch_active(db_session, fake_milvus, fake_es):
    from engine.app.indexing.publisher import GenerationPublisher

    topic = make_topic(db_session, active_index_generation="old")
    fake_es.fail_bulk = True
    result = GenerationPublisher(db_session, fake_milvus, fake_es).build(topic.kb_uid, "new")
    assert result.status == "failed"
    db_session.refresh(topic)
    assert topic.active_index_generation == "old"
    assert fake_milvus.deleted_generations == ["new"]
```

- [ ] **Step 2: Run and verify failures**

Run: `python -m pytest engine/tests/test_index_profiles.py engine/tests/test_generation_publisher.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement EmbeddingProfile**

```python
from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class EmbeddingProfile:
    provider: str
    model: str
    dimension: int
    metric: str
    normalize: bool

    @property
    def profile_id(self) -> str:
        raw = f"{self.provider}|{self.model}|{self.dimension}|{self.metric}|{int(self.normalize)}"
        return sha256(raw.encode()).hexdigest()[:16]

    @property
    def document_collection(self) -> str:
        return f"prism_kb_{self.profile_id}"

    @property
    def graph_collection(self) -> str:
        return f"prism_graph_{self.profile_id}"
```

- [ ] **Step 4: Implement scoped schemas**

Milvus rows include `tenant_id/kb_uid/file_uid/item_id/chunk_uid/source_type/generation/embedding_model_version/content/embedding`. Search methods require a scope object and construct native scalar expressions.

Elasticsearch v2 index includes the same scope fields, parent/child text, title, page range, and generation. Use `routing=kb_uid`; do not catch request errors and return `[]`.

- [ ] **Step 5: Implement generation publisher**

The publisher embeds child texts, writes Milvus and ES batches, validates row counts/dimensions and one scoped sample query, then conditionally updates `KnowledgeTopic.active_index_generation` from the expected old value to new. On any failure, delete only new-generation rows.

- [ ] **Step 6: Run unit and real service tests**

```bash
python -m pytest engine/tests/test_index_profiles.py engine/tests/test_generation_publisher.py -v
python -m pytest engine/tests/integration/test_generation_indexes.py -v
```

Expected: scoped queries return only requested KB; failed publish leaves old active.

- [ ] **Step 7: Commit generation indexes**

```bash
git add engine/app/indexing engine/app/milvus_client.py engine/app/es_client.py engine/app/ingestion/pipeline.py engine/tests/test_index_profiles.py engine/tests/test_generation_publisher.py engine/tests/integration/test_generation_indexes.py
git commit -m "feat(knowledge): 增加原子索引 generation 发布"
```

## Task 6: Implement Idempotent Delete and Reconciliation

**Files:**
- Create: `backend/app/services/knowledge_cleanup.py`
- Modify: `engine/app/jobs/knowledge_handlers.py`
- Create: `backend/tests/test_knowledge_cleanup.py`
- Create: `engine/tests/integration/test_knowledge_delete_cleanup.py`

- [ ] **Step 1: Write failing checkpointed cleanup test**

```python
def test_cleanup_resumes_after_es_failure(cleanup, file_record, fake_es):
    fake_es.fail_once = True
    first = cleanup.run(file_record.file_uid)
    assert first.status == "failed"
    assert first.checkpoint == "milvus_deleted"

    second = cleanup.run(file_record.file_uid)
    assert second.status == "succeeded"
    assert cleanup.storage.exists(file_record.storage_uri) is False
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest backend/tests/test_knowledge_cleanup.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement ordered checkpoints**

Order: tombstone already applied -> Milvus generations -> ES generations -> graph Mentions/Outbox -> parsed/source storage -> Item/Chunk/File rows. Store the completed checkpoint in Job result after each idempotent step. Missing external records count as success.

- [ ] **Step 4: Add reconciler**

Create a command that detects:

- queued Jobs absent from Redis and republishes them;
- inactive generations older than retention and deletes them;
- staging files older than 24h with no DB reference;
- external rows whose `kb_uid/file_uid/generation` no longer exists.

Dry-run is default; `--apply` performs cleanup.

- [ ] **Step 5: Run integration cleanup test and commit**

```bash
python -m pytest backend/tests/test_knowledge_cleanup.py engine/tests/integration/test_knowledge_delete_cleanup.py -v
git add backend/app/services/knowledge_cleanup.py engine/app/jobs/knowledge_handlers.py backend/tests/test_knowledge_cleanup.py engine/tests/integration/test_knowledge_delete_cleanup.py
git commit -m "feat(knowledge): 增加可恢复的跨存储清理"
```

## Plan Verification

- [ ] Run all focused tests from Tasks 1–6.
- [ ] Run `python -m pytest backend/tests/test_knowledge_api.py backend/tests/test_knowledge_job_queue.py engine/tests/test_ingest_api.py engine/tests/test_ingest_workers.py engine/tests/test_chunker.py engine/tests/test_milvus_client.py -v`.
- [ ] With real services, prove failed reindex preserves old generation.
- [ ] Confirm `rg -n "_ingest_lock" engine/app` finds no primary production path.
- [ ] Confirm upload/API responses contain no `storage_uri` or local path.
- [ ] Record task commits in the roadmap.
