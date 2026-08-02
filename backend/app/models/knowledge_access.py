from sqlalchemy import Column, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import CHAR, JSON

from ..database import Base
from ..utils.time import local_now
from .knowledge_types import KnowledgeBaseRole, TeamRole, uuid4_str


class TeamMember(Base):
    __tablename__ = "team_member"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_team_member_tenant_user"),
        Index("ix_team_member_tenant_role", "tenant_id", "role"),
    )

    id = Column(CHAR(36), primary_key=True, default=uuid4_str)
    tenant_id = Column(CHAR(36), nullable=False)
    user_id = Column(CHAR(36), nullable=False)
    role = Column(String(32), nullable=False, default=TeamRole.MEMBER.value, server_default=TeamRole.MEMBER.value)
    status = Column(String(32), nullable=False, default="active", server_default="active")
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)


class KnowledgeBaseMembership(Base):
    __tablename__ = "knowledge_base_membership"
    __table_args__ = (
        UniqueConstraint("tenant_id", "kb_uid", "user_id", name="uq_kb_membership_scope_user"),
        Index("ix_kb_membership_user", "tenant_id", "user_id"),
        Index("ix_kb_membership_kb", "tenant_id", "kb_uid"),
    )

    id = Column(CHAR(36), primary_key=True, default=uuid4_str)
    tenant_id = Column(CHAR(36), nullable=False)
    kb_uid = Column(CHAR(36), nullable=False)
    user_id = Column(CHAR(36), nullable=False)
    role = Column(String(32), nullable=False, default=KnowledgeBaseRole.VIEWER.value, server_default=KnowledgeBaseRole.VIEWER.value)
    granted_by = Column(CHAR(36), nullable=True)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)


class KnowledgeAccessAuditLog(Base):
    __tablename__ = "knowledge_access_audit_log"
    __table_args__ = (
        Index("ix_kb_access_audit_scope_created", "tenant_id", "kb_uid", "created_at"),
        Index("ix_kb_access_audit_actor", "tenant_id", "actor_id", "created_at"),
    )

    id = Column(CHAR(36), primary_key=True, default=uuid4_str)
    tenant_id = Column(CHAR(36), nullable=False)
    kb_uid = Column(CHAR(36), nullable=True)
    actor_id = Column(CHAR(36), nullable=False)
    action = Column(String(64), nullable=False)
    target_user_id = Column(CHAR(36), nullable=True)
    before = Column(JSON, nullable=True)
    after = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=local_now)
    note = Column(Text, nullable=True)
