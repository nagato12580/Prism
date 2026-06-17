# prism/backend/app/schemas/inbox.py
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


InboxKind = Literal["knowledge", "opinion", "resource", "task", "memory", "idea", "chat"]
InboxAction = Literal["make_wiki", "save_note", "save_resource", "remember", "review_later", "ignore"]


class InboxItemCreate(BaseModel):
    content: str = Field(..., min_length=1)
    title: Optional[str] = None
    source_type: str = "manual"
    source_url: Optional[str] = None
    source_platform: Optional[str] = None
    classify: bool = True


class InboxRawItemOut(BaseModel):
    id: str
    user_id: str
    title: str
    content: str
    source_type: str
    source_url: str
    source_platform: str
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InboxReviewOut(BaseModel):
    id: str
    raw_item_id: str
    user_id: str
    kind: InboxKind
    title: str
    summary: Optional[str]
    suggested_action: InboxAction
    category: str
    tags: list[str]
    rationale: Optional[str]
    confidence: float
    status: str
    settled_type: str
    settled_ref_id: str
    created_at: datetime
    updated_at: datetime
    raw_item: Optional[InboxRawItemOut] = None

    class Config:
        from_attributes = True


class InboxCreateResponse(BaseModel):
    item: InboxRawItemOut
    review: Optional[InboxReviewOut] = None


class ReviewUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    kind: Optional[InboxKind] = None
    suggested_action: Optional[InboxAction] = None
    category: Optional[str] = None
    tags: Optional[list[str]] = None


class ReviewSettleResponse(BaseModel):
    review: InboxReviewOut
    settled_type: str
    settled_ref_id: str


class NotebookNoteOut(BaseModel):
    id: str
    user_id: str
    title: str
    content: Optional[str]
    note_type: str
    category: str
    tags: list[str]
    source_raw_item_id: str
    source_review_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


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
