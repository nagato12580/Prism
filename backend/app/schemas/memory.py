from datetime import datetime

from pydantic import BaseModel


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
