# engine/app/jobs/knowledge_handlers.py
"""Parse, chunk, and index handlers that execute as durable Engine jobs."""
import logging
import sys
from datetime import timedelta
from hashlib import sha256
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from engine.app.config import settings as _engine_settings

from backend.app.models import KnowledgeFile, KnowledgeItem, KnowledgeChunk, KnowledgeTopic
from backend.app.models.knowledge_types import StageStatus, uuid4_str
from backend.app.services.entity_extraction import extract_entity_candidates_from_text
from backend.app.services.graph_facts import GraphFactScope, GraphFactWriter
from backend.app.config import settings
from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
from backend.app.storage.files import LocalFileStorage
from engine.app.indexing.publisher import GenerationPublisher, mark_kb_index_complete
from engine.app.indexing.profiles import DEFAULT_PROFILE
from engine.app.ingestion.parsers import build_default_registry
from engine.app.ingestion.presets import chunk_with_preset
from engine.app.knowledge.enrichment import activate_graph_generation

logger = logging.getLogger(__name__)


def _new_index_generation() -> str:
    return uuid4_str()


def _graph_content_hash(text: str) -> str:
    return sha256((text or "").encode("utf-8")).hexdigest()


def _build_scoped_graph_generation(db_session, tenant_id: str, kb_uid: str, generation: str) -> int:
    files = (
        db_session.query(KnowledgeFile)
        .filter(
            KnowledgeFile.tenant_id == tenant_id,
            KnowledgeFile.kb_uid == kb_uid,
            KnowledgeFile.deleted_at.is_(None),
            KnowledgeFile.parse_status == StageStatus.SUCCEEDED.value,
            KnowledgeFile.parsed_content_version.isnot(None),
        )
        .all()
    )
    file_generations = {
        file_row.file_uid: str(file_row.parsed_content_version)
        for file_row in files
        if file_row.parsed_content_version
    }
    chunks = (
        db_session.query(KnowledgeChunk)
        .filter(
            KnowledgeChunk.tenant_id == tenant_id,
            KnowledgeChunk.kb_uid == kb_uid,
            KnowledgeChunk.file_uid.in_(list(file_generations)),
            KnowledgeChunk.chunk_type == "child",
        )
        .order_by(KnowledgeChunk.file_uid, KnowledgeChunk.chunk_uid)
        .all()
    )
    writer = GraphFactWriter(db_session)
    settled_chunks = 0
    for chunk in chunks:
        if chunk.generation != file_generations.get(chunk.file_uid):
            continue
        candidates = extract_entity_candidates_from_text(
            chunk.chunk_text or "",
            source_kind="document_chunk",
        )
        if not candidates:
            continue
        writer.settle(
            GraphFactScope(
                tenant_id=tenant_id,
                kb_uid=kb_uid,
                file_uid=chunk.file_uid,
                item_id=chunk.item_id or "",
                chunk_uid=chunk.chunk_uid,
                graph_generation=generation,
            ),
            candidates,
            content_hash=_graph_content_hash(chunk.chunk_text or ""),
            extractor_config_hash="rule-graph-builder-v1",
            model_version="rule-based",
            prompt_version="rule-graph-builder-v1",
        )
        settled_chunks += 1
    return settled_chunks


def _delete_file_scoped_graph_facts(
    db_session,
    file_row: KnowledgeFile,
    generation: str,
    chunk_uids: list[str],
) -> tuple[list[str], list[str]]:
    from backend.app.models import EntityAlias, EntityMention, EntityRelation, KnowledgeEntity
    from backend.app.models.graph_outbox import GraphExtractionRevision
    from sqlalchemy.orm import aliased

    entity_ids = {
        row[0]
        for row in db_session.query(EntityMention.entity_id)
        .filter(
            EntityMention.tenant_id == file_row.tenant_id,
            EntityMention.kb_uid == file_row.kb_uid,
            EntityMention.graph_generation == generation,
            EntityMention.file_uid == file_row.file_uid,
        )
        .all()
    }
    relation_entity_rows = (
        db_session.query(EntityRelation.subject_entity_id, EntityRelation.object_entity_id)
        .filter(
            EntityRelation.tenant_id == file_row.tenant_id,
            EntityRelation.kb_uid == file_row.kb_uid,
            EntityRelation.graph_generation == generation,
            EntityRelation.file_uid == file_row.file_uid,
        )
        .all()
    )
    relation_ids = [
        row[0]
        for row in db_session.query(EntityRelation.id)
        .filter(
            EntityRelation.tenant_id == file_row.tenant_id,
            EntityRelation.kb_uid == file_row.kb_uid,
            EntityRelation.graph_generation == generation,
            EntityRelation.file_uid == file_row.file_uid,
        )
        .all()
    ]
    for subject_id, object_id in relation_entity_rows:
        if subject_id:
            entity_ids.add(subject_id)
        if object_id:
            entity_ids.add(object_id)

    db_session.query(EntityRelation).filter(
        EntityRelation.tenant_id == file_row.tenant_id,
        EntityRelation.kb_uid == file_row.kb_uid,
        EntityRelation.graph_generation == generation,
        EntityRelation.file_uid == file_row.file_uid,
    ).delete(synchronize_session=False)
    db_session.query(EntityMention).filter(
        EntityMention.tenant_id == file_row.tenant_id,
        EntityMention.kb_uid == file_row.kb_uid,
        EntityMention.graph_generation == generation,
        EntityMention.file_uid == file_row.file_uid,
    ).delete(synchronize_session=False)
    if chunk_uids:
        db_session.query(GraphExtractionRevision).filter(
            GraphExtractionRevision.tenant_id == file_row.tenant_id,
            GraphExtractionRevision.kb_uid == file_row.kb_uid,
            GraphExtractionRevision.file_uid == file_row.file_uid,
            GraphExtractionRevision.chunk_uid.in_(chunk_uids),
        ).delete(synchronize_session=False)

    if not entity_ids:
        return relation_ids, []
    outgoing = aliased(EntityRelation)
    incoming = aliased(EntityRelation)
    orphan_ids = [
        entity_id
        for (entity_id,) in db_session.query(KnowledgeEntity.id)
        .filter(KnowledgeEntity.id.in_(entity_ids))
        .outerjoin(EntityMention, EntityMention.entity_id == KnowledgeEntity.id)
        .outerjoin(outgoing, outgoing.subject_entity_id == KnowledgeEntity.id)
        .outerjoin(incoming, incoming.object_entity_id == KnowledgeEntity.id)
        .filter(EntityMention.id.is_(None))
        .filter(outgoing.id.is_(None))
        .filter(incoming.id.is_(None))
        .all()
    ]
    if orphan_ids:
        db_session.query(EntityAlias).filter(EntityAlias.entity_id.in_(orphan_ids)).delete(synchronize_session=False)
        db_session.query(KnowledgeEntity).filter(KnowledgeEntity.id.in_(orphan_ids)).delete(synchronize_session=False)
    return relation_ids, orphan_ids


def _build_file_scoped_graph_generation(db_session, file_row: KnowledgeFile, generation: str) -> tuple[int, list[str], list[str]]:
    chunks = (
        db_session.query(KnowledgeChunk)
        .filter(
            KnowledgeChunk.tenant_id == file_row.tenant_id,
            KnowledgeChunk.kb_uid == file_row.kb_uid,
            KnowledgeChunk.file_uid == file_row.file_uid,
            KnowledgeChunk.generation == str(file_row.parsed_content_version),
            KnowledgeChunk.chunk_type == "child",
        )
        .order_by(KnowledgeChunk.chunk_uid)
        .all()
    )
    removed_relation_ids, removed_entity_ids = _delete_file_scoped_graph_facts(
        db_session,
        file_row,
        generation,
        [chunk.chunk_uid for chunk in chunks],
    )
    writer = GraphFactWriter(db_session)
    settled_chunks = 0
    for chunk in chunks:
        candidates = extract_entity_candidates_from_text(
            chunk.chunk_text or "",
            source_kind="document_chunk",
        )
        if not candidates:
            continue
        writer.settle(
            GraphFactScope(
                tenant_id=file_row.tenant_id,
                kb_uid=file_row.kb_uid,
                file_uid=file_row.file_uid,
                item_id=file_row.item_id or "",
                chunk_uid=chunk.chunk_uid,
                graph_generation=generation,
            ),
            candidates,
            content_hash=_graph_content_hash(chunk.chunk_text or ""),
            extractor_config_hash="rule-graph-builder-v1",
            model_version="rule-based",
            prompt_version="rule-graph-builder-v1",
        )
        settled_chunks += 1
    return settled_chunks, removed_relation_ids, removed_entity_ids


def handle_delete(job_id, worker_id, db_session, job_svc, cleanup):
    lease = timedelta(seconds=120)
    try:
        job = job_svc.claim(job_id, worker_id, lease)
        if job is None:
            return {"status": "skipped"}
        job_svc.start(job_id, worker_id)
        result = cleanup.run(job.file_uid, job_id=job_id)
        if result.status != "succeeded":
            job_svc.fail(
                job_id,
                worker_id,
                "DELETE_CLEANUP_ERROR",
                result.error or "cleanup failed",
                True,
            )
            return {
                "status": "failed",
                "checkpoint": result.checkpoint,
                "error": result.error,
            }
        job_svc.succeed(job_id, worker_id, {"checkpoint": result.checkpoint})
        return {"status": "completed", "checkpoint": result.checkpoint}
    except Exception as exc:
        db_session.rollback()
        try:
            job_svc.fail(job_id, worker_id, "DELETE_CLEANUP_ERROR", str(exc), True)
        except Exception:
            pass
        return {"status": "failed", "error": str(exc)}
    finally:
        close = getattr(cleanup, "close", None)
        if close:
            close()


def handle_parse(
    job_id: str,
    worker_id: str,
    db_session,
    job_svc: KnowledgeJobService,
    publisher=None,
) -> dict:
    lease = timedelta(seconds=120)
    job = job_svc.claim(job_id, worker_id, lease)
    if job is None:
        return {"status": "skipped"}

    try:
        job_svc.start(job_id, worker_id)
    except Exception:
        return {"status": "skipped"}

    try:
        file_row = (
            db_session.query(KnowledgeFile)
            .filter_by(file_uid=job.file_uid, deleted_at=None)
            .one_or_none()
        )
        if file_row is None:
            job_svc.fail(job_id, worker_id, "FILE_NOT_FOUND", "File not found", False)
            return {"status": "failed", "error": "FILE_NOT_FOUND"}

        file_row.parse_status = StageStatus.RUNNING.value
        file_row.parse_error = None
        db_session.commit()

        db_session.refresh(job)
        if job.cancel_requested_at is not None:
            file_row.parse_status = StageStatus.PENDING.value
            db_session.commit()
            job_svc.cancel(job_id, worker_id)
            return {"status": "canceled"}

        storage = LocalFileStorage(Path(settings.KNOWLEDGE_STORAGE_ROOT))
        storage_path = Path(storage._resolve(file_row.storage_uri))
        content = storage_path.read_bytes()

        registry = build_default_registry()
        parsed = registry.parse(
            storage_path,
            media_type="document",
            config=file_row.parser_config_snapshot or {},
        )
        job_svc.heartbeat(job_id, worker_id, lease)
        db_session.refresh(job)
        if job.cancel_requested_at is not None:
            file_row.parse_status = StageStatus.PENDING.value
            db_session.commit()
            job_svc.cancel(job_id, worker_id)
            return {"status": "canceled"}

        preset_id = (file_row.chunk_config_snapshot or {}).get("preset_id", "general")
        chunks = chunk_with_preset(parsed.markdown, preset_id, {})
        db_session.refresh(job)
        if job.cancel_requested_at is not None:
            file_row.parse_status = StageStatus.PENDING.value
            db_session.commit()
            job_svc.cancel(job_id, worker_id)
            return {"status": "canceled"}

        next_version = (file_row.parsed_content_version or 0) + 1
        item = db_session.get(KnowledgeItem, file_row.item_id) if file_row.item_id else None
        if item is None:
            item = KnowledgeItem(
                tenant_id=file_row.tenant_id,
                kb_uid=file_row.kb_uid,
                title=file_row.original_filename,
                content=parsed.markdown,
                normalized_markdown=parsed.markdown,
                content_version=next_version,
            )
            db_session.add(item)
            db_session.flush()
            file_row.item_id = item.id
        else:
            item.title = file_row.original_filename
            item.content = parsed.markdown
            item.normalized_markdown = parsed.markdown
            item.content_version = next_version

        generation = str(next_version)
        db_session.query(KnowledgeChunk).filter_by(
            tenant_id=file_row.tenant_id,
            kb_uid=file_row.kb_uid,
            file_uid=file_row.file_uid,
            generation=generation,
        ).delete(synchronize_session=False)
        for parent in chunks:
            parent_chunk = KnowledgeChunk(
                tenant_id=file_row.tenant_id,
                chunk_uid=uuid4_str(),
                kb_uid=file_row.kb_uid,
                file_uid=file_row.file_uid,
                item_id=item.id,
                generation=generation,
                chunk_text=parent.content,
                chunk_type="parent",
                page_number=parent.page_start,
            )
            db_session.add(parent_chunk)
            db_session.flush()
            for child in parent.children:
                child_chunk = KnowledgeChunk(
                    tenant_id=file_row.tenant_id,
                    chunk_uid=uuid4_str(),
                    kb_uid=file_row.kb_uid,
                    file_uid=file_row.file_uid,
                    item_id=item.id,
                    generation=generation,
                    chunk_text=child.content,
                    chunk_type="child",
                    parent_id=parent_chunk.id,
                    parent_chunk_uid=parent_chunk.chunk_uid,
                    page_number=child.page_start,
                )
                db_session.add(child_chunk)

        file_row.parsed_content_version = next_version
        file_row.content_text = parsed.markdown
        file_row.parse_status = StageStatus.SUCCEEDED.value
        file_row.index_status = StageStatus.PENDING.value

        from engine.app.knowledge.enrichment import mark_enrichment_stale
        mark_enrichment_stale(
            db_session,
            file_row.kb_uid,
            reason="file_content_changed",
            commit=False,
        )

        job_svc.succeed(
            job_id,
            worker_id,
            {"item_id": item.id, "chunks_created": len(chunks)},
            commit=False,
        )
        db_session.commit()
        if job.payload and job.payload.get("auto_index"):
            index_job = job_svc.create(
                JobCommand(
                    "index",
                    file_row.tenant_id,
                    file_row.kb_uid,
                    file_row.file_uid,
                    {"content_version": file_row.parsed_content_version},
                ),
                f"{file_row.kb_uid}:{file_row.file_uid}:index:v{file_row.parsed_content_version}",
            )
            if publisher:
                publisher(index_job.id)
                job_svc.stage_enqueued(index_job.id)
        return {"status": "completed", "item_id": str(item.id)}

    except Exception as exc:
        logger.exception(
            "knowledge parse job failed job_id=%s kb_uid=%s file_uid=%s error=%s",
            job_id,
            getattr(job, "kb_uid", None),
            getattr(job, "file_uid", None),
            exc,
        )
        try:
            db_session.rollback()
            file_row = (
                db_session.query(KnowledgeFile)
                .filter_by(file_uid=job.file_uid, deleted_at=None)
                .one_or_none()
            )
            if file_row:
                file_row.parse_status = StageStatus.FAILED.value
                file_row.parse_error = {
                    "code": "PARSE_ERROR",
                    "message": str(exc),
                }
                db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            job_svc.fail(job_id, worker_id, "PARSE_ERROR", str(exc), True)
        except Exception:
            pass
        return {"status": "failed", "error": str(exc)}


def _build_generation_publisher(db_session):
    from elasticsearch import Elasticsearch

    from engine.app.indexing.es_index import V2_INDEX_NAME, ensure_v2_index
    from engine.app.indexing.milvus_index import MilvusGenerationIndex, _connect, ensure_collection

    _connect(settings.MILVUS_HOST, settings.MILVUS_PORT)
    collection = ensure_collection(
        DEFAULT_PROFILE,
        host=settings.MILVUS_HOST,
        port=settings.MILVUS_PORT,
    )
    es_client = Elasticsearch([settings.ES_HOST], request_timeout=30)
    es_index = ensure_v2_index(es_client, V2_INDEX_NAME)
    return GenerationPublisher(
        db_session,
        MilvusGenerationIndex(collection),
        es_index,
        DEFAULT_PROFILE,
    )


def handle_index(
    job_id: str,
    worker_id: str,
    db_session,
    job_svc: KnowledgeJobService,
    *,
    publisher_factory=_build_generation_publisher,
) -> dict:
    lease = timedelta(seconds=300)
    job = job_svc.claim(job_id, worker_id, lease)
    if job is None:
        return {"status": "skipped"}

    try:
        job_svc.start(job_id, worker_id)
    except Exception:
        return {"status": "skipped"}

    try:
        kb_files = []
        file_row = (
            db_session.query(KnowledgeFile)
            .filter_by(file_uid=job.file_uid, deleted_at=None)
            .one_or_none()
        )
        if file_row is None:
            job_svc.fail(job_id, worker_id, "FILE_NOT_FOUND", "File not found", False)
            return {"status": "failed", "error": "FILE_NOT_FOUND"}
        if file_row.parse_status != StageStatus.SUCCEEDED.value or not file_row.parsed_content_version:
            raise RuntimeError("file has not been parsed successfully")

        generation = _new_index_generation()
        file_row.index_status = StageStatus.RUNNING.value
        file_row.index_error = None
        db_session.commit()

        topic = (
            db_session.query(KnowledgeTopic)
            .populate_existing()
            .filter_by(
                tenant_id=file_row.tenant_id,
                kb_uid=file_row.kb_uid,
                deleted_at=None,
            )
            .one_or_none()
        )
        expected_old = topic.active_index_generation if topic is not None else None
        expected_old_graph = topic.active_graph_generation if topic is not None else None
        result = publisher_factory(db_session).build(
            file_row.kb_uid,
            generation,
            expected_old=expected_old,
        )
        if result.status != "succeeded":
            raise RuntimeError(result.error or "index build failed")

        mark_kb_index_complete(db_session, file_row.tenant_id, file_row.kb_uid, generation)
        kb_files = (
            db_session.query(KnowledgeFile)
            .filter(
                KnowledgeFile.tenant_id == file_row.tenant_id,
                KnowledgeFile.kb_uid == file_row.kb_uid,
                KnowledgeFile.deleted_at.is_(None),
                KnowledgeFile.parse_status == StageStatus.SUCCEEDED.value,
                KnowledgeFile.parsed_content_version.isnot(None),
            )
            .all()
        )
        for kb_file in kb_files:
            kb_file.graph_status = StageStatus.RUNNING.value
            kb_file.graph_error = None
        db_session.commit()

        _build_scoped_graph_generation(db_session, file_row.tenant_id, file_row.kb_uid, generation)
        activate_graph_generation(
            db_session,
            file_row.kb_uid,
            generation,
            expected_old=expected_old_graph,
        )
        for kb_file in kb_files:
            kb_file.graph_status = StageStatus.SUCCEEDED.value
            kb_file.graph_error = None
        db_session.commit()
        job_svc.succeed(
            job_id,
            worker_id,
            {"generation": generation, "row_count": result.row_count},
        )
        return {
            "status": "completed",
            "generation": generation,
            "row_count": result.row_count,
        }
    except Exception as exc:
        logger.exception(
            "knowledge index job failed job_id=%s kb_uid=%s file_uid=%s error=%s",
            job_id,
            getattr(job, "kb_uid", None),
            getattr(job, "file_uid", None),
            exc,
        )
        try:
            db_session.rollback()
            file_row = (
                db_session.query(KnowledgeFile)
                .filter_by(file_uid=job.file_uid, deleted_at=None)
                .one_or_none()
            )
            if kb_files:
                scoped_files = {
                    scoped.file_uid: scoped
                    for scoped in db_session.query(KnowledgeFile)
                    .filter(
                        KnowledgeFile.file_uid.in_([row.file_uid for row in kb_files]),
                        KnowledgeFile.deleted_at.is_(None),
                    )
                    .all()
                }
                for scoped in scoped_files.values():
                    if scoped.graph_status == StageStatus.RUNNING.value:
                        scoped.graph_status = StageStatus.FAILED.value
                    scoped.graph_error = {
                        "code": "GRAPH_ERROR",
                        "message": str(exc),
                    }
            if file_row:
                file_row.index_status = StageStatus.FAILED.value
                file_row.index_error = {
                    "code": "INDEX_ERROR",
                    "message": str(exc),
                }
                db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            job_svc.fail(job_id, worker_id, "INDEX_ERROR", str(exc), True)
        except Exception:
            pass
        return {"status": "failed", "error": str(exc)}


def handle_graph(
    job_id: str,
    worker_id: str,
    db_session,
    job_svc: KnowledgeJobService,
) -> dict:
    lease = timedelta(seconds=300)
    job = job_svc.claim(job_id, worker_id, lease)
    if job is None:
        return {"status": "skipped"}

    try:
        job_svc.start(job_id, worker_id)
    except Exception:
        return {"status": "skipped"}

    try:
        file_row = (
            db_session.query(KnowledgeFile)
            .filter_by(file_uid=job.file_uid, deleted_at=None)
            .one_or_none()
        )
        if file_row is None:
            job_svc.fail(job_id, worker_id, "FILE_NOT_FOUND", "File not found", False)
            return {"status": "failed", "error": "FILE_NOT_FOUND"}
        if file_row.parse_status != StageStatus.SUCCEEDED.value or not file_row.parsed_content_version:
            raise RuntimeError("file has not been parsed successfully")

        topic = (
            db_session.query(KnowledgeTopic)
            .populate_existing()
            .filter_by(
                tenant_id=file_row.tenant_id,
                kb_uid=file_row.kb_uid,
                deleted_at=None,
            )
            .one_or_none()
        )
        if topic is None:
            raise RuntimeError("knowledge base not found")

        expected_old_graph = topic.active_graph_generation
        generation = topic.active_graph_generation or topic.active_index_generation or _new_index_generation()
        file_row.graph_status = StageStatus.RUNNING.value
        file_row.graph_error = None
        db_session.commit()

        graph = None
        if file_row.item_id:
            from backend.app.services.graph_client import GraphClient

            graph = GraphClient()
            try:
                graph.delete_item_sources_generation(
                    file_row.tenant_id,
                    file_row.kb_uid,
                    generation,
                    file_row.item_id,
                )

                settled_chunks, removed_relation_ids, removed_entity_ids = _build_file_scoped_graph_generation(
                    db_session,
                    file_row,
                    generation,
                )
                for relation_id in removed_relation_ids:
                    graph.remove_scoped_relation(
                        file_row.tenant_id,
                        file_row.kb_uid,
                        generation,
                        relation_id,
                    )
                for entity_id in removed_entity_ids:
                    graph.remove_scoped_entity(
                        file_row.tenant_id,
                        file_row.kb_uid,
                        generation,
                        entity_id,
                    )
            finally:
                if graph is not None:
                    graph.close()
        else:
            settled_chunks, removed_relation_ids, removed_entity_ids = _build_file_scoped_graph_generation(
                db_session,
                file_row,
                generation,
            )
        if expected_old_graph is None:
            activate_graph_generation(
                db_session,
                file_row.kb_uid,
                generation,
                expected_old=expected_old_graph,
            )
        file_row.graph_status = StageStatus.SUCCEEDED.value
        file_row.graph_error = None
        db_session.commit()
        job_svc.succeed(
            job_id,
            worker_id,
            {
                "generation": generation,
                "file_uid": file_row.file_uid,
                "settled_chunks": settled_chunks,
                "removed_relation_count": len(removed_relation_ids),
                "removed_entity_count": len(removed_entity_ids),
            },
        )
        return {
            "status": "completed",
            "generation": generation,
            "file_uid": file_row.file_uid,
            "settled_chunks": settled_chunks,
            "removed_relation_count": len(removed_relation_ids),
            "removed_entity_count": len(removed_entity_ids),
        }
    except Exception as exc:
        logger.exception(
            "knowledge graph job failed job_id=%s kb_uid=%s file_uid=%s error=%s",
            job_id,
            getattr(job, "kb_uid", None),
            getattr(job, "file_uid", None),
            exc,
        )
        try:
            db_session.rollback()
            file_row = (
                db_session.query(KnowledgeFile)
                .filter_by(file_uid=job.file_uid, deleted_at=None)
                .one_or_none()
            )
            if file_row:
                file_row.graph_status = StageStatus.FAILED.value
                file_row.graph_error = {
                    "code": "GRAPH_ERROR",
                    "message": str(exc),
                }
            db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            job_svc.fail(job_id, worker_id, "GRAPH_ERROR", str(exc), True)
        except Exception:
            pass
        return {"status": "failed", "error": str(exc)}
