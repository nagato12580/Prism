# prism/backend/app/models/inbox.py
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.mysql import CHAR, JSON
from sqlalchemy.orm import relationship

from ..database import Base


def _uuid():
    return str(uuid.uuid4())


class InboxRawItem(Base):
    __tablename__ = "inbox_raw_item"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    title = Column(String(255), default="")
    content = Column(Text, nullable=False)
    source_type = Column(String(32), default="manual", comment="manual/wechat/web/video/comment")
    source_url = Column(String(1000), default="")
    source_platform = Column(String(100), default="")
    status = Column(String(24), default="pending", index=True, comment="pending/classified/settled/archived")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    reviews = relationship("InboxReviewItem", back_populates="raw_item", cascade="all, delete-orphan")


class InboxReviewItem(Base):
    __tablename__ = "inbox_review_item"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    raw_item_id = Column(CHAR(36), ForeignKey("inbox_raw_item.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    kind = Column(String(32), default="idea", index=True, comment="knowledge/opinion/resource/task/memory/idea/chat")
    title = Column(String(255), default="")
    summary = Column(Text)
    suggested_action = Column(String(32), default="save_note", comment="make_wiki/save_note/save_resource/remember/review_later/ignore")
    category = Column(String(128), default="")
    tags = Column(JSON, default=list)
    rationale = Column(Text)
    confidence = Column(Float, default=0.5)
    status = Column(String(24), default="pending", index=True, comment="pending/approved/rejected")
    settled_type = Column(String(32), default="", comment="knowledge/note/memory")
    settled_ref_id = Column(CHAR(36), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    raw_item = relationship("InboxRawItem", back_populates="reviews")


class NotebookNote(Base):
    __tablename__ = "notebook_note"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    title = Column(String(255), nullable=False)
    content = Column(Text)
    note_type = Column(String(32), default="note", index=True, comment="note/opinion/resource/task/idea")
    category = Column(String(128), default="")
    tags = Column(JSON, default=list)
    source_raw_item_id = Column(CHAR(36), default="")
    source_review_id = Column(CHAR(36), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
