# prism/backend/app/models/chat.py
import uuid
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.dialects.mysql import JSON, CHAR
from sqlalchemy.orm import relationship
from ..database import Base
from ..utils.time import local_now


def _uuid():
    return str(uuid.uuid4())


class ChatSession(Base):
    __tablename__ = "chat_session"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    title = Column(String(255), default="新对话", comment="会话标题")
    user_id = Column(CHAR(36), default="default-user")
    topic_id = Column(CHAR(36), nullable=True, default=None, comment="关联知识库主题")
    source_types = Column(JSON, nullable=True, default=None, comment="过滤数据来源类型")
    summary = Column(Text, default="", comment="LLM 生成的会话摘要")
    last_extracted_message_id = Column(CHAR(36), default="", comment="提取水位线：上次提取到的最后一条消息 ID")
    last_extracted_at = Column(DateTime, nullable=True, comment="上次触发提取的时间")
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)

    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan",
                            order_by="ChatMessage.created_at")


class ChatMessage(Base):
    __tablename__ = "chat_message"
    __table_args__ = (
        Index("ix_chat_message_session_created_id", "session_id", "created_at", "id"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    session_id = Column(CHAR(36), ForeignKey("chat_session.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False, comment="user/assistant/system")
    content = Column(Text, comment="消息内容")
    sources = Column(JSON, comment="引用的知识块ID列表")
    clarify = Column(JSON, nullable=True, default=None, comment="追问卡片数据")
    process = Column(JSON, nullable=True, default=None, comment="assistant process state")
    created_at = Column(DateTime, default=local_now)

    session = relationship("ChatSession", back_populates="messages")
