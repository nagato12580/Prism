# prism/backend/app/api/knowledge.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import cast, String, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import Optional

from ..database import get_db
from ..models.knowledge_item import KnowledgeItem, KnowledgeTopic, KnowledgeFile
from ..schemas.knowledge import (
    KnowledgeItemCreate, KnowledgeItemUpdate, KnowledgeItemOut, KnowledgeItemListOut,
    KnowledgeTopicCreate, KnowledgeTopicUpdate, KnowledgeTopicOut, KnowledgeResourceOut,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
DEFAULT_USER_ID = "default-user"


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
    topic = KnowledgeTopic(
        user_id=DEFAULT_USER_ID,
        name=payload.name.strip(),
        description=payload.description,
    )
    db.add(topic)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "duplicate_topic_name", "message": "Topic name already exists"},
        )
    db.refresh(topic)
    return _topic_out(topic, 0)


@router.get("/topics", response_model=list[KnowledgeTopicOut])
def list_topics(db: Session = Depends(get_db)):
    rows = (
        db.query(KnowledgeTopic, func.count(KnowledgeFile.id))
        .outerjoin(KnowledgeFile, KnowledgeFile.topic_id == KnowledgeTopic.id)
        .filter(KnowledgeTopic.user_id == DEFAULT_USER_ID)
        .group_by(KnowledgeTopic.id)
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
        topic.name = data["name"].strip()
    if "description" in data:
        topic.description = data["description"]
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "duplicate_topic_name", "message": "Topic name already exists"},
        )
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
