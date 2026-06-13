# prism/backend/app/schemas/chat.py
from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class ChatSessionCreate(BaseModel):
    title: Optional[str] = "新对话"


class ChatSessionOut(BaseModel):
    id: str
    title: str
    user_id: str
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
    created_at: datetime

    class Config:
        from_attributes = True


class ChatMessageCreate(BaseModel):
    role: str
    content: str
    sources: Optional[list] = None
