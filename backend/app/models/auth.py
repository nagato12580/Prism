from datetime import timedelta

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.mysql import CHAR

from ..config import settings
from ..database import Base
from ..utils.time import local_now
from .knowledge_types import uuid4_str


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        UniqueConstraint("email", name="uq_users_email"),
        Index("ix_users_status", "status"),
    )

    id = Column(CHAR(36), primary_key=True, default=uuid4_str)
    username = Column(String(64), nullable=False)
    display_name = Column(String(128), nullable=False)
    email = Column(String(255), nullable=True)
    status = Column(String(32), nullable=False, default="active", server_default="active")
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)


class AuthSession(Base):
    __tablename__ = "auth_session"
    __table_args__ = (
        Index("ix_auth_session_user", "user_id"),
        Index("ix_auth_session_expires_at", "expires_at"),
    )

    id = Column(CHAR(36), primary_key=True, default=uuid4_str)
    user_id = Column(CHAR(36), ForeignKey("users.id"), nullable=False)
    expires_at = Column(
        DateTime,
        nullable=False,
        default=lambda: local_now() + timedelta(hours=settings.SESSION_TTL_HOURS),
    )
    created_at = Column(DateTime, default=local_now)
    last_seen_at = Column(DateTime, default=local_now)
    created_by_mode = Column(String(32), nullable=False, default="dev_login", server_default="dev_login")
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(255), nullable=True)
