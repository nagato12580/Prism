from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class MemoryEntryOut(BaseModel):
    id: str
    user_id: str
    title: str
    content: str
    memory_type: str
    category: str
    tags: list[str]
    importance: float
    source_raw_item_id: str
    source_review_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MemorySourceCreate(BaseModel):
    source_type: str
    source_id: str = ""
    session_id: str = ""
    message_id: str = ""
    span_text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemorySourceOut(BaseModel):
    id: str
    user_id: str
    source_type: str
    source_id: str
    session_id: str
    message_id: str
    span_text: str
    occurred_at: datetime
    metadata: dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


def memory_source_to_out(source) -> MemorySourceOut:
    return MemorySourceOut(
        id=source.id,
        user_id=source.user_id,
        source_type=source.source_type,
        source_id=source.source_id,
        session_id=source.session_id,
        message_id=source.message_id,
        span_text=source.span_text,
        occurred_at=source.occurred_at,
        metadata=source.source_metadata or {},
        created_at=source.created_at,
    )


class MemoryDraftCreate(BaseModel):
    draft_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    decision_hint: str = "review"
    risk_level: str = "medium"
    confidence: float = 0.7
    conflict_ids: list[str] = Field(default_factory=list)
    source: Optional[MemorySourceCreate] = None


class MemoryDraftOut(BaseModel):
    id: str
    user_id: str
    draft_type: str
    payload: dict[str, Any]
    decision_hint: str
    risk_level: str
    confidence: float
    status: str
    conflict_ids: list[str]
    source: Optional[MemorySourceOut] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MemoryStatementOut(BaseModel):
    id: str
    user_id: str
    content: str
    statement_type: str
    temporal_type: str
    confidence: float
    importance: float
    status: str
    valid_from: datetime
    valid_until: Optional[datetime] = None
    superseded_by_id: str
    source: Optional[MemorySourceOut] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MemoryDraftConfirmOut(BaseModel):
    draft: MemoryDraftOut
    statement: MemoryStatementOut


class MemorySupersedePayload(BaseModel):
    superseded_statement_id: str


class MemoryExtractionRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)


class MemoryExtractionOut(BaseModel):
    session_id: str
    messages_scanned: int
    candidates_found: int
    drafts_created: int
    candidates_skipped: int
    draft_ids: list[str]
    drafts: list[MemoryDraftOut]
