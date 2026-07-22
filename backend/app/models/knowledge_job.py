from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.dialects.mysql import CHAR, JSON

from ..database import Base
from ..utils.time import local_now
from .knowledge_types import JobStatus, uuid4_str


class KnowledgeJob(Base):
    __tablename__ = "knowledge_job"
    __table_args__ = (
        Index("ix_knowledge_job_status_available_priority_created", "status", "available_at", "priority", "created_at"),
        Index("ix_knowledge_job_resource_type_status", "resource_id", "job_type", "status"),
        Index("ix_knowledge_job_item_id", "item_id"),
        Index("ix_knowledge_job_topic_id", "topic_id"),
        UniqueConstraint("idempotency_key", name="uq_knowledge_job_idempotency_key"),
    )

    id = Column(CHAR(36), primary_key=True, default=uuid4_str)
    tenant_id = Column(CHAR(36), nullable=False)
    kb_uid = Column(CHAR(36), nullable=False)
    file_uid = Column(CHAR(36), nullable=True)
    idempotency_key = Column(String(255), nullable=False)
    payload = Column(JSON, nullable=True)
    result = Column(JSON, nullable=True)
    job_type = Column(String(32), nullable=True, comment="ingest / governance")
    resource_id = Column(CHAR(36), nullable=True)
    item_id = Column(CHAR(36), nullable=True)
    topic_id = Column(CHAR(36), nullable=True)
    status = Column(
        Enum(
            JobStatus,
            name="knowledge_job_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda statuses: [status.value for status in statuses],
            length=24,
        ),
        nullable=False,
        default=JobStatus.QUEUED,
        server_default=JobStatus.QUEUED.value,
    )
    priority = Column(Integer, nullable=False, default=100, server_default="100")
    attempt = Column(Integer, nullable=False, default=0, server_default="0")
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    max_attempts = Column(Integer, nullable=False, default=3, server_default="3")
    next_run_at = Column(DateTime, nullable=True)
    progress_current = Column(Integer, nullable=False, default=0, server_default="0")
    progress_total = Column(Integer, nullable=False, default=0, server_default="0")
    stage = Column(String(64), nullable=False, default="", server_default="")
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    retryable = Column(Boolean, nullable=False, default=False, server_default=false())
    lease_owner = Column(String(128), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)
    cancel_requested_at = Column(DateTime, nullable=True)
    canceled_by = Column(CHAR(36), nullable=True)
    locked_by = Column(String(128), nullable=True)
    locked_at = Column(DateTime, nullable=True)
    available_at = Column(DateTime, default=local_now, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)
