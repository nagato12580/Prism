# prism/backend/app/api/knowledge.py
import hashlib
import threading
from pathlib import Path
from typing import Optional

import httpx
import redis
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import cast, String, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .upload import _trigger_ingestion
from ..config import settings
from ..database import SessionLocal, get_db
from ..models.knowledge_item import KnowledgeItem, KnowledgeTopic, KnowledgeFile
from ..schemas.knowledge import (
    KnowledgeItemCreate, KnowledgeItemUpdate, KnowledgeItemOut, KnowledgeItemListOut,
    KnowledgeTopicCreate, KnowledgeTopicUpdate, KnowledgeTopicOut, KnowledgeResourceOut,
    KnowledgeResourceUpdate, TopicIngestOut,
)
from ..services.knowledge_job_queue import enqueue_governance_job, enqueue_ingest_job, enqueue_topic_ingest_jobs
from ..services.document_text_quality import assess_document_text
from ..utils.file_parser import count_pages, extract_text
from ..utils.media_type import infer_media_type

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
DEFAULT_USER_ID = "default-user"
UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
RESOURCE_INGEST_TIMEOUT_SECONDS = 1800


def _redis_client():
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def _topic_out(topic: KnowledgeTopic, resource_count: int = 0) -> KnowledgeTopicOut:
    return KnowledgeTopicOut(
        id=topic.id,
        user_id=topic.user_id,
        name=topic.name,
        description=topic.description,
        created_at=topic.created_at,
        updated_at=topic.updated_at,
        resource_count=resource_count,
    )


def _get_topic_or_404(topic_id: str, db: Session) -> KnowledgeTopic:
    topic = db.query(KnowledgeTopic).filter(
        KnowledgeTopic.id == topic_id,
        KnowledgeTopic.user_id == DEFAULT_USER_ID,
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail={"code": "topic_not_found", "message": "Topic not found"})
    return topic


def _normalize_topic_name(raw_name: str) -> str:
    name = raw_name.strip()
    if not name:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_topic_name", "message": "Topic name cannot be empty"},
        )
    return name


def _ensure_topic_name_unique(name: str, db: Session, *, exclude_topic_id: Optional[str] = None) -> None:
    query = db.query(KnowledgeTopic).filter(
        KnowledgeTopic.user_id == DEFAULT_USER_ID,
        KnowledgeTopic.name == name,
    )
    if exclude_topic_id is not None:
        query = query.filter(KnowledgeTopic.id != exclude_topic_id)
    if query.first():
        raise HTTPException(
            status_code=409,
            detail={"code": "duplicate_topic_name", "message": "Topic name already exists"},
        )


def _is_duplicate_topic_name_integrity_error(exc: IntegrityError) -> bool:
    message = str(exc)
    return (
        "uq_knowledge_topic_user_name" in message
        or "UNIQUE constraint failed: knowledge_topic.user_id, knowledge_topic.name" in message
    )


def _commit_topic_change(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _is_duplicate_topic_name_integrity_error(exc):
            raise HTTPException(
                status_code=409,
                detail={"code": "duplicate_topic_name", "message": "Topic name already exists"},
            ) from exc
        raise


def _parse_tags(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _resource_title(filename: str) -> str:
    return Path(filename or "resource").stem or "resource"


def _read_upload(file: UploadFile) -> tuple[bytes, str]:
    content = file.file.read()
    md5 = hashlib.md5(content).hexdigest()
    return content, md5


def _save_upload(content: bytes, filename: str | None, topic_id: str, md5: str) -> Path:
    ext = Path(filename or "").suffix.lower()
    topic_dir = UPLOAD_DIR / DEFAULT_USER_ID / topic_id
    topic_dir.mkdir(parents=True, exist_ok=True)
    saved_path = topic_dir / f"{md5}{ext}"
    saved_path.write_bytes(content)
    return saved_path


def _run_resource_ingestion(resource_id: str, item_id: str) -> None:
    db = SessionLocal()
    try:
        status = "failed"
        error_message = None
        try:
            resp = httpx.post(
                f"{settings.ENGINE_BASE_URL}/api/v1/ingest",
                json={"item_id": item_id},
                timeout=RESOURCE_INGEST_TIMEOUT_SECONDS,
            )
            if resp.status_code == 200:
                chunk_count = resp.json().get("chunks", 0)
                if chunk_count > 0:
                    status = "done"
                else:
                    error_message = "Ingestion returned 0 chunks (content may be empty)"
            else:
                error_message = _engine_error_message(resp)
        except Exception as exc:
            error_message = str(exc)

        resource = db.query(KnowledgeFile).filter(
            KnowledgeFile.id == resource_id,
            KnowledgeFile.user_id == DEFAULT_USER_ID,
        ).first()
        if not resource:
            return
        resource.processing_status = status
        resource.error_message = error_message
        db.commit()
    finally:
        db.close()


def _trigger_resource_ingestion(resource_id: str, item_id: str) -> None:
    thread = threading.Thread(
        target=_run_resource_ingestion,
        args=(resource_id, item_id),
        daemon=True,
    )
    thread.start()


def _engine_error_message(resp: httpx.Response) -> str:
    detail = ""
    try:
        body = resp.json()
        if isinstance(body, dict):
            raw_detail = body.get("detail")
            if isinstance(raw_detail, dict):
                detail = raw_detail.get("message") or raw_detail.get("code") or str(raw_detail)
            elif raw_detail is not None:
                detail = str(raw_detail)
    except Exception:
        detail = resp.text.strip()
    if not detail:
        detail = resp.text.strip()
    if detail:
        return f"Engine returned {resp.status_code}: {detail[:500]}"
    return f"Engine returned {resp.status_code}"


@router.post("", response_model=KnowledgeItemOut)
def create_item(payload: KnowledgeItemCreate, db: Session = Depends(get_db)):
    item = KnowledgeItem(
        title=payload.title,
        content=payload.content,
        source_type=payload.source_type,
        source_ref=payload.source_ref,
        tags=payload.tags or [],
        category=payload.category,
        user_id=DEFAULT_USER_ID,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("", response_model=list[KnowledgeItemListOut])
def list_items(
    category: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(KnowledgeItem).filter(KnowledgeItem.status != "archived")
    if category:
        query = query.filter(KnowledgeItem.category == category)
    if source_type:
        query = query.filter(KnowledgeItem.source_type == source_type)
    if tag:
        query = query.filter(cast(KnowledgeItem.tags, String).contains(f'"{tag}"'))
    return query.order_by(KnowledgeItem.created_at.desc()).all()


@router.post("/topics", response_model=KnowledgeTopicOut)
def create_topic(payload: KnowledgeTopicCreate, db: Session = Depends(get_db)):
    name = _normalize_topic_name(payload.name)
    _ensure_topic_name_unique(name, db)
    topic = KnowledgeTopic(
        user_id=DEFAULT_USER_ID,
        name=name,
        description=payload.description,
    )
    db.add(topic)
    _commit_topic_change(db)
    db.refresh(topic)
    return _topic_out(topic, 0)


@router.get("/topics", response_model=list[KnowledgeTopicOut])
def list_topics(db: Session = Depends(get_db)):
    resource_counts = (
        db.query(
            KnowledgeFile.topic_id.label("topic_id"),
            func.count(KnowledgeFile.id).label("resource_count"),
        )
        .group_by(KnowledgeFile.topic_id)
        .subquery()
    )
    rows = (
        db.query(
            KnowledgeTopic,
            func.coalesce(resource_counts.c.resource_count, 0),
        )
        .outerjoin(resource_counts, resource_counts.c.topic_id == KnowledgeTopic.id)
        .filter(KnowledgeTopic.user_id == DEFAULT_USER_ID)
        .order_by(KnowledgeTopic.updated_at.desc())
        .all()
    )
    return [_topic_out(topic, resource_count) for topic, resource_count in rows]


@router.get("/topics/{topic_id}", response_model=KnowledgeTopicOut)
def get_topic(topic_id: str, db: Session = Depends(get_db)):
    topic = _get_topic_or_404(topic_id, db)
    count = db.query(KnowledgeFile).filter(KnowledgeFile.topic_id == topic.id).count()
    return _topic_out(topic, count)


@router.post("/topics/{topic_id}/ingest", response_model=TopicIngestOut)
def ingest_topic(topic_id: str, db: Session = Depends(get_db)):
    _get_topic_or_404(topic_id, db)
    result = enqueue_topic_ingest_jobs(
        db,
        _redis_client(),
        topic_id,
        queue_name=settings.KNOWLEDGE_INGEST_QUEUE,
    )
    return TopicIngestOut(
        queued=result.queued,
        skipped=result.skipped,
        failed=result.failed,
        job_ids=result.job_ids,
        messages=result.messages,
    )


@router.put("/topics/{topic_id}", response_model=KnowledgeTopicOut)
def update_topic(topic_id: str, payload: KnowledgeTopicUpdate, db: Session = Depends(get_db)):
    topic = _get_topic_or_404(topic_id, db)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        candidate_name = _normalize_topic_name(data["name"])
        _ensure_topic_name_unique(candidate_name, db, exclude_topic_id=topic.id)
        topic.name = candidate_name
    if "description" in data:
        topic.description = data["description"]
    _commit_topic_change(db)
    db.refresh(topic)
    count = db.query(KnowledgeFile).filter(KnowledgeFile.topic_id == topic.id).count()
    return _topic_out(topic, count)


@router.delete("/topics/{topic_id}")
def delete_topic(topic_id: str, db: Session = Depends(get_db)):
    topic = _get_topic_or_404(topic_id, db)
    count = db.query(KnowledgeFile).filter(KnowledgeFile.topic_id == topic.id).count()
    if count:
        raise HTTPException(
            status_code=409,
            detail={"code": "topic_not_empty", "message": "Delete resources before deleting the topic"},
        )
    db.delete(topic)
    db.commit()
    return {"detail": "deleted"}


@router.post("/topics/{topic_id}/resources", response_model=KnowledgeResourceOut)
async def upload_topic_resource(
    topic_id: str,
    file: UploadFile = File(...),
    description: str | None = Form(None),
    tags: str | None = Form(None),
    db: Session = Depends(get_db),
):
    topic = _get_topic_or_404(topic_id, db)
    try:
        media_type = infer_media_type(file.filename or "", file.content_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "unsupported_file_type", "message": str(exc)},
        ) from exc

    content, md5 = _read_upload(file)
    duplicate = db.query(KnowledgeFile).filter(
        KnowledgeFile.user_id == DEFAULT_USER_ID,
        KnowledgeFile.topic_id == topic.id,
        KnowledgeFile.md5 == md5,
    ).first()
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail={"code": "duplicate_resource_in_topic", "message": "Resource already exists in this topic"},
        )

    saved_path = _save_upload(content, file.filename, topic.id, md5)
    resource = KnowledgeFile(
        user_id=DEFAULT_USER_ID,
        topic_id=topic.id,
        title=_resource_title(file.filename or ""),
        original_filename=file.filename or "resource",
        media_type=media_type,
        mime_type=file.content_type,
        file_ext=Path(file.filename or "").suffix.lower(),
        file_size=len(content),
        md5=md5,
        storage_path=str(saved_path),
        processing_status="metadata_only" if media_type != "document" else "processing",
        description=description,
        tags=_parse_tags(tags),
        source_type="upload",
    )
    db.add(resource)
    db.flush()

    if media_type == "document":
        try:
            text = extract_text(str(saved_path))
            resource.content_text = text
            resource.page_count = count_pages(str(saved_path))
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
            item = KnowledgeItem(
                title=resource.title,
                content=text,
                source_type="file",
                source_ref=str(saved_path),
                tags=resource.tags or [],
                category=topic.name,
                user_id=DEFAULT_USER_ID,
            )
            db.add(item)
            db.flush()
            resource.item_id = item.id
            resource.processing_status = "completed"
        except Exception as exc:
            resource.processing_status = "failed"
            resource.error_message = str(exc)

    db.commit()
    db.refresh(resource)

    # P0: 不再自动触发 ingestion。用户通过前端按钮手动触发向量化。
    # 文件解析完成，状态为 "completed"，等待用户点击"向量化"。

    return resource


@router.get("/topics/{topic_id}/resources", response_model=list[KnowledgeResourceOut])
def list_topic_resources(
    topic_id: str,
    media_type: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    processing_status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    _get_topic_or_404(topic_id, db)
    query = db.query(KnowledgeFile).filter(KnowledgeFile.topic_id == topic_id)
    if media_type:
        query = query.filter(KnowledgeFile.media_type == media_type)
    if processing_status:
        query = query.filter(KnowledgeFile.processing_status == processing_status)
    if tag:
        query = query.filter(cast(KnowledgeFile.tags, String).contains(f'"{tag}"'))
    return query.order_by(KnowledgeFile.uploaded_at.desc()).all()


@router.get("/resources/{resource_id}", response_model=KnowledgeResourceOut)
def get_resource(resource_id: str, db: Session = Depends(get_db)):
    resource = db.query(KnowledgeFile).filter(
        KnowledgeFile.id == resource_id,
        KnowledgeFile.user_id == DEFAULT_USER_ID,
    ).first()
    if not resource:
        raise HTTPException(
            status_code=404,
            detail={"code": "resource_not_found", "message": "Resource not found"},
        )
    return resource


@router.delete("/resources/{resource_id}")
def delete_resource(resource_id: str, db: Session = Depends(get_db)):
    resource = db.query(KnowledgeFile).filter(
        KnowledgeFile.id == resource_id,
        KnowledgeFile.user_id == DEFAULT_USER_ID,
    ).first()
    if not resource:
        raise HTTPException(
            status_code=404,
            detail={"code": "resource_not_found", "message": "Resource not found"},
        )

    storage_path = Path(resource.storage_path)
    item = db.query(KnowledgeItem).filter(KnowledgeItem.id == resource.item_id).first() if resource.item_id else None
    db.delete(resource)
    if item:
        db.delete(item)
    db.commit()
    storage_path.unlink(missing_ok=True)
    return {"detail": "deleted"}


@router.post("/resources/{resource_id}/ingest", response_model=KnowledgeResourceOut)
def ingest_resource(resource_id: str, db: Session = Depends(get_db)):
    """Queue resource ingestion without waiting for Engine to finish."""
    resource = db.query(KnowledgeFile).filter(
        KnowledgeFile.id == resource_id,
        KnowledgeFile.user_id == DEFAULT_USER_ID,
    ).first()
    if not resource:
        raise HTTPException(
            status_code=404,
            detail={"code": "resource_not_found", "message": "Resource not found"},
        )
    if not resource.item_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "no_item", "message": "Resource has no associated knowledge item"},
        )
    if resource.processing_status == "text_invalid":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "text_invalid",
                "message": resource.error_message or "Resource text is invalid",
            },
        )
    try:
        enqueue_ingest_job(
            db,
            _redis_client(),
            resource.id,
            queue_name=settings.KNOWLEDGE_INGEST_QUEUE,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": str(exc), "message": str(exc)},
        ) from exc
    db.refresh(resource)
    return resource


@router.post("/resources/{resource_id}/governance/retry", response_model=KnowledgeResourceOut)
def retry_resource_governance(resource_id: str, db: Session = Depends(get_db)):
    resource = db.query(KnowledgeFile).filter(
        KnowledgeFile.id == resource_id,
        KnowledgeFile.user_id == DEFAULT_USER_ID,
    ).first()
    if not resource:
        raise HTTPException(
            status_code=404,
            detail={"code": "resource_not_found", "message": "Resource not found"},
        )
    if resource.processing_status != "done":
        raise HTTPException(
            status_code=409,
            detail={"code": "not_vectorized", "message": "Resource is not vectorized"},
        )
    if resource.governance_status != "failed":
        raise HTTPException(
            status_code=409,
            detail={"code": "governance_not_failed", "message": "Governance is not failed"},
        )

    try:
        enqueue_governance_job(
            db,
            _redis_client(),
            resource.id,
            queue_name=settings.KNOWLEDGE_GOVERNANCE_QUEUE,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": str(exc), "message": str(exc)},
        ) from exc
    db.refresh(resource)
    return resource


@router.put("/resources/{resource_id}", response_model=KnowledgeResourceOut)
def update_resource(resource_id: str, payload: KnowledgeResourceUpdate, db: Session = Depends(get_db)):
    resource = db.query(KnowledgeFile).filter(
        KnowledgeFile.id == resource_id,
        KnowledgeFile.user_id == DEFAULT_USER_ID,
    ).first()
    if not resource:
        raise HTTPException(
            status_code=404,
            detail={"code": "resource_not_found", "message": "Resource not found"},
        )

    data = payload.model_dump(exclude_unset=True)
    if "title" in data:
        title = (data["title"] or "").strip()
        if not title:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_resource_title", "message": "Resource title cannot be empty"},
            )
        resource.title = title
        if resource.item_id:
            item = db.query(KnowledgeItem).filter(KnowledgeItem.id == resource.item_id).first()
            if item:
                item.title = title

    db.commit()
    db.refresh(resource)
    return resource


@router.get("/{item_id}", response_model=KnowledgeItemOut)
def get_item(item_id: str, db: Session = Depends(get_db)):
    item = db.query(KnowledgeItem).filter(KnowledgeItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="知识条目不存在")
    return item


@router.put("/{item_id}", response_model=KnowledgeItemOut)
def update_item(item_id: str, payload: KnowledgeItemUpdate, db: Session = Depends(get_db)):
    item = db.query(KnowledgeItem).filter(KnowledgeItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="知识条目不存在")
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}")
def delete_item(item_id: str, db: Session = Depends(get_db)):
    item = db.query(KnowledgeItem).filter(KnowledgeItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="知识条目不存在")
    db.delete(item)
    db.commit()
    return {"detail": "已删除"}
