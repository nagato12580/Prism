"""Legacy ingest compatibility adapter backed by durable Jobs."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models import KnowledgeFile, KnowledgeItem
from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
from engine.app.config import settings
from engine.app.jobs import redis_queue

router = APIRouter(prefix="/ingest", tags=["ingest"])


class IngestRequest(BaseModel):
    item_id: str


@router.post("", status_code=202)
def ingest(req: IngestRequest, db: Session = Depends(get_db)):
    item = db.get(KnowledgeItem, req.item_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "item_not_found"})
    file_row = db.query(KnowledgeFile).filter_by(
        tenant_id=item.tenant_id,
        kb_uid=item.kb_uid,
        item_id=item.id,
        deleted_at=None,
    ).one_or_none()
    if file_row is None:
        raise HTTPException(status_code=409, detail={"code": "file_not_registered"})

    jobs = KnowledgeJobService(db)
    job = jobs.create(
        JobCommand(
            "index",
            item.tenant_id,
            item.kb_uid,
            file_row.file_uid,
            {"content_version": item.content_version},
        ),
        f"{item.kb_uid}:{file_row.file_uid}:index:v{item.content_version}",
    )
    try:
        redis_queue.push_job(
            redis_queue.redis_client(), settings.KNOWLEDGE_INGEST_QUEUE, job.id
        )
        jobs.stage_enqueued(job.id)
        db.refresh(job)
    except Exception:
        db.rollback()
    return {"id": job.id, "job_type": job.job_type, "status": job.status}
