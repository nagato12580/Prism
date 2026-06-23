# prism/backend/app/schemas/wiki.py
"""Wiki API 请求/响应 Schema"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── WikiDocument ──────────────────────────────────────────

class WikiDocumentOut(BaseModel):
    id: str
    file_id: str
    status: str
    extract_stage: str
    progress_current: int
    progress_total: int
    user_id: str
    created_at: datetime
    # 从 knowledge_file join 的额外字段
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None

    class Config:
        from_attributes = True


class WikiDocumentDetailOut(WikiDocumentOut):
    """文档详情，含日志。"""
    logs: list["WikiExtractionLogOut"] = []


# ── WikiConcept ──────────────────────────────────────────

class WikiConceptOut(BaseModel):
    id: str
    document_id: str
    name: str
    type: str
    description: Optional[str]
    aliases: str
    group_name: str
    category: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── WikiKnowledgePoint ──────────────────────────────────

class WikiKnowledgePointOut(BaseModel):
    id: str
    document_id: str
    title: str
    description: Optional[str]
    content: Optional[str]
    category: str
    tags: str
    aliases: str
    group_name: str
    status: str
    images: Optional[str]
    user_id: str
    created_at: datetime

    class Config:
        from_attributes = True


class WikiKnowledgePointListOut(BaseModel):
    """列表项（不含 content，避免响应过大）。"""
    id: str
    document_id: str
    title: str
    description: Optional[str]
    category: str
    tags: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── WikiKnowledgeRelation ───────────────────────────────

class WikiKnowledgeRelationOut(BaseModel):
    id: str
    from_point_id: str
    to_point_id: str
    type: str
    confidence: float
    created_at: datetime
    # 关联知识点标题（查询时 join 填充）
    from_title: Optional[str] = None
    to_title: Optional[str] = None

    class Config:
        from_attributes = True


# ── WikiImage ────────────────────────────────────────────

class WikiImageOut(BaseModel):
    id: str
    document_id: str
    image_index: int
    storage_path: str
    caption: Optional[str]
    mime_type: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── WikiExtractionLog ───────────────────────────────────

class WikiExtractionLogOut(BaseModel):
    id: str
    document_id: str
    stage: str
    message: str
    status: str
    progress_current: int
    progress_total: int
    created_at: datetime

    class Config:
        from_attributes = True


# ── Request schemas ─────────────────────────────────────

class WikiExtractRequest(BaseModel):
    doc_id: str = Field(..., description="wiki_document.id")
