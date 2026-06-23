# prism/backend/app/models/wiki.py
"""Wiki 文档知识抽取 — 数据模型"""
import uuid

from sqlalchemy import Column, String, Text, Integer, Float, DateTime, ForeignKey
from sqlalchemy.dialects.mysql import CHAR
from sqlalchemy.orm import relationship

from ..database import Base
from ..utils.time import local_now


def _uuid():
    return str(uuid.uuid4())


class WikiDocument(Base):
    """Wiki 管线特有数据，关联 knowledge_file。"""
    __tablename__ = "wiki_document"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    file_id = Column(CHAR(36), ForeignKey("knowledge_file.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(20), default="pending", comment="pending/processing/completed/failed")
    extract_stage = Column(String(50), default="", comment="Current stage name")
    progress_current = Column(Integer, default=0)
    progress_total = Column(Integer, default=0)
    user_id = Column(CHAR(36), default="default-user")
    created_at = Column(DateTime, default=local_now)

    file = relationship("KnowledgeFile")
    concepts = relationship("WikiConcept", back_populates="document", cascade="all, delete-orphan")
    knowledge_points = relationship("WikiKnowledgePoint", back_populates="document", cascade="all, delete-orphan")
    images = relationship("WikiImage", back_populates="document", cascade="all, delete-orphan")
    logs = relationship("WikiExtractionLog", back_populates="document", cascade="all, delete-orphan")


class WikiConcept(Base):
    """LLM 提取的原始概念（Stage 2 中间产物）。"""
    __tablename__ = "wiki_concept"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    document_id = Column(CHAR(36), ForeignKey("wiki_document.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(512), nullable=False, comment="Concept name (Chinese)")
    type = Column(String(32), default="concept", comment="concept/technique/source/claim/artifact")
    description = Column(Text, comment="Specific factual description")
    aliases = Column(String(1024), default="", comment="Aliases, comma separated")
    group_name = Column(String(256), default="", index=True, comment="LLM assigned group name")
    category = Column(String(128), default="", comment="Category")
    created_at = Column(DateTime, default=local_now)

    document = relationship("WikiDocument", back_populates="concepts")


class WikiKnowledgePoint(Base):
    """合并后的最终知识点（Stage 3 产物）。"""
    __tablename__ = "wiki_knowledge_point"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    document_id = Column(CHAR(36), ForeignKey("wiki_document.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(512), nullable=False, comment="Knowledge point title")
    description = Column(Text, comment="Refined description (100-200 chars, Stage 3.5a)")
    content = Column(Text, comment="Structured Markdown article (Stage 3.5b)")
    category = Column(String(128), default="", comment="Category")
    tags = Column(String(1024), default="", comment="Tags, comma separated")
    aliases = Column(String(1024), default="", comment="Aliases, comma separated")
    group_name = Column(String(256), default="", comment="Group name")
    status = Column(String(16), default="整理中", comment="整理中/已发布")
    images = Column(Text, comment="Associated images JSON: [{'id':'uuid','caption':'desc'},...]")
    user_id = Column(CHAR(36), default="default-user")
    created_at = Column(DateTime, default=local_now)

    document = relationship("WikiDocument", back_populates="knowledge_points")


class WikiKnowledgeRelation(Base):
    """知识点间关系。"""
    __tablename__ = "wiki_knowledge_relation"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    from_point_id = Column(CHAR(36), ForeignKey("wiki_knowledge_point.id", ondelete="CASCADE"), nullable=False)
    to_point_id = Column(CHAR(36), ForeignKey("wiki_knowledge_point.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(64), default="", comment="implements/extends/optimizes/contradicts/cites/prerequisite_of/trades_off/derived_from")
    confidence = Column(Float, default=1.0, comment="Confidence 0.0~1.0")
    created_at = Column(DateTime, default=local_now)


class WikiImage(Base):
    """文档内嵌图片及视觉 LLM 描述（Stage 1.5）。"""
    __tablename__ = "wiki_image"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    document_id = Column(CHAR(36), ForeignKey("wiki_document.id", ondelete="CASCADE"), nullable=False)
    image_index = Column(Integer, default=0, comment="Image sequence (1-based)")
    storage_path = Column(String(500), default="", comment="Storage path")
    caption = Column(Text, comment="Vision LLM description")
    mime_type = Column(String(100), default="", comment="MIME type")
    created_at = Column(DateTime, default=local_now)

    document = relationship("WikiDocument", back_populates="images")


class WikiExtractionLog(Base):
    """管线执行日志。"""
    __tablename__ = "wiki_extraction_log"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    document_id = Column(CHAR(36), ForeignKey("wiki_document.id", ondelete="CASCADE"), nullable=False)
    stage = Column(String(50), default="", comment="Stage name")
    message = Column(Text, comment="Log content")
    status = Column(String(16), default="info", comment="info/warning/error")
    progress_current = Column(Integer, default=0)
    progress_total = Column(Integer, default=0)
    created_at = Column(DateTime, default=local_now)

    document = relationship("WikiDocument", back_populates="logs")
