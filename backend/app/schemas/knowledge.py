# prism/backend/app/schemas/knowledge.py
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Literal, Optional


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


class KnowledgeTopicCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class KnowledgeTopicUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None


class KnowledgeTopicOut(BaseModel):
    id: str
    user_id: str
    name: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime
    resource_count: int = 0

    class Config:
        from_attributes = True


class KnowledgeResourceUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)


class KnowledgeResourceOut(BaseModel):
    id: str
    user_id: str
    topic_id: Optional[str]
    item_id: Optional[str]
    title: str
    original_filename: str
    media_type: Literal["document", "image", "audio", "video"]
    mime_type: Optional[str]
    file_ext: str
    file_size: int
    md5: str
    storage_path: str
    processing_status: str
    description: Optional[str]
    tags: Optional[list[str]]
    source_type: str
    page_count: Optional[int]
    content_text: Optional[str]
    uploaded_at: datetime
    last_modified_at: datetime
    created_at: datetime
    updated_at: datetime
    error_message: Optional[str]

    class Config:
        from_attributes = True
