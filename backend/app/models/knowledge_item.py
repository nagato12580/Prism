# prism/backend/app/models/knowledge_item.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Integer, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.mysql import JSON, CHAR
from sqlalchemy.orm import relationship
from ..database import Base


def _uuid():
    return str(uuid.uuid4())


class KnowledgeItem(Base):
    __tablename__ = "knowledge_item"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    title = Column(String(255), nullable=False, comment="标题")
    content = Column(Text, comment="Markdown 内容")
    summary = Column(Text, comment="AI 生成摘要")
    source_type = Column(String(20), default="manual", comment="file/url/chat/manual")
    source_ref = Column(String(500), comment="原始文件路径/URL/对话ID")
    tags = Column(JSON, comment="标签数组")
    category = Column(String(255), comment="分类路径")
    status = Column(String(20), default="published", comment="draft/published/archived")
    user_id = Column(CHAR(36), default="default-user", comment="用户ID(预留多用户)")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    chunks = relationship("KnowledgeChunk", back_populates="item", cascade="all, delete-orphan")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunk"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    item_id = Column(CHAR(36), ForeignKey("knowledge_item.id", ondelete="CASCADE"), nullable=False)
    chunk_text = Column(Text, nullable=False, comment="分块后文本")
    chunk_index = Column(Integer, default=0, comment="块序号")
    embedding_id = Column(String(100), comment="Milvus 向量 ID")
    extra_meta = Column(JSON, comment="页码/位置等元数据")
    created_at = Column(DateTime, default=datetime.utcnow)

    item = relationship("KnowledgeItem", back_populates="chunks")


class KnowledgeFile(Base):
    __tablename__ = "knowledge_file"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    original_name = Column(String(255), nullable=False, comment="原始文件名")
    file_path = Column(String(500), nullable=False, comment="存储路径")
    file_type = Column(String(20), comment="文件类型")
    file_size = Column(Integer, default=0, comment="文件大小(字节)")
    parse_status = Column(String(20), default="pending", comment="pending/parsing/done/failed")
    item_id = Column(CHAR(36), ForeignKey("knowledge_item.id", ondelete="SET NULL"), comment="关联知识条目")
    created_at = Column(DateTime, default=datetime.utcnow)
