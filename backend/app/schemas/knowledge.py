# prism/backend/app/schemas/knowledge.py
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional


class KnowledgeItemCreate(BaseModel):
    title: str = Field(..., max_length=255)
    content: Optional[str] = None
    source_type: str = "manual"
    source_ref: Optional[str] = None
    tags: Optional[list[str]] = None
    category: Optional[str] = None


class KnowledgeItemUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None
    category: Optional[str] = None
    status: Optional[str] = None


class KnowledgeItemOut(BaseModel):
    id: str
    title: str
    content: Optional[str]
    summary: Optional[str]
    source_type: str
    source_ref: Optional[str]
    tags: Optional[list[str]]
    category: Optional[str]
    status: str
    user_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KnowledgeItemListOut(BaseModel):
    """列表项（不含 content，避免响应过大）。"""
    id: str
    title: str
    summary: Optional[str]
    source_type: str
    tags: Optional[list[str]]
    category: Optional[str]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True
