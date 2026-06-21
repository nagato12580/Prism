# prism/backend/app/models/knowledge_item.py
import uuid

from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.mysql import JSON, CHAR
from sqlalchemy.orm import relationship, synonym

from ..database import Base
from ..utils.time import local_now


def _uuid():
    return str(uuid.uuid4())


class KnowledgeTopic(Base):
    __tablename__ = "knowledge_topic"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_knowledge_topic_user_name"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", nullable=False, comment="User id")
    name = Column(String(255), nullable=False, comment="Topic name")
    description = Column(Text, comment="Topic description")
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)

    resources = relationship("KnowledgeFile", back_populates="topic", cascade="all, delete-orphan")


class KnowledgeItem(Base):
    __tablename__ = "knowledge_item"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    title = Column(String(255), nullable=False, comment="Title")
    content = Column(Text, comment="Markdown content")
    summary = Column(Text, comment="AI generated summary")
    source_type = Column(String(20), default="manual", comment="file/url/chat/manual")
    source_ref = Column(String(500), comment="Original file path, URL, or chat ID")
    tags = Column(JSON, comment="Tag list")
    category = Column(String(255), comment="Category path")
    status = Column(String(20), default="published", comment="draft/published/archived")
    user_id = Column(CHAR(36), default="default-user", comment="User id")
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)

    chunks = relationship("KnowledgeChunk", back_populates="item", cascade="all, delete-orphan")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunk"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    item_id = Column(CHAR(36), ForeignKey("knowledge_item.id", ondelete="CASCADE"), nullable=False)
    chunk_text = Column(Text, nullable=False, comment="Chunk text")
    chunk_index = Column(Integer, default=0, comment="Chunk index")
    chunk_type = Column(String(16), default="child", comment="child / parent")
    parent_id = Column(CHAR(36), nullable=True, default=None, comment="子块指向父块 ID")
    embedding_id = Column(String(100), comment="Milvus vector ID")
    extra_meta = Column(JSON, comment="Page, position, and other metadata")
    created_at = Column(DateTime, default=local_now)

    item = relationship("KnowledgeItem", back_populates="chunks")


class KnowledgeFile(Base):
    __tablename__ = "knowledge_file"
    __table_args__ = (
        UniqueConstraint("user_id", "topic_id", "md5", name="uq_knowledge_file_user_topic_md5"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", nullable=False, comment="User id")
    topic_id = Column(CHAR(36), ForeignKey("knowledge_topic.id", ondelete="CASCADE"), nullable=True)
    item_id = Column(CHAR(36), ForeignKey("knowledge_item.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(255), nullable=False, default="", comment="Resource title")
    original_filename = Column("original_name", String(255), nullable=False, default="", comment="Original filename")
    media_type = Column(String(20), nullable=False, default="document", comment="document/image/audio/video")
    mime_type = Column(String(100), comment="MIME type")
    file_ext = Column("file_type", String(20), nullable=False, default="", comment="File extension")
    file_size = Column(Integer, default=0, comment="File size in bytes")
    md5 = Column(String(32), nullable=False, default="", comment="File MD5")
    storage_path = Column("file_path", String(500), nullable=False, default="", comment="Stored file path")
    processing_status = Column("parse_status", String(20), default="pending", comment="pending/processing/completed/failed/metadata_only")
    description = Column(Text, comment="Resource description")
    tags = Column(JSON, comment="Tags")
    source_type = Column(String(20), default="upload", comment="upload")
    page_count = Column(Integer, nullable=True, comment="Document page count")
    content_text = Column(Text, comment="Parsed text")
    uploaded_at = Column(DateTime, default=local_now)
    last_modified_at = Column(DateTime, default=local_now, onupdate=local_now)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)
    error_message = Column(Text, comment="Processing error")

    topic = relationship("KnowledgeTopic", back_populates="resources")
    item = relationship("KnowledgeItem")
    original_name = synonym("original_filename")
    file_path = synonym("storage_path")
    file_type = synonym("file_ext")
    parse_status = synonym("processing_status")

    # Validator removed: "done" is now a distinct status from "completed".
    # "completed" = text extracted, waiting for manual vectorization.
    # "done" = fully ingested with vectors in Milvus.
