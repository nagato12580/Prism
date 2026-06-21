import uuid

from sqlalchemy import Column, DateTime, Float, String, Text
from sqlalchemy.dialects.mysql import CHAR, JSON

from ..database import Base
from ..utils.time import local_now


def _uuid():
    return str(uuid.uuid4())


class MemoryEntry(Base):
    __tablename__ = "memory_entry"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    memory_type = Column(String(32), default="preference", index=True, comment="preference/fact/goal/context")
    category = Column(String(128), default="")
    tags = Column(JSON, default=list)
    importance = Column(Float, default=0.6)
    source_raw_item_id = Column(CHAR(36), default="")
    source_review_id = Column(CHAR(36), default="")
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)
