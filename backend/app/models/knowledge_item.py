# prism/backend/app/models/knowledge_item.py
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import JSON, CHAR
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import relationship, synonym

from ..database import Base
from ..utils.time import local_now
from .knowledge_types import ResourceStatus, StageStatus, uuid4_str


DocumentText = Text().with_variant(MEDIUMTEXT, "mysql")


class KnowledgeTopic(Base):
    __tablename__ = "knowledge_topic"
    __table_args__ = (
        UniqueConstraint("kb_uid", name="uq_knowledge_topic_kb_uid"),
    )

    id = Column(CHAR(36), primary_key=True, default=uuid4_str)
    user_id = Column(CHAR(36), nullable=True, comment="Legacy user id")
    kb_uid = Column(CHAR(36), nullable=False, default=uuid4_str)
    tenant_id = Column(CHAR(36), nullable=False)
    owner_user_id = Column(CHAR(36), nullable=False)
    name = Column(String(255), nullable=False, comment="Topic name")
    description = Column(Text, comment="Topic description")
    status = Column(
        String(24),
        nullable=False,
        default=ResourceStatus.ACTIVE.value,
        server_default=ResourceStatus.ACTIVE.value,
    )
    deleted_at = Column(DateTime, nullable=True)
    version = Column(Integer, nullable=False, default=1, server_default="1")
    embedding_profile = Column(JSON, nullable=True)
    parser_config = Column(JSON, nullable=True)
    chunk_config = Column(JSON, nullable=True)
    retrieval_config = Column(JSON, nullable=True)
    graph_config = Column(JSON, nullable=True)
    active_index_generation = Column(CHAR(36), nullable=True)
    active_graph_generation = Column(CHAR(36), nullable=True)
    mindmap = Column(JSON, nullable=True)
    mindmap_version = Column(Integer, nullable=True)
    mindmap_generated_at = Column(DateTime, nullable=True)
    sample_questions = Column(JSON, nullable=True)
    sample_questions_version = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)

    resources = relationship("KnowledgeFile", back_populates="topic", cascade="all, delete-orphan")


class KnowledgeItem(Base):
    __tablename__ = "knowledge_item"

    id = Column(CHAR(36), primary_key=True, default=uuid4_str)
    tenant_id = Column(CHAR(36), nullable=False)
    kb_uid = Column(CHAR(36), nullable=False)
    title = Column(String(255), nullable=False, comment="Title")
    content = Column(DocumentText, comment="Markdown content")
    normalized_markdown = Column(DocumentText, nullable=True)
    summary = Column(Text, comment="AI generated summary")
    source_type = Column(String(32), default="manual", comment="file/url/chat/manual")
    source_ref = Column(String(500), comment="Original file path, URL, or chat ID")
    content_version = Column(Integer, nullable=False, default=1, server_default="1")
    tags = Column(JSON, comment="Tag list")
    category = Column(String(255), comment="Category path")
    status = Column(String(24), default="published", comment="draft/published/archived")
    user_id = Column(CHAR(36), default="default-user", comment="User id")
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)

    chunks = relationship("KnowledgeChunk", back_populates="item", cascade="all, delete-orphan")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunk"

    __table_args__ = (
        UniqueConstraint("chunk_uid", "generation", name="uq_knowledge_chunk_uid_generation"),
    )

    id = Column(CHAR(36), primary_key=True, default=uuid4_str)
    chunk_uid = Column(CHAR(36), nullable=False, default=uuid4_str)
    kb_uid = Column(CHAR(36), nullable=False)
    file_uid = Column(CHAR(36), nullable=False)
    item_id = Column(CHAR(36), ForeignKey("knowledge_item.id", ondelete="CASCADE"), nullable=True)
    generation = Column(CHAR(36), nullable=False, default="0", server_default="0")
    chunk_text = Column(Text, nullable=False, comment="Chunk text")
    chunk_index = Column(Integer, default=0, comment="Chunk index")
    chunk_type = Column(String(16), default="child", comment="child / parent")
    parent_id = Column(
        CHAR(36),
        ForeignKey("knowledge_chunk.id", ondelete="SET NULL"),
        nullable=True,
        comment="Child chunk's parent row ID",
    )
    parent_chunk_uid = Column(CHAR(36), nullable=True)
    page_number = Column(Integer, nullable=True)
    char_start = Column(Integer, nullable=True)
    char_end = Column(Integer, nullable=True)
    token_start = Column(Integer, nullable=True)
    token_end = Column(Integer, nullable=True)
    title_path = Column(JSON, nullable=True)
    embedding_id = Column(String(100), comment="Milvus vector ID")
    extra_meta = Column(JSON, comment="Page, position, and other metadata")
    created_at = Column(DateTime, default=local_now)

    item = relationship("KnowledgeItem", back_populates="chunks")


class KnowledgeFile(Base):
    __tablename__ = "knowledge_file"
    __table_args__ = (
        UniqueConstraint("file_uid", name="uq_knowledge_file_file_uid"),
    )

    id = Column(CHAR(36), primary_key=True, default=uuid4_str)
    file_uid = Column(CHAR(36), nullable=False, default=uuid4_str)
    kb_uid = Column(CHAR(36), nullable=False)
    tenant_id = Column(CHAR(36), nullable=False)
    user_id = Column(CHAR(36), nullable=True, comment="Legacy user id")
    topic_id = Column(CHAR(36), ForeignKey("knowledge_topic.id", ondelete="CASCADE"), nullable=True)
    item_id = Column(CHAR(36), ForeignKey("knowledge_item.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(255), nullable=True, comment="Resource title")
    storage_uri = Column(String(1024), nullable=True)
    relative_path = Column(String(1024), nullable=True)
    original_filename = Column("original_name", String(255), nullable=True, comment="Original filename")
    media_type = Column(String(64), nullable=True, comment="document/image/audio/video")
    mime_type = Column(String(100), comment="MIME type")
    file_type = Column(String(20), nullable=True, comment="Legacy file extension")
    content_sha256 = Column(CHAR(64), nullable=True)
    size_bytes = Column(BigInteger, nullable=True)
    file_size = Column(BigInteger, nullable=True, comment="Legacy file size in bytes")
    md5 = Column(String(32), nullable=True, comment="File MD5")
    file_path = Column(String(500), nullable=True, comment="Legacy stored file path")
    parser_config_snapshot = Column(JSON, nullable=True)
    chunk_config_snapshot = Column(JSON, nullable=True)
    parse_status = Column(
        String(24),
        nullable=False,
        default=StageStatus.PENDING.value,
        server_default=StageStatus.PENDING.value,
    )
    index_status = Column(
        String(24),
        nullable=False,
        default=StageStatus.PENDING.value,
        server_default=StageStatus.PENDING.value,
    )
    graph_status = Column(
        String(24),
        nullable=False,
        default=StageStatus.PENDING.value,
        server_default=StageStatus.PENDING.value,
    )
    parsed_content_version = Column(Integer, nullable=False, default=0, server_default="0")
    active_index_generation = Column(CHAR(36), nullable=True)
    parse_error = Column(JSON, nullable=True)
    index_error = Column(JSON, nullable=True)
    graph_error = Column(JSON, nullable=True)
    parse_started_at = Column(DateTime, nullable=True)
    parse_finished_at = Column(DateTime, nullable=True)
    index_started_at = Column(DateTime, nullable=True)
    index_finished_at = Column(DateTime, nullable=True)
    graph_started_at = Column(DateTime, nullable=True)
    graph_finished_at = Column(DateTime, nullable=True)
    last_job_id = Column(CHAR(36), nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    description = Column(Text, comment="Resource description")
    tags = Column(JSON, comment="Tags")
    source_type = Column(String(32), default="upload", comment="upload")
    page_count = Column(Integer, nullable=True, comment="Document page count")
    content_text = Column(DocumentText, comment="Parsed text")
    uploaded_at = Column(DateTime, default=local_now)
    last_modified_at = Column(DateTime, default=local_now, onupdate=local_now)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)
    error_message = Column(Text, comment="Processing error")
    governance_status = Column(String(24), nullable=True, default="not_started")
    governance_progress_current = Column(Integer, nullable=True, default=0)
    governance_progress_total = Column(Integer, nullable=True, default=0)
    governance_error_message = Column(Text, comment="Governance error")
    governance_started_at = Column(DateTime, nullable=True)
    governance_finished_at = Column(DateTime, nullable=True)

    topic = relationship("KnowledgeTopic", back_populates="resources")
    item = relationship("KnowledgeItem")
    original_name = synonym("original_filename")
    storage_path = synonym("file_path")
    file_ext = synonym("file_type")
    processing_status = synonym("parse_status")
