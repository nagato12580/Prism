"""Engine knowledge processing & search endpoints."""
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from engine.app.ingestion.parsers import build_default_registry
from engine.app.retrieval.unified import unified_search

logger = logging.getLogger("uvicorn.error")
router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class ProcessRequest(BaseModel):
    kb_uid: str
    file_uid: str


class SearchRequest(BaseModel):
    kb_uid: str
    query: str
    max_results: int = 5


@router.post("/process")
def process_file(req: ProcessRequest):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from datetime import timedelta
    from backend.app.models import KnowledgeFile, KnowledgeItem
    from backend.app.models.knowledge_types import JobStatus, StageStatus
    from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
    from backend.app.storage.files import LocalFileStorage
    from engine.app.config import settings as engine_settings
    from engine.app.ingestion.pipeline import ingest_item
    from engine.app.indexing.publisher import activate_generation

    engine = create_engine(engine_settings.DATABASE_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        file_row = (
            db.query(KnowledgeFile)
            .filter_by(file_uid=req.file_uid, kb_uid=req.kb_uid, deleted_at=None)
            .one_or_none()
        )
        if file_row is None:
            raise HTTPException(404, "FILE_NOT_FOUND")

        storage_root = Path(engine_settings.KNOWLEDGE_STORAGE_ROOT)
        storage = LocalFileStorage(storage_root)
        storage_path = Path(storage._resolve(file_row.storage_uri))
        content = storage_path.read_bytes()

        registry = build_default_registry()
        parsed = registry.parse(
            storage_path,
            media_type="document",
            config=file_row.parser_config_snapshot or {},
        )

        file_row.parse_status = StageStatus.RUNNING.value
        db.commit()

        item = KnowledgeItem(
            tenant_id=file_row.tenant_id,
            kb_uid=file_row.kb_uid,
            title=file_row.original_filename,
            content=parsed.markdown,
            normalized_markdown=parsed.markdown,
            content_version=1,
        )
        db.add(item)
        db.flush()
        item_id = item.id

        file_row.item_id = item_id
        file_row.parse_status = StageStatus.SUCCEEDED.value
        file_row.parsed_content_version = 1
        file_row.index_status = StageStatus.RUNNING.value
        db.commit()

        child_chunks = ingest_item(item_id)
        logger.info("[knowledge.process] ingest_item done item_id=%s chunks=%s", item_id, child_chunks)

        file_row.index_status = StageStatus.SUCCEEDED.value
        db.commit()

        job_svc = KnowledgeJobService(db)
        parse_job_id = None
        try:
            parse_job = job_svc.create(
                JobCommand("parse", file_row.tenant_id, file_row.kb_uid, file_row.file_uid, {}),
                f"{file_row.kb_uid}:{file_row.file_uid}:parse:v1",
            )
            if parse_job.status == JobStatus.QUEUED.value:
                job_svc.claim(parse_job.id, "sync-processor", timedelta(seconds=300))
                job_svc.start(parse_job.id, "sync-processor")
                job_svc.succeed(parse_job.id, "sync-processor", {"item_id": item_id, "chunks": child_chunks})
            elif parse_job.status == JobStatus.SUCCEEDED.value:
                pass
            parse_job_id = parse_job.id
        except Exception as exc:
            logger.warning("[knowledge.process] job tracking failed: %s", exc)

        try:
            activate_generation(db, file_row.kb_uid, "0")
        except Exception as exc:
            logger.warning("[knowledge.process] activate_generation failed: %s", exc)

        return {
            "status": "succeeded",
            "item_id": item_id,
            "file_uid": req.file_uid,
            "chunks": child_chunks,
            "parse_status": file_row.parse_status,
            "index_status": file_row.index_status,
            "job_id": parse_job_id,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[knowledge.process] failed: %s", exc)
        try:
            db.rollback()
            file_row = (
                db.query(KnowledgeFile)
                .filter_by(file_uid=req.file_uid, kb_uid=req.kb_uid, deleted_at=None)
                .one_or_none()
            )
            if file_row:
                file_row.parse_status = StageStatus.FAILED.value
                db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(500, detail=str(exc))
    finally:
        db.close()


@router.post("/search")
def search_knowledge(req: SearchRequest):
    try:
        results = unified_search(req.query, req.max_results, topic_ids=[req.kb_uid])
        items = []
        for hit in results:
            items.append({
                "chunk_id": hit.get("chunk_id", ""),
                "item_id": hit.get("item_id", ""),
                "text": hit.get("text", "") or hit.get("chunk_text", "") or hit.get("snippet", ""),
                "score": hit.get("score", 0.0),
                "source_kind": hit.get("source_kind", ""),
                "title": hit.get("title", "") or hit.get("display_title", ""),
            })
        return {"status": "ok", "results": items, "total": len(items)}
    except Exception as exc:
        logger.exception("[knowledge.search] failed: %s", exc)
        return {"status": "error", "results": [], "error": str(exc)}
