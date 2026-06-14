# prism/backend/app/api/knowledge.py
import hashlib
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import cast, String, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .upload import _trigger_ingestion
from ..database import get_db
from ..models.knowledge_item import KnowledgeItem, KnowledgeTopic, KnowledgeFile
from ..schemas.knowledge import (
    KnowledgeItemCreate, KnowledgeItemUpdate, KnowledgeItemOut, KnowledgeItemListOut,
    KnowledgeTopicCreate, KnowledgeTopicUpdate, KnowledgeTopicOut, KnowledgeResourceOut,
)
from ..utils.file_parser import count_pages, extract_text
from ..utils.media_type import infer_media_type

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
DEFAULT_USER_ID = "default-user"
UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


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


def _save_upload(file: UploadFile, topic_id: str) -> tuple[Path, bytes, str]:
    content = file.file.read()
    md5 = hashlib.md5(content).hexdigest()
    ext = Path(file.filename or "").suffix.lower()
    topic_dir = UPLOAD_DIR / DEFAULT_USER_ID / topic_id
    topic_dir.mkdir(parents=True, exist_ok=True)
    saved_path = topic_dir / f"{md5}{ext}"
    saved_path.write_bytes(content)
    return saved_path, content, md5


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

    saved_path, content, md5 = _save_upload(file, topic.id)
    duplicate = db.query(KnowledgeFile).filter(
        KnowledgeFile.user_id == DEFAULT_USER_ID,
        KnowledgeFile.topic_id == topic.id,
        KnowledgeFile.md5 == md5,
    ).first()
    if duplicate:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=409,
            detail={"code": "duplicate_resource_in_topic", "message": "Resource already exists in this topic"},
        )

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

    if resource.item_id and resource.processing_status == "completed":
        _trigger_ingestion(resource.item_id)

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
