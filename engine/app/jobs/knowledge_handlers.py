# engine/app/jobs/knowledge_handlers.py
"""Parse, chunk, and index handlers that execute as durable Engine jobs."""
import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from backend.app.models import KnowledgeFile, KnowledgeItem, KnowledgeChunk
from backend.app.models.knowledge_types import StageStatus, uuid4_str
from backend.app.services.knowledge_jobs import KnowledgeJobService
from backend.app.storage.files import LocalFileStorage
from engine.app.ingestion.parsers import build_default_registry
from engine.app.ingestion.presets import chunk_with_preset


def handle_parse(job_id: str, worker_id: str, db_session, job_svc: KnowledgeJobService) -> dict:
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

        storage = LocalFileStorage(Path(os.environ.get("KNOWLEDGE_STORAGE_ROOT", "/tmp/prism-storage")))
        storage_path = Path(storage._resolve(file_row.storage_uri))
        content = storage_path.read_bytes()

        registry = build_default_registry()
        parsed = registry.parse(
            storage_path,
            media_type="document",
            config=file_row.parser_config_snapshot or {},
        )

        item = KnowledgeItem(
            tenant_id=file_row.tenant_id,
            kb_uid=file_row.kb_uid,
            title=file_row.original_filename,
            content=parsed.markdown,
            normalized_markdown=parsed.markdown,
            content_version=1,
        )
        db_session.add(item)
        db_session.flush()

        file_row.item_id = item.id
        file_row.parse_status = StageStatus.SUCCEEDED.value
        file_row.parsed_content_version = 1
        db_session.commit()

        preset_id = (file_row.chunk_config_snapshot or {}).get("preset_id", "general")
        chunks = chunk_with_preset(parsed.markdown, preset_id, {})
        for parent in chunks:
            parent_chunk = KnowledgeChunk(
                chunk_uid=uuid4_str(),
                kb_uid=file_row.kb_uid,
                file_uid=file_row.file_uid,
                generation="0",
                chunk_text=parent.content,
                page_number=parent.page_start,
            )
            db_session.add(parent_chunk)
            db_session.flush()
            for child in parent.children:
                child_chunk = KnowledgeChunk(
                    chunk_uid=uuid4_str(),
                    kb_uid=file_row.kb_uid,
                    file_uid=file_row.file_uid,
                    generation="0",
                    chunk_text=child.content,
                    parent_id=parent_chunk.id,
                    page_number=child.page_start,
                )
                db_session.add(child_chunk)

        file_row.index_status = StageStatus.PENDING.value
        db_session.commit()

        job_svc.succeed(job_id, worker_id, {"item_id": item.id, "chunks_created": len(chunks)})
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
