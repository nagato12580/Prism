# prism/backend/app/api/knowledge.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import cast, String
from sqlalchemy.orm import Session
from typing import Optional

from ..database import get_db
from ..models.knowledge_item import KnowledgeItem
from ..schemas.knowledge import (
    KnowledgeItemCreate, KnowledgeItemUpdate, KnowledgeItemOut, KnowledgeItemListOut
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.post("", response_model=KnowledgeItemOut)
def create_item(payload: KnowledgeItemCreate, db: Session = Depends(get_db)):
    item = KnowledgeItem(
        title=payload.title,
        content=payload.content,
        source_type=payload.source_type,
        source_ref=payload.source_ref,
        tags=payload.tags or [],
        category=payload.category,
        user_id="default-user",
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
