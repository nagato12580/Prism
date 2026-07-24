# engine/app/jobs/knowledge_handlers.py
"""Parse, chunk, and index handlers that execute as durable Engine jobs."""
import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from backend.app.models import KnowledgeFile, KnowledgeItem, KnowledgeChunk
from backend.app.models.knowledge_types import StageStatus, uuid4_str
from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
from backend.app.storage.files import LocalFileStorage
from engine.app.ingestion.parsers import build_default_registry
from engine.app.ingestion.presets import chunk_with_preset


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
        db_session.commit()

        db_session.refresh(job)
        if job.cancel_requested_at is not None:
            file_row.parse_status = StageStatus.PENDING.value
            db_session.commit()
            job_svc.cancel(job_id, worker_id)
            return {"status": "canceled"}

        storage = LocalFileStorage(Path(os.environ.get("KNOWLEDGE_STORAGE_ROOT", "/tmp/prism-storage")))
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
        try:
            db_session.rollback()
            file_row = (
                db_session.query(KnowledgeFile)
                .filter_by(file_uid=job.file_uid, deleted_at=None)
                .one_or_none()
            )
            if file_row:
                file_row.parse_status = StageStatus.FAILED.value
                db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            job_svc.fail(job_id, worker_id, "PARSE_ERROR", str(exc), True)
        except Exception:
            pass
        return {"status": "failed", "error": str(exc)}
