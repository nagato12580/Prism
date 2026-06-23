import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.mysql import CHAR, JSON
from sqlalchemy.orm import relationship

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
    embedding_ref = Column(String(255), default="")
    embedding_model = Column(String(128), default="")
    embedding_status = Column(String(32), default="pending", index=True)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)


class MemoryStatus:
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class MemorySource(Base):
    __tablename__ = "memory_source"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    source_type = Column(String(64), nullable=False, index=True)
    source_id = Column(String(128), default="")
    session_id = Column(CHAR(36), default="", index=True)
    message_id = Column(CHAR(36), default="", index=True)
    span_text = Column(Text, default="")
    occurred_at = Column(DateTime, default=local_now, index=True)
    source_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=local_now)


class MemoryStatement(Base):
    __tablename__ = "memory_statement"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    content = Column(Text, nullable=False)
    statement_type = Column(String(64), default="fact", index=True)
    temporal_type = Column(String(64), default="stable", index=True)
    confidence = Column(Float, default=0.7)
    importance = Column(Float, default=0.6)
    status = Column(String(32), default=MemoryStatus.DRAFT, index=True)
    valid_from = Column(DateTime, default=local_now)
    valid_until = Column(DateTime, nullable=True)
    superseded_by_id = Column(CHAR(36), default="", index=True)
    embedding_ref = Column(String(255), default="")
    embedding_model = Column(String(128), default="")
    embedding_status = Column(String(32), default="pending", index=True)
    source_id = Column(CHAR(36), ForeignKey("memory_source.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)

    source = relationship("MemorySource")


class MemoryEntity(Base):
    __tablename__ = "memory_entity"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    name = Column(String(255), nullable=False, index=True)
    entity_type = Column(String(64), default="topic", index=True)
    description = Column(Text, default="")
    aliases = Column(JSON, default=list)
    confidence = Column(Float, default=0.7)
    importance = Column(Float, default=0.6)
    mention_count = Column(Integer, default=1)
    status = Column(String(32), default=MemoryStatus.DRAFT, index=True)
    source_ids = Column(JSON, default=list)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)


class MemoryRelation(Base):
    __tablename__ = "memory_relation"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    subject_entity_id = Column(CHAR(36), ForeignKey("memory_entity.id"), nullable=False, index=True)
    predicate = Column(String(64), nullable=False, index=True)
    object_entity_id = Column(CHAR(36), ForeignKey("memory_entity.id"), nullable=False, index=True)
    statement_id = Column(CHAR(36), ForeignKey("memory_statement.id"), nullable=True, index=True)
    confidence = Column(Float, default=0.7)
    status = Column(String(32), default=MemoryStatus.DRAFT, index=True)
    valid_from = Column(DateTime, default=local_now)
    valid_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)


class MemoryEvent(Base):
    __tablename__ = "memory_event"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    event_time = Column(DateTime, nullable=True, index=True)
    event_type = Column(String(64), default="decision", index=True)
    related_entity_ids = Column(JSON, default=list)
    statement_id = Column(CHAR(36), ForeignKey("memory_statement.id"), nullable=True, index=True)
    confidence = Column(Float, default=0.7)
    status = Column(String(32), default=MemoryStatus.DRAFT, index=True)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)


class MemoryInsight(Base):
    __tablename__ = "memory_insight"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    theme = Column(String(128), nullable=False, index=True)
    content = Column(Text, nullable=False)
    insight_type = Column(String(64), default="recent_focus", index=True)
    source_statement_ids = Column(JSON, default=list)
    confidence = Column(Float, default=0.7)
    importance = Column(Float, default=0.6)
    status = Column(String(32), default=MemoryStatus.CONFIRMED, index=True)
    valid_from = Column(DateTime, default=local_now)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)


class MemoryDraft(Base):
    __tablename__ = "memory_draft"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    draft_type = Column(String(64), nullable=False, index=True)
    payload = Column(JSON, default=dict)
    decision_hint = Column(String(64), default="review")
    risk_level = Column(String(32), default="medium", index=True)
    confidence = Column(Float, default=0.7)
    status = Column(String(32), default=MemoryStatus.DRAFT, index=True)
    conflict_ids = Column(JSON, default=list)
    source_id = Column(CHAR(36), ForeignKey("memory_source.id"), nullable=True, index=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)

    source = relationship("MemorySource")
