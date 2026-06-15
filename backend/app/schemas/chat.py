# prism/backend/app/schemas/chat.py
from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class ChatSessionCreate(BaseModel):
    title: Optional[str] = "新对话"
    topic_id: Optional[str] = None
    source_types: Optional[list[str]] = None


class ChatSessionUpdate(BaseModel):
    """Partial update — only set fields are applied."""
    title: Optional[str] = None
    topic_id: Optional[str] = None
    source_types: Optional[list[str]] = None


class ChatSessionOut(BaseModel):
    id: str
    title: str
    user_id: str
    topic_id: Optional[str] = None
    source_types: Optional[list] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ChatMessageOut(BaseModel):
    id: str
    session_id: str
    role: str
    content: Optional[str]
    sources: Optional[list]
    clarify: Optional[dict] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ChatMessageCreate(BaseModel):
    role: str
    content: str
    sources: Optional[list] = None
    clarify: Optional[dict] = None
