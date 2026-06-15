# prism/backend/app/models/chat.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.mysql import JSON, CHAR
from sqlalchemy.orm import relationship
from ..database import Base


def _uuid():
    return str(uuid.uuid4())


class ChatSession(Base):
    __tablename__ = "chat_session"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    title = Column(String(255), default="新对话", comment="会话标题")
    user_id = Column(CHAR(36), default="default-user")
    topic_id = Column(CHAR(36), nullable=True, default=None, comment="关联知识库主题")
    source_types = Column(JSON, nullable=True, default=None, comment="过滤数据来源类型")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan",
                            order_by="ChatMessage.created_at")


class ChatMessage(Base):
    __tablename__ = "chat_message"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    session_id = Column(CHAR(36), ForeignKey("chat_session.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False, comment="user/assistant/system")
    content = Column(Text, comment="消息内容")
    sources = Column(JSON, comment="引用的知识块ID列表")
    clarify = Column(JSON, nullable=True, default=None, comment="追问卡片数据")
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("ChatSession", back_populates="messages")
